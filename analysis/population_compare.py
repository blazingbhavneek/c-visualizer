#!/usr/bin/env python3
"""Population-aware comparison of the cleaned c-visualizer index vs legacy.

Reads the batch group.json to derive the valid process population
(snapshotted - failed), builds longest-prefix process-root ownership from the
per-process index_metadata.json files (valid roots) and group.json failure
project_root entries (failed roots), then re-tabulates the Step 0 and Step 1
record populations by owner. Read-only; reruns no pipeline.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import step0 as s0


def load_group(path: Path) -> dict:
    group = json.loads(path.read_text(encoding="utf-8"))
    snap = {p["process_name"] for p in group["processes"]}
    fail = {f["process_name"] for f in group["failures"]}
    failed_roots = {
        f["process_name"]: f["project_root"]
        for f in group["failures"]
        if f.get("project_root")
    }
    return {
        "snapshotted": snap,
        "failed": fail,
        "valid": snap - fail,
        "overlap": snap & fail,
        "failed_roots": failed_roots,
    }


def valid_roots(results_dir: Path, valid: set[str]) -> dict[str, str]:
    roots: dict[str, str] = {}
    for name in sorted(valid):
        meta = results_dir / name / "index" / "index_metadata.json"
        if not meta.is_file():
            continue
        payload = json.loads(meta.read_text(encoding="utf-8"))
        root = str(payload.get("process_root") or "").rstrip("/")
        if root:
            roots[name] = root
    return roots


def make_ownership(valid_roots: dict[str, str], failed_roots: dict[str, str]):
    entries = [(root, name, "valid") for name, root in valid_roots.items()]
    entries += [(root, name, "failed") for name, root in failed_roots.items()]
    entries.sort(key=lambda item: len(item[0]), reverse=True)

    def owner(absolute: str) -> tuple[str, str]:
        path = (absolute or "").replace("\\", "/")
        for root, name, kind in entries:
            if path == root or path.startswith(root + "/"):
                return kind, name
        return "unowned", ""

    return owner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cvisualizer-index", type=Path, required=True)
    parser.add_argument("--legacy-index", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--group", type=Path, required=True)
    parser.add_argument("--step1-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    pop = load_group(args.group)
    vroots = valid_roots(args.results_dir, pop["valid"])
    owner = make_ownership(vroots, pop["failed_roots"])
    source_root = args.source_root.resolve()

    out: dict = {
        "population": {
            "snapshotted": len(pop["snapshotted"]),
            "failed": len(pop["failed"]),
            "overlap": len(pop["overlap"]),
            "valid": len(pop["valid"]),
            "valid_roots_found": len(vroots),
        }
    }

    # ---- Step 0: direct records -------------------------------------------
    definitions = s0.SourceDefinitions(args.source_root)
    source_lines = s0.SourceLines(args.source_root)
    facts = s0.read_facts(args.cvisualizer_index / "discovery_facts.csv")
    cviz_aggregate = s0.load_exact_index(args.cvisualizer_index, source_root)
    legacy_direct, _ = s0.load_direct_legacy_records(
        args.legacy_index, args.source_root, source_lines, definitions
    )
    cviz_direct_final, cviz_direct_evidence, evidence_by_record, direct_rows = (
        s0.direct_cvisualizer_records(facts, cviz_aggregate, source_root, definitions)
    )

    shared = cviz_direct_final & legacy_direct
    cviz_only = cviz_direct_final - legacy_direct
    legacy_only = legacy_direct - cviz_direct_final

    def tabulate(records: set[s0.Record]) -> Counter:
        counts: Counter = Counter()
        by_resource: dict[str, Counter] = defaultdict(Counter)
        for record in records:
            kind, name = owner(s0.path_for_record(record, source_root))
            counts[kind] += 1
            by_resource[record.resource][kind] += 1
        return counts

    step0_out = {
        "cviz_direct_final": {
            "records": len(cviz_direct_final),
            "owners": dict(tabulate(cviz_direct_final)),
        },
        "cviz_direct_evidence": {
            "direct_fact_rows": direct_rows,
            "evidence_records": len(cviz_direct_evidence),
            "not_promoted": len(cviz_direct_evidence - cviz_direct_final),
        },
        "legacy_direct": {
            "records": len(legacy_direct),
            "owners": dict(tabulate(legacy_direct)),
        },
        "shared": len(shared),
        "cviz_only": {
            "records": len(cviz_only),
            "owners": dict(tabulate(cviz_only)),
        },
        "legacy_only": {
            "records": len(legacy_only),
            "owners": dict(tabulate(legacy_only)),
        },
    }

    # Legacy-only records inside valid process roots: the comparable gap.
    valid_legacy_only: list[s0.Record] = [
        r
        for r in legacy_only
        if owner(s0.path_for_record(r, source_root))[0] == "valid"
    ]
    facts_by_site: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    for record, rows in evidence_by_record.items():
        facts_by_site[record.site].extend(rows)
    gap = s0.legacy_gap_classification(
        legacy_only, cviz_direct_evidence, facts_by_site, source_lines, definitions
    )
    valid_gap = s0.legacy_gap_classification(
        set(valid_legacy_only),
        cviz_direct_evidence,
        facts_by_site,
        source_lines,
        definitions,
    )
    valid_source = s0.source_classification(set(valid_legacy_only), source_root)
    all_source = s0.source_classification(legacy_only, source_root)

    step0_out["legacy_only_in_valid_roots"] = {
        "records": len(valid_legacy_only),
        "gap_classification": valid_gap,
        "source_classification": valid_source,
    }
    step0_out["legacy_only_source_classification_all"] = all_source
    step0_out["legacy_only_gap_classification_all"] = gap

    # Per-resource owner tabs for legacy-only and cviz-only.
    def resource_tabs(records: set[s0.Record]) -> dict[str, dict]:
        tabs: dict[str, Counter] = defaultdict(Counter)
        for record in records:
            kind, name = owner(s0.path_for_record(record, source_root))
            tabs[record.resource][kind] += 1
        return {k: dict(v) for k, v in tabs.items()}

    step0_out["legacy_only_by_resource"] = resource_tabs(legacy_only)
    step0_out["cviz_only_by_resource"] = resource_tabs(cviz_only)
    step0_out["legacy_by_resource"] = resource_tabs(legacy_direct)

    # Which failed process roots hold the most legacy-only records.
    failed_owner_names = Counter()
    for record in legacy_only:
        kind, name = owner(s0.path_for_record(record, source_root))
        if kind == "failed":
            failed_owner_names[name] += 1
    step0_out["legacy_only_top_failed_processes"] = dict(
        failed_owner_names.most_common(15)
    )
    unowned_dirs = Counter()
    for record in legacy_only:
        kind, _ = owner(s0.path_for_record(record, source_root))
        if kind == "unowned":
            rel = s0.path_for_record(record, source_root).replace(
                str(source_root) + "/", ""
            )
            parts = rel.split("/")
            unowned_dirs["/".join(parts[:2])] += 1
    step0_out["legacy_only_unowned_top_dirs"] = dict(unowned_dirs.most_common(15))

    # cviz-only fact status for UNREACHABLE share.
    cviz_only_statuses = Counter()
    for record in cviz_only:
        for row in evidence_by_record.get(record, []):
            cviz_only_statuses[row.get("status", "")] += 1
    step0_out["cviz_only_fact_statuses"] = dict(cviz_only_statuses)

    # ---- Step 1: indirect sites from step1.json ---------------------------
    if args.step1_json and args.step1_json.is_file():
        step1 = json.loads(args.step1_json.read_text(encoding="utf-8"))
        sites = step1["sites"]

        def membership(site: dict) -> str:
            has_cviz = bool(site.get("cvisualizer", {}).get("fact_rows")) or (
                "cvisualizer" in site and site.get("cvisualizer", {}).get("expressions")
            )
            has_legacy = bool(site.get("legacy", {}).get("proof_rows"))
            if has_cviz and has_legacy:
                return "common"
            if has_cviz:
                return "cvisualizer_only"
            return "legacy_only"

        member_owner: dict[str, Counter] = defaultdict(Counter)
        legacy_only_owner_names = Counter()
        legacy_only_unowned_dirs = Counter()
        cviz_only_statuses = Counter()
        for site in sites:
            member = membership(site)
            kind, name = owner(site.get("absolute_file", ""))
            member_owner[member][kind] += 1
            if member == "legacy_only" and kind == "failed":
                legacy_only_owner_names[name] += 1
            if member == "legacy_only" and kind == "unowned":
                rel = site.get("absolute_file", "").replace(str(source_root) + "/", "")
                legacy_only_unowned_dirs["/".join(rel.split("/")[:2])] += 1
            if member in ("cvisualizer_only", "common"):
                cviz_only_statuses.update(
                    site.get("cvisualizer", {}).get("statuses", {})
                )

        step1_out = {
            "member_owner": {k: dict(v) for k, v in member_owner.items()},
            "legacy_only_top_failed_processes": dict(
                legacy_only_owner_names.most_common(15)
            ),
            "legacy_only_unowned_top_dirs": dict(
                legacy_only_unowned_dirs.most_common(15)
            ),
        }
        out["step1"] = step1_out

    out["step0"] = step0_out

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
