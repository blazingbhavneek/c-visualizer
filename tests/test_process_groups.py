import json
import tempfile
import unittest
from pathlib import Path

from frontend.server import VisualizerHandler
from process_groups import (
    discover_processes,
    load_group_manifest,
    process_output_names,
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

    def test_duplicate_process_names_are_path_qualified_for_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "chukyu"
            first = root / "t-dxi" / "src" / "dxi510d"
            second = first / "dxi510d"
            for process in (first, second):
                process.mkdir(parents=True, exist_ok=True)
                (process / "Makefile").write_text("SRCS = main.c\n", encoding="utf-8")

            paths = validate_processes([first, second])
            names = process_output_names(paths, root=root)

            self.assertEqual(names[first.resolve()], "t-dxi__src__dxi510d")
            self.assertEqual(
                names[second.resolve()], "t-dxi__src__dxi510d__dxi510d"
            )

    def test_target_override_allows_missing_optional_project_metadata(self):
        from process_groups import load_project_state
        from state.state import State

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_dir = root / "json_data"
            json_dir.mkdir()
            spec = Path(__file__).resolve().parents[1] / "target_specs" / "build_index_targets.json"
            try:
                state = load_project_state(json_dir, targets_path=spec)
                self.assertEqual(state.get("FUNCTION_POINTER_ARGS"), {})
                self.assertEqual(state.get("FUNCTION_MAP"), {})
                self.assertEqual(len(state.get("FUNCTION_TYPES")), 33)
            finally:
                State().reset()

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


class TargetOverrideTests(unittest.TestCase):
    """--targets override loading: valid specs load, broken specs fail hard."""

    REPO = Path(__file__).resolve().parents[1]
    CANONICAL_SPEC = REPO / "target_specs" / "build_index_targets.json"

    def _json_dir(self, root: Path) -> Path:
        json_dir = root / "proj" / "json_data"
        json_dir.mkdir(parents=True)
        (json_dir / "function_callback_info.json").write_text("{}", encoding="utf-8")
        (json_dir / "combined_data.json").write_text("{}", encoding="utf-8")
        return json_dir

    def test_invalid_targets_override_fails_before_discovery(self):
        from process_groups import load_project_state
        from state.state import State

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_dir = self._json_dir(root)
            spec = json.loads(self.CANONICAL_SPEC.read_text(encoding="utf-8"))
            del spec["targets"]["mpf_mfs_addque"]  # silently shrunk registry
            bad = root / "bad_targets.json"
            bad.write_text(json.dumps(spec), encoding="utf-8")
            try:
                with self.assertRaises(ValueError) as ctx:
                    load_project_state(json_dir, targets_path=bad)
            finally:
                State().reset()
        self.assertIn("mpf_mfs_addque", str(ctx.exception))
        self.assertIn("refusing to start a discovery run", str(ctx.exception))

    def test_valid_targets_override_loads_spec_and_types(self):
        from process_groups import load_project_state
        from state.state import State

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_dir = self._json_dir(root)
            try:
                state = load_project_state(
                    json_dir, targets_path=self.CANONICAL_SPEC
                )
                spec = state.get("TARGET_SPEC")
                self.assertEqual(len(spec["targets"]), 33)
                self.assertEqual(state.get("FUNCTION_TYPES"), spec["targets"])
                self.assertEqual(state.get("FUNCTION_POINTER_ARGS"), {})
                self.assertEqual(state.get("FUNCTION_MAP"), {})
            finally:
                State().reset()

    def test_library_signatures_enrich_function_map_without_losing_docs(self):
        from process_groups import load_project_state
        from state.state import State

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_dir = self._json_dir(root)
            (json_dir / "combined_data.json").write_text(
                json.dumps(
                    {
                        "pmf_addevent": {
                            "description": "registered event callback",
                            "parameters": [{"name": "eventno"}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (json_dir / "function_registry.json").write_text(
                json.dumps(
                    {
                        "mpf_mfs_open": {
                            "prototype": "int mpf_mfs_open(MPF_MFS_FCB *, char *, int, int, ssize_t, int)",
                            "parameters": [],
                        },
                        "pmf_addevent": {
                            "prototype": "int pmf_addevent(int, void (*)(), size_t)",
                            "parameters": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (json_dir / "function_callback_info.json").write_text(
                json.dumps(
                    {
                        "pmf_addevent": {
                            "prototype": "int pmf_addevent(int, void (*)(PMF_EVNHEAD *, void *), size_t)",
                            "func_argument": [2],
                            "total_args": 3,
                        }
                    }
                ),
                encoding="utf-8",
            )
            try:
                state = load_project_state(json_dir, targets_path=self.CANONICAL_SPEC)
                function_map = state.get("FUNCTION_MAP")

                self.assertEqual(
                    function_map["pmf_addevent"]["description"],
                    "registered event callback",
                )
                self.assertEqual(
                    function_map["pmf_addevent"]["prototype"],
                    "int pmf_addevent(int, void (*)(PMF_EVNHEAD *, void *), size_t)",
                )
                self.assertEqual(function_map["pmf_addevent"]["total_args"], 3)
                self.assertEqual(
                    function_map["mpf_mfs_open"]["prototype"],
                    "int mpf_mfs_open(MPF_MFS_FCB *, char *, int, int, ssize_t, int)",
                )
                self.assertEqual(
                    state.get("FUNCTION_SIGNATURES")["mpf_mfs_open"]["prototype"],
                    "int mpf_mfs_open(MPF_MFS_FCB *, char *, int, int, ssize_t, int)",
                )
            finally:
                State().reset()


if __name__ == "__main__":
    unittest.main()
