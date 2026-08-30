"""Phase 3 cross-process ownership tests: evidence, not double counts."""

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from aggregate_index import (
    _load_process_manifest,
    _owner_for_path,
    _owner_resolution_statuses,
    classify_cross_process_rows,
)
from discovery_index import (
    EVIDENCE_COLUMNS,
    NormalizedDiscoveryFact,
    build_discovery_payloads,
    build_target_site_inventory,
    classify_reachability,
    rel_to_source_root,
    valueflow_records_to_facts,
)


def _fact(
    *,
    target_function="mpf_mfs_open_H",
    file="t-a/src/procA/a.c",
    line=10,
    arg_index=2,
    value="1234",
    status="EXACT",
    in_process=True,
    reachability="DIRECT_ROOT",
    operation="OPEN",
):
    return NormalizedDiscoveryFact(
        resolver="valueflow",
        target_function=target_function,
        target_site_file=file,
        target_site_line=line,
        arg_index=arg_index,
        target_expression="fno",
        resource="mfs_file",
        value=value,
        operation=operation,
        source_file="t-a/src/procA/open.c",
        source_line=20,
        source_expr="FNO_A",
        origin_kind="MACRO",
        resolved_by="SYNTAX",
        link_method="VARTRACE",
        path_count=1,
        status=status,
        in_process=in_process,
        reachability=reachability,
    )


