"""Load one run selection into a single cross-process corpus.

The frontend picks one run per process, so a question is always asked against
a *set* of snapshots rather than one.  This module joins that set into one
queryable object and is the only place that knows the on-disk layout.

Two properties of the snapshot data drive the whole design here, and both are
measured rather than assumed (see `tests/test_wiki_corpus.py`):

**Function ids are shared across processes.**  `_stable_id` hashes the
definition path, so the shared `test_scada/lib/scf_stubs.c` yields *identical*
ids in every process that links it.  On the current corpus 31 of 1115 ids are
multi-process, 25 of them internal — and those 25 are the `scf_*` daemon API
stubs, which is to say the most-asked-about functions in the tree.  So a
function is keyed by id alone, carries `processes` as a tuple, and anything
call-graph shaped is keyed by `(process, function_id)`: the same stub is
called from different places in different processes, and merging those edges
would invent call paths that do not exist.

**Resources are keyed by `kind + name`, not id.**  Their ids happen to be
stable across snapshots today, but the frontend has always joined on
`kind + name` and the cross-process daemon coupling is the interesting part:
28 of 38 resource keys are touched by more than one process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1


class SnapshotError(RuntimeError):
    """A snapshot was missing, unreadable, or of an unsupported schema."""


@dataclass(frozen=True, slots=True)
class FunctionRef:
    """One function, merged across every process whose snapshot defines it."""

    id: str
    name: str
    file: str | None
    file_name: str | None
    start_line: int
    end_line: int
    is_external: bool
    is_library_api: bool
    is_static: bool
    summary: str | None
    summary_status: str
    summary_hint: str | None
    source: str | None
    call_count: int
    resource_interaction_count: int
    processes: tuple[str, ...]

    @property
    def has_source(self) -> bool:
        return bool(self.source and self.source.strip())

    @property
    def location(self) -> str:
        if self.start_line and self.start_line > 0:
            return f"{self.file_name or '?'}:{self.start_line}-{self.end_line}"
        return self.file_name or "(external)"

    def signature(self) -> str:
        """First non-comment, non-blank line of the definition.

        Good enough to show a caller what it is looking at without paying for
        the whole body, which is what most agent turns actually need.
        """
        if not self.has_source:
            return f"{self.name}(…)"
        for line in self.source.splitlines():  # type: ignore[union-attr]
            stripped = line.strip()
            if not stripped or stripped.startswith(("/*", "*", "//", "#")):
                continue
            return stripped.rstrip("{").strip()
        return f"{self.name}(…)"


@dataclass(frozen=True, slots=True)
class Call:
    """One call edge, always within one process."""

    id: str
    process: str
    source: str
    target: str
    line: int | None
    kind: str
    via: str | None


@dataclass(frozen=True, slots=True)
class ResourceRef:
    """A daemon resource, joined across processes on `kind + name`."""

    kind: str
    name: str
    resolved: bool
    processes: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.kind} {self.name}"


@dataclass(frozen=True, slots=True)
class Interaction:
    """Evidence that one function touches one daemon resource.

    `function_id` is the function this is attributed to; `origin_function_id`
    is what the exporter recorded, kept so the difference stays inspectable.
    See `Corpus._attribute` for why they differ.
    """

    id: str
    process: str
    function_id: str | None
    origin_function_id: str | None
    resource_key: str
    target_api: str
    operation: str
    launch_via: str | None
    call_number: str | None
    argument_index: int | None
    argument_value: str | None
    path: str | None


@dataclass(frozen=True, slots=True)
class Trace:
    """One tracer-recorded invocation chain, still in raw label form.

    Resolution to function ids lives in `graphops`, because it needs the call
    graph to disambiguate names and this module stays a pure loader.
    """

    id: str
    process: str
    target_api: str
    labels: tuple[str, ...]
    display_path: str


@dataclass(slots=True)
class ProcessSnapshot:
    """One process's slice of the corpus."""

    name: str
    run_id: str
    root: str
    main_file: str | None
    entry_function_id: str | None
    generated_at: str
    function_ids: frozenset[str]
    outgoing: dict[str, list[Call]] = field(default_factory=dict)
    incoming: dict[str, list[Call]] = field(default_factory=dict)


