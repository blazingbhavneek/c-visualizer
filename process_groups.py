"""Discover process projects and persist reproducible multi-process groups.

A group deliberately references one immutable graph snapshot per process rather
than merging their function ID namespaces.  That keeps process ownership intact
while still giving the frontend enough information to join IPC resources across
the whole pipeline.
"""

from __future__ import annotations

import json
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


def load_project_state(json_dir: Path):
    """Load one process family's configuration without changing legacy loaders."""
    import pickle

    from state.state import State

    json_dir = json_dir.expanduser().resolve()
    state = State()
    state.set(
        "FUNCTION_TYPES",
        json.loads((json_dir / "mpf_data.json").read_text(encoding="utf-8")),
    )
    state.set(
        "FUNCTION_POINTER_ARGS",
        json.loads(
            (json_dir / "function_callback_info.json").read_text(encoding="utf-8")
        ),
    )
    function_map_pickle = json_dir.parent / "pickle_data" / "function_map.pkl"
    if function_map_pickle.is_file():
        with function_map_pickle.open("rb") as handle:
            function_map = pickle.load(handle)
    else:
        function_map = json.loads(
            (json_dir / "combined_data.json").read_text(encoding="utf-8")
        )
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
    """Resolve process paths and reject invalid or ambiguous batch inputs."""

    resolved: list[Path] = []
    seen_paths: set[Path] = set()
    names: dict[str, Path] = {}
    for candidate in projects:
        project = candidate.expanduser().resolve()
        if project in seen_paths:
            continue
        if not project.is_dir():
            raise ValueError(f"Process directory does not exist: {project}")
        if not (project / "Makefile").is_file():
            raise ValueError(f"Process needs a Makefile: {project}")
        previous = names.get(project.name)
        if previous is not None and previous != project:
            raise ValueError(
                "Process names must be unique in one group; "
                f"both {previous} and {project} are named {project.name!r}."
            )
        seen_paths.add(project)
        names[project.name] = project
        resolved.append(project)
    if not resolved:
        raise ValueError("No process directories were selected.")
    return resolved


def validate_group_name(group_name: str) -> str:
    """Validate a group name before a potentially long analyzer batch starts."""

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
