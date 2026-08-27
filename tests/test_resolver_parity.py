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
from target_spec import load_target_spec


class ResolverParityTests(unittest.TestCase):
    """Run both resolver entry points on one fixture without a live model."""

    REPO = Path(__file__).resolve().parents[1]
    SPEC_PATH = REPO / "target_specs" / "build_index_targets.json"

    def _write_fixture(self, root: Path) -> Path:
        project = root / "parity_project"
        project.mkdir()
        (project / "Makefile").write_text(
            "SRCS = main.c\nINCLUDE = -I.\nLIBS =\n", encoding="utf-8"
        )
        (project / "defs.h").write_text(
            "#define FILE_NO 1234\n"
            "#define QUEUE_NO 5678\n"
            "#define MPF_MFS_READLOCK 1\n",
            encoding="latin-1",
        )
        (project / "main.c").write_text(
            '#include "defs.h"\n'
            "typedef struct FCB FCB;\n"
            "void mpf_mfs_open_H(FCB *, int, int, int, int);\n"
            "void mpf_mfs_getrec(FCB *, int, int);\n"
            "void mpf_mfs_addque(void *, int, void *);\n"
            "void pmf_forkproc_H(const char *);\n"
            "FCB *global_fcb;\n"
            "int main(void) {\n"
            "    mpf_mfs_open_H(global_fcb, FILE_NO, 0, 0, MPF_MFS_READLOCK);\n"
            "    mpf_mfs_getrec(global_fcb, 0, 1);\n"
            "    mpf_mfs_addque(0, QUEUE_NO, 0);\n"
            '    pmf_forkproc_H("child");\n'
            "    return 0;\n"
            "}\n",
            encoding="latin-1",
        )
        return project

    @staticmethod
    def _inventory(index_dir: Path) -> set[tuple[str, int, int, str]]:
        with (index_dir / "discovery_facts.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            return {
                (
                    row["target_site_file"],
                    int(row["target_site_line"]),
                    int(row["arg_index"]),
                    row["target_function"],
                )
                for row in csv.DictReader(handle)
            }

    def _run(self, project: Path, results: Path, resolver: str) -> Path:
        spec = load_target_spec(self.SPEC_PATH)
        state = State()
        state.reset()
        state.set("FUNCTION_TYPES", spec["targets"])
        state.set("TARGET_SPEC", spec)
        state.set("FUNCTION_POINTER_ARGS", {})
        state.set("FUNCTION_MAP", {})
        state.set("TIME", f"parity-{resolver}")
        state.set("PROJECT_NAME", project.name)

        async def mocked_legacy_trace(**_kwargs):
            # Keep the legacy branch deterministic and offline.  trace_variable
            # still runs its legacy adapter and writes the same index contract;
            # only the model-backed path enumeration is replaced.
            return []

        try:
            with patch.dict(
                os.environ,
                {
                    "VISUALIZER_RESULTS_ROOT": str(results),
                    "PROJECT_STRUCTURE_CACHE_ROOT": str(results / "cache"),
                    "VISUALIZER_USE_PROJECT_STRUCTURE_PICKLE": "0",
                },
            ), patch(
                "project_aware.make_llm_calls_for_function",
                new=mocked_legacy_trace,
            ):
                trace_variable(
                    project,
                    summary_config=SummaryConfig(enabled=False),
                    resolver=resolver,
                    source_root=project.parent,
                    valueflow_path_cap=100,
                    valueflow_concurrency=1,
                )
        finally:
            state.reset()
        return results / project.name / "index"

    def test_legacy_and_valueflow_share_exact_target_site_inventory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._write_fixture(root)
            legacy_index = self._run(project, root / "legacy-results", "legacy")
            valueflow_index = self._run(project, root / "valueflow-results", "valueflow")

            self.assertEqual(
                self._inventory(legacy_index), self._inventory(valueflow_index)
            )
            legacy_metadata = json.loads(
                (legacy_index / "index_metadata.json").read_text()
            )
            valueflow_metadata = json.loads(
                (valueflow_index / "index_metadata.json").read_text()
            )
            self.assertEqual(
                legacy_metadata["counts"]["target_sites"],
                valueflow_metadata["counts"]["target_sites"],
            )
            self.assertEqual(legacy_metadata["target_registry"], valueflow_metadata["target_registry"])

            # The resolver answers are allowed to differ: legacy is mocked to
            # return no LLM answer, while value-flow can resolve syntax-only
            # literals/macros.  The parity guarantee is the shared inventory.
            self.assertEqual(legacy_metadata["resolver"], "legacy")
            self.assertEqual(valueflow_metadata["resolver"], "valueflow")


if __name__ == "__main__":
    unittest.main()
