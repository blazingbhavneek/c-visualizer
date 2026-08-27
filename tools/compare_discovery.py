"""Compare one c-visualizer discovery index with a build-index snapshot.

The two pipelines do not emit the same surrounding metadata, so this tool
compares only the shared discovery domain:

* forkproc call sites and target packages;
* exact MFS file/record accesses;
* exact MFS queue accesses;
* dynamic queue hints;
* c-visualizer evidence status and provenance counts.

Paths are normalized before comparison.  A c-visualizer index is normally
per-process while ``index_chukyu_no_llm`` is aggregate; by default the build
snapshot is filtered to the process prefix recorded in the c-visualizer
metadata.  Use ``--all-reference`` to disable that filter.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


EXACT_FILES = {
    "mfs_file_access.json": "mfs_file",
    "mfs_queue_access.json": "mfs_queue",
}


@dataclass(frozen=True, order=True)
class DiscoveryRecord:
    """One comparable exact or dynamic discovery record."""

    resource: str
    path: str
    line: int
    operation: str
    value: str = ""
    raw: str = ""

    @property
    def site_key(self) -> tuple[str, str, int, str]:
        return (self.resource, self.path, self.line, self.operation)

    def as_dict(self) -> dict[str, Any]:
        result = {
            "resource": self.resource,
            "file": self.path,
            "line": self.line,
            "operation": self.operation,
        }
        if self.value:
            result["value"] = self.value
        if self.raw:
            result["raw"] = self.raw
        return result


@dataclass
class LoadedIndex:
    metadata: dict[str, Any]
    exact: set[DiscoveryRecord]
    dynamic: set[DiscoveryRecord]
    evidence_sites: set[tuple[str, int, str, int]]
    evidence_statuses: Counter[str]
    evidence_provenance: Counter[str]


def _read_json(directory: Path, filename: str, default: Any) -> Any:
    path = directory / filename
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_path(value: str | Path, source_root: Path | None = None) -> str:
    """Normalize absolute/relative source paths to forward-slash form."""

    text = str(value or "").replace("\\", "/")
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute() and source_root is not None:
        try:
            text = path.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            text = path.resolve().as_posix()
    elif not path.is_absolute():
        text = re.sub(r"^\./+", "", text)
    return text


def _record_file_access(
    payload: dict[str, list[dict[str, Any]]],
    resource: str,
    source_root: Path | None,
) -> Iterable[DiscoveryRecord]:
    for value, entries in payload.items():
        for entry in entries or []:
            yield DiscoveryRecord(
                resource=resource,
                path=normalize_path(entry.get("file", ""), source_root),
                line=int(entry.get("line", 0)),
                operation=str(entry.get("lock", "")),
                value=str(value),
                raw=str(entry.get("fno_raw", "")),
            )


def _record_forkproc(
    payload: dict[str, list[dict[str, Any]]], source_root: Path | None
) -> Iterable[DiscoveryRecord]:
    for caller, entries in payload.items():
        for entry in entries or []:
            yield DiscoveryRecord(
                resource="forkproc",
                path=normalize_path(caller, source_root),
                line=int(entry.get("line", 0)),
                operation="FORKPROC",
                value=str(entry.get("target", "")),
            )


def _record_dynamic(
    payload: dict[str, list[dict[str, Any]]], source_root: Path | None
) -> Iterable[DiscoveryRecord]:
    for caller, entries in payload.items():
        for entry in entries or []:
            yield DiscoveryRecord(
                resource="mfs_queue_dynamic",
                path=normalize_path(caller, source_root),
                line=int(entry.get("line", 0)),
                operation=str(entry.get("lock", "")),
                raw=str(entry.get("expr", "")),
            )


def _metadata_process_prefix(
    metadata: dict[str, Any], source_root: Path | None
) -> str | None:
    process_root = metadata.get("process_root")
    metadata_root = metadata.get("source_root")
    if not process_root:
        return None
    chosen_root = source_root or (Path(metadata_root) if metadata_root else None)
    if chosen_root is None:
        return None
    try:
        prefix = Path(process_root).resolve().relative_to(chosen_root.resolve()).as_posix()
    except ValueError:
        return None
    return prefix.rstrip("/") or None


def _in_prefix(path: str, prefix: str | None) -> bool:
    return not prefix or path == prefix or path.startswith(prefix + "/")


def _load_common_index(
    directory: str | Path,
    *,
    source_root: str | Path | None = None,
    load_evidence: bool = False,
) -> LoadedIndex:
    directory = Path(directory).expanduser().resolve()
    root = Path(source_root).expanduser().resolve() if source_root else None
    metadata = _read_json(directory, "index_metadata.json", {})

    exact: set[DiscoveryRecord] = set()
    for filename, resource in EXACT_FILES.items():
        exact.update(
            _record_file_access(_read_json(directory, filename, {}), resource, root)
        )
    exact.update(
        _record_forkproc(
            _read_json(directory, "forkproc_targets_by_caller.json", {}), root
        )
    )

    dynamic = set(
        _record_dynamic(
            _read_json(directory, "mfs_dynamic_addque.json", {}), root
        )
    )

    evidence_sites: set[tuple[str, int, str, int]] = set()
    statuses: Counter[str] = Counter()
    provenance: Counter[str] = Counter()
    if load_evidence:
        evidence_path = directory / "discovery_facts.csv"
        if evidence_path.is_file():
            with evidence_path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    evidence_sites.add(
                        (
                            normalize_path(row.get("target_site_file", ""), root),
                            int(row.get("target_site_line", 0) or 0),
                            str(row.get("target_function", "")),
                            int(row.get("arg_index", 0) or 0),
                        )
                    )
                    statuses[str(row.get("status", ""))] += 1
                    resolved_by = str(row.get("resolved_by", ""))
                    if resolved_by:
                        provenance[resolved_by] += 1

    return LoadedIndex(
        metadata=metadata if isinstance(metadata, dict) else {},
        exact=exact,
        dynamic=dynamic,
        evidence_sites=evidence_sites,
        evidence_statuses=statuses,
        evidence_provenance=provenance,
    )


def _filter_index(index: LoadedIndex, prefix: str | None) -> LoadedIndex:
    if not prefix:
        return index
    return LoadedIndex(
        metadata=index.metadata,
        exact={record for record in index.exact if _in_prefix(record.path, prefix)},
        dynamic={record for record in index.dynamic if _in_prefix(record.path, prefix)},
        evidence_sites={site for site in index.evidence_sites if _in_prefix(site[0], prefix)},
        evidence_statuses=index.evidence_statuses,
        evidence_provenance=index.evidence_provenance,
    )


def _by_site(records: set[DiscoveryRecord]) -> dict[tuple, set[str]]:
    grouped: dict[tuple, set[str]] = {}
    for record in records:
        grouped.setdefault(record.site_key, set()).add(record.value)
    return grouped


def _sorted_records(records: Iterable[DiscoveryRecord]) -> list[dict[str, Any]]:
    return [record.as_dict() for record in sorted(records)]


def _value_comparison(
    reference: set[DiscoveryRecord], candidate: set[DiscoveryRecord]
) -> dict[str, Any]:
    reference_by_site = _by_site(reference)
    candidate_by_site = _by_site(candidate)
    all_sites = set(reference_by_site) | set(candidate_by_site)

    shared: set[DiscoveryRecord] = set()
    reference_only: set[DiscoveryRecord] = set()
    candidate_only: set[DiscoveryRecord] = set()
    disagreements: list[dict[str, Any]] = []

    for site in sorted(all_sites):
        reference_values = reference_by_site.get(site, set())
        candidate_values = candidate_by_site.get(site, set())
        common_values = reference_values & candidate_values
        shared.update(
            DiscoveryRecord(site[0], site[1], site[2], site[3], value)
            for value in common_values
        )
        reference_only.update(
            DiscoveryRecord(site[0], site[1], site[2], site[3], value)
            for value in reference_values - common_values
        )
        candidate_only.update(
            DiscoveryRecord(site[0], site[1], site[2], site[3], value)
            for value in candidate_values - common_values
        )
        if reference_values and candidate_values and reference_values != candidate_values:
            disagreements.append(
                {
                    "resource": site[0],
                    "file": site[1],
                    "line": site[2],
                    "operation": site[3],
                    "reference_values": sorted(reference_values),
                    "cvisualizer_values": sorted(candidate_values),
                }
            )

    return {
        "shared_exact": _sorted_records(shared),
        "reference_only": _sorted_records(reference_only),
        "cvisualizer_only": _sorted_records(candidate_only),
        "value_disagreements": disagreements,
        "reference_site_count": len(reference_by_site),
        "cvisualizer_site_count": len(candidate_by_site),
        "site_union_count": len(set(reference_by_site) | set(candidate_by_site)),
        "site_intersection_count": len(set(reference_by_site) & set(candidate_by_site)),
    }


def compare_indexes(
    cvisualizer_index: str | Path,
    build_index: str | Path,
    *,
    source_root: str | Path | None = None,
    process_prefix: str | None = None,
    all_reference: bool = False,
) -> dict[str, Any]:
    """Return a deterministic JSON-serializable comparison report."""

    candidate = _load_common_index(
        cvisualizer_index, source_root=source_root, load_evidence=True
    )
    reference = _load_common_index(build_index, source_root=source_root)
    prefix = process_prefix
    if prefix:
        prefix = normalize_path(prefix)
    elif not all_reference:
        prefix = _metadata_process_prefix(candidate.metadata, Path(source_root) if source_root else None)
    reference = _filter_index(reference, prefix)

    exact_report = _value_comparison(reference.exact, candidate.exact)
    dynamic_reference = reference.dynamic
    dynamic_candidate = candidate.dynamic
    dynamic_shared = dynamic_reference & dynamic_candidate

    raw_disagreements = []
    reference_raw: dict[tuple, set[str]] = {}
    candidate_raw: dict[tuple, set[str]] = {}
    for record in reference.exact:
        reference_raw.setdefault((record.resource, record.path, record.line, record.operation, record.value), set()).add(record.raw)
    for record in candidate.exact:
        candidate_raw.setdefault((record.resource, record.path, record.line, record.operation, record.value), set()).add(record.raw)
    for identity in sorted(set(reference_raw) & set(candidate_raw)):
        if reference_raw[identity] != candidate_raw[identity]:
            raw_disagreements.append(
                {
                    "resource": identity[0],
                    "file": identity[1],
                    "line": identity[2],
                    "operation": identity[3],
                    "value": identity[4],
                    "reference_raw": sorted(reference_raw[identity]),
                    "cvisualizer_raw": sorted(candidate_raw[identity]),
                }
            )

    candidate_metadata_counts = candidate.metadata.get("counts") or {}
    return {
        "schema_version": 1,
        "reference": {
            "index": str(Path(build_index).expanduser().resolve()),
            "pipeline": "build-index",
            "process_prefix": prefix or "",
            "exact_record_count": len(reference.exact),
            "dynamic_record_count": len(reference.dynamic),
            "provenance": {"REGEX_INDEX": len(reference.exact)},
        },
        "cvisualizer": {
            "index": str(Path(cvisualizer_index).expanduser().resolve()),
            "pipeline": "c-visualizer",
            "process_name": candidate.metadata.get("process_name", ""),
            "resolver": candidate.metadata.get("resolver", ""),
            "target_registry": candidate.metadata.get("target_registry", {}),
            "target_site_inventory_count": int(candidate_metadata_counts.get("target_sites", len(candidate.evidence_sites))),
            "exact_record_count": len(candidate.exact),
            "dynamic_record_count": len(candidate.dynamic),
            "evidence_statuses": dict(sorted(candidate.evidence_statuses.items())),
            "evidence_provenance": dict(sorted(candidate.evidence_provenance.items())),
        },
        "exact": exact_report,
        "dynamic": {
            "shared": _sorted_records(dynamic_shared),
            "reference_only": _sorted_records(dynamic_reference - dynamic_shared),
            "cvisualizer_only": _sorted_records(dynamic_candidate - dynamic_shared),
        },
        "raw_expression_disagreements": raw_disagreements,
        "target_sites": {
            "cvisualizer_inventory": int(candidate_metadata_counts.get("target_sites", len(candidate.evidence_sites))),
            "cvisualizer_evidence_sites": len(candidate.evidence_sites),
            "comparable_site_union": exact_report["site_union_count"],
            "comparable_site_intersection": exact_report["site_intersection_count"],
        },
    }


def _summary(report: dict[str, Any]) -> str:
    exact = report["exact"]
    dynamic = report["dynamic"]
    visualizer = report["cvisualizer"]
    lines = [
        "Discovery comparison",
        f"  reference:    {report['reference']['index']}",
        f"  c-visualizer: {visualizer['index']} ({visualizer.get('resolver') or 'unknown'})",
        f"  process scope: {report['reference']['process_prefix'] or 'all reference records'}",
        "",
        f"  comparable sites: {exact['site_intersection_count']} shared / {exact['site_union_count']} union",
        f"  exact records:    {len(exact['shared_exact'])} shared, "
        f"{len(exact['reference_only'])} regex-only, {len(exact['cvisualizer_only'])} c-visualizer-only",
        f"  value disagreements: {len(exact['value_disagreements'])}",
        f"  dynamic queue: {len(dynamic['shared'])} shared, "
        f"{len(dynamic['reference_only'])} regex-only, {len(dynamic['cvisualizer_only'])} c-visualizer-only",
        f"  evidence statuses: {json.dumps(visualizer['evidence_statuses'], sort_keys=True)}",
        f"  evidence provenance: {json.dumps(visualizer['evidence_provenance'], sort_keys=True)}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cvisualizer-index", type=Path, required=True)
    parser.add_argument("--build-index", type=Path, required=True)
    parser.add_argument(
        "--source-root",
        type=Path,
        help="Common source root used to relativize absolute paths.",
    )
    parser.add_argument(
        "--process-prefix",
        help="Reference path prefix to compare, e.g. t-cha/src/cha100d.",
    )
    parser.add_argument(
        "--all-reference",
        action="store_true",
        help="Compare against every build-index record instead of the candidate process scope.",
    )
    parser.add_argument("--json", action="store_true", help="Write the full report as JSON.")
    parser.add_argument("--output", type=Path, help="Also write the full JSON report to this file.")
    args = parser.parse_args(argv)

    report = compare_indexes(
        args.cvisualizer_index,
        args.build_index,
        source_root=args.source_root,
        process_prefix=args.process_prefix,
        all_reference=args.all_reference,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_summary(report))
        if args.output:
            print(f"\nFull report: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
