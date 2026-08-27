import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.compare_discovery import compare_indexes


class CompareDiscoveryTests(unittest.TestCase):
    def test_normalizes_paths_filters_process_and_reports_value_disagreement(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = root / "results" / "proj" / "index"
            reference = root / "index_chukyu_no_llm"
            candidate.mkdir(parents=True)
            reference.mkdir()

            (candidate / "index_metadata.json").write_text(
                json.dumps(
                    {
                        "process_name": "proj",
                        "process_root": str(root / "proj"),
                        "source_root": str(root),
                        "resolver": "valueflow",
                        "counts": {"target_sites": 4},
                    }
                ),
                encoding="utf-8",
            )
            (candidate / "discovery_facts.csv").write_text(
                "target_function,target_site_file,target_site_line,arg_index,status,resolved_by\n"
                "mpf_mfs_open_H,proj/main.c,10,2,EXACT,SYNTAX\n"
                "mpf_mfs_addque,proj/main.c,11,2,DYNAMIC,SYNTAX\n",
                encoding="utf-8",
            )
            (candidate / "mfs_file_access.json").write_text(
                json.dumps(
                    {
                        "1234": [
                            {"file": "proj/main.c", "line": 10, "lock": "READ", "fno_raw": "FNO"}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (candidate / "mfs_queue_access.json").write_text(
                json.dumps(
                    {
                        "5678": [
                            {"file": "proj/main.c", "line": 12, "lock": "ADDQUE", "fno_raw": "QNO"}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (candidate / "forkproc_targets_by_caller.json").write_text(
                json.dumps({"proj/main.c": [{"line": 13, "target": "child"}]}),
                encoding="utf-8",
            )
            (candidate / "mfs_dynamic_addque.json").write_text(
                json.dumps({"proj/main.c": [{"line": 11, "expr": "q.field", "lock": "ADDQUE"}]}),
                encoding="utf-8",
            )

            (reference / "mfs_file_access.json").write_text(
                json.dumps(
                    {
                        "1234": [
                            {"file": "proj/main.c", "line": 10, "lock": "READ", "fno_raw": "OTHER_FNO"}
                        ],
                        "9999": [
                            {"file": "other/main.c", "line": 1, "lock": "READ", "fno_raw": "OTHER"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (reference / "mfs_queue_access.json").write_text("{}", encoding="utf-8")
            (reference / "forkproc_targets_by_caller.json").write_text(
                json.dumps(
                    {
                        "proj/main.c": [{"line": 13, "target": "child"}],
                        "other/main.c": [{"line": 2, "target": "other"}],
                    }
                ),
                encoding="utf-8",
            )
            (reference / "mfs_dynamic_addque.json").write_text("{}", encoding="utf-8")

            report = compare_indexes(candidate, reference, source_root=root)

            self.assertEqual(report["reference"]["process_prefix"], "proj")
            self.assertEqual(len(report["exact"]["shared_exact"]), 2)
            self.assertEqual(len(report["exact"]["value_disagreements"]), 0)
            self.assertEqual(report["exact"]["reference_only"], [])
            self.assertEqual(len(report["exact"]["cvisualizer_only"]), 1)
            self.assertEqual(len(report["dynamic"]["cvisualizer_only"]), 1)
            self.assertEqual(report["cvisualizer"]["evidence_statuses"], {"DYNAMIC": 1, "EXACT": 1})

    def test_value_disagreement_is_reported_by_site(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = root / "candidate"
            reference = root / "reference"
            candidate.mkdir()
            reference.mkdir()
            for directory, value in ((candidate, "1234"), (reference, "4321")):
                (directory / "mfs_file_access.json").write_text(
                    json.dumps(
                        {
                            value: [
                                {"file": "main.c", "line": 4, "lock": "READ", "fno_raw": value}
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                (directory / "mfs_queue_access.json").write_text("{}", encoding="utf-8")
                (directory / "forkproc_targets_by_caller.json").write_text("{}", encoding="utf-8")
                (directory / "mfs_dynamic_addque.json").write_text("{}", encoding="utf-8")

            report = compare_indexes(candidate, reference, all_reference=True)
            disagreement = report["exact"]["value_disagreements"][0]
            self.assertEqual(disagreement["file"], "main.c")
            self.assertEqual(disagreement["reference_values"], ["4321"])
            self.assertEqual(disagreement["cvisualizer_values"], ["1234"])


if __name__ == "__main__":
    unittest.main()
