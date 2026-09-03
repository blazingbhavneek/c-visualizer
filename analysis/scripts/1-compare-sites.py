#!/usr/bin/env python3
"""Reproduce the tables in analysis/1-sites.md.

The comparison has two surfaces:

* site discovery and evidence, from per-process target_sites.csv plus the
  aggregate discovery_facts.csv; and
* the build-index-compatible JSON export, compared directly with the legacy
  index JSON files.

Close/closeall calls are excluded because the legacy index has no equivalent
resource record.  A site is one source path plus line; this run has at most one
non-close target function at each such location.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

SCRIPT = Path(__file__).resolve()
CVIS_ROOT = SCRIPT.parents[2]
ANALYSIS_ROOT = SCRIPT.parents[1]
DEFAULT_RESULTS = CVIS_ROOT / "results_backup" / "csv_results6"
DEFAULT_LEGACY = CVIS_ROOT.parent / "index_baseline"
DEFAULT_SPEC = CVIS_ROOT / "target_specs" / "build_index_targets.json"
DEFAULT_REPORT = ANALYSIS_ROOT / "1-sites.md"
DEFAULT_JSON = ANALYSIS_ROOT / "1-sites-data.json"

BEGIN_MARKER = "<!-- BEGIN GENERATED: 1-site-comparison -->"
END_MARKER = "<!-- END GENERATED: 1-site-comparison -->"

UNRESOLVED_STATUSES = {"UNRESOLVED", "NO_TARGET"}
HANDLE_OPERATIONS = {
    "GETREC",
    "GETREC_D",
    "READREC",
    "READREC_D",
    "UPDATEREC",
    "UPDATEREC_D",
    "WRITEREC",
    "WRITEREC_D",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def normalized_path(value: Any, source_root: Path | None = None) -> str:
    text = str(value or "").replace("\\", "/")
    path = Path(text)
    if path.is_absolute() and source_root is not None:
        try:
            return path.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()
    return re.sub(r"^\./+", "", text)


def canonical_value(value: Any, operation: str) -> str:
    text = str(value or "")
    if operation == "FORKPROC" and len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1]
    return text


def display_path(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(CVIS_ROOT).as_posix()
    except ValueError:
        try:
            return "../" + path.relative_to(CVIS_ROOT.parent).as_posix()
        except ValueError:
            return path.as_posix()


def load_target_spec(path: Path) -> tuple[set[str], set[str], set[str]]:
    payload = read_json(path)
    targets = payload.get("targets") or {}
    excluded = {
        name
        for name, settings in targets.items()
        if (settings.get("discovery") or {}).get("resource") == "none"
    }
    wrappers = {
        name for name, settings in targets.items() if settings.get("semantic_wrapper")
    }
    handle_targets = {
        name
        for name, settings in targets.items()
        if settings.get("dependent_functions")
    }
    return excluded, wrappers, handle_targets


def load_inventory(
    results_dir: Path, excluded_targets: set[str]
) -> tuple[dict[tuple[str, int], set[str]], int]:
    inventory: dict[tuple[str, int], set[str]] = defaultdict(set)
    files = sorted(results_dir.glob("*/index/target_sites.csv"))
    for path in files:
        for row in rows(path):
            function = row.get("target_function", "")
            if function in excluded_targets:
                continue
            site = (
                normalized_path(row.get("target_site_file", "")),
                int(row.get("target_site_line", 0) or 0),
            )
            inventory[site].add(function)

    ambiguous = {site: names for site, names in inventory.items() if len(names) != 1}
    if ambiguous:
        sample = list(sorted(ambiguous.items()))[:5]
        raise ValueError(f"Multiple target functions share a source line: {sample}")
    return dict(inventory), len(files)


def load_facts(results_dir: Path, excluded_targets: set[str]) -> tuple[
    dict[tuple[str, int], list[dict[str, str]]],
    dict[str, Any],
]:
    path = results_dir / "index" / "discovery_facts.csv"
    by_site: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    close_sites: set[tuple[str, int]] = set()
    total_rows = 0
    excluded_rows = 0
    llm_rows: Counter[str] = Counter()
    llm_sites: dict[tuple[str, int], set[str]] = defaultdict(set)
    resolution_rows: Counter[str] = Counter()
    resolution_sites: dict[str, set[tuple[str, int]]] = defaultdict(set)
    runtime_origins: Counter[str] = Counter()
    runtime_values: set[str] = set()
    runtime_numeric_values: set[str] = set()
    runtime_operation_values: set[tuple[str, str]] = set()

    for row in rows(path):
        total_rows += 1
        site = (
            normalized_path(row.get("target_site_file", "")),
            int(row.get("target_site_line", 0) or 0),
        )
        if row.get("target_function", "") in excluded_targets:
            excluded_rows += 1
            close_sites.add(site)
            continue
        by_site[site].append(row)
        resolution = row.get("resolution_status", "")
        resolution_rows[resolution] += 1
        resolution_sites[resolution].add(site)
        if resolution == "RUNTIME":
            runtime_origins[row.get("origin_kind", "")] += 1
            value = row.get("resolved_value", "")
            if value:
                runtime_values.add(value)
                runtime_operation_values.add((row.get("operation", ""), value))
                if re.fullmatch(r"\d+", value):
                    runtime_numeric_values.add(value)
        if row.get("resolved_by") == "LLM":
            status = row.get("status", "")
            llm_rows[status] += 1
            llm_sites[site].add(status)

    return dict(by_site), {
        "all_rows": total_rows,
        "included_rows": total_rows - excluded_rows,
        "excluded_rows": excluded_rows,
        "excluded_sites": len(close_sites),
        "resolution_status_rows": dict(sorted(resolution_rows.items())),
        "resolution_status_sites": {
            key: len(value) for key, value in sorted(resolution_sites.items())
        },
        "runtime_origin_rows": dict(sorted(runtime_origins.items())),
        "runtime_unique_values": len(runtime_values),
        "runtime_unique_numeric_values": len(runtime_numeric_values),
        "runtime_unique_operation_values": len(runtime_operation_values),
        "llm_rows": dict(sorted(llm_rows.items())),
        "llm_sites": len(llm_sites),
        "llm_exact_sites": sum("EXACT" in statuses for statuses in llm_sites.values()),
    }


def runtime_process_csv_summary(
    results_dir: Path, source_root: Path, excluded_targets: set[str]
) -> tuple[dict[str, Any], set[tuple[str, int]]]:
    """Count row-level RUNTIME statuses in the per-process result CSVs."""
    runtime_rows = 0
    runtime_sites: set[tuple[str, int]] = set()
    runtime_functions: Counter[str] = Counter()
    for path in sorted(results_dir.glob("*.csv")):
        for row in rows(path):
            if row.get("target_number->status") != "RUNTIME":
                continue
            if row.get("function_name", "") in excluded_targets:
                continue
            runtime_rows += 1
            site = (
                normalized_path(row.get("target_name_src->path", ""), source_root),
                int(row.get("target_name_src->line_number", 0) or 0),
            )
            runtime_sites.add(site)
            runtime_functions[row.get("function_name", "")] += 1
    return (
        {
            "rows": runtime_rows,
            "sites": len(runtime_sites),
            "functions": dict(sorted(runtime_functions.items())),
        },
        runtime_sites,
    )


def load_index_values(
    directory: Path, source_root: Path
) -> tuple[dict[tuple[str, int], set[tuple[str, str]]], set[tuple[str, int, str, str]]]:
    values: dict[tuple[str, int], set[tuple[str, str]]] = defaultdict(set)
    records: set[tuple[str, int, str, str]] = set()

    for filename in ("mfs_file_access.json", "mfs_queue_access.json"):
        payload = read_json(directory / filename)
        for value, entries in payload.items():
            for entry in entries or []:
                path = normalized_path(entry.get("file", ""), source_root)
                line = int(entry.get("line", 0) or 0)
                operation = str(entry.get("lock", ""))
                normalized_value = canonical_value(value, operation)
                values[(path, line)].add((operation, normalized_value))
                records.add((path, line, operation, normalized_value))

    payload = read_json(directory / "forkproc_targets_by_caller.json")
    for caller, entries in payload.items():
        path = normalized_path(caller, source_root)
        for entry in entries or []:
            line = int(entry.get("line", 0) or 0)
            operation = "FORKPROC"
            value = canonical_value(entry.get("target", ""), operation)
            values[(path, line)].add((operation, value))
            records.add((path, line, operation, value))

    return dict(values), records


def load_exact_fact_values(
    facts_by_site: dict[tuple[str, int], list[dict[str, str]]],
) -> tuple[dict[tuple[str, int], set[tuple[str, str]]], set[tuple[str, int, str, str]]]:
    values: dict[tuple[str, int], set[tuple[str, str]]] = defaultdict(set)
    records: set[tuple[str, int, str, str]] = set()
    for site, site_rows in facts_by_site.items():
        for row in site_rows:
            if row.get("status") != "EXACT" or not row.get("resolved_value"):
                continue
            operation = row.get("operation", "")
            value = canonical_value(row.get("resolved_value", ""), operation)
            values[site].add((operation, value))
            records.add((site[0], site[1], operation, value))
    return dict(values), records


def load_fact_values(
    facts_by_site: dict[tuple[str, int], list[dict[str, str]]],
    statuses: set[str],
    field: str = "status",
) -> dict[tuple[str, int], set[tuple[str, str]]]:
    """Collect resolved values for a selected set of fact statuses."""
    values: dict[tuple[str, int], set[tuple[str, str]]] = defaultdict(set)
    for site, site_rows in facts_by_site.items():
        for row in site_rows:
            if row.get(field) not in statuses or not row.get("resolved_value"):
                continue
            operation = row.get("operation", "")
            value = canonical_value(row.get("resolved_value", ""), operation)
            values[site].add((operation, value))
    return dict(values)


def site_value_density(
    values: dict[tuple[str, int], set[tuple[str, str]]],
    denominator_sites: set[tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """Summarize distinct values attached to each site.

    The requested ratio is the sum of each site's distinct raw values divided
    by the selected site denominator. Operation/value pairs are included as a
    separate audit number because one raw value can be used by more than one
    operation.
    """
    sites = set(values) if denominator_sites is None else set(denominator_sites)
    site_value_total = sum(
        len({value for _, value in values.get(site, set())}) for site in sites
    )
    site_pair_total = sum(len(values.get(site, set())) for site in sites)
    global_values = {value for site in sites for _, value in values.get(site, set())}
    global_pairs = {pair for site in sites for pair in values.get(site, set())}
    value_bearing_sites = sum(bool(values.get(site)) for site in sites)
    return {
        "sites": len(sites),
        "value_bearing_sites": value_bearing_sites,
        "site_value_total": site_value_total,
        "site_operation_value_total": site_pair_total,
        "global_unique_values": len(global_values),
        "global_unique_operation_values": len(global_pairs),
        "values_per_site": (site_value_total / len(sites) if sites else None),
        "operation_values_per_site": (site_pair_total / len(sites) if sites else None),
    }


def filter_operation_values(
    values: dict[tuple[str, int], set[tuple[str, str]]],
    handle_operations: bool,
) -> dict[tuple[str, int], set[tuple[str, str]]]:
    """Keep either handle-dependent or direct-argument operation values."""
    filtered: dict[tuple[str, int], set[tuple[str, str]]] = {}
    for site, pairs in values.items():
        selected = {
            pair
            for pair in pairs
            if (pair[0] in HANDLE_OPERATIONS) == handle_operations
        }
        if selected:
            filtered[site] = selected
    return filtered


def fact_category(site_rows: list[dict[str, str]]) -> str:
    statuses = {row.get("status", "") for row in site_rows}
    exact_rows = [row for row in site_rows if row.get("status") == "EXACT"]
    if exact_rows:
        direct = any(
            row.get("source_expr", "").strip()
            and row.get("source_expr", "").strip()
            == row.get("target_expression", "").strip()
            for row in exact_rows
        )
        return "exact_direct" if direct else "exact_traced"
    if "DYNAMIC" in statuses:
        return "dynamic"
    if statuses & {"EXTERNAL", "ALIAS_INTERNAL"}:
        return "external"
    if "UNREACHABLE" in statuses:
        return "unreachable"
    return "unresolved"


def metadata_terms(site_rows: list[dict[str, str]]) -> set[str]:
    terms: set[str] = set()
    for row in site_rows:
        try:
            metadata = json.loads(row.get("metadata") or "{}")
        except json.JSONDecodeError:
            terms.add("INVALID_METADATA")
            continue
        terms.add(str(metadata.get("termination_reason") or ""))
    return terms


def unresolved_reason(site_rows: list[dict[str, str]]) -> str:
    terms = metadata_terms(site_rows)
    functions = {row.get("target_function", "") for row in site_rows}
    if "HANDLE_AMBIGUOUS" in terms:
        return "HANDLE_AMBIGUOUS"
    if "UNSUPPORTED_SYNTAX" in terms:
        return "UNSUPPORTED_SYNTAX"
    if terms == {"LITERAL"} and all(
        name.startswith("pmf_forkproc") for name in functions
    ):
        return "fork target rejected by package-name validation"
    if terms == {"MACRO"}:
        return "resolved macro evidence still labeled UNRESOLVED"
    if terms == {"ENUM"}:
        return "resolved enum evidence still labeled UNRESOLVED"
    return "+".join(sorted(terms)) or "unclassified"


class SourceClassifier:
    """Classify obvious comment, #if 0, and #ifdef NOP legacy-only lines."""

    def __init__(self, source_root: Path):
        self.source_root = source_root
        self.cache: dict[str, list[str]] = {}

    @staticmethod
    def _without_comments(line: str, in_block: bool) -> tuple[str, bool]:
        output: list[str] = []
        index = 0
        quote: str | None = None
        escaped = False
        while index < len(line):
            char = line[index]
            following = line[index + 1] if index + 1 < len(line) else ""
            if in_block:
                if char == "*" and following == "/":
                    in_block = False
                    index += 2
                else:
                    index += 1
                continue
            if quote:
                output.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                index += 1
                continue
            if char in {'"', "'"}:
                quote = char
                output.append(char)
                index += 1
                continue
            if char == "/" and following == "*":
                in_block = True
                index += 2
                continue
            if char == "/" and following == "/":
                break
            output.append(char)
            index += 1
        return "".join(output), in_block

    def scan(self, relative_path: str) -> list[str]:
        if relative_path in self.cache:
            return self.cache[relative_path]
        path = self.source_root / relative_path
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            self.cache[relative_path] = []
            return []

        classifications: list[str] = []
        in_block = False
        # Each tuple is (known conditional, active, label).
        stack: list[tuple[bool, bool, str]] = []
        for line in lines:
            clean, in_block = self._without_comments(line, in_block)
            stripped = clean.strip()
            inactive = [label for known, active, label in stack if known and not active]
            if not stripped:
                classification = "comment or blank"
            elif inactive:
                classification = inactive[-1]
            else:
                classification = "not emitted by inventory"
            classifications.append(classification)

            directive = re.match(
                r"\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)", clean
            )
            if not directive:
                continue
            operation, argument = directive.group(1), directive.group(2).strip()
            if operation == "if":
                is_zero = bool(re.fullmatch(r"\(?\s*0\s*\)?(?:\s*/\*.*)?", argument))
                stack.append((is_zero, not is_zero, "#if 0"))
            elif operation == "ifdef":
                is_nop = argument.split()[0] == "NOP" if argument else False
                stack.append((is_nop, not is_nop, "#ifdef NOP"))
            elif operation == "ifndef":
                stack.append((False, True, "unknown conditional"))
            elif operation in {"else", "elif"} and stack:
                known, active, label = stack[-1]
                if known:
                    stack[-1] = (known, not active, f"else of {label}")
            elif operation == "endif" and stack:
                stack.pop()

        self.cache[relative_path] = classifications
        return classifications

    def classify(self, site: tuple[str, int]) -> str:
        lines = self.scan(site[0])
        if not lines or site[1] < 1 or site[1] > len(lines):
            return "missing source"
        return lines[site[1] - 1]

    def line(self, site: tuple[str, int]) -> str:
        path = self.source_root / site[0]
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        if site[1] < 1 or site[1] > len(lines):
            return ""
        return lines[site[1] - 1]


