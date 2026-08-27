"""Discover process projects and persist reproducible multi-process groups.

A group deliberately references one immutable graph snapshot per process rather
than merging their function ID namespaces.  That keeps process ownership intact
while still giving the frontend enough information to join IPC resources across
the whole pipeline.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


GROUP_SCHEMA_VERSION = 1
_GROUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_IGNORED_DISCOVERY_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "results",
}


def load_project_state(json_dir: Path, targets_path: Path | None = None):
    """Load one process family's configuration without changing legacy loaders.

    ``targets_path`` (the ``--targets`` override) replaces ONLY the target
    function set (FUNCTION_TYPES).  Callback metadata and the function map
    still come from the selected project's ``json_dir``, and the override
    must not change the project source mapping or the selected process root.
    When an override is used it is loaded through the target-spec loader so
    duplicate names fail early, the registry digest can be recorded in
    the discovery-index metadata, and any validation problem fails the run
    before discovery proceeds (a comparison must never run on a silently
    wrong or shrunk target registry).
    """
    import pickle

    from state.state import State

    json_dir = json_dir.expanduser().resolve()
    state = State()

    target_path = (
        targets_path.expanduser().resolve() if targets_path is not None else json_dir / "mpf_data.json"
    )
    if targets_path is not None:
        from target_spec import load_target_spec, validate_target_spec

        spec = load_target_spec(target_path)
        problems = validate_target_spec(spec)
        if problems:
            detail = "\n".join(f"    - {problem}" for problem in problems)
            raise ValueError(
                f"Target registry failed validation ({target_path}); refusing to "
                "start a discovery run with a wrong target set:\n"
                f"{detail}"
            )
        state.set("TARGET_SPEC", spec)
        state.set("FUNCTION_TYPES", spec["targets"])
    else:
        state.set(
            "FUNCTION_TYPES",
            json.loads(target_path.read_text(encoding="utf-8")),
        )
    callback_path = json_dir / "function_callback_info.json"
    callback_info = (
        json.loads(callback_path.read_text(encoding="utf-8"))
        if callback_path.is_file()
        else {}
    )
    state.set("FUNCTION_POINTER_ARGS", callback_info)

    # The callback registry also carries useful prototypes/arity information.
    # Keep it separate from FUNCTION_POINTER_ARGS because the call-graph
    # builder only consumes func_argument, while LLM/tool prompts benefit from
    # the signature metadata.
    function_registry_path = json_dir / "function_registry.json"
    function_registry = (
        json.loads(function_registry_path.read_text(encoding="utf-8"))
        if function_registry_path.is_file()
        else {}
    )
    state.set("FUNCTION_SIGNATURES", function_registry)
    function_map_pickle = json_dir.parent / "pickle_data" / "function_map.pkl"
    if function_map_pickle.is_file():
        with function_map_pickle.open("rb") as handle:
            function_map = pickle.load(handle)
    else:
        combined_data_path = json_dir / "combined_data.json"
        function_map = (
            json.loads(combined_data_path.read_text(encoding="utf-8"))
            if combined_data_path.is_file()
            else {}
        )
    # Enrich the documentation map with the checked-in library signatures.
    # Do not replace non-empty documentation/parameter lists with the sparse
    # registry entries.  callback_info is loaded last because its prototypes
    # match the current opt-modern headers for callback APIs (for example
    # pmf_addevent), whereas function_registry contains older declarations for
    # some of those functions.
    function_map = {
        str(name): dict(value) if isinstance(value, dict) else value
        for name, value in (function_map or {}).items()
    }

    def merge_signature(name: str, metadata: dict) -> None:
        if not isinstance(metadata, dict):
            return
        existing = function_map.get(name)
        if not isinstance(existing, dict):
            existing = {}
        merged = dict(existing)
        for key, value in metadata.items():
            if value in (None, "", [], {}):
                continue
            if key == "parameters" and merged.get(key):
                continue
            merged[key] = value
        function_map[name] = merged

    for name, metadata in function_registry.items():
        merge_signature(str(name), metadata)
    for name, metadata in callback_info.items():
        merge_signature(str(name), metadata)

    state.set("FUNCTION_MAP", function_map)
    return state


def discover_processes(folder: Path) -> list[Path]:
    """Return every process directory below *folder* in stable path order.

    A process is a directory containing a ``Makefile``.  If the supplied
    folder is itself a process it is returned alone; otherwise discovery is
    recursive so category folders can be used as inputs too.
    """

    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Process folder does not exist: {folder}")
    if (folder / "Makefile").is_file():
        return [folder]

    processes: set[Path] = set()
    for makefile in folder.rglob("Makefile"):
        try:
            relative_parts = makefile.relative_to(folder).parts[:-1]
        except ValueError:
            continue
        if any(part in _IGNORED_DISCOVERY_DIRS for part in relative_parts):
            continue
        processes.add(makefile.parent.resolve())
    return sorted(processes, key=lambda path: str(path))


def validate_processes(projects: Iterable[Path]) -> list[Path]:
    """Resolve process paths and reject invalid batch inputs.

    Basename collisions are valid in recursive repository scans.  Callers
    should use :func:`process_output_names` before writing results so those
    projects receive deterministic path-qualified output names.
    """

    resolved: list[Path] = []
    seen_paths: set[Path] = set()
    for candidate in projects:
        project = candidate.expanduser().resolve()
        if project in seen_paths:
            continue
        if not project.is_dir():
            raise ValueError(f"Process directory does not exist: {project}")
        if not (project / "Makefile").is_file():
            raise ValueError(f"Process needs a Makefile: {project}")
        seen_paths.add(project)
        resolved.append(project)
    if not resolved:
        raise ValueError("No process directories were selected.")
    return resolved


def process_output_names(
    projects: Iterable[Path], root: Path | None = None
) -> dict[Path, str]:
    """Return collision-safe result names for a batch of process paths.

    Unique basenames retain the historical output layout.  Colliding
    basenames are renamed using their path relative to *root* (or a common
    parent when no root is supplied).  The real source path remains the
    process root; this only controls result/visualizer naming.
    """

    resolved = [Path(project).expanduser().resolve() for project in projects]
    counts: dict[str, int] = defaultdict(int)
    for project in resolved:
        counts[project.name] += 1

    if root is not None:
        root_path: Path | None = Path(root).expanduser().resolve()
    elif resolved:
        try:
            root_path = Path(os.path.commonpath([str(project) for project in resolved]))
        except ValueError:
            root_path = None
    else:
        root_path = None

    names: dict[Path, str] = {}
    used: set[str] = set()
    for project in resolved:
        if counts[project.name] == 1:
            candidate = project.name
        else:
            try:
                relative = project.relative_to(root_path) if root_path else project
            except ValueError:
                relative = project
            candidate = "__".join(relative.parts)
            candidate = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate).strip("_")
            candidate = candidate or project.name

        if candidate in used:
            absolute_text = str(project).replace("/", "__").replace("\\", "__")
            candidate = re.sub(r"[^A-Za-z0-9_.-]+", "_", absolute_text).strip("_")
        used.add(candidate)
        names[project] = candidate
    return names


def validate_group_name(group_name: str) -> str:
    """
    Validate a group name before a potentially long analyzer batch starts.
    Group name must start with an alphanumeric character and contain only letters, numbers, dots, underscores, or hyphens
    """

    if not _GROUP_NAME.fullmatch(group_name):
        raise ValueError(
            "Group name must start with an alphanumeric character and contain "
            "only letters, numbers, dots, underscores, or hyphens."
        )
    return group_name


def scan_graph_runs(results_root: Path) -> list[dict]:
    """Read all valid per-process graph snapshots under a results root."""

    results_root = results_root.expanduser().resolve()
    runs: list[dict] = []
    for graph_path in (results_root / "visualizer").glob("*/runs/*/graph.json"):
        try:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        process = graph.get("process") if isinstance(graph.get("process"), dict) else {}
        runs.append(
            {
                "process_name": process.get("name") or graph_path.parents[2].name,
                "run_id": graph.get("run_id") or graph_path.parent.name,
                "generated_at": graph.get("generated_at"),
                "function_count": len(graph.get("functions", [])),
                "resource_count": len(graph.get("resources", [])),
                "interaction_count": len(graph.get("interactions", [])),
                "graph_path": graph_path.resolve(),
                "graph": graph,
            }
        )
    return sorted(
        runs,
        key=lambda run: (
            str(run["process_name"]),
            str(run.get("generated_at") or ""),
            str(run["run_id"]),
        ),
        reverse=True,
    )


def select_process_runs(
    runs: Iterable[dict],
    process_names: Iterable[str] | None = None,
    policy: str = "latest-with-interactions",
) -> list[dict]:
    """Choose exactly one existing snapshot for each selected process."""

    if policy not in {"latest", "latest-with-interactions"}:
        raise ValueError(f"Unknown run-selection policy: {policy}")
    requested = set(process_names or [])
    by_process: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        name = str(run["process_name"])
        if requested and name not in requested:
            continue
        by_process[name].append(run)

    missing = requested - set(by_process)
    if missing:
        raise ValueError(
            "No graph snapshots found for process(es): " + ", ".join(sorted(missing))
        )
    if not by_process:
        raise ValueError("No graph snapshots are available to combine.")

    selected: list[dict] = []
    for name in sorted(by_process):
        candidates = sorted(
            by_process[name],
            key=lambda run: (
                str(run.get("generated_at") or ""),
                str(run.get("run_id") or ""),
            ),
            reverse=True,
        )
        if policy == "latest-with-interactions":
            selected.append(
                next(
                    (run for run in candidates if run.get("interaction_count", 0) > 0),
                    candidates[0],
                )
            )
        else:
            selected.append(candidates[0])
    return selected


def _load_exact_runs(graph_paths: Iterable[Path]) -> list[dict]:
    paths = [Path(path).expanduser().resolve() for path in graph_paths]
    selected: list[dict] = []
    for path in paths:
        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load graph snapshot {path}: {exc}") from exc
        process = graph.get("process") if isinstance(graph.get("process"), dict) else {}
        run = {
            "process_name": process.get("name") or path.parents[2].name,
            "run_id": graph.get("run_id") or path.parent.name,
            "generated_at": graph.get("generated_at"),
            "function_count": len(graph.get("functions", [])),
            "resource_count": len(graph.get("resources", [])),
            "interaction_count": len(graph.get("interactions", [])),
            "graph_path": path,
            "graph": graph,
        }
        selected.append(run)

    seen_names: set[str] = set()
    duplicates: set[str] = set()
    for run in selected:
        name = str(run["process_name"])
        if name in seen_names:
            duplicates.add(name)
        seen_names.add(name)
    if duplicates:
        raise ValueError(
            "A group can contain only one snapshot per process: "
            + ", ".join(sorted(duplicates))
        )
    if not selected:
        raise ValueError("No graph snapshots are available to combine.")
    return sorted(selected, key=lambda run: str(run["process_name"]))


def _shared_resources(selected: Iterable[dict]) -> list[dict]:
    joined: dict[tuple[str, str], dict] = {}
    for run in selected:
        process_name = str(run["process_name"])
        graph = run["graph"]
        resources = {
            str(resource.get("id")): resource
            for resource in graph.get("resources", [])
            if resource.get("id") is not None
        }
        for interaction in graph.get("interactions", []):
            resource = resources.get(str(interaction.get("resource_id")))
            if not resource:
                continue
            kind = str(resource.get("kind") or "unknown")
            name = str(resource.get("name") or resource.get("id"))
            entry = joined.setdefault(
                (kind, name),
                {
                    "key": f"{kind}:{name}",
                    "kind": kind,
                    "name": name,
                    "processes": set(),
                    "operations": set(),
                    "interaction_count": 0,
                },
            )
            entry["processes"].add(process_name)
            if interaction.get("operation"):
                entry["operations"].add(str(interaction["operation"]))
            entry["interaction_count"] += 1

    output = []
    for entry in joined.values():
        processes = sorted(entry.pop("processes"))
        operations = sorted(entry.pop("operations"))
        output.append(
            {
                **entry,
                "processes": processes,
                "operations": operations,
                "is_cross_process": len(processes) > 1,
            }
        )
    return sorted(output, key=lambda item: (item["kind"], item["name"]))


def write_group_manifest(
    results_root: Path,
    group_name: str,
    *,
    graph_paths: Iterable[Path] | None = None,
    process_names: Iterable[str] | None = None,
    policy: str = "latest-with-interactions",
    failures: Iterable[dict] | None = None,
    run_id: str | None = None,
) -> Path:
    """Pin process snapshots into one reusable multi-process group."""

    validate_group_name(group_name)
    results_root = results_root.expanduser().resolve()
    if graph_paths is not None:
        selected = _load_exact_runs(graph_paths)
        selection_policy = "exact-batch-snapshots"
    else:
        selected = select_process_runs(
            scan_graph_runs(results_root), process_names=process_names, policy=policy
        )
        selection_policy = policy

    generated_at = datetime.now(timezone.utc).isoformat()
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = results_root / "visualizer" / "groups" / group_name / "runs" / run_id
    suffix = 2
    while run_dir.exists():
        run_dir = run_dir.with_name(f"{run_id}-{suffix}")
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=False)

    members = []
    for run in selected:
        graph_path = Path(run["graph_path"])
        try:
            relative_graph = graph_path.relative_to(results_root)
        except ValueError:
            relative_graph = graph_path
        members.append(
            {
                "process_name": run["process_name"],
                "run_id": run["run_id"],
                "generated_at": run.get("generated_at"),
                "graph": str(relative_graph),
                "function_count": run["function_count"],
                "resource_count": run["resource_count"],
                "interaction_count": run["interaction_count"],
            }
        )

    shared_resources = _shared_resources(selected)
    manifest = {
        "schema_version": GROUP_SCHEMA_VERSION,
        "name": group_name,
        "run_id": run_dir.name,
        "generated_at": generated_at,
        "selection_policy": selection_policy,
        "processes": members,
        "failures": list(failures or []),
        "totals": {
            "processes": len(members),
            "functions": sum(item["function_count"] for item in members),
            "resources": sum(item["resource_count"] for item in members),
            "interactions": sum(item["interaction_count"] for item in members),
            "cross_process_resources": sum(
                1 for item in shared_resources if item["is_cross_process"]
            ),
        },
        "shared_resources": shared_resources,
    }
    manifest_path = run_dir / "group.json"
    _write_json(manifest_path, manifest)

    index_path = results_root / "visualizer" / "groups.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(index, list):
            index = []
    except (OSError, json.JSONDecodeError):
        index = []
    index.append(
        {
            "name": group_name,
            "run_id": run_dir.name,
            "generated_at": generated_at,
            "manifest": str(manifest_path.relative_to(results_root)),
            **manifest["totals"],
        }
    )
    _write_json(index_path, index)
    return manifest_path


def resolve_group_manifest(results_root: Path, selector: str | Path) -> Path:
    """Resolve an explicit manifest path, ``name@run``, or latest group name."""

    results_root = results_root.expanduser().resolve()
    direct = Path(selector).expanduser()
    if direct.is_file():
        return direct.resolve()

    value = str(selector)
    if "@" in value:
        name, group_run = value.rsplit("@", 1)
        candidate = (
            results_root
            / "visualizer"
            / "groups"
            / name
            / "runs"
            / group_run
            / "group.json"
        )
        if candidate.is_file():
            return candidate.resolve()
        raise ValueError(f"Process group not found: {value}")

    candidates = sorted(
        (results_root / "visualizer" / "groups" / value / "runs").glob(
            "*/group.json"
        ),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    if not candidates:
        raise ValueError(f"Process group not found: {value}")
    return candidates[0].resolve()


def load_group_manifest(results_root: Path, selector: str | Path) -> tuple[Path, dict]:
    path = resolve_group_manifest(results_root, selector)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load process group {path}: {exc}") from exc
    if not isinstance(manifest.get("processes"), list):
        raise ValueError(f"Invalid process group manifest: {path}")
    return path, manifest


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
