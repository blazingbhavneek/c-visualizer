from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from itertools import product
from pathlib import Path

from output_paths import process_results_dir
from value_flow.resolver import ResolvedSeed, ValueFlowResolver

FACT_COLUMNS = [
    "fact_id",
    "process_name",
    "function_name",
    "target_site_file",
    "target_site_line",
    "target_site_id",
    "arg_index",
    "value",
    "origin_kind",
    "source_file",
    "source_line",
    "source_expr",
    "type",
    "launch_via",
    "call_function",
    "call_number",
    "link_method",
    "metadata",
    "path_count",
    "resolved_by",
]

PATH_COLUMNS = ["fact_id", "path_index", "path", "path_length"]

LEGACY_COLUMNS = [
    "process_name",
    "function_name",
    "target_number->ans",
    "call_number",
    "target_number->path_str",
    "launch_via",
    "call_function",
    "type",
    "function_name_src->path",
    "function_name_src->line_number",
    "target_name_src->path",
    "target_name_src->line_number",
]


@dataclass(frozen=True, slots=True)
class OutputPaths:
    facts: Path
    paths: Path
    legacy: Path
    truncations: Path


def _atomic_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        Path(temporary_name).replace(path)
    except Exception:
        try:
            Path(temporary_name).unlink()
        except OSError:
            pass
        raise


def _display_call_number(value: str | None) -> str:
    return "NA" if value in {None, "", "-1", "-1.0"} else str(value)


def _target_component(value: str) -> str:
    """Render a C string literal as the identifier component it denotes."""
    text = str(value).strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text


def _legacy_rows(records: list[ResolvedSeed], process_name: str) -> list[dict]:
    """Write one row per target invocation and distinct argument-path tuple."""
    # `records` are one source fact for one target argument. A target such as
    # pmf_setsem(process, index) needs both configured arguments combined into
    # one target name (for example, svm300d_0), while alternative source paths
    # must stay as separate rows.
    grouped: dict[tuple, list[ResolvedSeed]] = {}
    for record in records:
        key = (
            record.seed.site.site_id,
            record.operation,
            record.seed.launch_via,
            record.seed.call_function,
            record.call_number,
        )
        grouped.setdefault(key, []).append(record)

    rows: list[dict] = []
    for group in grouped.values():
        choices_by_index: dict[int, list[tuple[ResolvedSeed, list[str]]]] = {}
        for record in group:
            # One record can have several provenance paths. They remain
            # independent choices; cache reuse must not collapse them.
            for labels in record.legacy_paths or [record.legacy_labels]:
                choices_by_index.setdefault(record.arg_index, []).append(
                    (record, labels)
                )

        ordered_indices = sorted(choices_by_index)
        for combination in product(*(choices_by_index[index] for index in ordered_indices)):
            representative = combination[0][0]
            values = [item.fact.value for item, _ in combination]
            target_value = (
                "_".join(_target_component(value) for value in values)
                if len(ordered_indices) > 1
                else values[0]
            )
            display_paths = ["->".join(labels) for _, labels in combination]
            path = " | ".join(dict.fromkeys(display_paths))
            site = representative.seed.site
            rows.append(
                {
                    "process_name": process_name,
                    "function_name": representative.seed.target_function,
                    "target_number->ans": target_value,
                    "call_number": _display_call_number(representative.call_number),
                    "target_number->path_str": path,
                    "launch_via": representative.seed.launch_via,
                    "call_function": representative.seed.call_function,
                    "type": representative.operation,
                    "function_name_src->path": representative.seed.function_source_file,
                    "function_name_src->line_number": representative.seed.function_source_line,
                    "target_name_src->path": site.file_path,
                    "target_name_src->line_number": site.line,
                }
            )
    return rows


