import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from function_summaries import SummaryConfig
from project_aware import trace_variable
from state.state import State


class NoTargetPipelineTests(unittest.TestCase):
    def test_project_without_tracked_apis_still_writes_complete_graph(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            project = temp / "plain_project"
            project.mkdir()
            (project / "Makefile").write_text(
                "SRCS = main.c helpers.c\nINCLUDE =\nLIBS =\n", encoding="utf-8"
            )
            (project / "main.c").write_text(
                '#include "inline_helper.h"\n'
                "int helper(void);\n"
                "int main(void) { return helper() + inline_helper(); }\n",
                encoding="latin-1",
            )
            (project / "inline_helper.h").write_text(
                "static inline int inline_helper(void) { return 2; }\n",
                encoding="latin-1",
            )
            (project / "helpers.c").write_text(
                "int helper(void) { return 3; }\n"
                "static int never_called(void) { return 4; }\n",
                encoding="latin-1",
            )

            state = State()
            state.reset()
            state.set("FUNCTION_TYPES", {})
            state.set("FUNCTION_POINTER_ARGS", {})
            state.set("FUNCTION_MAP", {})
            state.set("TIME", "integration-run")
            state.set("PROJECT_NAME", project.name)
            results_root = temp / "results"
            cache_root = temp / "cache"
            with patch.dict(
                os.environ,
                {
                    "VISUALIZER_RESULTS_ROOT": str(results_root),
                    "PROJECT_STRUCTURE_CACHE_ROOT": str(cache_root),
                },
            ):
                answers = trace_variable(
                    project,
                    summary_config=SummaryConfig(enabled=False),
                )
            state.reset()

            self.assertEqual(answers, {})
            graph_path = (
                results_root
                / "visualizer"
                / project.name
                / "runs"
                / "integration-run"
                / "graph.json"
            )
            snapshot = json.loads(graph_path.read_text(encoding="utf-8"))
            names = {item["name"] for item in snapshot["functions"] if not item["is_external"]}
            self.assertEqual(names, {"main", "helper", "never_called", "inline_helper"})
            by_name = {item["name"]: item for item in snapshot["functions"]}
            self.assertFalse(by_name["helper"]["is_static"])
            self.assertTrue(by_name["never_called"]["is_static"])
            self.assertEqual(len(snapshot["calls"]), 2)
            self.assertEqual(len(snapshot["source_files"]), 4)
            self.assertIsNotNone(snapshot["process"]["entry_function_id"])


if __name__ == "__main__":
    unittest.main()