class CrossProcessClassificationTests(unittest.TestCase):
    def test_classify_rows_uses_manifest_and_owner_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            proc_a = root / "t-a" / "src" / "procA"
            proc_b = root / "t-a" / "src" / "procB"
            lib = root / "t-a" / "src" / "libshared"
            orphan_lib = root / "t-elsewhere" / "libnowhere"
            for path in (proc_a, proc_b, lib, orphan_lib):
                path.mkdir(parents=True)

            manifest = [
                {
                    "process_name": "procA",
                    "process_root": str(proc_a),
                    "source_root": str(root),
                    "is_library": False,
                    "is_executable": True,
                },
                {
                    "process_name": "procB",
                    "process_root": str(proc_b),
                    "source_root": str(root),
                    "is_library": False,
                    "is_executable": True,
                },
                {
                    "process_name": "libshared",
                    "process_root": str(lib),
                    "source_root": str(root),
                    "is_library": True,
                    "is_executable": False,
                },
            ]
            # libshared (the owning library) resolved one site exactly and
            # has unresolved evidence for the other.
            owner_statuses = {
                "libshared": {
                    (str(lib / "b.c"), 55, 2): "resolved",
                    (str(lib / "c.c"), 60, 2): "present",
                }
            }
            evidence = []

            def make_row(file, line, reachability):
                row = {column: "" for column in EVIDENCE_COLUMNS}
                row["target_site_file"] = str(file)
                row["target_site_line"] = str(line)
                row["target_function"] = "mpf_mfs_open_H"
                row["arg_index"] = "2"
                row["evidence_process"] = "procA"
                row["reachability"] = reachability
                row["status"] = "UNREACHABLE"
                return row

            evidence = [
                make_row("t-a/src/libshared/b.c", 55, "OUT_OF_PROCESS_SCOPE"),
                make_row("t-a/src/libshared/c.c", 60, "OUT_OF_PROCESS_SCOPE"),
                make_row("t-elsewhere/libnowhere/o.c", 1, "OUT_OF_PROCESS_SCOPE"),
                make_row("t-a/src/procA/own.c", 9, "UNREACHABLE_IN_PROCESS"),
            ]

            evidence, cross_rows, counts = classify_cross_process_rows(
                evidence, manifest, owner_statuses, root
            )

        # Owner with a root-proven exact result: globally proven live.
        self.assertEqual(evidence[0]["reachability"], "CROSS_PROCESS_CALLER")
        self.assertEqual(evidence[0]["owner_process"], "libshared")
        self.assertEqual(evidence[0]["owner_kind"], "library")
        # Owner present but unresolved: still not globally resolved.
        self.assertEqual(evidence[1]["reachability"], "CROSS_PROCESS_CALLER")
        # No owner process: evidence only.
        self.assertEqual(evidence[2]["reachability"], "OUT_OF_PROCESS_SCOPE")
        self.assertEqual(evidence[2]["owner_process"], "")
        # In-process row untouched.
        self.assertEqual(evidence[3]["reachability"], "UNREACHABLE_IN_PROCESS")

        self.assertEqual(counts["cross_process_caller_rows"], 2)
        self.assertEqual(counts["out_of_process_scope_rows"], 1)
        self.assertEqual(len(cross_rows), 2)
        by_site = {row["target_site_line"]: row for row in cross_rows}
        self.assertEqual(by_site["55"]["owner_resolution_status"], "resolved")
        self.assertEqual(by_site["60"]["owner_resolution_status"], "present")
        self.assertEqual(by_site["55"]["observed_from_process"], "procA")

    def test_manifest_owner_is_longest_prefix_not_basename(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outer = root / "t-a" / "src" / "procOuter"
            inner = root / "t-a" / "src" / "procOuter" / "nested" / "procInner"
            for path in (outer, inner):
                path.mkdir(parents=True)
            manifest = [
                {
                    "process_name": "procOuter",
                    "process_root": str(outer),
                    "source_root": str(root),
                    "is_library": False,
                    "is_executable": True,
                },
                {
                    "process_name": "procInner",
                    "process_root": str(inner),
                    "source_root": str(root),
                    "is_library": False,
                    "is_executable": True,
                },
            ]
            owner = _owner_for_path(inner / "main.c", manifest)
        self.assertEqual(owner["process_name"], "procInner")

    def test_owner_statuses_from_owner_evidence_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index_a = root / "csv_results" / "procA" / "index"
            index_b = root / "csv_results" / "procB" / "index"
            lib = root / "t-a" / "src" / "libx"
            for path in (root / "t-a" / "src" / "procA",
                         root / "t-a" / "src" / "procB",
                         lib):
                path.mkdir(parents=True)
            index_a.mkdir(parents=True)
            index_b.mkdir(parents=True)

            def write_index(index_dir, name, site_file, status, reachability):
                (index_dir / "index_metadata.json").write_text(
                    json.dumps(
                        {
                            "process_name": name,
                            "process_root": str(root / "t-a" / "src" / name),
                            "source_root": str(root),
                            "root_diagnostics": {
                                "root_state": "OK",
                                "accepted_entry_points": ["main"],
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                row = {column: "" for column in EVIDENCE_COLUMNS}
                row["target_site_file"] = site_file
                row["target_site_line"] = "55"
                row["arg_index"] = "2"
                row["status"] = status
                row["reachability"] = reachability
                row["evidence_process"] = name
                stream = io.StringIO()
                writer = csv.DictWriter(
                    stream, fieldnames=EVIDENCE_COLUMNS, lineterminator="\n"
                )
                writer.writeheader()
                writer.writerow(row)
                (index_dir / "discovery_facts.csv").write_text(
                    stream.getvalue(), encoding="utf-8"
                )

            # procB observed a libx site and resolved it exactly from a root.
            write_index(
                index_b,
                "procB",
                "t-a/src/libx/site.c",
                "EXACT",
                "DIRECT_ROOT",
            )
            # Old file without a reachability column is tolerated.
            old_row = {column: "" for column in EVIDENCE_COLUMNS}
            old_row["target_site_file"] = "t-a/src/libx/old.c"
            old_row["target_site_line"] = "7"
            old_row["arg_index"] = "2"
            old_row["status"] = "UNREACHABLE"
            old_row["evidence_process"] = "procA"
            stream = io.StringIO()
            writer = csv.DictWriter(
                stream, fieldnames=EVIDENCE_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerow(old_row)
            (index_a / "discovery_facts.csv").write_text(
                stream.getvalue(), encoding="utf-8"
            )
            (index_a / "index_metadata.json").write_text(
                json.dumps(
                    {
                        "process_name": "procA",
                        "process_root": str(root / "t-a" / "src" / "procA"),
                        "source_root": str(root),
                        "root_diagnostics": {
                            "root_state": "OK",
                            "accepted_entry_points": ["main"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            manifest = _load_process_manifest([index_a, index_b])
            statuses = _owner_resolution_statuses([index_a, index_b], manifest)

        lib_owner = next(
            entry for entry in manifest
            if entry["process_name"] == "procB"
        )
        self.assertTrue(lib_owner["is_executable"])
        self.assertIn(
            (str((lib / "site.c").resolve()), 55, 2), statuses["procB"]
        )
        self.assertEqual(statuses["procB"][(str((lib / "site.c").resolve()), 55, 2)], "resolved")


class ExactPromotionGateTests(unittest.TestCase):
    def test_cross_process_rows_never_promote_and_orphan_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_root = root / "t-a" / "src" / "procA"
            process_root.mkdir(parents=True)
            (process_root / "main.c").write_text(
                "int main(void)\n{\n    mpf_mfs_open_H(&h, 1234, 0, 0, 0);\n    return 0;\n}\n",
                encoding="latin-1",
            )

            in_process = _fact(
                file="t-a/src/procA/main.c",
                line=3,
                reachability="DIRECT_ROOT",
            )
            cross = _fact(
                file="t-a/src/libshared/other.c",
                line=55,
                value="4321",
                in_process=False,
                reachability="OUT_OF_PROCESS_SCOPE",
            )
            orphan = _fact(
                file="t-a/src/procA/orphan.c",
                line=77,
                value="1111",
                status="EXACT",
                reachability="UNREACHABLE_IN_PROCESS",
            )
            facts = [in_process, cross, orphan]

            payloads = build_discovery_payloads(
                process_name="procA",
                source_root=root,
                process_root=process_root,
                target_sites=[],
                facts=facts,
                resolver="valueflow",
            )

            file_access = json.loads(payloads["mfs_file_access.json"])
            metadata = json.loads(payloads["index_metadata.json"])
            csv_text = payloads["discovery_facts.csv"]

        # Only the root-proven in-process row promotes.
        self.assertEqual(set(file_access), {"1234"})
        self.assertNotIn("4321", {fno for fno in file_access})
        self.assertNotIn("1111", {fno for fno in file_access})
        reach_counts = metadata["counts"]["reachability"]
        self.assertEqual(reach_counts["OUT_OF_PROCESS_SCOPE"], 1)
        self.assertEqual(reach_counts["UNREACHABLE_IN_PROCESS"], 1)
        self.assertEqual(reach_counts["DIRECT_ROOT"], 1)
        self.assertIn("reachability", csv_text)
        self.assertIn("evidence_process", csv_text)
        self.assertIn("owner_process", csv_text)


class ReachabilityContractTests(unittest.TestCase):
    def test_missing_resolver_state_is_unknown_not_dead_code(self):
        self.assertEqual(
            classify_reachability(None, in_process=True, caller_id="[a]f"),
            "UNKNOWN",
        )

    def test_root_parse_failure_is_explicit(self):
        state = {
            "root_state": "ROOT_PARSE_FAILURE",
            "direct_reachable": set(),
            "reachable": set(),
        }
        self.assertEqual(
            classify_reachability(state, in_process=True, caller_id="[a]f"),
            "ROOT_PARSE_FAILURE",
        )

    def test_callback_only_functions_classify_as_callback(self):
        state = {
            "root_state": "OK",
            "direct_reachable": {"[a]main"},
            "reachable": {"[a]main", "[a]handler"},
        }
        self.assertEqual(
            classify_reachability(state, in_process=True, caller_id="[a]handler"),
            "CALLBACK",
        )
        self.assertEqual(
            classify_reachability(state, in_process=True, caller_id="[a]main"),
            "DIRECT_ROOT",
        )
        self.assertEqual(
            classify_reachability(state, in_process=False, caller_id="[a]main"),
            "OUT_OF_PROCESS_SCOPE",
        )


if __name__ == "__main__":
    unittest.main()