class Corpus:
    """Every snapshot in one run selection, joined and indexed."""

    def __init__(self) -> None:
        self.functions: dict[str, FunctionRef] = {}
        self.processes: dict[str, ProcessSnapshot] = {}
        self.calls: list[Call] = []
        self.resources: dict[str, ResourceRef] = {}
        self.interactions: list[Interaction] = []
        self.traces: list[Trace] = []

        self._by_name: dict[str, list[str]] = {}
        self._interactions_by_function: dict[tuple[str, str], list[Interaction]] = {}
        self._interactions_by_resource: dict[str, list[Interaction]] = {}
        self._traces_by_api: dict[str, list[Trace]] = {}

    # ------------------------------------------------------------- accessors

    def function(self, function_id: str) -> FunctionRef | None:
        return self.functions.get(function_id)

    def by_name(self, name: str, process: str | None = None) -> list[FunctionRef]:
        """Every function with this exact name, best-defined first.

        A name is not unique — headers, static duplicates and external stubs
        collide — so callers get the whole list.  Ordering puts the definition
        an agent actually wants to read first: one with source, in the process
        being asked about, and not an external stub.
        """
        refs = [self.functions[fid] for fid in self._by_name.get(name, [])]
        if process:
            scoped = [ref for ref in refs if process in ref.processes]
            refs = scoped or refs
        return sorted(
            refs,
            key=lambda ref: (
                ref.is_external,
                not ref.has_source,
                not (process in ref.processes if process else True),
                -(ref.end_line - ref.start_line),
            ),
        )

    def resolve_name(self, name: str, process: str | None = None) -> FunctionRef | None:
        candidates = self.by_name(name, process)
        return candidates[0] if candidates else None

    def outgoing(self, function_id: str, process: str | None = None) -> list[Call]:
        return self._edges("outgoing", function_id, process)

    def incoming(self, function_id: str, process: str | None = None) -> list[Call]:
        return self._edges("incoming", function_id, process)

    def _edges(self, side: str, function_id: str, process: str | None) -> list[Call]:
        found: list[Call] = []
        names = [process] if process else list(self.processes)
        for name in names:
            snapshot = self.processes.get(name)
            if snapshot is None:
                continue
            table = snapshot.outgoing if side == "outgoing" else snapshot.incoming
            found.extend(table.get(function_id, ()))
        return found

    def interactions_for(self, function_id: str, process: str | None = None) -> list[Interaction]:
        if process:
            return list(self._interactions_by_function.get((process, function_id), ()))
        found: list[Interaction] = []
        for name in self.processes:
            found.extend(self._interactions_by_function.get((name, function_id), ()))
        return found

    def interactions_on(self, resource_key: str) -> list[Interaction]:
        return list(self._interactions_by_resource.get(resource_key, ()))

    def traces_for_api(self, target_api: str) -> list[Trace]:
        return list(self._traces_by_api.get(target_api, ()))

    def resource(self, key: str) -> ResourceRef | None:
        return self.resources.get(key)

    def iter_functions(self) -> Iterator[FunctionRef]:
        return iter(self.functions.values())

    @property
    def stats(self) -> dict[str, int]:
        return {
            "processes": len(self.processes),
            "functions": len(self.functions),
            "calls": len(self.calls),
            "resources": len(self.resources),
            "interactions": len(self.interactions),
            "traces": len(self.traces),
        }

    # ---------------------------------------------------------------- loading

    def add_snapshot(self, snapshot: dict[str, Any]) -> None:
        version = snapshot.get("schema_version")
        if version != SCHEMA_VERSION:
            raise SnapshotError(f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")

        process = snapshot.get("process") or {}
        process_name = str(process.get("name") or "")
        if not process_name:
            raise SnapshotError("snapshot has no process name")

        function_ids = set()
        for raw in snapshot.get("functions") or []:
            function_ids.add(self._merge_function(raw, process_name))

        record = ProcessSnapshot(
            name=process_name,
            run_id=str(snapshot.get("run_id") or ""),
            root=str(process.get("root") or ""),
            main_file=process.get("main_file"),
            entry_function_id=process.get("entry_function_id"),
            generated_at=str(snapshot.get("generated_at") or ""),
            function_ids=frozenset(function_ids),
        )
        self.processes[process_name] = record

        for raw in snapshot.get("calls") or []:
            call = Call(
                id=str(raw.get("id")),
                process=process_name,
                source=str(raw.get("source")),
                target=str(raw.get("target")),
                line=raw.get("line"),
                kind=str(raw.get("kind") or "direct"),
                via=raw.get("via"),
            )
            self.calls.append(call)
            record.outgoing.setdefault(call.source, []).append(call)
            record.incoming.setdefault(call.target, []).append(call)

        resource_keys: dict[str, str] = {}
        for raw in snapshot.get("resources") or []:
            kind = str(raw.get("kind") or "daemon_resource")
            name = str(raw.get("name") or "")
            key = f"{kind} {name}"
            resource_keys[str(raw.get("id"))] = key
            existing = self.resources.get(key)
            processes = tuple(sorted(set((existing.processes if existing else ()) + (process_name,))))
            self.resources[key] = ResourceRef(
                kind=kind,
                name=name,
                # A resource resolved in any one process is resolved: an
                # UNRESOLVED row elsewhere is a gap in that trace, not evidence
                # that the queue does not exist.
                resolved=bool(raw.get("resolved")) or bool(existing and existing.resolved),
                processes=processes,
            )

        for raw in snapshot.get("interactions") or []:
            key = resource_keys.get(str(raw.get("resource_id")))
            if key is None:
                continue
            binding = raw.get("argument_binding") or {}
            origin = raw.get("function_id")
            interaction = Interaction(
                id=str(raw.get("id")),
                process=process_name,
                function_id=self._attribute(raw.get("path"), origin, process_name),
                origin_function_id=origin,
                resource_key=key,
                target_api=str(raw.get("target_api") or ""),
                operation=str(raw.get("operation") or ""),
                launch_via=raw.get("launch_via"),
                call_number=(str(raw["call_number"]) if raw.get("call_number") is not None else None),
                argument_index=binding.get("argument_index"),
                argument_value=(str(binding["value"]) if binding.get("value") is not None else None),
                path=raw.get("path"),
            )
            self.interactions.append(interaction)
            if interaction.function_id:
                self._interactions_by_function.setdefault(
                    (process_name, interaction.function_id), []
                ).append(interaction)
            self._interactions_by_resource.setdefault(key, []).append(interaction)

        for raw in snapshot.get("traces") or []:
            trace = Trace(
                id=str(raw.get("id")),
                process=process_name,
                target_api=str(raw.get("target_api") or ""),
                labels=tuple(str(label) for label in raw.get("labels") or ()),
                display_path=str(raw.get("display_path") or ""),
            )
            self.traces.append(trace)
            self._traces_by_api.setdefault(trace.target_api, []).append(trace)

    def _attribute(self, path: str | None, origin: str | None, process_name: str) -> str | None:
        """Attribute an interaction to the function that actually performs it.

        The exporter's `function_id` comes from a call-site match that usually
        misses, falling back to the `call_function` field — which is `main`
        for essentially every row.  Measured on the current corpus: **all 240
        interactions are attributed to `main`**, so only the six `main`s carry
        any daemon evidence, and asking "what does `bo_hist_audit` touch"
        answers "nothing" even though it calls `scf_hist_save` directly.

        The interaction's own `path` field holds the full call chain in the
        tracer's label grammar and ends at the daemon API, so the real caller
        is recoverable: walk back from the API to the last label that resolves
        to a non-external function.  Skipping external ones matters for macro
        chains, where the label immediately before the API is the macro itself
        (`RAISE_ALARM`) rather than the code that wrote it (`bo_on_scan`).

        The exporter's value is kept as `origin_function_id`, and is used
        unchanged whenever the path cannot be resolved.
        """
        from .labels import parse_path

        labels = parse_path(path or "")
        if len(labels) < 2:
            return origin

        for label in reversed(labels[:-1]):
            candidates = self.by_name(label.name, process_name)
            for candidate in candidates:
                if candidate.is_external:
                    continue
                if label.file_name and candidate.file_name != label.file_name:
                    continue
                return candidate.id
        return origin

    def _merge_function(self, raw: dict[str, Any], process_name: str) -> str:
        function_id = str(raw.get("id"))
        existing = self.functions.get(function_id)
        processes = tuple(sorted(set((existing.processes if existing else ()) + (process_name,))))

        if existing is not None:
            # Same id means same definition site, so the only thing that can
            # legitimately differ between snapshots is which processes reach it
            # and the per-process counters.  Keep the richer summary: a process
            # whose summary pass ran should not be overwritten by one whose
            # did not.
            better_summary = existing.summary or raw.get("summary")
            self.functions[function_id] = FunctionRef(
                **{
                    **{
                        slot: getattr(existing, slot)
                        for slot in FunctionRef.__slots__  # type: ignore[attr-defined]
                    },
                    "summary": better_summary,
                    "summary_status": (
                        "ready" if better_summary else existing.summary_status
                    ),
                    "processes": processes,
                    "call_count": max(existing.call_count, int(raw.get("call_count") or 0)),
                    "resource_interaction_count": max(
                        existing.resource_interaction_count,
                        int(raw.get("resource_interaction_count") or 0),
                    ),
                }
            )
            return function_id

        name = str(raw.get("name") or "unknown")
        self.functions[function_id] = FunctionRef(
            id=function_id,
            name=name,
            file=raw.get("file"),
            file_name=raw.get("file_name"),
            start_line=int(raw.get("start_line") or -1),
            end_line=int(raw.get("end_line") or -1),
            is_external=bool(raw.get("is_external")),
            is_library_api=bool(raw.get("is_library_api")),
            is_static=bool(raw.get("is_static")),
            summary=raw.get("summary"),
            summary_status=str(raw.get("summary_status") or "pending"),
            summary_hint=raw.get("summary_hint"),
            source=raw.get("source"),
            call_count=int(raw.get("call_count") or 0),
            resource_interaction_count=int(raw.get("resource_interaction_count") or 0),
            processes=processes,
        )
        self._by_name.setdefault(name, []).append(function_id)
        return function_id


# ----------------------------------------------------------------- filesystem


def graph_path(results_root: Path, process_name: str, run_id: str) -> Path:
    return Path(results_root) / "visualizer" / process_name / "runs" / run_id / "graph.json"


def load_snapshot(results_root: Path, process_name: str, run_id: str) -> dict[str, Any]:
    path = graph_path(results_root, process_name, run_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SnapshotError(f"no snapshot at {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"could not read {path}: {exc}") from exc


def load_corpus(results_root: Path, runs: dict[str, str]) -> Corpus:
    """Build a corpus from an explicit {process_name: run_id} selection.

    One unreadable snapshot must not lose the rest of the selection — a
    question about `proc_hvac` is still answerable when `proc_boiler`'s newest
    run is half-written.  Failures are recorded on the corpus instead.
    """
    corpus = Corpus()
    failures: list[str] = []
    for process_name, run_id in sorted((runs or {}).items()):
        try:
            corpus.add_snapshot(load_snapshot(results_root, str(process_name), str(run_id)))
        except SnapshotError as exc:
            failures.append(str(exc))
    if not corpus.processes:
        raise SnapshotError("; ".join(failures) or "no runs selected")
    corpus.failures = failures  # type: ignore[attr-defined]
    return corpus


def newest_runs(results_root: Path) -> dict[str, str]:
    """The default selection: newest run per process that carries evidence.

    Mirrors `chooseRuns()` in the frontend deliberately.  The newest run alone
    is empty of resources and interactions for most processes, so preferring it
    blindly answers daemon questions with "no evidence" when the evidence is
    one run back.
    """
    from process_groups import scan_graph_runs

    best: dict[str, tuple[int, str, str]] = {}
    for run in scan_graph_runs(Path(results_root)):
        process_name = str(run["process_name"])
        rank = (
            1 if int(run.get("interaction_count") or 0) > 0 else 0,
            str(run.get("generated_at") or ""),
            str(run["run_id"]),
        )
        if process_name not in best or rank > best[process_name]:
            best[process_name] = rank
    return {name: rank[2] for name, rank in sorted(best.items())}
