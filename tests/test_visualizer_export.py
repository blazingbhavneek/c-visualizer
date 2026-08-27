import json
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from call_graph.data_classes import CallSite, FunctionNode
from helpers.Preprocess.preprocess import Preprocess
from state.state import State
from visualizer_export import (
    VisualizerCollector,
    build_complete_call_graph,
    build_complete_file_functions,
)


class VisualizerCollectorTests(unittest.TestCase):
    def test_complete_file_functions_reuses_parsed_header_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            header = Path(temp_dir) / "api.h"
            header.write_text(
                "static int header_api(int value) { return value + 1; }\n",
                encoding="latin-1",
            )
            trees = Preprocess().preprocess(project_structure={"api.h": header})

            definitions = build_complete_file_functions(trees, {})

            self.assertEqual(
                definitions["api.h"]["header_api"]["start_line"],
                1,
            )
            self.assertEqual(definitions["api.h"]["header_api"]["end_line"], 1)

    def test_adapter_caches_the_original_builder_outputs_without_filtering(self):
        main = FunctionNode("main", "main.c", "/project/main.c")
        isolated = FunctionNode("isolated", "main.c", "/project/main.c")
        registry = {node.unique_id: node for node in (main, isolated)}
        graph = {main.unique_id: []}

        class OriginalBuilder:
            node_registry = registry
            macros = {"CALL": ("target()", "/project/main.h", "CALL")}

            def build(self):
                return graph

        state = State()
        state.reset()
        with patch(
            "call_graph.call_graph.CallGraphBuilder", return_value=OriginalBuilder()
        ), patch(
            "call_graph.call_graph.build_call_trees", return_value={main.unique_id: object()}
        ):
            actual_graph, actual_registry, tree_objects, macros = build_complete_call_graph(
                {"main.c": "/project/main.c"},
                {},
            )

        self.assertIs(actual_graph, graph)
        self.assertIs(actual_registry, registry)
        self.assertIn(isolated.unique_id, actual_registry)
        self.assertIn(main.unique_id, tree_objects)
        self.assertIn("CALL", macros)
        self.assertIs(state.get("CALL_GRAPH"), graph)
        state.reset()

    def test_uses_definition_index_when_original_node_has_no_source_range(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            header = root / "inline.h"
            header.write_text(
                "static inline int inline_value(void) { return 5; }\n",
                encoding="latin-1",
            )
            node = FunctionNode("inline_value", "inline.h", str(header), is_static=True)
            collector = VisualizerCollector(
                process_name="process",
                process_root=root,
                project_structure={"inline.h": str(header)},
                file_functions={
                    "inline.h": {
                        "inline_value": {"start_line": 1, "end_line": 1}
                    }
                },
                main_file_name=None,
                results_root=root / "results",
            )

            collector.capture_call_graph(graph={}, registry={node.unique_id: node})
            exported = next(iter(collector.functions.values()))

            self.assertEqual(exported["start_line"], 1)
            self.assertEqual(exported["end_line"], 1)
            self.assertIn("inline_value", exported["source"])

    def test_persists_isolated_functions_sources_and_idempotent_checkpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "process"
            root.mkdir()
            source_path = root / "main.c"
            source_path.write_text(
                "int leaf(void) { return 7; }\n"
                "int main(void) { return leaf(); }\n"
                "static int isolated(void) { return 9; }\n",
                encoding="latin-1",
            )
            (root / "Makefile").write_text("SRCS = main.c\n", encoding="utf-8")

            leaf = FunctionNode("leaf", "main.c", str(source_path), start_line=1, end_line=1)
            main = FunctionNode("main", "main.c", str(source_path), start_line=2, end_line=2)
            isolated = FunctionNode(
                "isolated",
                "main.c",
                str(source_path),
                is_static=True,
                start_line=3,
                end_line=3,
            )
            registry = {node.unique_id: node for node in (leaf, main, isolated)}
            graph = {
                main.unique_id: [CallSite(callee=leaf, line_number=2)],
            }
            collector = VisualizerCollector(
                process_name="process",
                process_root=root,
                project_structure={"main.c": str(source_path)},
                file_functions={
                    "main.c": {
                        "leaf": {"start_line": 1, "end_line": 1},
                        "main": {"start_line": 2, "end_line": 2},
                        "isolated": {"start_line": 3, "end_line": 3},
                    }
                },
                main_file_name="main.c",
                run_id="test-run",
                results_root=Path(temp_dir) / "results",
            )
            collector.capture_call_graph(graph=graph, registry=registry)
            first_path = collector.write()
            collector.functions[collector._function_id(leaf)]["summary"] = "Returns seven."
            collector.functions[collector._function_id(leaf)]["summary_status"] = "ready"
            second_path = collector.write()

            self.assertEqual(first_path, second_path)
            snapshot = json.loads(first_path.read_text(encoding="utf-8"))
            self.assertEqual(len([fn for fn in snapshot["functions"] if not fn["is_external"]]), 3)
            isolated_snapshot = next(fn for fn in snapshot["functions"] if fn["name"] == "isolated")
            self.assertIn("static int isolated", isolated_snapshot["source"])
            self.assertTrue(any(item["file_name"] == "Makefile" for item in snapshot["source_files"]))
            manifest = json.loads((Path(temp_dir) / "results" / "visualizer" / "runs.json").read_text())
            self.assertEqual(len(manifest), 1)

    def test_rehydrates_resumed_interactions_from_process_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "process"
            root.mkdir()
            source_path = root / "main.c"
            source_path.write_text("int main(void) { return api(10, 20); }\n", encoding="latin-1")

            main = FunctionNode("main", "main.c", str(source_path), start_line=1, end_line=1)
            api = FunctionNode("api", "main.c", str(source_path), is_external=True)
            collector = VisualizerCollector(
                process_name="process",
                process_root=root,
                project_structure={"main.c": str(source_path)},
                file_functions={"main.c": {"main": {"start_line": 1, "end_line": 1}}},
                main_file_name="main.c",
                results_root=Path(temp_dir) / "results",
            )
            collector.capture_call_graph(
                graph={main.unique_id: [CallSite(callee=api, line_number=1)]},
                registry={main.unique_id: main, api.unique_id: api},
            )

            csv_path = Path(temp_dir) / "process.csv"
            fieldnames = [
                "call_number", "target_number->path_str", "target_number->ans",
                "process_name", "launch_via", "call_function", "function_name", "type",
                "function_name_src->path", "function_name_src->line_number",
                "target_name_src->path", "target_name_src->line_number",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "call_number": "NA",
                        "target_number->path_str": "main->api",
                        "target_number->ans": "10, 20",
                        "process_name": "process",
                        "launch_via": "FORK",
                        "call_function": "main",
                        "function_name": "api",
                        "type": "ENQ",
                    }
                )

            restored = collector.rehydrate_interactions(csv_path, {"api": [1, 2]})

            self.assertEqual(restored, 2)
            self.assertEqual(len(collector.resources), 2)
            self.assertEqual(
                {item["argument_binding"]["value"] for item in collector.interactions.values()},
                {"10", "20"},
            )
            self.assertTrue(
                all(item["function_id"] == collector._function_id(main) for item in collector.interactions.values())
            )

    def test_exports_nonstandard_entry_function(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "process"
            root.mkdir()
            source_path = root / "entry.c"
            source_path.write_text(
                "int pmf_main_H(void) { return 0; }\n", encoding="latin-1"
            )
            entry = FunctionNode(
                "pmf_main_H", "entry.c", str(source_path), start_line=1, end_line=1
            )
            collector = VisualizerCollector(
                process_name="process",
                process_root=root,
                project_structure={"entry.c": str(source_path)},
                file_functions={
                    "entry.c": {"pmf_main_H": {"start_line": 1, "end_line": 1}}
                },
                main_file_name="entry.c",
                entry_function_name="pmf_main_H",
                results_root=Path(temp_dir) / "results",
            )
            collector.capture_call_graph(graph={}, registry={entry.unique_id: entry})

            snapshot = json.loads(collector.write().read_text(encoding="utf-8"))

            self.assertEqual(snapshot["process"]["entry_function"], "pmf_main_H")
            self.assertEqual(
                snapshot["process"]["entry_function_id"], collector._function_id(entry)
            )

    def test_exports_all_lifecycle_entry_points(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "process"
            root.mkdir()
            source_path = root / "entry.c"
            source_path.write_text(
                "int pmf_main_H(void) { return 0; }\n"
                "int pmf_end_H(void) { return 0; }\n",
                encoding="latin-1",
            )
            main = FunctionNode(
                "pmf_main_H", "entry.c", str(source_path), start_line=1, end_line=1
            )
            end = FunctionNode(
                "pmf_end_H", "entry.c", str(source_path), start_line=2, end_line=2
            )
            collector = VisualizerCollector(
                process_name="process",
                process_root=root,
                project_structure={"entry.c": str(source_path)},
                file_functions={
                    "entry.c": {
                        "pmf_main_H": {"start_line": 1, "end_line": 1},
                        "pmf_end_H": {"start_line": 2, "end_line": 2},
                    }
                },
                main_file_name="entry.c",
                entry_function_name="pmf_main_H",
                entry_points=[("entry.c", "pmf_main_H"), ("entry.c", "pmf_end_H")],
                results_root=Path(temp_dir) / "results",
            )
            collector.capture_call_graph(
                graph={}, registry={main.unique_id: main, end.unique_id: end}
            )

            snapshot = json.loads(collector.write().read_text(encoding="utf-8"))

            self.assertEqual(
                [(item["function"], item["file"]) for item in snapshot["process"]["entry_points"]],
                [("pmf_main_H", "entry.c"), ("pmf_end_H", "entry.c")],
            )


if __name__ == "__main__":
    unittest.main()
