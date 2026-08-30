"""Whole-repository build-index adapter for c-visualizer batch runs.

The c-visualizer resolver is intentionally per-process: that is where its
source graph and value-flow evidence are scoped.  The original forkproc
pipeline is intentionally whole-repository: it owns Makefile/program
metadata, reverse indexes, MFS definitions/macros, collision information and
the unified graph.

This module joins those two scopes without copying the original structural
parser.  It runs ``forkproc_checker/build_index.py --no-valueflow`` to create
the complete structural index, then replaces the five discovery artifacts
with the deterministic union of the c-visualizer per-process indexes and
rebuilds ``graph.json`` from the resulting directory.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

from discovery_index import EVIDENCE_COLUMNS


_C_VISUALIZER_ROOT = Path(__file__).resolve().parents[1]
_BUILD_INDEX = _C_VISUALIZER_ROOT / "build_index.py"
_BUILD_GRAPH = _C_VISUALIZER_ROOT / "build_graph.py"

_DISCOVERY_JSON_FILES = (
    "forkproc_callers.json",
    "forkproc_targets_by_caller.json",
    "mfs_file_access.json",
    "mfs_queue_access.json",
    "mfs_dynamic_addque.json",
)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary_name, path)
    except Exception:
        try:
            Path(temporary_name).unlink()
        except OSError:
            pass
        raise


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _fno_key(value: str) -> tuple[int, Any]:
    return (0, int(value)) if str(value).isdigit() else (1, str(value))


def _record_key(value: dict[str, Any]) -> tuple:
    return (
        str(value.get("file", "")),
        int(value.get("line", 0) or 0),
        str(value.get("lock", "")),
        str(value.get("fno_raw", "")),
    )


def _merge_access_indexes(
    process_indexes: Iterable[Path], filename: str
) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, dict[tuple, dict[str, Any]]] = defaultdict(dict)
    for index_dir in process_indexes:
        payload = _read_json(index_dir / filename, {})
        if not isinstance(payload, dict):
            continue
        for fno, entries in payload.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                merged[str(fno)][_record_key(entry)] = {
                    "file": str(entry.get("file", "")),
                    "line": int(entry.get("line", 0) or 0),
                    "lock": str(entry.get("lock", "")),
                    "fno_raw": str(entry.get("fno_raw", "")),
                }
    return {
        fno: [merged[fno][key] for key in sorted(merged[fno])]
        for fno in sorted(merged, key=_fno_key)
    }


def _merge_forkproc_callers(process_indexes: Iterable[Path]) -> dict[str, list[str]]:
    merged: dict[str, set[str]] = defaultdict(set)
    for index_dir in process_indexes:
        payload = _read_json(index_dir / "forkproc_callers.json", {})
        if not isinstance(payload, dict):
            continue
        for target, callers in payload.items():
            if isinstance(callers, list):
                merged[str(target)].update(str(caller) for caller in callers)
    return {
        target: sorted(callers)
        for target, callers in sorted(merged.items())
    }


def _merge_forkproc_targets(process_indexes: Iterable[Path]) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, set[tuple[int, str]]] = defaultdict(set)
    for index_dir in process_indexes:
        payload = _read_json(index_dir / "forkproc_targets_by_caller.json", {})
        if not isinstance(payload, dict):
            continue
        for caller, entries in payload.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                merged[str(caller)].add(
                    (int(entry.get("line", 0) or 0), str(entry.get("target", "")))
                )
    return {
        caller: [
            {"line": line, "target": target}
            for line, target in sorted(entries)
        ]
        for caller, entries in sorted(merged.items())
    }


def _merge_dynamic_indexes(process_indexes: Iterable[Path]) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, dict[tuple, dict[str, Any]]] = defaultdict(dict)
    for index_dir in process_indexes:
        payload = _read_json(index_dir / "mfs_dynamic_addque.json", {})
        if not isinstance(payload, dict):
            continue
        for caller, entries in payload.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                value = {
                    "line": int(entry.get("line", 0) or 0),
                    "expr": str(entry.get("expr", "")),
                    "lock": str(entry.get("lock", "")),
                }
                merged[str(caller)][(value["line"], value["expr"], value["lock"])] = value
    return {
        caller: [merged[caller][key] for key in sorted(merged[caller])]
        for caller in sorted(merged)
    }


def _load_process_manifest(indexes: Iterable[Path]) -> list[dict[str, Any]]:
    """Per-process ownership manifest built from index metadata.

    Each entry carries canonical absolute paths.  Ownership is decided by
    longest-prefix match on the process root, never by basename; a process
    directory named ``lib*`` without executable roots is library-owned.
    """
    entries: list[dict[str, Any]] = []
    for index_dir in indexes:
        metadata = _read_json(index_dir / "index_metadata.json", {})
        if not isinstance(metadata, dict):
            continue
        process_root = str(metadata.get("process_root") or "")
        if not process_root:
            continue
        try:
            resolved_root = str(Path(process_root).resolve())
        except OSError:
            continue
        root_diagnostics = metadata.get("root_diagnostics") or {}
        accepted = root_diagnostics.get("accepted_entry_points") or []
        entries.append(
            {
                "process_name": str(
                    metadata.get("process_name")
                    or index_dir.parent.name
                ),
                "process_root": resolved_root,
                "source_root": str(
                    Path(str(metadata.get("source_root") or "")).resolve()
                    if metadata.get("source_root")
                    else ""
                ),
                "is_library": Path(resolved_root).name.startswith("lib"),
                "is_executable": bool(accepted)
                and str(root_diagnostics.get("root_state") or "")
                != "NO_PROCESS_ROOT",
            }
        )
    # Longest path first so a specific process root wins over a parent scope.
    entries.sort(key=lambda entry: len(entry["process_root"].rstrip(os.sep)), reverse=True)
    return entries


def _owner_for_path(
    path: str | Path, manifest: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The process whose root is the longest prefix of ``path``."""
    if not path:
        return None
    try:
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            return None
        resolved = resolved.resolve()
    except OSError:
        return None
    resolved_text = str(resolved)
    best = None
    for entry in manifest:
        root = entry["process_root"]
        if resolved_text == root or resolved_text.startswith(root + os.sep):
            if best is None or len(root) > len(best["process_root"]):
                best = entry
    return best


