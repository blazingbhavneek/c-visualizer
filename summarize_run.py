#!/usr/bin/env python3
"""Fill in function summaries for results that already exist.

A `graph.json` snapshot carries every function's source, the complete call
edges and whatever summaries a previous run managed to produce, so summarizing
after the fact needs nothing but the results folder - no re-parse, no project
structure pickle, no access to the original source tree:

    python summarize_run.py --results-root <out>/results/csv_results \\
        --process proc_boiler \\
        --summary-model MODEL --summary-base-url URL --wiki-url URL

Only functions whose `summary` is still empty are sent to the model; the
snapshot is rewritten in place, so the run keeps its ID and stays selectable in
the frontend exactly as before.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from function_summaries import SummaryConfig, summarize_collector
from output_paths import results_root
from visualizer_export import VisualizerCollector


class SnapshotCollector:
    """The slice of `VisualizerCollector` that `summarize_collector` uses."""

    def __init__(self, graph_path: Path) -> None:
        self.graph_path = Path(graph_path)
        self.snapshot = json.loads(self.graph_path.read_text(encoding="utf-8"))
        self.functions = {
            function["id"]: function for function in self.snapshot.get("functions", [])
        }
        self.calls = {call["id"]: call for call in self.snapshot.get("calls", [])}
        self.process_name = (self.snapshot.get("process") or {}).get(
            "name"
        ) or self.graph_path.parents[2].name
        # <results_root>/visualizer/<process>/runs/<run_id>/graph.json
        self.results_root = self.graph_path.parents[4]

    def pending(self) -> int:
        return sum(
            1
            for function in self.functions.values()
            if not function.get("is_external")
            and not function.get("is_library_api")
            and not (function.get("summary") or "").strip()
        )

    def write(self) -> Path:
        """Checkpoint back into the same snapshot, keeping its run identity."""
        self.snapshot["functions"] = sorted(
            self.functions.values(), key=lambda item: (item["name"], item["id"])
        )
        VisualizerCollector._atomic_write_json(self.graph_path, self.snapshot)
        return self.graph_path


def find_graphs(
    root: Path, process: str | None, run: str | None, all_runs: bool
) -> list[Path]:
    visualizer = Path(root).expanduser().resolve() / "visualizer"
    pattern = f"{process or '*'}/runs/{run or '*'}/graph.json"
    graphs = sorted(visualizer.glob(pattern))
    if all_runs or run or not graphs:
        return graphs
    # Default to one snapshot per process: the newest run.
    newest: dict[str, Path] = {}
    for graph in graphs:
        newest[graph.parents[2].name] = graph
    return sorted(newest.values())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the missing function summaries of finished runs."
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=results_root(),
        help="Results folder, e.g. <output-root>/results/csv_results.",
    )
    parser.add_argument("--process", help="Only this process (default: every process).")
    parser.add_argument("--run", help="Only this run id (default: the newest run).")
    parser.add_argument(
        "--all-runs", action="store_true", help="Every run, not only the newest."
    )
    parser.add_argument(
        "--graph", type=Path, help="Summarize exactly this graph.json and nothing else."
    )
    parser.add_argument("--summary-model")
    parser.add_argument("--summary-base-url")
    parser.add_argument("--wiki-url")
    parser.add_argument("--wiki-placeholder", action="store_true")
    parser.add_argument("--summary-concurrency", type=int)
    parser.add_argument(
        "--redo-all",
        action="store_true",
        help="Also re-summarize functions that already have a summary.",
    )
    args = parser.parse_args()

    config = SummaryConfig.from_env()
    config.enabled = True
    config.only_missing = not args.redo_all
    if args.summary_model:
        config.model = args.summary_model
    if args.summary_base_url:
        config.base_url = args.summary_base_url
    if args.wiki_url:
        config.wiki_url = args.wiki_url
    if args.wiki_placeholder:
        config.wiki_placeholder = True
    if args.summary_concurrency:
        config.concurrency = max(1, args.summary_concurrency)

    graphs = (
        [args.graph.expanduser().resolve()]
        if args.graph
        else find_graphs(args.results_root, args.process, args.run, args.all_runs)
    )
    if not graphs:
        print("No graph.json snapshots matched.")
        return 1

    failed = 0
    for graph_path in graphs:
        collector = SnapshotCollector(graph_path)
        pending = collector.pending()
        print(f"{collector.process_name} [{graph_path.parent.name}]: {pending} missing")
        if pending == 0 and config.only_missing:
            continue
        try:
            report = asyncio.run(summarize_collector(collector, config))
        except Exception as exc:
            failed += 1
            print(f"  summarization failed: {exc}")
            continue
        collector.write()
        print(f"  {report} -> {graph_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