def write_trace_logs(
    *,
    records: list[ResolvedSeed],
    resolver: ValueFlowResolver,
    process_name: str,
    output_root: Path,
) -> Path:
    """Write one readable log per resolved fact, target call down to its source.

    Each step is a query the resolver actually answered, with the wall time it
    cost and whether the model was consulted, so a slow run can be attributed to
    a specific hop rather than to the process as a whole.
    """
    log_dir = process_results_dir(process_name) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for stale in log_dir.glob("*.log"):
        stale.unlink()

    summary: list[str] = []
    for index, record in enumerate(sorted(records, key=lambda item: -item.seconds), 1):
        site = record.seed.site
        fact = record.fact
        chain = resolver.provenance_tokens(fact, record.query_token) or [
            record.query_token
        ]
        # provenance_tokens runs source -> target; a log reads target -> source.
        steps = list(reversed(chain))
        llm_steps = sum(
            1 for step in steps if resolver.timings.get(step, {}).get("used_llm")
        )

        lines = [
            f"TARGET   {record.seed.target_function}  "
            f"{Path(site.file_path).name}:{site.line}  arg {record.arg_index}",
            f"RESULT   {fact.value}  ({fact.origin_kind})  type={record.operation}"
            + (f"  link={fact.link_method}" if fact.link_method else ""),
            f"SOURCE   {Path(fact.source_file).name}:{fact.source_line}  "
            f"{fact.source_expr}",
            f"TOTAL    {record.seconds:.3f}s over {len(steps)} step(s), "
            f"{llm_steps} model call(s)",
            f"PATHS    {record.path_count} source-to-target path(s)",
            "",
            "chain (target -> source):",
        ]
        for position, step in enumerate(steps, 1):
            timing = resolver.timings.get(step, {})
            lines.append(
                f"  [{position}] {timing.get('seconds', 0.0):8.3f}s  "
                f"{'LLM   ' if timing.get('used_llm') else 'SYNTAX'}  "
                f"{resolver.query_labels.get(step, step)}"
            )

        safe = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            f"{record.seed.target_function}_{Path(site.file_path).name}_"
            f"{site.line}_arg{record.arg_index}_{fact.value}",
        ).strip("_")[:120]
        (log_dir / f"{index:03d}_{safe}.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        summary.append(
            f"{record.seconds:8.3f}s  {llm_steps} llm  "
            f"{record.seed.target_function} "
            f"{Path(site.file_path).name}:{site.line} arg{record.arg_index} "
            f"-> {fact.value} ({fact.origin_kind})"
        )

    (log_dir / "000_summary.log").write_text(
        "slowest first\n\n" + "\n".join(summary) + "\n", encoding="utf-8"
    )
    return log_dir


