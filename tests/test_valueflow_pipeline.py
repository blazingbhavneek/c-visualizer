import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from function_summaries import SummaryConfig
from project_aware import trace_variable
from state.state import State


class ValueFlowPipelineTests(unittest.TestCase):
    def test_valueflow_writes_all_three_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            project = temp / "valueflow_project"
            project.mkdir()
            (project / "Makefile").write_text(
                "SRCS = main.c\nINCLUDE =\nLIBS =\n", encoding="utf-8"
            )
            (project / "main.c").write_text(
                "int traced_api(int value);\n"
                "int main(void) { traced_api(17); return 0; }\n",
                encoding="latin-1",
            )
            state = State()
            state.reset()
            state.set(
                "FUNCTION_TYPES",
                {
                    "traced_api": {
                        "type": "READF",
                        "launch": "FORK",
                        "indices": [1],
                        "get_upper": True,
                        "dependent_functions": [],
                    }
                },
            )
            state.set("FUNCTION_POINTER_ARGS", {})
            state.set("FUNCTION_MAP", {})
            state.set("TIME", "valueflow-run")
            state.set("PROJECT_NAME", project.name)
            results = temp / "results"
            cache = temp / "project-cache"
            with patch.dict(
                os.environ,
                {
                    "VISUALIZER_RESULTS_ROOT": str(results),
                    "PROJECT_STRUCTURE_CACHE_ROOT": str(cache),
                },
            ):
                answers = trace_variable(
                    project,
                    summary_config=SummaryConfig(enabled=False),
                    resolver="valueflow",
                )
            state.reset()

            self.assertIn("traced_api", answers)
            process_dir = results / project.name
            facts_path = process_dir / "facts.csv"
            paths_path = process_dir / "paths.csv"
            # The legacy feed deliberately stays at the old top-level path.
            legacy_path = results / f"{project.name}.csv"
            self.assertTrue(facts_path.is_file())
            self.assertTrue(paths_path.is_file())
            self.assertTrue(legacy_path.is_file())
            with facts_path.open(encoding="utf-8-sig", newline="") as handle:
                facts = list(csv.DictReader(handle))
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0]["value"], "17")
            self.assertEqual(facts[0]["origin_kind"], "CONST")
            self.assertEqual(facts[0]["resolved_by"], "SYNTAX")
            stats = json.loads((process_dir / "run_stats.json").read_text())
            self.assertEqual(stats["llm_query_count"], 0)
            self.assertTrue((process_dir / "summary.md").is_file())
            self.assertTrue(
                (process_dir / "targets" / "traced_api" / "unique_paths.xlsx").is_file()
            )
            snapshot = json.loads(
                (
                    results
                    / "visualizer"
                    / project.name
                    / "runs"
                    / "valueflow-run"
                    / "graph.json"
                ).read_text()
            )
            self.assertEqual(len(snapshot["interactions"]), 1)


if __name__ == "__main__":
    unittest.main()