def relation_counts(
    reference: dict[tuple[str, int], set[tuple[str, str]]],
    candidate: dict[tuple[str, int], set[tuple[str, str]]],
) -> tuple[Counter[str], list[dict[str, Any]]]:
    counts: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    for site in sorted(reference.keys() & candidate.keys()):
        old_values = reference[site]
        new_values = candidate[site]
        if old_values == new_values:
            relation = "equal"
        elif new_values < old_values:
            relation = "new_strict_subset_of_legacy"
        elif old_values < new_values:
            relation = "legacy_strict_subset_of_new"
        elif old_values & new_values:
            relation = "partial_overlap"
        else:
            relation = "disjoint"
        counts[relation] += 1
        if relation != "equal":
            details.append(
                {
                    "file": site[0],
                    "line": site[1],
                    "relation": relation,
                    "legacy": [list(value) for value in sorted(old_values)],
                    "new": [list(value) for value in sorted(new_values)],
                }
            )
    return counts, details


def process_summary(results_dir: Path) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    failed: list[str] = []
    totals: Counter[str] = Counter()
    for path in sorted(results_dir.glob("*/run_stats.json")):
        payload = read_json(path)
        status = str(payload.get("process_status") or "unknown")
        statuses[status] += 1
        if status != "success":
            failed.append(path.parent.name)
        for key in ("llm_query_count", "answered_query_count"):
            totals[key] += int(payload.get(key) or 0)
    return {
        "total": sum(statuses.values()),
        "statuses": dict(sorted(statuses.items())),
        "failed": failed,
        "llm_query_count": totals["llm_query_count"],
        "answered_query_count": totals["answered_query_count"],
    }


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    results_dir = args.results_dir.resolve()
    legacy_index = args.legacy_index.resolve()
    target_spec = args.target_spec.resolve()
    aggregate_index = results_dir / "index"
    aggregate_metadata = read_json(aggregate_index / "index_metadata.json")
    metadata_source = Path(aggregate_metadata.get("source_root") or "/home/chukyu")
    source_root = (args.source_root or metadata_source).resolve()

    excluded_targets, wrappers, handle_targets = load_target_spec(target_spec)
    inventory, inventory_file_count = load_inventory(results_dir, excluded_targets)
    facts_by_site, fact_meta = load_facts(results_dir, excluded_targets)
    runtime_process, runtime_sites = runtime_process_csv_summary(
        results_dir, source_root, excluded_targets
    )
    inventory_sites = set(inventory)
    direct_inventory_sites = {
        site
        for site, functions in inventory.items()
        if next(iter(functions)) not in handle_targets
    }
    handle_inventory_sites = inventory_sites - direct_inventory_sites
    fact_sites = set(facts_by_site)

    if inventory_sites != fact_sites:
        missing_facts = sorted(inventory_sites - fact_sites)[:10]
        missing_inventory = sorted(fact_sites - inventory_sites)[:10]
        raise ValueError(
            "Inventory/fact mismatch after exclusions: "
            f"without facts={missing_facts}, without inventory={missing_inventory}"
        )

    legacy_values, legacy_records = load_index_values(legacy_index, source_root)
    aggregate_values, aggregate_records = load_index_values(
        aggregate_index, source_root
    )
    fact_exact_values, fact_exact_records = load_exact_fact_values(facts_by_site)
    fact_exact_dynamic_values = load_fact_values(facts_by_site, {"EXACT", "DYNAMIC"})
    fact_resolved_runtime_values = load_fact_values(
        facts_by_site, {"RESOLVED", "RUNTIME"}, field="resolution_status"
    )
    legacy_direct_values = filter_operation_values(legacy_values, False)
    legacy_handle_values = filter_operation_values(legacy_values, True)
    aggregate_direct_values = filter_operation_values(aggregate_values, False)
    aggregate_handle_values = filter_operation_values(aggregate_values, True)
    fact_exact_direct_values = filter_operation_values(fact_exact_values, False)
    fact_exact_dynamic_direct_values = filter_operation_values(
        fact_exact_dynamic_values, False
    )
    fact_resolved_runtime_direct_values = filter_operation_values(
        fact_resolved_runtime_values, False
    )
    direct_shared_sites = set(legacy_direct_values) & set(aggregate_direct_values)
    handle_shared_sites = set(legacy_handle_values) & set(aggregate_handle_values)
    legacy_sites = set(legacy_values)
    runtime_legacy_sites = runtime_sites & legacy_sites
    legacy_runtime_pairs = {
        pair for site in runtime_legacy_sites for pair in legacy_values[site]
    }
    same_runtime_pairs = {
        (row.get("operation", ""), row.get("resolved_value", ""))
        for site in runtime_legacy_sites
        for row in facts_by_site.get(site, [])
        if row.get("resolution_status") == "RUNTIME" and row.get("resolved_value")
    }
    legacy_runtime_values = {value for _, value in legacy_runtime_pairs}
    same_runtime_values = {value for _, value in same_runtime_pairs}

    source = SourceClassifier(source_root)
    legacy_only = legacy_sites - inventory_sites
    legacy_only_classes = Counter(source.classify(site) for site in legacy_only)
    inactive_classes = {"#if 0", "#ifdef NOP", "comment or blank"}
    legacy_inactive = {
        site for site in legacy_only if source.classify(site) in inactive_classes
    }
    legacy_live = legacy_sites - legacy_inactive

    categories = {
        site: fact_category(site_rows) for site, site_rows in facts_by_site.items()
    }
    category_counts = Counter(categories.values())
    broad_resolved = {
        site for site, category in categories.items() if category != "unresolved"
    }
    exact_sites = {
        site for site, category in categories.items() if category.startswith("exact_")
    }

    unresolved_sites = {
        site: unresolved_reason(facts_by_site[site])
        for site, category in categories.items()
        if category == "unresolved"
    }
    unresolved_counts = Counter(unresolved_sites.values())
    shared_unresolved_counts = Counter(
        reason for site, reason in unresolved_sites.items() if site in legacy_sites
    )

    wrapper_sites = {
        site
        for site, functions in inventory.items()
        if next(iter(functions)) in wrappers
    }
    wrapper_categories = Counter(categories[site] for site in wrapper_sites)
    wrapper_pattern = re.compile(
        r"\b(?:"
        + "|".join(map(re.escape, sorted(wrappers, key=len, reverse=True)))
        + r")\s*\("
    )
    legacy_wrapper_sites = {
        site for site in legacy_sites if wrapper_pattern.search(source.line(site))
    }

    process = process_summary(results_dir)
    aggregate_counts = aggregate_metadata.get("counts") or {}
    expected_requested = int(aggregate_counts.get("processes_requested") or 0)
    expected_included = int(aggregate_counts.get("processes_included") or 0)
    expected_failed = int(aggregate_counts.get("processes_failed") or 0)
    observed_success = int(process["statuses"].get("success", 0))
    observed_failed = int(process["statuses"].get("failed", 0))
    if expected_requested and process["total"] != expected_requested:
        raise ValueError(
            f"Run-status count {process['total']} != aggregate requested count "
            f"{expected_requested}"
        )
    if expected_included and (
        inventory_file_count != expected_included
        or observed_success != expected_included
    ):
        raise ValueError(
            "Successful process artifacts are incomplete: "
            f"metadata={expected_included}, statuses={observed_success}, "
            f"target inventories={inventory_file_count}"
        )
    if expected_failed and observed_failed != expected_failed:
        raise ValueError(
            f"Failed-process count {observed_failed} != aggregate count {expected_failed}"
        )
    failed_baseline_sites = {
        site
        for site in legacy_sites
        if any(name in Path(site[0]).parts for name in process["failed"])
    }

    aggregate_relations, aggregate_disagreements = relation_counts(
        legacy_values, aggregate_values
    )
    evidence_relations, evidence_disagreements = relation_counts(
        legacy_values, fact_exact_values
    )

    exact_shared_records = legacy_records & aggregate_records
    aggregate_shared_sites = legacy_sites & set(aggregate_values)
    evidence_shared_sites = legacy_sites & set(fact_exact_values)

    return {
        "inputs": {
            "results_dir": display_path(results_dir),
            "aggregate_index": display_path(aggregate_index),
            "legacy_index": display_path(legacy_index),
            "source_root": source_root.as_posix(),
            "target_registry_version": (
                aggregate_metadata.get("target_registry") or {}
            ).get("version", ""),
            "discovery_scope": aggregate_metadata.get("discovery_scope", ""),
        },
        "run": {
            **process,
            "inventory_files": inventory_file_count,
            "failed_baseline_sites": len(failed_baseline_sites),
        },
        "legacy": {
            "records": len(legacy_records),
            "sites": len(legacy_sites),
            "live_sites": len(legacy_live),
            "inactive_sites": len(legacy_inactive),
            "legacy_only_classification": dict(sorted(legacy_only_classes.items())),
        },
        "new": {
            "inventory_sites": len(inventory_sites),
            "direct_inventory_sites": len(direct_inventory_sites),
            "handle_inventory_sites": len(handle_inventory_sites),
            "fact_sites": len(fact_sites),
            "fact_rows": fact_meta["included_rows"],
            "excluded_close_sites": fact_meta["excluded_sites"],
            "excluded_close_rows": fact_meta["excluded_rows"],
            "runtime_process_csv": runtime_process,
            "runtime_aggregate": {
                "rows": fact_meta["resolution_status_rows"].get("RUNTIME", 0),
                "sites": fact_meta["resolution_status_sites"].get("RUNTIME", 0),
                "origins": fact_meta["runtime_origin_rows"],
                "unique_values": fact_meta["runtime_unique_values"],
                "unique_numeric_values": fact_meta["runtime_unique_numeric_values"],
                "unique_operation_values": fact_meta["runtime_unique_operation_values"],
            },
            "runtime_legacy_comparison": {
                "runtime_sites_with_legacy_records": len(runtime_legacy_sites),
                "runtime_sites_without_legacy_records": len(
                    runtime_sites - legacy_sites
                ),
                "legacy_records_at_runtime_sites": sum(
                    len(legacy_values[site]) for site in runtime_legacy_sites
                ),
                "legacy_unique_values_at_runtime_sites": len(legacy_runtime_values),
                "legacy_unique_operation_values_at_runtime_sites": len(
                    legacy_runtime_pairs
                ),
                "new_unique_values_at_shared_runtime_sites": len(same_runtime_values),
                "new_unique_operation_values_at_shared_runtime_sites": len(
                    same_runtime_pairs
                ),
            },
            "categories": dict(category_counts),
            "broad_resolved_sites": len(broad_resolved),
            "exact_sites": len(exact_sites),
            "exact_records": len(fact_exact_records),
            "unresolved_reasons": dict(unresolved_counts),
            "llm_query_count": process["llm_query_count"],
            "llm_fact_rows": sum(fact_meta["llm_rows"].values()),
            "llm_fact_rows_by_status": fact_meta["llm_rows"],
            "llm_sites": fact_meta["llm_sites"],
            "llm_exact_sites": fact_meta["llm_exact_sites"],
        },
        "site_comparison": {
            "legacy_sites": len(legacy_sites),
            "legacy_live_sites": len(legacy_live),
            "new_inventory_sites": len(inventory_sites),
            "shared_inventory_sites": len(legacy_sites & inventory_sites),
            "legacy_only_sites": len(legacy_only),
            "new_only_sites": len(inventory_sites - legacy_sites),
            "shared_broad_resolved_sites": len(legacy_sites & broad_resolved),
            "shared_exact_sites": len(evidence_shared_sites),
            "new_only_broad_resolved_sites": len(broad_resolved - legacy_sites),
            "new_only_unresolved_sites": len(
                (inventory_sites - legacy_sites) - broad_resolved
            ),
            "shared_unresolved_reasons": dict(shared_unresolved_counts),
        },
        "compatibility_index": {
            "legacy_records": len(legacy_records),
            "new_records": len(aggregate_records),
            "shared_records": len(exact_shared_records),
            "legacy_sites": len(legacy_sites),
            "new_sites": len(aggregate_values),
            "shared_sites": len(aggregate_shared_sites),
            "relations": dict(aggregate_relations),
        },
        "exact_evidence_values": {
            "legacy_sites": len(legacy_sites),
            "new_sites": len(fact_exact_values),
            "shared_sites": len(evidence_shared_sites),
            "relations": dict(evidence_relations),
        },
        "value_density": {
            "legacy_export": site_value_density(legacy_values),
            "new_aggregate_export": site_value_density(aggregate_values),
            "legacy_direct_export": site_value_density(legacy_direct_values),
            "new_direct_export": site_value_density(aggregate_direct_values),
            "legacy_handle_export": site_value_density(legacy_handle_values),
            "new_handle_export": site_value_density(aggregate_handle_values),
            "legacy_direct_shared_export": site_value_density(
                legacy_direct_values, direct_shared_sites
            ),
            "new_direct_shared_export": site_value_density(
                aggregate_direct_values, direct_shared_sites
            ),
            "legacy_handle_shared_export": site_value_density(
                legacy_handle_values, handle_shared_sites
            ),
            "new_handle_shared_export": site_value_density(
                aggregate_handle_values, handle_shared_sites
            ),
            "new_exact_facts_by_exact_site": site_value_density(fact_exact_values),
            "new_exact_facts_by_all_inventory_site": site_value_density(
                fact_exact_values, inventory_sites
            ),
            "new_exact_dynamic_facts_by_all_inventory_site": site_value_density(
                fact_exact_dynamic_values, inventory_sites
            ),
            "new_resolved_runtime_facts_by_all_inventory_site": site_value_density(
                fact_resolved_runtime_values, inventory_sites
            ),
            "new_exact_direct_facts": site_value_density(fact_exact_direct_values),
            "new_exact_direct_facts_by_all_direct_inventory_sites": site_value_density(
                fact_exact_direct_values, direct_inventory_sites
            ),
            "new_exact_dynamic_direct_facts": site_value_density(
                fact_exact_dynamic_direct_values
            ),
            "new_exact_dynamic_direct_facts_by_all_direct_inventory_sites": site_value_density(
                fact_exact_dynamic_direct_values, direct_inventory_sites
            ),
            "new_resolved_runtime_direct_facts": site_value_density(
                fact_resolved_runtime_direct_values
            ),
            "new_resolved_runtime_direct_facts_by_all_direct_inventory_sites": site_value_density(
                fact_resolved_runtime_direct_values, direct_inventory_sites
            ),
        },
        "wrappers": {
            "names": sorted(wrappers),
            "legacy_indexed_sites": len(legacy_wrapper_sites),
            "legacy_inactive_sites": len(legacy_wrapper_sites & legacy_inactive),
            "live_shared_sites": len(legacy_wrapper_sites & wrapper_sites),
            "new_inventory_sites": len(wrapper_sites),
            "new_only_sites": len(wrapper_sites - legacy_sites),
            "new_categories": dict(wrapper_categories),
        },
        "audit": {
            "legacy_only_sites": [
                {
                    "file": site[0],
                    "line": site[1],
                    "classification": source.classify(site),
                }
                for site in sorted(legacy_only)
            ],
            "shared_unresolved_sites": [
                {
                    "file": site[0],
                    "line": site[1],
                    "function": facts_by_site[site][0].get("target_function", ""),
                    "expression": facts_by_site[site][0].get("target_expression", ""),
                    "reason": unresolved_sites[site],
                }
                for site in sorted(unresolved_sites)
                if site in legacy_sites
            ],
            "aggregate_value_differences": aggregate_disagreements,
            "exact_evidence_value_differences": evidence_disagreements,
            "new_only_by_function": dict(
                Counter(
                    next(iter(inventory[site]))
                    for site in inventory_sites - legacy_sites
                ).most_common()
            ),
        },
    }


def pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "n/a"
    return f"{100 * numerator / denominator:.1f}%"


def relation_value(relations: dict[str, int], key: str) -> int:
    return int(relations.get(key, 0))


def render_markdown(data: dict[str, Any]) -> str:
    return render_compact_markdown(data)


def render_compact_markdown(data: dict[str, Any]) -> str:
    new = data["new"]
    comparison = data["site_comparison"]
    density = data["value_density"]
    legacy_density = density["legacy_export"]
    new_density = density["new_aggregate_export"]
    legacy_direct = density["legacy_direct_export"]
    legacy_handle = density["legacy_handle_export"]
    new_resolved_runtime = density[
        "new_resolved_runtime_direct_facts_by_all_direct_inventory_sites"
    ]
    density_increase_pct = 100 * (
        new_resolved_runtime["values_per_site"] / legacy_direct["values_per_site"] - 1
    )
    lines = [
        BEGIN_MARKER,
        "_Generated by `analysis/scripts/1-compare-sites.py`; this table is the machine-checked numeric checkpoint for the narrative above._",
        "_The main value comparison excludes handle-dependent record functions from both sides. It includes all new non-handle sites and their RESOLVED/RUNTIME facts. The export and handle rows are diagnostics._",
        "",
        "| Checkpoint | Legacy | New | Shared |",
        "|---|---:|---:|---:|",
        f"| Site locations | {comparison['legacy_sites']:,} | {comparison['new_inventory_sites']:,} | {comparison['shared_inventory_sites']:,} |",
        f"| Active old sites / all new sites | {comparison['legacy_live_sites']:,} | {comparison['new_inventory_sites']:,} | {comparison['shared_inventory_sites']:,} |",
        f"| Sites with a usable result | {comparison['legacy_live_sites']:,} | {new['broad_resolved_sites']:,} | {comparison['shared_broad_resolved_sites']:,} |",
        f"| Exact result (new) | — | {new['exact_sites']:,} | {comparison['shared_exact_sites']:,} |",
        f"| Only on one side | {comparison['legacy_only_sites']:,} | {comparison['new_only_sites']:,} | — |",
        f"| Main comparison: legacy non-handle values/site | {legacy_direct['site_value_total']:,} / {legacy_direct['sites']:,} = {legacy_direct['values_per_site']:.2f} | — | — |",
        f"| Main comparison: new non-handle RESOLVED + RUNTIME values/site | — | {new_resolved_runtime['site_value_total']:,} / {new_resolved_runtime['sites']:,} = {new_resolved_runtime['values_per_site']:.2f} | — |",
        f"| New density increase over legacy | — | +{density_increase_pct:.1f}% | — |",
        f"| New final export (diagnostic) | — | {new_density['site_value_total']:,} / {new_density['sites']:,} = {new_density['values_per_site']:.2f} | — |",
        f"| Legacy handle multiplication (diagnostic) | {legacy_handle['site_value_total']:,} / {legacy_handle['sites']:,} = {legacy_handle['values_per_site']:.2f} | — | — |",
        "",
        END_MARKER,
    ]
    return "\n".join(lines)


def replace_generated_block(report: Path, generated: str) -> None:
    text = report.read_text(encoding="utf-8")
    start = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        raise ValueError(f"Generated markers are missing or invalid in {report}")
    end += len(END_MARKER)
    report.write_text(text[:start] + generated + text[end:], encoding="utf-8")


def check_generated_block(report: Path, generated: str) -> bool:
    text = report.read_text(encoding="utf-8")
    start = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        return False
    end += len(END_MARKER)
    return text[start:end] == generated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--legacy-index", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument("--source-root", type=Path)
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