def write_outputs(
    *,
    records: list[ResolvedSeed],
    resolver: ValueFlowResolver,
    process_name: str,
    output_root: Path,
    run_stats: dict | None = None,
) -> OutputPaths:
    """Write the fact, provenance-path, and legacy compatibility CSVs once."""
    # Output has three levels. Do not confuse them while debugging:
    #   facts.csv  = one resolved source value for one target argument
    #   paths.csv  = every source-to-target route for that fact
    #   <process>.csv = values combined per target invocation for old consumers
    process_dir = process_results_dir(process_name)
    fact_path = process_dir / "facts.csv"
    path_path = process_dir / "paths.csv"
    # The legacy feed keeps its old location: rehydrate_interactions and any
    # existing downstream tooling look for exactly this path.
    legacy_path = output_root / f"{process_name}.csv"
    truncation_path = process_dir / "truncated_paths.log"

    fact_rows: list[dict] = []
    path_rows: list[dict] = []
    truncations: list[str] = []
    for record in records:
        fact_id = resolver.fact_id(record, process_name)
        site = record.seed.site
        fact = record.fact
        fact_rows.append(
            {
                "fact_id": fact_id,
                "process_name": process_name,
                "function_name": record.seed.target_function,
                "target_site_file": site.file_path,
                "target_site_line": site.line,
                "target_site_id": site.site_id,
                "arg_index": record.arg_index,
                "value": fact.value,
                "origin_kind": fact.origin_kind,
                "source_file": fact.source_file,
                "source_line": fact.source_line,
                "source_expr": fact.source_expr,
                "type": record.operation,
                "launch_via": record.seed.launch_via,
                "call_function": record.seed.call_function,
                "call_number": _display_call_number(record.call_number),
                "link_method": fact.link_method,
                "metadata": json.dumps(fact.metadata or {}, ensure_ascii=False, sort_keys=True),
                "path_count": record.path_count,
                "resolved_by": fact.resolved_by,
            }
        )
        for path_index, path in enumerate(record.paths, start=1):
            path_rows.append(
                {
                    "fact_id": fact_id,
                    "path_index": path_index,
                    "path": " -> ".join(path),
                    "path_length": len(path),
                }
            )
        if record.paths_truncated:
            truncations.append(
                f"{fact_id}: wrote {len(record.paths)} of {record.path_count} provenance paths"
            )

    fact_rows.sort(
        key=lambda row: (
            row["function_name"],
            row["target_site_id"],
            int(row["arg_index"]),
            row["source_file"],
            int(row["source_line"]),
            row["value"],
        )
    )
    path_rows.sort(key=lambda row: (row["fact_id"], int(row["path_index"])))
    legacy_rows = _legacy_rows(records, process_name)
    legacy_rows.sort(
        key=lambda row: (
            row["function_name"],
            row["target_name_src->path"],
            int(row["target_name_src->line_number"]),
            row["target_number->ans"],
        )
    )

    resolved_by = Counter(row["resolved_by"] for row in fact_rows)
    origins = Counter(row["origin_kind"] for row in fact_rows)
    targets = sorted({row["function_name"] for row in fact_rows})
    stats = run_stats or {}
    tokens = stats.get("Tokens") or {}
    model_calls = stats.get("llm_query_count", 0)
    wall = stats.get("wall_seconds")
    slowest = sorted(records, key=lambda item: -item.seconds)[:5]
    (process_dir / "summary.md").parent.mkdir(parents=True, exist_ok=True)
    (process_dir / "summary.md").write_text(
        "\n".join(
            [
                f"# {process_name}",
                "",
                "## Run",
                "",
                "| measure | value |",
                "| --- | --- |",
                f"| target invocations found | {stats.get('seed_count', len(records))} |",
                f"| facts produced | {len(records)} |",
                f"| target functions | {len(targets)} |",
                f"| questions answered | {stats.get('answered_query_count', 'n/a')} |",
                f"| **model calls** | **{model_calls}** |",
                f"| resolved without a model | {resolved_by.get('SYNTAX', 0)} of {len(fact_rows)} facts |",
                f"| tokens (in / out / total) | {tokens.get('Input_tokens', 0)} / "
                f"{tokens.get('Output_tokens', 0)} / {tokens.get('Total_tokens', 0)} |",
                f"| wall time | {wall:.1f}s |" if wall else "| wall time | n/a |",
                "",
                f"Origins: "
                + ", ".join(f"{key} {value}" for key, value in origins.most_common()),
                "",
                "### Slowest resolutions",
                "",
                "| seconds | model calls | target | value |",
                "| --- | --- | --- | --- |",
                *(
                    f"| {item.seconds:.2f} | "
                    f"{sum(1 for step in (resolver.provenance_tokens(item.fact, item.query_token) or []) if resolver.timings.get(step, {}).get('used_llm'))} | "
                    f"{item.seed.target_function} "
                    f"{Path(item.seed.site.file_path).name}:{item.seed.site.line} | "
                    f"{item.fact.value} |"
                    for item in slowest
                ),
                "",
                "Each time is inclusive of the shared upstream questions that fact",
                "depended on, so facts that reuse a question overlap and these do not",
                "sum to wall time. Full per-resolution timings: `logs/000_summary.log`.",
                "",
                "## What each file is",
                "",
                "| path | contents |",
                "| --- | --- |",
                "| `facts.csv` | one row per (target invocation, argument, source). The answer. |",
                "| `paths.csv` | how each fact's value travels from its source to the target, joined by `fact_id`. |",
                "| `logs/000_summary.log` | every fact, slowest first, with model-call counts. |",
                "| `logs/<n>_<target>.log` | one resolution: target down to source, timed per step. |",
                "| `targets/<function>/unique_paths.xlsx` | per-target audit: `all_paths` + `unique_target_invocations`. |",
                "| `targets/<function>/graph.html` | interactive call diagram (`graph.md` is the mermaid form). |",
                "| `run_stats.json` | seeds, queries answered, model calls, tokens. |",
                "| `query_cache.json` | resolved queries, reused on the next run. |",
                "| `truncated_paths.log` | facts whose path list hit the cap (empty is good). |",
                "",
                f"`../{process_name}.csv` is the legacy machine feed the visualizer reads;",
                "it stays outside this folder because that path is a contract.",
                "",
                "## Targets",
                "",
                *(f"- {name}" for name in targets),
                "",
            ]
        ),
        encoding="utf-8",
    )

    _atomic_csv(fact_path, FACT_COLUMNS, fact_rows)
    _atomic_csv(path_path, PATH_COLUMNS, path_rows)
    _atomic_csv(legacy_path, LEGACY_COLUMNS, legacy_rows)
    truncation_path.parent.mkdir(parents=True, exist_ok=True)
    truncation_path.write_text(
        "\n".join(truncations) + ("\n" if truncations else ""), encoding="utf-8"
    )
    return OutputPaths(fact_path, path_path, legacy_path, truncation_path)
