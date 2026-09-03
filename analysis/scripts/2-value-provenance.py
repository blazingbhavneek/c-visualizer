#!/usr/bin/env python3
"""Generate the numeric checkpoint for analysis/2-value-provenance.md.

The report is a small, source-backed study of why values differ between the
legacy index and C-visualizer.  The Python side only checks the selected
examples and writes compact tables; the analysis agent owns the explanation.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

SCRIPT = Path(__file__).resolve()
CVIS_ROOT = SCRIPT.parents[2]
ANALYSIS_ROOT = SCRIPT.parents[1]
DEFAULT_RESULTS = CVIS_ROOT / "results_backup" / "csv_results7"
DEFAULT_LEGACY = CVIS_ROOT.parent / "index_baseline"
DEFAULT_SPEC = CVIS_ROOT / "target_specs" / "build_index_targets.json"
DEFAULT_REPORT = ANALYSIS_ROOT / "2-value-provenance.md"
DEFAULT_JSON = ANALYSIS_ROOT / "2-value-provenance-data.json"

BEGIN_MARKER = "<!-- BEGIN GENERATED: 2-value-provenance -->"
END_MARKER = "<!-- END GENERATED: 2-value-provenance -->"

EXAMPLES = [
    {
        "name": "DxiGetAdr.c:133",
        "file": "t-dxi/src/libdxi/DxiGetAdr.c",
        "line": 133,
        "group": "source_proven",
    },
    {
        "name": "DxiGetAdr.c:185",
        "file": "t-dxi/src/libdxi/DxiGetAdr.c",
        "line": 185,
        "group": "source_proven",
    },
    {
        "name": "DxiSndHdr.c:265",
        "file": "t-dxi/src/libdxi/DxiSndHdr.c",
        "line": 265,
        "group": "source_proven",
    },
    {
        "name": "DxiSndHdr.c:687",
        "file": "t-dxi/src/libdxi/DxiSndHdr.c",
        "line": 687,
        "group": "source_proven",
    },
    {
        "name": "dxiG_cirmng.c:805",
        "file": "t-dxi/src/libdxiinside/dxiG_cirmng.c",
        "line": 805,
        "group": "source_proven",
    },
    {
        "name": "DxiSndHdr.c:291",
        "file": "t-dxi/src/libdxi/DxiSndHdr.c",
        "line": 291,
        "group": "runtime",
    },
    {
        "name": "dxi_uptbn.c:74",
        "file": "t-dxi/src/libdxiinside/dxi_uptbn.c",
        "line": 74,
        "group": "runtime",
    },
    {
        "name": "dxi_uptbn.c:111",
        "file": "t-dxi/src/libdxiinside/dxi_uptbn.c",
        "line": 111,
        "group": "runtime",
    },
    {
        "name": "dxi_uptbn.c:148",
        "file": "t-dxi/src/libdxiinside/dxi_uptbn.c",
        "line": 148,
        "group": "runtime",
    },
    {
        "name": "dxi800d_reg.c:115",
        "file": "t-dxi/src/dxi800d/dxi800d_reg.c",
        "line": 115,
        "group": "runtime",
    },
    {
        "name": "dxi_dblcirreq.c:100",
        "file": "t-dxi/src/libdxiinside/dxi_dblcirreq.c",
        "line": 100,
        "group": "runtime",
    },
    {
        "name": "DxiItcReq2.c:711",
        "file": "t-dxi/src/libdxi/DxiItcReq2.c",
        "line": 711,
        "group": "provenance_boundary",
    },
]

RUNTIME_WARNINGS = [
    {
        "name": "DxiSndHdr.c:567",
        "file": "t-dxi/src/libdxi/DxiSndHdr.c",
        "line": 567,
    },
    {
        "name": "DxiSndHdr.c:622",
        "file": "t-dxi/src/libdxi/DxiSndHdr.c",
        "line": 622,
    },
    {
        "name": "DxiItcReq2.c:575",
        "file": "t-dxi/src/libdxi/DxiItcReq2.c",
        "line": 575,
    },
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def normalized_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def canonical_value(value: Any, operation: str) -> str:
    text = str(value or "")
    if operation == "FORKPROC" and len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1]
    return text


def load_excluded_targets(path: Path) -> set[str]:
    payload = read_json(path)
    return {
        name
        for name, settings in (payload.get("targets") or {}).items()
        if (settings.get("discovery") or {}).get("resource") == "none"
    }


def load_legacy_values(
    directory: Path,
) -> dict[tuple[str, int], set[str]]:
    values: dict[tuple[str, int], set[str]] = defaultdict(set)
    for filename in ("mfs_file_access.json", "mfs_queue_access.json"):
        payload = read_json(directory / filename)
        for value, entries in payload.items():
            for entry in entries or []:
                site = (
                    normalized_path(entry.get("file")),
                    int(entry.get("line", 0) or 0),
                )
                values[site].add(str(value))

    payload = read_json(directory / "forkproc_targets_by_caller.json")
    for caller, entries in payload.items():
        for entry in entries or []:
            site = (normalized_path(caller), int(entry.get("line", 0) or 0))
            values[site].add(canonical_value(entry.get("target", ""), "FORKPROC"))
    return dict(values)


def load_facts(
    results_dir: Path, excluded_targets: set[str]
) -> tuple[dict[tuple[str, int], list[dict[str, str]]], dict[str, Any]]:
    facts: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    all_rows = 0
    excluded_rows = 0
    for row in rows(results_dir / "index" / "discovery_facts.csv"):
        all_rows += 1
        if row.get("target_function", "") in excluded_targets:
            excluded_rows += 1
            continue
        site = (
            normalized_path(row.get("target_site_file")),
            int(row.get("target_site_line", 0) or 0),
        )
        facts[site].append(row)

    status_rows = Counter(
        row.get("status", "") for site_rows in facts.values() for row in site_rows
    )
    resolution_rows = Counter(
        row.get("resolution_status", "")
        for site_rows in facts.values()
        for row in site_rows
    )

    def site_counts(field: str) -> dict[str, int]:
        counts = Counter()
        for site_rows in facts.values():
            counts.update({row.get(field, "") for row in site_rows})
        return dict(sorted(counts.items()))

    return dict(facts), {
        "all_rows": all_rows,
        "included_rows": all_rows - excluded_rows,
        "excluded_rows": excluded_rows,
        "sites": len(facts),
        "status_rows": dict(sorted(status_rows.items())),
        "status_sites": site_counts("status"),
        "resolution_rows": dict(sorted(resolution_rows.items())),
        "resolution_sites": site_counts("resolution_status"),
    }


def sorted_values(site_rows: list[dict[str, str]], statuses: set[str]) -> list[str]:
    values = {
        canonical_value(row.get("resolved_value", ""), row.get("operation", ""))
        for row in site_rows
        if row.get("status", "") in statuses and row.get("resolved_value", "")
    }
    return sorted(values, key=lambda value: (not value.isdigit(), value))


def example_snapshot(
    item: dict[str, Any],
    legacy_values: dict[tuple[str, int], set[str]],
    facts: dict[tuple[str, int], list[dict[str, str]]],
) -> dict[str, Any]:
    site = (item["file"], item["line"])
    site_rows = facts.get(site, [])
    exact_values = sorted_values(site_rows, {"EXACT"})
    dynamic_values = sorted_values(site_rows, {"DYNAMIC"})
    external_values = sorted_values(site_rows, {"EXTERNAL"})
    return {
        **item,
        "legacy_values": sorted(legacy_values.get(site, set())),
        "exact_values": exact_values,
        "dynamic_values": dynamic_values,
        "external_values": external_values,
        "statuses": sorted({row.get("status", "") for row in site_rows}),
        "resolution_statuses": sorted(
            {row.get("resolution_status", "") for row in site_rows}
        ),
        "origins": sorted({row.get("origin_kind", "") for row in site_rows}),
        "link_methods": sorted({row.get("link_method", "") for row in site_rows}),
        "fact_rows": len(site_rows),
    }


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    results_dir = args.results_dir.resolve()
    legacy_index = args.legacy_index.resolve()
    excluded_targets = load_excluded_targets(args.target_spec.resolve())
    metadata = read_json(results_dir / "index" / "index_metadata.json")
    facts, fact_meta = load_facts(results_dir, excluded_targets)
    legacy_values = load_legacy_values(legacy_index)

    snapshots = [example_snapshot(item, legacy_values, facts) for item in EXAMPLES]
    warning_snapshots = [
        example_snapshot(item, legacy_values, facts) for item in RUNTIME_WARNINGS
    ]

    exact_runtime_values: dict[tuple[str, int], set[str]] = defaultdict(set)
    for site, site_rows in facts.items():
        exact_runtime_values[site].update(
            sorted_values(site_rows, {"EXACT", "DYNAMIC"})
        )
    value_total = sum(len(values) for values in exact_runtime_values.values())

    return {
        "inputs": {
            "results_dir": str(results_dir),
            "aggregate_index": str(results_dir / "index"),
            "legacy_index": str(legacy_index),
            "source_root": metadata.get("source_root", ""),
            "target_registry_version": (metadata.get("target_registry") or {}).get(
                "version", ""
            ),
        },
        "run": {
            "metadata_counts": metadata.get("counts") or {},
            "fact_meta": fact_meta,
            "exact_dynamic_value_total": value_total,
            "exact_dynamic_values_per_site": (
                value_total / fact_meta["sites"] if fact_meta["sites"] else None
            ),
        },
        "examples": snapshots,
        "runtime_warnings": warning_snapshots,
    }


def display_values(values: list[str]) -> str:
    return ", ".join(values) if values else "—"


def render_markdown(data: dict[str, Any]) -> str:
    run = data["run"]
    meta = run["fact_meta"]
    status_rows = meta["status_rows"]
    resolution_rows = meta["resolution_rows"]
    lines = [
        BEGIN_MARKER,
        "_Generated by `analysis/scripts/2-value-provenance.py`; the prose and source explanations above are written by the analysis agent._",
        "",
        "| Checkpoint | Result |",
        "|---|---:|",
        f"| Fact rows after close exclusion | {meta['included_rows']:,} |",
        f"| Unique target sites | {meta['sites']:,} |",
        f"| `EXACT` rows / sites | {status_rows.get('EXACT', 0):,} / {meta['status_sites'].get('EXACT', 0):,} |",
        f"| `DYNAMIC` rows / sites | {status_rows.get('DYNAMIC', 0):,} / {meta['status_sites'].get('DYNAMIC', 0):,} |",
        f"| `RESOLVED` rows / sites | {resolution_rows.get('RESOLVED', 0):,} / {meta['resolution_sites'].get('RESOLVED', 0):,} |",
        f"| `RUNTIME` rows / sites | {resolution_rows.get('RUNTIME', 0):,} / {meta['resolution_sites'].get('RUNTIME', 0):,} |",
        f"| Exact + dynamic values summed per site | {run['exact_dynamic_value_total']:,} / {meta['sites']:,} = {run['exact_dynamic_values_per_site']:.2f} |",
        "",
        "### Example checkpoint",
        "",
        "| Site | Legacy values | New exact values | New runtime values | Status |",
        "|---|---|---|---|---|",
    ]
    for item in data["examples"]:
        new_status = ", ".join(item["statuses"]) or "NO_FACTS"
        lines.append(
            f"| `{item['name']}` | {display_values(item['legacy_values'])} | "
            f"{display_values(item['exact_values'])} | "
            f"{display_values(item['dynamic_values'])} | {new_status} |"
        )

    lines.extend(
        [
            "",
            "### Runtime warning checkpoint",
            "",
            "| Site | Current runtime values | Status |",
            "|---|---|---|",
        ]
    )
    for item in data["runtime_warnings"]:
        lines.append(
            f"| `{item['name']}` | {display_values(item['dynamic_values'])} | "
            f"{', '.join(item['statuses']) or 'NO_FACTS'} |"
        )
    lines.extend(["", END_MARKER])
    return "\n".join(lines)


def replace_generated_block(report: Path, generated: str) -> None:
    text = report.read_text(encoding="utf-8")
    start = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < start:
        raise ValueError(f"Generated markers are missing or invalid in {report}")
    end += len(END_MARKER)
    report.write_text(text[:start] + generated + text[end:], encoding="utf-8")


def check_generated_block(report: Path, generated: str) -> bool:
    text = report.read_text(encoding="utf-8")
    start = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < start:
        return False
    end += len(END_MARKER)
    return text[start:end] == generated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--legacy-index", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument("--target-spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--write-report", type=Path)
    parser.add_argument("--check-report", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data = analyze(args)
    generated = render_markdown(data)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.write_report:
        replace_generated_block(args.write_report, generated)
    if args.check_report and not check_generated_block(args.check_report, generated):
        print(f"Generated block is stale: {args.check_report}", file=sys.stderr)
        return 1
    if args.print_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif not args.write_report and not args.check_report:
        print(generated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
