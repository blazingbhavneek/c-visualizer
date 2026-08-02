import json
import tempfile
import unittest
from pathlib import Path

from frontend.server import VisualizerHandler
from process_groups import (
    discover_processes,
    load_group_manifest,
    scan_graph_runs,
    select_process_runs,
    validate_processes,
    write_group_manifest,
)


def write_graph(
    results_root: Path,
    process_name: str,
    run_id: str,
    *,
    generated_at: str,
    resource_name: str | None = None,
) -> Path:
    resources = []
    interactions = []
    if resource_name:
        resources = [{"id": f"resource-{process_name}", "kind": "QUEUE", "name": resource_name}]
        interactions = [
            {
                "id": f"interaction-{process_name}",
                "function_id": f"function-{process_name}",
                "resource_id": f"resource-{process_name}",
                "operation": "ENQ" if process_name == "producer" else "DEQ",
            }
        ]
    graph = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated_at,
        "process": {"name": process_name, "root": f"/src/{process_name}"},
        "functions": [{"id": f"function-{process_name}", "name": "main"}],
        "resources": resources,
        "interactions": interactions,
        "calls": [],
    }
    path = (
        results_root
        / "visualizer"
        / process_name
        / "runs"
        / run_id
        / "graph.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(graph), encoding="utf-8")
    return path


class ProcessGroupTests(unittest.TestCase):
    def test_discovers_makefile_processes_recursively_and_validates_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "line-a" / "producer"
            second = root / "line-b" / "consumer"
            ignored = root / "node_modules" / "dependency"
            for process in (first, second, ignored):
                process.mkdir(parents=True)
                (process / "Makefile").write_text("SRCS = main.c\n", encoding="utf-8")

            discovered = discover_processes(root)
            self.assertEqual(discovered, [first.resolve(), second.resolve()])
            self.assertEqual(validate_processes(discovered), discovered)

    def test_existing_run_policy_prefers_latest_snapshot_with_interactions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            results_root = Path(temp_dir)
            write_graph(
                results_root,
                "producer",
                "older-useful",
                generated_at="2026-01-01T00:00:00+00:00",
                resource_name="orders",
            )
            write_graph(
                results_root,
                "producer",
                "newer-empty",
                generated_at="2026-01-02T00:00:00+00:00",
            )

            runs = scan_graph_runs(results_root)
            useful = select_process_runs(runs, policy="latest-with-interactions")
            latest = select_process_runs(runs, policy="latest")

            self.assertEqual(useful[0]["run_id"], "older-useful")
            self.assertEqual(latest[0]["run_id"], "newer-empty")

    def test_group_pins_exact_snapshots_and_joins_cross_process_resource(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            results_root = Path(temp_dir)
            producer = write_graph(
                results_root,
                "producer",
                "run-one",
                generated_at="2026-01-01T00:00:00+00:00",
                resource_name="orders",
            )
            consumer = write_graph(
                results_root,
                "consumer",
                "run-two",
                generated_at="2026-01-01T00:01:00+00:00",
                resource_name="orders",
            )

            manifest_path = write_group_manifest(
                results_root,
                "order-pipeline",
                graph_paths=[producer, consumer],
                failures=[{"process_name": "optional", "error": "not configured"}],
                run_id="batch-one",
            )
            resolved_path, manifest = load_group_manifest(results_root, "order-pipeline")

            self.assertEqual(resolved_path, manifest_path.resolve())
            self.assertEqual(manifest["selection_policy"], "exact-batch-snapshots")
            self.assertEqual(
                {(item["process_name"], item["run_id"]) for item in manifest["processes"]},
                {("producer", "run-one"), ("consumer", "run-two")},
            )
            self.assertEqual(manifest["totals"]["processes"], 2)
            self.assertEqual(manifest["totals"]["cross_process_resources"], 1)
            shared = manifest["shared_resources"][0]
            self.assertEqual(shared["processes"], ["consumer", "producer"])
            self.assertEqual(shared["operations"], ["DEQ", "ENQ"])
            self.assertTrue(shared["is_cross_process"])
            self.assertEqual(len(manifest["failures"]), 1)

            group_index = json.loads(
                (results_root / "visualizer" / "groups.json").read_text(encoding="utf-8")
            )
            self.assertEqual(group_index[0]["name"], "order-pipeline")

    def test_frontend_run_listing_can_be_pinned_to_group_members(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            results_root = Path(temp_dir)
            write_graph(
                results_root,
                "producer",
                "kept",
                generated_at="2026-01-01T00:00:00+00:00",
            )
            write_graph(
                results_root,
                "producer",
                "not-kept",
                generated_at="2026-01-02T00:00:00+00:00",
            )
            write_graph(
                results_root,
                "unrelated",
                "also-not-kept",
                generated_at="2026-01-03T00:00:00+00:00",
            )

            handler = object.__new__(VisualizerHandler)
            handler.results_root = results_root
            handler.group_members = {("producer", "kept")}
            runs = VisualizerHandler._runs(handler)

            self.assertEqual(
                [(run["process_name"], run["run_id"]) for run in runs],
                [("producer", "kept")],
            )


if __name__ == "__main__":
    unittest.main()
