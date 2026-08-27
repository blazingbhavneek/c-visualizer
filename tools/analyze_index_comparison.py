#!/usr/bin/env python3
"""Statistical comparison of the existing c-visualizer and legacy indexes.

This script is deliberately read-only.  It compares the index artifacts that
already exist on disk; it does not invoke either pipeline.

The report keeps two questions separate:

* exact graph reduction: how many exact records each pipeline promotes into
  its JSON indexes;
* evidence quality: how many c-visualizer call sites are retained in the
  evidence CSV, and how they are classified/provenanced.

Usage from the c-visualizer directory::

    .venv/bin/python tools/analyze_index_comparison.py \
      --cvisualizer-index results/csv_results/index \
      --build-index ../index \
      --source-root /home/chukyu \
      --output-dir results/csv_results/analysis
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


FILE_OPERATIONS = {
    "READ",
    "WRITE",
    "FWRITE",
    "CLEAR",
    "GETREC",
    "GETREC_D",
    "READREC",
    "UPDATEREC",
    "UPDATEREC_D",
    "WRITEREC",
    "COPYFILE_FROM",
    "COPYFILE_TO",
    "COPYREC_FROM",
    "COPYREC_TO",
}
QUEUE_OPERATIONS = {"ADDQUE", "DELQUE"}


@dataclass(frozen=True, order=True)
class Record:
    resource: str
    file: str
    line: int
    operation: str
    value: str = ""
    raw: str = ""

    @property
    def site(self) -> tuple[str, str, int, str]:
        return self.resource, self.file, self.line, self.operation


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def normalise_path(value: str, source_root: Path | None) -> str:
    text = str(value or "").replace("\\", "/")
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute() and source_root is not None:
        try:
            return path.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()
    return re.sub(r"^\./+", "", text)


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def load_exact_index(directory: Path, source_root: Path | None) -> set[Record]:
    records: set[Record] = set()

    for filename, resource in (
        ("mfs_file_access.json", "mfs_file"),
        ("mfs_queue_access.json", "mfs_queue"),
    ):
        payload = read_json(directory / filename, {})
        if not isinstance(payload, dict):
            continue
        for value, entries in payload.items():
            for entry in entries or []:
                records.add(
                    Record(
                        resource,
                        normalise_path(str(entry.get("file", "")), source_root),
                        int_value(entry.get("line")),
                        str(entry.get("lock", "")),
                        str(value),
                        str(entry.get("fno_raw", "")),
                    )
                )

    payload = read_json(directory / "forkproc_targets_by_caller.json", {})
    if isinstance(payload, dict):
        for caller, entries in payload.items():
            for entry in entries or []:
                records.add(
                    Record(
                        "forkproc",
                        normalise_path(str(caller), source_root),
                        int_value(entry.get("line")),
                        "FORKPROC",
                        str(entry.get("target", "")),
                    )
                )
    return records


def load_dynamic_index(directory: Path, source_root: Path | None) -> set[Record]:
    payload = read_json(directory / "mfs_dynamic_addque.json", {})
    records: set[Record] = set()
    if not isinstance(payload, dict):
        return records
    for caller, entries in payload.items():
        for entry in entries or []:
            records.add(
                Record(
                    "mfs_queue_dynamic",
                    normalise_path(str(caller), source_root),
                    int_value(entry.get("line")),
                    str(entry.get("lock", "")),
                    raw=str(entry.get("expr", "")),
                )
            )
    return records


def evidence_resource(operation: str) -> str:
    if operation == "FORKPROC":
        return "forkproc"
    if operation in QUEUE_OPERATIONS:
        return "mfs_queue"
    if operation in FILE_OPERATIONS:
        return "mfs_file"
    return ""


def load_evidence(
    path: Path, source_root: Path | None
) -> tuple[list[dict[str, str]], dict[tuple, set[str]]]:
    rows: list[dict[str, str]] = []
    statuses_by_site: dict[tuple, set[str]] = defaultdict(set)
    if not path.is_file():
        return rows, statuses_by_site
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = {str(key): str(value or "") for key, value in raw.items()}
            row["target_site_file"] = normalise_path(
                row.get("target_site_file", ""), source_root
            )
            row["source_file"] = normalise_path(row.get("source_file", ""), source_root)
            resource = evidence_resource(row.get("operation", ""))
            if resource:
                site = (
                    resource,
                    row["target_site_file"],
                    int_value(row.get("target_site_line")),
                    row.get("operation", ""),
                )
                statuses_by_site[site].add(row.get("status", ""))
            rows.append(row)
    return rows, statuses_by_site


def count_by(records: Iterable[Record], attribute: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(record, attribute)) for record in records).items()))


def record_report(reference: set[Record], candidate: set[Record]) -> dict[str, Any]:
    shared = reference & candidate
    reference_only = reference - candidate
    candidate_only = candidate - reference

    ref_sites = {record.site for record in reference}
    cand_sites = {record.site for record in candidate}
    disagreements = []
    for site in sorted(ref_sites & cand_sites):
        ref_values = sorted(record.value for record in reference if record.site == site)
        cand_values = sorted(record.value for record in candidate if record.site == site)
        if ref_values != cand_values:
            disagreements.append(
                {
                    "resource": site[0],
                    "file": site[1],
                    "line": site[2],
                    "operation": site[3],
                    "reference_values": ref_values,
                    "cvisualizer_values": cand_values,
                }
            )

    return {
        "reference_records": len(reference),
        "cvisualizer_records": len(candidate),
        "shared_records": len(shared),
        "reference_only_records": len(reference_only),
        "cvisualizer_only_records": len(candidate_only),
        "reference_sites": len(ref_sites),
        "cvisualizer_sites": len(cand_sites),
        "shared_sites": len(ref_sites & cand_sites),
        "reference_only_sites": len(ref_sites - cand_sites),
        "cvisualizer_only_sites": len(cand_sites - ref_sites),
        "value_disagreement_sites": len(disagreements),
        "reference_by_resource": count_by(reference, "resource"),
        "cvisualizer_by_resource": count_by(candidate, "resource"),
        "reference_by_operation": count_by(reference, "operation"),
        "cvisualizer_by_operation": count_by(candidate, "operation"),
        "value_disagreements": disagreements,
    }


def evidence_report(rows: list[dict[str, str]]) -> dict[str, Any]:
    status = Counter(row.get("status", "") for row in rows)
    provenance = Counter(row.get("resolved_by", "") for row in rows if row.get("resolved_by"))
    origin = Counter(row.get("origin_kind", "") for row in rows if row.get("origin_kind"))
    operations = Counter(row.get("operation", "") for row in rows if row.get("operation"))
    sites = {
        (
            row.get("target_site_file", ""),
            int_value(row.get("target_site_line")),
            row.get("target_function", ""),
            int_value(row.get("arg_index")),
        )
        for row in rows
    }
    exact_rows = [row for row in rows if row.get("status") == "EXACT"]
    exact_sites = {
        (
            row.get("target_site_file", ""),
            int_value(row.get("target_site_line")),
            row.get("target_function", ""),
            int_value(row.get("arg_index")),
        )
        for row in exact_rows
    }
    proof_rows = [
        row
        for row in exact_rows
        if row.get("source_file")
        and int_value(row.get("source_line")) > 0
        and int_value(row.get("path_count")) > 0
    ]
    values_per_site: Counter[int] = Counter()
    values: dict[tuple, set[str]] = defaultdict(set)
    for row in exact_rows:
        site = (
            row.get("target_site_file", ""),
            int_value(row.get("target_site_line")),
            row.get("target_function", ""),
            int_value(row.get("arg_index")),
        )
        if row.get("resolved_value"):
            values[site].add(row["resolved_value"])
    for possible_values in values.values():
        values_per_site[len(possible_values)] += 1

    return {
        "fact_rows": len(rows),
        "fact_sites": len(sites),
        "exact_fact_rows": len(exact_rows),
        "exact_fact_sites": len(exact_sites),
        "exact_rate": round(len(exact_rows) / len(rows), 6) if rows else 0.0,
        "exact_rows_with_source_proof": len(proof_rows),
        "exact_source_proof_rate": round(len(proof_rows) / len(exact_rows), 6)
        if exact_rows
        else 0.0,
        "status_counts": dict(sorted(status.items())),
        "resolved_by_counts": dict(sorted(provenance.items())),
        "origin_kind_counts": dict(sorted(origin.items())),
        "operation_counts": dict(sorted(operations.items())),
        "exact_values_per_site": dict(sorted(values_per_site.items())),
    }


def equivalence_report(
    reference: set[Record],
    candidate: set[Record],
    evidence_sites: dict[tuple, set[str]],
) -> dict[str, Any]:
    """Compare both pipelines on the same legacy exact-site universe.

    This intentionally reports a vector of measures instead of inventing one
    weighted score.  Evidence coverage, strict exact reproduction, and value
    equality answer different questions.
    """
    reference_sites = {record.site for record in reference}
    candidate_sites = {record.site for record in candidate}
    evidence_site_set = set(evidence_sites)
    exact_evidence_sites = {
        site for site, statuses in evidence_sites.items() if "EXACT" in statuses
    }
    covered = reference_sites & evidence_site_set
    exact_evidence_on_reference = reference_sites & exact_evidence_sites
    exact_json_on_reference = reference_sites & candidate_sites

    status_on_reference_sites = Counter()
    for site in sorted(covered):
        status_on_reference_sites["+".join(sorted(evidence_sites[site]))] += 1

    reference_values: dict[tuple, set[str]] = defaultdict(set)
    candidate_values: dict[tuple, set[str]] = defaultdict(set)
    for record in reference:
        reference_values[record.site].add(record.value)
    for record in candidate:
        candidate_values[record.site].add(record.value)

    value_set_comparison = Counter()
    for site in sorted(exact_json_on_reference):
        expected = reference_values[site]
        actual = candidate_values[site]
        if actual == expected:
            value_set_comparison["equal"] += 1
        elif actual < expected:
            value_set_comparison["cvisualizer_subset"] += 1
        elif actual > expected:
            value_set_comparison["cvisualizer_superset"] += 1
        elif actual & expected:
            value_set_comparison["partial_overlap"] += 1
        else:
            value_set_comparison["disjoint"] += 1

    def rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 6) if denominator else 0.0

    return {
        "legacy_exact_site_universe": len(reference_sites),
        "cvisualizer_evidence_site_universe": len(evidence_site_set),
        "legacy_sites_with_any_cvisualizer_evidence": len(covered),
        "legacy_sites_without_cvisualizer_evidence": len(reference_sites - evidence_site_set),
        "legacy_site_evidence_coverage": rate(len(covered), len(reference_sites)),
        "legacy_sites_with_cvisualizer_exact_evidence": len(exact_evidence_on_reference),
        "strict_exact_evidence_reproduction": rate(
            len(exact_evidence_on_reference), len(reference_sites)
        ),
        "legacy_sites_reproduced_in_cvisualizer_json": len(exact_json_on_reference),
        "strict_json_site_reproduction": rate(
            len(exact_json_on_reference), len(reference_sites)
        ),
        "strict_json_site_jaccard": rate(
            len(reference_sites & candidate_sites),
            len(reference_sites | candidate_sites),
        ),
        "status_on_legacy_sites_with_evidence": dict(
            sorted(status_on_reference_sites.items())
        ),
        "value_set_comparison_on_shared_json_sites": {
            "sites": len(exact_json_on_reference),
            "counts": dict(sorted(value_set_comparison.items())),
            "equal_rate": rate(
                value_set_comparison["equal"], len(exact_json_on_reference)
            ),
        },
    }


def graph_stats(directory: Path) -> dict[str, Any]:
    graph = read_json(directory / "graph.json", {})
    stats = graph.get("meta", {}).get("stats", {}) if isinstance(graph, dict) else {}
    return {
        "total_nodes": stats.get("total_nodes", 0),
        "total_edges": stats.get("total_edges", 0),
        "node_counts": stats.get("node_counts", {}),
        "edge_counts": stats.get("edge_counts", {}),
        "confidence_counts": stats.get("confidence_counts", {}),
    }


def build_report(
    cvisualizer_index: Path,
    build_index: Path,
    source_root: Path | None,
) -> dict[str, Any]:
    reference = load_exact_index(build_index, source_root)
    candidate = load_exact_index(cvisualizer_index, source_root)
    evidence_rows, evidence_sites = load_evidence(
        cvisualizer_index / "discovery_facts.csv", source_root
    )
    metadata = read_json(cvisualizer_index / "index_metadata.json", {})
    counts = metadata.get("counts", {}) if isinstance(metadata, dict) else {}

    evidence_site_status_counts: Counter[str] = Counter()
    for statuses in evidence_sites.values():
        label = "+".join(sorted(statuses))
        evidence_site_status_counts[label] += 1

    exact_candidate_sites = {record.site for record in candidate}
    evidence_comparable_sites = set(evidence_sites)
    return {
        "schema_version": 1,
        "inputs": {
            "cvisualizer_index": str(cvisualizer_index),
            "build_index": str(build_index),
            "source_root": str(source_root) if source_root else "",
        },
        "scope": {
            "pipeline": "existing artifacts only",
            "cvisualizer_metadata": {
                "processes_requested": counts.get("processes_requested"),
                "processes_included": counts.get("processes_included"),
                "processes_failed": counts.get("processes_failed"),
                "discovery_scope": metadata.get("discovery_scope"),
            },
        },
        "exact_records": record_report(reference, candidate),
        "evidence": evidence_report(evidence_rows),
        "equivalence": equivalence_report(reference, candidate, evidence_sites),
        "evidence_comparable_sites": {
            "sites_with_resource_operation": len(evidence_comparable_sites),
            "site_status_combinations": dict(sorted(evidence_site_status_counts.items())),
            "exact_json_sites": len(exact_candidate_sites),
            "evidence_sites_not_in_exact_json": len(
                evidence_comparable_sites - exact_candidate_sites
            ),
        },
        "graph": {
            "reference": graph_stats(build_index),
            "cvisualizer": graph_stats(cvisualizer_index),
        },
        "interpretation": {
            "exact_graph_reduction_is_observed": len(candidate) < len(reference),
            "evidence_is_retained_outside_exact_graph": len(evidence_rows) > len(candidate),
            "claims_requiring_ground_truth": [
                "Fewer exact records alone does not prove higher accuracy.",
                "The legacy index has no equivalent per-site unresolved/status/proof table, so recall of unresolved values cannot be proven from these two indexes alone.",
                "The two failed processes must be repaired and rerun before calling the aggregate whole-repository complete.",
            ],
        },
    }


def write_csvs(output_dir: Path, report: dict[str, Any]) -> None:
    exact = report["exact_records"]
    with (output_dir / "comparison_by_resource.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["resource", "reference_records", "cvisualizer_records"])
        resources = sorted(
            set(exact["reference_by_resource"]) | set(exact["cvisualizer_by_resource"])
        )
        for resource in resources:
            writer.writerow(
                [
                    resource,
                    exact["reference_by_resource"].get(resource, 0),
                    exact["cvisualizer_by_resource"].get(resource, 0),
                ]
            )

    with (output_dir / "evidence_statuses.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["status", "facts"])
        for status, count in report["evidence"]["status_counts"].items():
            writer.writerow([status, count])


def summary(report: dict[str, Any]) -> str:
    exact = report["exact_records"]
    evidence = report["evidence"]
    scope = report["scope"]["cvisualizer_metadata"]
    return "\n".join(
        [
            "Index comparison (existing artifacts; no pipeline run)",
            f"  c-visualizer scope: {scope.get('processes_included')}/{scope.get('processes_requested')} processes; failed={scope.get('processes_failed')}",
            f"  exact records:      legacy={exact['reference_records']} c-visualizer={exact['cvisualizer_records']} shared={exact['shared_records']}",
            f"  exact sites:        legacy={exact['reference_sites']} c-visualizer={exact['cvisualizer_sites']} shared={exact['shared_sites']}",
            f"  value disagreements: {exact['value_disagreement_sites']}",
            f"  legacy-site coverage: {report['equivalence']['legacy_sites_with_any_cvisualizer_evidence']}/{report['equivalence']['legacy_exact_site_universe']} ({report['equivalence']['legacy_site_evidence_coverage']:.1%}) have c-visualizer evidence",
            f"  strict reproduction: {report['equivalence']['legacy_sites_with_cvisualizer_exact_evidence']}/{report['equivalence']['legacy_exact_site_universe']} ({report['equivalence']['strict_exact_evidence_reproduction']:.1%}) are EXACT in evidence",
            f"  value sets equal:    {report['equivalence']['value_set_comparison_on_shared_json_sites']['counts'].get('equal', 0)}/{report['equivalence']['value_set_comparison_on_shared_json_sites']['sites']} ({report['equivalence']['value_set_comparison_on_shared_json_sites']['equal_rate']:.1%}) shared JSON sites",
            f"  evidence facts:     {evidence['fact_rows']} ({evidence['exact_fact_rows']} EXACT; rate={evidence['exact_rate']:.1%})",
            f"  exact proof rows:   {evidence['exact_rows_with_source_proof']}/{evidence['exact_fact_rows']} ({evidence['exact_source_proof_rate']:.1%})",
            f"  statuses:           {json.dumps(evidence['status_counts'], sort_keys=True)}",
            f"  graph edges:        legacy={report['graph']['reference']['total_edges']} c-visualizer={report['graph']['cvisualizer']['total_edges']}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cvisualizer-index", type=Path, required=True)
    parser.add_argument("--build-index", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    cvisualizer_index = args.cvisualizer_index.expanduser().resolve()
    build_index = args.build_index.expanduser().resolve()
    source_root = args.source_root.expanduser().resolve() if args.source_root else None
    report = build_report(cvisualizer_index, build_index, source_root)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csvs(output_dir, report)
    print(summary(report))
    print(f"  report:             {output_dir / 'comparison.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