def _owner_resolution_statuses(
    indexes: Iterable[Path], manifest: list[dict[str, Any]]
) -> dict[str, dict[tuple[str, int, int], str]]:
    """Owner-process fact rows keyed by (absolute site file, line, arg index).

    Values are the strongest owner-side outcome: ``resolved`` (an EXACT row
    with root-proven reachability), ``present`` (some fact exists), or
    ``absent`` is left out of the map entirely.
    """
    root_proven = {"DIRECT_ROOT", "CALLBACK"}
    by_process: dict[str, dict[tuple[str, int, int], str]] = {}
    for index_dir in indexes:
        metadata = _read_json(index_dir / "index_metadata.json", {})
        if not isinstance(metadata, dict):
            continue
        process_name = str(metadata.get("process_name") or index_dir.parent.name)
        source_root = str(metadata.get("source_root") or "")
        path = index_dir / "discovery_facts.csv"
        if not path.is_file():
            continue
        facts: dict[tuple[str, int, int], str] = by_process.setdefault(
            process_name, {}
        )
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                site_file = str(raw.get("target_site_file", "") or "")
                if not site_file:
                    continue
                site_path = Path(site_file)
                if not site_path.is_absolute() and source_root:
                    site_path = Path(source_root) / site_path
                try:
                    site_key_file = str(site_path.resolve())
                except OSError:
                    continue
                try:
                    line = int(raw.get("target_site_line", 0) or 0)
                    arg_index = int(raw.get("arg_index", 0) or 0)
                except ValueError:
                    continue
                key = (site_key_file, line, arg_index)
                reachability = str(raw.get("reachability", "") or "")
                status = str(raw.get("status", "") or "")
                if status == "EXACT" and reachability in root_proven:
                    facts[key] = "resolved"
                elif facts.get(key) != "resolved":
                    facts[key] = facts.get(key, "present")
    return by_process


