import csv
import json
import tempfile
import unittest
from pathlib import Path

from aggregate_index import merge_cvisualizer_discoveries


class AggregateIndexTests(unittest.TestCase):
    def test_merges_process_discoveries_and_rebuilds_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            structural = root / "index"
            structural.mkdir()
            (structural / "mfs_fno_macros.json").write_text(
                '{"1234":["FILE_A"],"5678":["QUEUE_A"]}', encoding="utf-8"
            )
            (structural / "makefile_types.json").write_text(
                '{"t-demo/src/proc":{"type":"PROGRAM","artifact":"proc"}}',
                encoding="utf-8",
            )
            (structural / "mfs_file_defs.json").write_text(
                '{"1234":{"name":"FILE_A","pkg":"t-demo"}}', encoding="utf-8"
            )
            (structural / "func_defs.json").write_text(
                '{"t-demo/src/proc/main.c":["main"]}', encoding="utf-8"
            )
            for filename, payload in {
                "func_call_reverse.json": {},
                "include_reverse.json": {},
                "struct_defs.json": {},
                "struct_composition.json": {},
                "type_usage_reverse.json": {},
                "program_descs.json": {},
            }.items():
                (structural / filename).write_text(json.dumps(payload), encoding="utf-8")

            first = root / "proc-a" / "index"
            second = root / "proc-b" / "index"
            for index_dir, process_name in ((first, "proc-a"), (second, "proc-b")):
                index_dir.mkdir(parents=True)
                (index_dir / "index_metadata.json").write_text(
                    json.dumps({
                        "resolver": "valueflow",
                        "target_registry": {"digest": "abc"},
                    }),
                    encoding="utf-8",
                )
                (index_dir / "discovery_facts.csv").write_text(
                    "target_function,target_site_file,target_site_line,arg_index,target_expression,resolved_value,origin_kind,resolved_by,link_method,operation,source_file,source_line,path_count,resolver,status\n"
                    f"fn,t-demo/src/{process_name}/main.c,10,1,x,1234,AST,VALUEFLOW,,READ,,0,1,valueflow,EXACT\n",
                    encoding="utf-8",
                )
            (first / "mfs_file_access.json").write_text(
                '{"1234":[{"file":"t-demo/src/proc-a/main.c","line":10,"lock":"READ","fno_raw":"FILE_A"}]}',
                encoding="utf-8",
            )
            (second / "mfs_file_access.json").write_text(
                '{"1234":[{"file":"t-demo/src/proc-b/main.c","line":11,"lock":"WRITE","fno_raw":"FILE_A"}]}',
                encoding="utf-8",
            )
            for index_dir in (first, second):
                (index_dir / "mfs_queue_access.json").write_text("{}", encoding="utf-8")
                (index_dir / "mfs_dynamic_addque.json").write_text("{}", encoding="utf-8")
                (index_dir / "forkproc_callers.json").write_text("{}", encoding="utf-8")
                (index_dir / "forkproc_targets_by_caller.json").write_text("{}", encoding="utf-8")

            result = merge_cvisualizer_discoveries(
                structural,
                [first, second],
                source_root=root,
                process_count=2,
            )

            self.assertEqual(result, structural.resolve())
            self.assertEqual(
                json.loads((structural / "mfs_file_access.json").read_text()),
                {
                    "1234": [
                        {"file": "t-demo/src/proc-a/main.c", "line": 10, "lock": "READ", "fno_raw": "FILE_A"},
                        {"file": "t-demo/src/proc-b/main.c", "line": 11, "lock": "WRITE", "fno_raw": "FILE_A"},
                    ]
                },
            )
            metadata = json.loads((structural / "index_metadata.json").read_text())
            self.assertEqual(metadata["source_scope"], "whole-repository")
            self.assertEqual(metadata["counts"]["processes_included"], 2)
            with (structural / "discovery_facts.csv").open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)
            graph = json.loads((structural / "graph.json").read_text())
            self.assertIn("nodes", graph)
            self.assertIn("edges", graph)


if __name__ == "__main__":
    unittest.main()
