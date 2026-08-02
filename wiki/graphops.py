"""Pure graph traversal over a loaded `Corpus`.

Everything here is deterministic and model-free.  That is deliberate: a large
share of the questions this tool gets asked ("what calls X", "who writes to
Q_ALARM_LO", "how does X reach Y") are *structural*, and answering them by
traversal is faster, cheaper and more trustworthy than asking a model to
reconstruct the same facts from source it has only partly read.  The agent in
`agent.py` uses these same functions as its tools, so a subagent's claims are
grounded in the graph rather than in recollection.

The trace-label grammar
-----------------------
`traces[].labels` entries look like::

    [main.c]main[312:373]
    [scf_stubs.c:332]scf_evt_register (accepts callback)-> bo_on_trip[39:39]
    [bo_safety.c:332]bo_on_trip[748:771]
    [bo_combust.c:548]bo_combust_task[420:438]
    [scf_stubs.c:430]scf_hist_save[23:23]

which decodes as ``[<file-defining-subject>:<call-site-line-in-the-caller>]``
then ``<subject>`` then ``[<subject-def-start>:<subject-def-end>]``.

The callback form is the one worth care: in that second line the trailing
``[39:39]`` is **`scf_evt_register`'s** definition range, not `bo_on_trip`'s —
verified against the snapshot, where `bo_on_trip` is `[748:771]` and
`scf_evt_register` is `[39:39]`.  The registered callback then appears again
as its own next label.  Reading that line as a single `bo_on_trip` node both
mis-attributes the line range and double-counts the hop, so the parser treats
the subject as the API and lets the following label carry the callback.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import asdict, dataclass
from typing import Iterable

from .corpus import Corpus, FunctionRef, Interaction

# `[file]name[start:end]` / `[file:line]name[start:end]`
LABEL_PLAIN = re.compile(
    r"^\[(?P<file>[^\]:]+)(?::(?P<line>-?\d+))?\]"
    r"(?P<name>[A-Za-z_]\w*)"
    r"\[(?P<start>-?\d+):(?P<end>-?\d+)\]$"
)

# `[file:line]api (accepts callback)-> callback[api_start:api_end]`
LABEL_CALLBACK = re.compile(
    r"^\[(?P<file>[^\]:]+)(?::(?P<line>-?\d+))?\]"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<note>[^)]*callback[^)]*)\)->\s*"
    r"(?P<target>[A-Za-z_]\w*)"
    r"\[(?P<start>-?\d+):(?P<end>-?\d+)\]$"
)

# `[line]MACRO (macro expansion)-> function`
#
# The odd one out: no file and no definition range, because a macro has
# neither in the registry (`RAISE_ALARM` is recorded as external, `[-1:-1]`).
# The bracket holds the line in the *calling* function where the macro is
# written.  Structurally this is the callback form again — the expansion
# follows as its own next label — so it decodes into the same shape.
LABEL_MACRO = re.compile(
    r"^\[(?P<line>-?\d+)\]"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<note>[^)]*macro[^)]*)\)->\s*"
    r"(?P<target>[A-Za-z_]\w*)$"
)

# Call kinds that move control into a different function body.  `macro_call`
# is excluded: the expansion edge that follows it carries the real hop, and
# counting both doubles every macro in a path.
TRAVERSABLE_KINDS = frozenset({"direct", "indirect", "callback", "macro_expansion"})


@dataclass(slots=True)
class Step:
    """One hop of an invocation path, shaped for the frontend contract."""

    function_id: str | None
    name: str
    file_name: str | None
    line: int | None
    kind: str
    via: str | None = None
    note: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Path:
    id: str
    label: str
    process: str
    origin: str  # "trace" | "bfs"
    steps: list[Step]
    target_api: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "process": self.process,
            "origin": self.origin,
            "target_api": self.target_api,
            "steps": [step.as_dict() for step in self.steps],
        }

    @property
    def function_ids(self) -> list[str]:
        return [step.function_id for step in self.steps if step.function_id]


@dataclass(slots=True)
class ParsedLabel:
    """One decoded label.

    `target` is set only on the two indirection forms, where this label
    *hands control to* another function that appears as the following label:
    a callback registration, or a macro expansion.  `relation` says which.
    """

    name: str
    file_name: str | None
    call_line: int | None
    def_start: int
    def_end: int
    target: str | None
    relation: str | None  # "callback" | "macro"
    note: str | None


def parse_trace_label(label: str) -> ParsedLabel | None:
    """Decode one `traces[].labels` entry. Returns None if unrecognised."""
    text = label.strip()

    match = LABEL_CALLBACK.match(text)
    if match:
        return ParsedLabel(
            name=match.group("name"),
            file_name=match.group("file"),
            call_line=int(match.group("line")) if match.group("line") else None,
            def_start=int(match.group("start")),
            def_end=int(match.group("end")),
            target=match.group("target"),
            relation="callback",
            note=match.group("note").strip(),
        )

    match = LABEL_MACRO.match(text)
    if match:
        return ParsedLabel(
            name=match.group("name"),
            file_name=None,
            call_line=int(match.group("line")),
            def_start=-1,
            def_end=-1,
            target=match.group("target"),
            relation="macro",
            note=match.group("note").strip(),
        )

    match = LABEL_PLAIN.match(text)
    if match:
        return ParsedLabel(
            name=match.group("name"),
            file_name=match.group("file"),
            call_line=int(match.group("line")) if match.group("line") else None,
            def_start=int(match.group("start")),
            def_end=int(match.group("end")),
            target=None,
            relation=None,
            note=None,
        )
    return None


def _resolve_labelled(
    corpus: Corpus, parsed: ParsedLabel, process: str
) -> FunctionRef | None:
    """Pick the function a label names.

    The label carries the definition range, so use it: names collide between
    headers, static duplicates and external stubs, and the range identifies
    exactly one definition.  Fall back to name resolution when the range does
    not match anything, which happens for library stubs recorded with a
    placeholder range.
    """
    candidates = corpus.by_name(parsed.name, process)
    if parsed.file_name is not None:
        for candidate in candidates:
            if (
                candidate.file_name == parsed.file_name
                and candidate.start_line == parsed.def_start
                and candidate.end_line == parsed.def_end
            ):
                return candidate
        for candidate in candidates:
            if candidate.file_name == parsed.file_name:
                return candidate
    # Macro labels carry no file and no range at all, so name resolution
    # (already ordered by definition quality) is all there is to go on.
    return candidates[0] if candidates else None


def resolve_trace(corpus: Corpus, trace, path_id: str | None = None) -> Path | None:
    """Turn one tracer trace into a resolved, id-bearing invocation path."""
    parsed_labels: list[ParsedLabel] = []
    for label in trace.labels:
        parsed = parse_trace_label(label)
        if parsed is not None:
            parsed_labels.append(parsed)

    steps: list[Step] = []
    for position, parsed in enumerate(parsed_labels):
        previous = parsed_labels[position - 1] if position else None
        function = _resolve_labelled(corpus, parsed, trace.process)

        # The label before this one may have handed control here — by
        # registering this function as a callback, or by expanding to it.
        # That is what makes the hop something other than a plain call.
        via = None
        kind = "direct"
        note = None
        if previous is not None and previous.target == parsed.name:
            kind = "callback" if previous.relation == "callback" else "macro_expansion"
            via = previous.name
            note = previous.note
        elif parsed.target:
            # This label *is* the indirection site.
            kind = "registers_callback" if parsed.relation == "callback" else "expands_macro"
            note = f"{parsed.note or parsed.relation} → {parsed.target}"

        steps.append(
            Step(
                function_id=function.id if function else None,
                name=parsed.name,
                file_name=parsed.file_name,
                line=parsed.call_line,
                kind=kind,
                via=via,
                note=note,
            )
        )

    if len(steps) < 2:
        return None

    return Path(
        id=path_id or f"path:{trace.id}",
        label=" → ".join(step.name for step in steps),
        process=trace.process,
        origin="trace",
        steps=steps,
        target_api=trace.target_api or None,
    )


def traces_as_paths(corpus: Corpus, target_api: str, limit: int = 6) -> list[Path]:
    """Every recorded invocation path that ends at one daemon API."""
    paths: list[Path] = []
    seen: set[str] = set()
    for trace in corpus.traces_for_api(target_api):
        resolved = resolve_trace(corpus, trace, path_id=f"path:{trace.id}")
        if resolved is None:
            continue
        # Different traces routinely resolve to the same chain of functions.
        signature = f"{resolved.process}|{resolved.label}"
        if signature in seen:
            continue
        seen.add(signature)
        paths.append(resolved)
        if len(paths) >= limit:
            break
    return paths


# ----------------------------------------------------------------- traversal


def callers(corpus: Corpus, function_id: str, process: str | None = None) -> list[dict]:
    """Who calls this function, with the edge kind and call site."""
    out = []
    for call in corpus.incoming(function_id, process):
        source = corpus.function(call.source)
        if source is None:
            continue
        out.append(
            {
                "id": source.id,
                "name": source.name,
                "file_name": source.file_name,
                "process": call.process,
                "line": call.line,
                "kind": call.kind,
                "via": (corpus.function(call.via).name if call.via and corpus.function(call.via) else call.via),
            }
        )
    return sorted(out, key=lambda item: (item["process"], item["name"], item["line"] or 0))


def callees(corpus: Corpus, function_id: str, process: str | None = None) -> list[dict]:
    """What this function calls, with the edge kind and call site."""
    out = []
    for call in corpus.outgoing(function_id, process):
        target = corpus.function(call.target)
        if target is None:
            continue
        out.append(
            {
                "id": target.id,
                "name": target.name,
                "file_name": target.file_name,
                "process": call.process,
                "line": call.line,
                "kind": call.kind,
                "is_external": target.is_external,
                "via": (corpus.function(call.via).name if call.via and corpus.function(call.via) else call.via),
            }
        )
    return sorted(out, key=lambda item: (item["process"], item["line"] or 0, item["name"]))


def call_paths(
    corpus: Corpus,
    source_id: str,
    target_id: str,
    process: str | None = None,
    max_paths: int = 4,
    max_depth: int = 12,
) -> list[Path]:
    """Shortest control-flow paths from one function to another.

    Breadth-first, so paths come out shortest-first, which is what a reader
    wants: the direct route before the scenic one.  Cycles are excluded
    per-path rather than globally, since a function legitimately appears on
    several distinct paths.
    """
    processes = [process] if process else list(corpus.processes)
    found: list[Path] = []

    for process_name in processes:
        snapshot = corpus.processes.get(process_name)
        if snapshot is None:
            continue
        if source_id not in snapshot.function_ids or target_id not in snapshot.function_ids:
            continue

        queue: deque[list] = deque([[(source_id, None)]])
        seen_signatures: set[tuple[str, ...]] = set()

        while queue and len(found) < max_paths:
            trail = queue.popleft()
            current_id, _ = trail[-1]

            if current_id == target_id and len(trail) > 1:
                signature = tuple(node for node, _ in trail)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                found.append(_trail_to_path(corpus, trail, process_name, len(found)))
                continue

            if len(trail) > max_depth:
                continue

            visited = {node for node, _ in trail}
            for call in snapshot.outgoing.get(current_id, ()):
                if call.kind not in TRAVERSABLE_KINDS:
                    continue
                if call.target in visited:
                    continue
                queue.append(trail + [(call.target, call)])

    return found[:max_paths]


def _trail_to_path(corpus: Corpus, trail: list, process_name: str, position: int) -> Path:
    steps: list[Step] = []
    for function_id, call in trail:
        function = corpus.function(function_id)
        via_ref = corpus.function(call.via) if call and call.via else None
        steps.append(
            Step(
                function_id=function_id,
                name=function.name if function else function_id,
                file_name=function.file_name if function else None,
                line=call.line if call else None,
                kind=call.kind if call else "entry",
                via=via_ref.name if via_ref else (call.via if call else None),
                note=None,
            )
        )
    return Path(
        id=f"path:bfs:{process_name}:{position}",
        label=" → ".join(step.name for step in steps),
        process=process_name,
        origin="bfs",
        steps=steps,
    )


def paths_from_entry(
    corpus: Corpus, function_id: str, process: str | None = None, max_paths: int = 3
) -> list[Path]:
    """How `main` reaches this function — the question users actually ask."""
    processes = [process] if process else list(corpus.processes)
    found: list[Path] = []
    for process_name in processes:
        snapshot = corpus.processes.get(process_name)
        if snapshot is None or not snapshot.entry_function_id:
            continue
        if function_id not in snapshot.function_ids:
            continue
        found.extend(
            call_paths(
                corpus,
                snapshot.entry_function_id,
                function_id,
                process=process_name,
                max_paths=max_paths,
            )
        )
    return found[:max_paths]


# ----------------------------------------------------------------- resources


def interaction_direction(interaction: Interaction) -> str:
    """Mirror of `interactionDirection()` in `src/graph/model.js`.

    Kept in lockstep with the frontend on purpose: an answer that says a
    function *writes* a queue while the graph draws the arrow inward would be
    the most confusing possible failure.
    """
    by_api = {
        "scf_evt_post": "out",
        "scf_var_evt": "out",
        "scf_timer_start": "out",
        "scf_evt_register": "in",
        "scf_tag_open": "both",
        "scf_sem_wait": "both",
        "scf_signal_hook": "in",
    }
    if interaction.target_api in by_api:
        return by_api[interaction.target_api]
    if interaction.operation in {
        "WRITEF", "SAVEF", "WRITEQ", "SAVEQ", "ENQ",
        "CLEARF", "CLEARQ", "SIGNAL", "FORK", "KILL",
    }:
        return "out"
    if interaction.operation in {"READF", "READQ", "DEQ", "LOADF"}:
        return "in"
    return "both"


def resources_for_function(corpus: Corpus, function_id: str, process: str | None = None) -> list[dict]:
    """Every daemon resource one function touches, deduped by resource key."""
    grouped: dict[str, dict] = {}
    for interaction in corpus.interactions_for(function_id, process):
        resource = corpus.resource(interaction.resource_key)
        if resource is None:
            continue
        entry = grouped.setdefault(
            resource.key,
            {
                "key": resource.key,
                "kind": resource.kind,
                "name": resource.name,
                "resolved": resource.resolved,
                "direction": interaction_direction(interaction),
                "processes": list(resource.processes),
                "operations": [],
                "target_apis": [],
                "bindings": [],
            },
        )
        if interaction.operation and interaction.operation not in entry["operations"]:
            entry["operations"].append(interaction.operation)
        if interaction.target_api and interaction.target_api not in entry["target_apis"]:
            entry["target_apis"].append(interaction.target_api)
        if interaction.argument_value is not None:
            binding = {
                "argument_index": interaction.argument_index,
                "value": interaction.argument_value,
                "launch_via": interaction.launch_via,
            }
            if binding not in entry["bindings"]:
                entry["bindings"].append(binding)
    return list(grouped.values())


def functions_for_resource(corpus: Corpus, resource_key: str) -> dict:
    """Which functions touch one resource, split by direction.

    This is the cross-process question the 3D overview exists to show, and the
    one a flat file-oriented wiki cannot answer at all: 28 of 38 resource keys
    in the current corpus are touched by more than one process.
    """
    resource = corpus.resource(resource_key)
    if resource is None:
        return {}

    producers: dict[str, dict] = {}
    consumers: dict[str, dict] = {}
    for interaction in corpus.interactions_on(resource_key):
        function = corpus.function(interaction.function_id) if interaction.function_id else None
        if function is None:
            continue
        direction = interaction_direction(interaction)
        record = {
            "id": function.id,
            "name": function.name,
            "file_name": function.file_name,
            "process": interaction.process,
            "operation": interaction.operation,
            "target_api": interaction.target_api,
            "value": interaction.argument_value,
            "launch_via": interaction.launch_via,
        }
        key = f"{interaction.process}|{function.id}|{interaction.operation}"
        if direction in {"out", "both"}:
            producers.setdefault(key, record)
        if direction in {"in", "both"}:
            consumers.setdefault(key, record)

    return {
        "key": resource.key,
        "kind": resource.kind,
        "name": resource.name,
        "resolved": resource.resolved,
        "processes": list(resource.processes),
        "producers": sorted(producers.values(), key=lambda item: (item["process"], item["name"])),
        "consumers": sorted(consumers.values(), key=lambda item: (item["process"], item["name"])),
    }


def find_resources(corpus: Corpus, text: str, limit: int = 8) -> list[str]:
    """Resource keys matching a fragment — `Q_ALARM_LO`, `3000`, `queue`."""
    needle = (text or "").strip().lower()
    if not needle:
        return []
    exact, partial = [], []
    for key, resource in corpus.resources.items():
        name = resource.name.lower()
        if name == needle or key.lower() == needle:
            exact.append(key)
        elif needle in key.lower():
            partial.append(key)
    return (exact + partial)[:limit]