def _merge_evidence(process_indexes: Iterable[Path]) -> list[dict[str, str]]:
    rows: dict[tuple[str, ...], dict[str, str]] = {}
    for index_dir in process_indexes:
        path = index_dir / "discovery_facts.csv"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                row = {column: str(raw.get(column, "")) for column in EVIDENCE_COLUMNS}
                rows[tuple(row[column] for column in EVIDENCE_COLUMNS)] = row
    return [rows[key] for key in sorted(rows)]


def _write_evidence(path: Path, rows: list[dict[str, str]]) -> None:
    from io import StringIO

    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=EVIDENCE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(path, stream.getvalue())


def _rebuild_collisions(
    structural_dir: Path,
    file_access: dict[str, list[dict[str, Any]]],
    queue_access: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    macros = _read_json(structural_dir / "mfs_fno_macros.json", {})
    base_re = re.compile(r"\s*[+\-]\s*\d+$")
    result: dict[str, dict[str, Any]] = {}
    fnos = set(file_access) | set(queue_access)
    for fno in sorted(fnos, key=_fno_key):
        groups: dict[str, set[str]] = defaultdict(set)
        for entry in list(file_access.get(fno, [])) + list(queue_access.get(fno, [])):
            raw = str(entry.get("fno_raw", ""))
            base = base_re.sub("", raw).strip() if raw else str(fno)
            groups[base].add(str(entry.get("file", "")))
        if len(groups) >= 2:
            result[str(fno)] = {
                "macros": macros.get(str(fno), []),
                "groups": {
                    base: sorted(files) for base, files in sorted(groups.items())
                },
            }
    return result


def classify_cross_process_rows(
    evidence: list[dict[str, str]],
    manifest: list[dict[str, Any]],
    owner_statuses: dict[str, dict[tuple[str, int, int], str]],
    source_root: str | Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    """Rewrite out-of-process evidence rows with owner information.

    Returns ``(evidence, cross_process_rows, counts)``.  A target site
    outside the observing process is evidence for the observer but its
    ownership and resolution belong to the process (or library) whose root
    contains the site.  These rows never enter any exact JSON index:
    per-process promotion already excludes out-of-process sites, and the
    aggregate only unions per-process exact indexes.
    """
    source_root = Path(source_root)
    cross_process_rows: list[dict[str, str]] = []
    counts = {
        "cross_process_caller_rows": 0,
        "out_of_process_scope_rows": 0,
        "unresolved_owner_rows": 0,
    }
    observing_roots = {
        entry["process_name"]: entry["process_root"] for entry in manifest
    }
    for row in evidence:
        reachability = row.get("reachability", "") or ""
        if reachability not in ("", "UNKNOWN", "OUT_OF_PROCESS_SCOPE"):
            continue
        observed = row.get("evidence_process", "") or ""
        site_file = row.get("target_site_file", "") or ""
        if not site_file:
            continue
        site_path = Path(site_file)
        if not site_path.is_absolute():
            site_path = source_root / site_path
        try:
            site_abs = site_path.resolve()
        except OSError:
            continue
        # A site under the observing process's own root is in-process
        # evidence; only rows outside it are cross-process candidates.
        observing_root = observing_roots.get(observed, "")
        if observing_root and (
            str(site_abs) == observing_root
            or str(site_abs).startswith(observing_root + os.sep)
        ):
            continue
        owner = _owner_for_path(site_abs, manifest)
        if owner is None:
            row["reachability"] = (
                reachability if reachability else "OUT_OF_PROCESS_SCOPE"
            )
            if row["reachability"] == "OUT_OF_PROCESS_SCOPE":
                counts["out_of_process_scope_rows"] += 1
            continue
        owner_name = owner["process_name"]
        row["reachability"] = "CROSS_PROCESS_CALLER"
        row["owner_process"] = owner_name
        row["owner_kind"] = "library" if owner["is_library"] else "process"
        site_key = (
            str(site_abs),
            int(row.get("target_site_line", 0) or 0),
            int(row.get("arg_index", 0) or 0),
        )
        owner_status = owner_statuses.get(owner_name, {}).get(site_key, "absent")
        if owner_status == "absent" or not owner["is_executable"]:
            counts["unresolved_owner_rows"] += 1
        counts["cross_process_caller_rows"] += 1
        try:
            line = int(row.get("target_site_line", 0) or 0)
        except ValueError:
            line = 0
        cross_process_rows.append(
            {
                "target_site_file": site_file,
                "target_site_line": str(line),
                "target_function": row.get("target_function", "") or "",
                "observed_from_process": observed,
                "owner_process": owner_name,
                "owner_kind": row["owner_kind"],
                "owner_resolution_status": owner_status,
                "owner_reachability": row.get("reachability", "") or "",
            }
        )
    cross_process_rows.sort(
        key=lambda item: (
            item["target_site_file"],
            item["target_site_line"],
            item["target_function"],
            item["observed_from_process"],
        )
    )
    return evidence, cross_process_rows, counts


def merge_cvisualizer_discoveries(
    structural_dir: str | Path,
    process_indexes: Iterable[str | Path],
    *,
    source_root: str | Path,
    process_count: int,
    failed_processes: int = 0,
) -> Path:
    """Overlay aggregate c-visualizer discovery records on structural indexes."""
    structural_dir = Path(structural_dir).expanduser().resolve()
    indexes = [Path(path).expanduser().resolve() for path in process_indexes]
    indexes = sorted({path for path in indexes if path.is_dir()}, key=str)

    forkproc_callers = _merge_forkproc_callers(indexes)
    forkproc_targets = _merge_forkproc_targets(indexes)
    file_access = _merge_access_indexes(indexes, "mfs_file_access.json")
    queue_access = _merge_access_indexes(indexes, "mfs_queue_access.json")
    dynamic = _merge_dynamic_indexes(indexes)
    evidence = _merge_evidence(indexes)

    # Cross-process classification: see classify_cross_process_rows.
    manifest = _load_process_manifest(indexes)
    owner_statuses = _owner_resolution_statuses(indexes, manifest)
    evidence, cross_process_rows, cross_counts = classify_cross_process_rows(
        evidence, manifest, owner_statuses, source_root
    )
    cross_process_count = cross_counts["cross_process_caller_rows"]
    out_of_scope_count = cross_counts["out_of_process_scope_rows"]
    unresolved_owner_count = cross_counts["unresolved_owner_rows"]

    overlays = {
        "forkproc_callers.json": forkproc_callers,
        "forkproc_targets_by_caller.json": forkproc_targets,
        "mfs_file_access.json": file_access,
        "mfs_queue_access.json": queue_access,
        "mfs_dynamic_addque.json": dynamic,
        "mfs_fno_collisions.json": _rebuild_collisions(
            structural_dir, file_access, queue_access
        ),
    }
    for filename, payload in overlays.items():
        _atomic_write(structural_dir / filename, _json_text(payload))
    _write_evidence(structural_dir / "discovery_facts.csv", evidence)

    cross_process_stream = StringIO()
    cross_process_columns = (
        "target_site_file",
        "target_site_line",
        "target_function",
        "observed_from_process",
        "owner_process",
        "owner_kind",
        "owner_resolution_status",
        "owner_reachability",
    )
    cross_process_writer = csv.DictWriter(
        cross_process_stream, fieldnames=cross_process_columns, lineterminator="\n"
    )
    cross_process_writer.writeheader()
    cross_process_writer.writerows(cross_process_rows)
    _atomic_write(
        structural_dir / "cross_process_callers.csv", cross_process_stream.getvalue()
    )

    metadata_sources = [
        _read_json(index_dir / "index_metadata.json", {}) for index_dir in indexes
    ]
    first_metadata = next(
        (metadata for metadata in metadata_sources if isinstance(metadata, dict)), {}
    )
    counts = {
        "processes_requested": process_count,
        "processes_included": len(indexes),
        "processes_failed": failed_processes,
        "evidence_facts": len(evidence),
        "forkproc_callers": len(forkproc_callers),
        "mfs_file_access_entries": sum(len(entries) for entries in file_access.values()),
        "mfs_queue_access_entries": sum(len(entries) for entries in queue_access.values()),
        "mfs_dynamic_addque_entries": sum(len(entries) for entries in dynamic.values()),
        "cross_process_caller_rows": cross_process_count,
        "out_of_process_scope_rows": out_of_scope_count,
        "unresolved_owner_rows": unresolved_owner_count,
    }
    metadata = {
        "schema_version": 2,
        "pipeline": "c-visualizer",
        "structural_backend": "forkproc_checker/build_index.py",
        "structural_mode": "regex-baseline-with-cvisualizer-discovery-overlay",
        "resolver": sorted(
            {
                str(metadata.get("resolver", ""))
                for metadata in metadata_sources
                if isinstance(metadata, dict) and metadata.get("resolver")
            }
        ),
        "source_root": str(Path(source_root).expanduser().resolve()),
        "source_scope": "whole-repository",
        "discovery_scope": "whole-repository" if failed_processes == 0 else "partial",
        "target_registry": first_metadata.get("target_registry", {}),
        "process_count": process_count,
        "included_process_indexes": [str(path) for path in indexes],
        "counts": counts,
        "notes": [
            "The 16 structural index artifacts come from the existing build-index stages.",
            "The five discovery artifacts are the deterministic union of successful c-visualizer process indexes.",
            "graph.json is rebuilt after the c-visualizer discovery overlay.",
        ],
    }
    _atomic_write(
        structural_dir / "index_metadata.json",
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    )

    # Import the canonical graph builder only after the structural builder has
    # completed.  It reads the same 16-file directory as build_index.py.
    sys.path.insert(0, str(_C_VISUALIZER_ROOT))
    try:
        from build_graph import build_graph

        graph = build_graph(structural_dir)
    finally:
        try:
            sys.path.remove(str(_C_VISUALIZER_ROOT))
        except ValueError:
            pass
    _atomic_write(structural_dir / "graph.json", _json_text(graph))
    return structural_dir


def run_structural_builder(source_root: str | Path, output_dir: str | Path) -> Path:
    """Run the existing full regex structural pipeline without value-flow."""
    source_root = Path(source_root).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"Aggregate source root does not exist: {source_root}")
    command = [
        sys.executable,
        str(_BUILD_INDEX),
        "--root",
        str(source_root),
        "-o",
        str(output_dir),
        "--no-valueflow",
    ]
    completed = subprocess.run(
        command,
        cwd=str(_C_VISUALIZER_ROOT),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(output_dir / "build_index.log", completed.stdout or "")
    if completed.returncode != 0:
        raise RuntimeError(
            "build_index structural stage failed with exit code "
            f"{completed.returncode}; see {output_dir / 'build_index.log'}"
        )
    return output_dir


def build_aggregate_index(
    *,
    source_root: str | Path,
    output_dir: str | Path,
    process_indexes: Iterable[str | Path],
    process_count: int,
    failed_processes: int = 0,
) -> Path:
    """Build and overlay a whole-repository c-visualizer index."""
    structural_dir = run_structural_builder(source_root, output_dir)
    return merge_cvisualizer_discoveries(
        structural_dir,
        process_indexes,
        source_root=source_root,
        process_count=process_count,
        failed_processes=failed_processes,
    )
