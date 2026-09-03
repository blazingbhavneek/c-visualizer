import csv
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from discovery_index import (
    EVIDENCE_COLUMNS,
    NormalizedDiscoveryFact,
    build_discovery_payloads,
)
from value_flow.outputs import FACT_COLUMNS, LEGACY_COLUMNS, _legacy_target_value
from value_flow.resolver import ValueFlowResolver
from value_flow.status import (
    EXTERNAL,
    RESOLVED,
    RUNTIME,
    UNRESOLVED,
    classify_records,
)
from value_flow.transfers import Binding, RouteArm, RouteGuide


def _record(value, origin, *, site="site:1", metadata=None):
    return SimpleNamespace(
        seed=SimpleNamespace(site=SimpleNamespace(site_id=site)),
        arg_index=1,
        fact=SimpleNamespace(
            value=value,
            origin_kind=origin,
            metadata=metadata or {},
        ),
    )


class ResolutionStatusTests(unittest.TestCase):
    def test_exact_external_runtime_and_unresolved_are_distinct(self):
        exact = _record("42", "CONST", site="exact")
        external = _record("event", "EXTERNAL_ENTRY", site="external")
        runtime_input = _record("recv(fd, &msg, n, 0)", "RUNTIME_DATA", site="input")
        unresolved = _record("UNRESOLVED", "UNRESOLVED", site="unknown")
        first = _record(
            "100", "CONST_TABLE", site="runtime", metadata={"set_id": "set:table"}
        )
        second = _record(
            "200", "CONST_TABLE", site="runtime", metadata={"set_id": "set:table"}
        )

        statuses = classify_records(
            [exact, external, runtime_input, unresolved, first, second]
        )

        self.assertEqual(statuses[id(exact)].status, RESOLVED)
        self.assertEqual(statuses[id(external)].status, EXTERNAL)
        self.assertEqual(statuses[id(runtime_input)].status, RUNTIME)
        self.assertEqual(statuses[id(unresolved)].status, UNRESOLVED)
        self.assertEqual(statuses[id(first)].status, RUNTIME)
        self.assertEqual(statuses[id(second)].value_set_id, "set:table")

    def test_partial_static_set_stays_unresolved(self):
        known = _record("100", "CONST", site="partial")
        missing = _record("UNRESOLVED", "UNRESOLVED", site="partial")

        statuses = classify_records([known, missing])

        self.assertEqual(statuses[id(known)].status, UNRESOLVED)
        self.assertEqual(statuses[id(missing)].status, UNRESOLVED)

    def test_runtime_genesis_is_runtime_and_complete(self):
        runtime = _record(
            "recv(fd, &message, size, 0)",
            "RUNTIME_DATA",
            site="runtime-input",
            metadata={"trace_complete": True, "termination_reason": "RUNTIME_INPUT"},
        )

        status = classify_records([runtime])[id(runtime)]

        self.assertEqual(status.status, RUNTIME)
        self.assertTrue(runtime.fact.metadata["trace_complete"])

    def test_unknown_expression_is_provenance_not_an_answer(self):
        resolver = object.__new__(ValueFlowResolver)
        resolver.external_unknown = True
        site = SimpleNamespace(file_path="main.c", line=10)
        seed = SimpleNamespace(site=site)
        route = RouteGuide("route:1", "root", (), "site:1", "DIRECT_ROOT")
        arm = RouteArm(
            "route:1",
            "corr:1",
            [Binding(1, "UNKNOWN", "choose(index)")],
            source_by_arg={
                1: {
                    "file": "main.c",
                    "line": 10,
                    "expr": "choose(index)",
                }
            },
        )

        fact = resolver._fact_from_transfer_binding(
            seed=seed,
            route=route,
            arm=arm,
            binding=arm.bindings[0],
            operation="READF",
        )

        self.assertEqual(fact.value, "UNRESOLVED")
        self.assertEqual(fact.source_expr, "choose(index)")
        self.assertEqual(fact.metadata["unresolved_expr"], "choose(index)")

    def test_nonliteral_exact_is_provenance_not_an_answer(self):
        resolver = object.__new__(ValueFlowResolver)
        site = SimpleNamespace(file_path="main.c", line=10)
        seed = SimpleNamespace(site=site)
        route = RouteGuide("route:1", "root", (), "site:1", "DIRECT_ROOT")
        arm = RouteArm(
            "route:1",
            "corr:1",
            [Binding(1, "EXACT", "choose(index)")],
            source_by_arg={1: {"expr": "choose(index)", "origin_kind": "CONST"}},
        )

        fact = resolver._fact_from_transfer_binding(
            seed=seed,
            route=route,
            arm=arm,
            binding=arm.bindings[0],
            operation="READF",
        )

        self.assertEqual(fact.value, "UNRESOLVED")
        self.assertEqual(fact.source_expr, "choose(index)")
        self.assertEqual(fact.metadata["unresolved_expr"], "choose(index)")

    def test_external_binding_overrides_stale_const_origin(self):
        resolver = object.__new__(ValueFlowResolver)
        resolver.functions = {}
        site = SimpleNamespace(file_path="main.c", line=10)
        seed = SimpleNamespace(site=site)
        route = RouteGuide("route:1", "root", (), "site:1", "DIRECT_ROOT")
        arm = RouteArm(
            "route:1",
            "corr:1",
            [Binding(1, "EXTERNAL", "input_value")],
            source_by_arg={1: {"expr": "input_value", "origin_kind": "CONST"}},
        )

        fact = resolver._fact_from_transfer_binding(
            seed=seed,
            route=route,
            arm=arm,
            binding=arm.bindings[0],
            operation="READF",
        )

        self.assertEqual(fact.value, "input_value")
        self.assertEqual(fact.origin_kind, "EXTERNAL_DATA")

    def test_project_local_call_cannot_be_external(self):
        resolver = object.__new__(ValueFlowResolver)
        resolver.functions = {
            "choose": SimpleNamespace(
                function_id="choose",
                ast_node=object(),
                node=SimpleNamespace(
                    name="choose",
                    file_name="table.c",
                    start_line=1,
                ),
            )
        }
        site = SimpleNamespace(file_path="main.c", line=10)
        seed = SimpleNamespace(site=site)
        route = RouteGuide("route:1", "root", (), "site:1", "DIRECT_ROOT")
        arm = RouteArm(
            "route:1",
            "corr:1",
            [Binding(1, "EXTERNAL", "choose(index)")],
            source_by_arg={1: {"expr": "choose(index)", "origin_kind": "CONST"}},
        )

        fact = resolver._fact_from_transfer_binding(
            seed=seed,
            route=route,
            arm=arm,
            binding=arm.bindings[0],
            operation="READF",
        )

        self.assertEqual(fact.value, "UNRESOLVED")
        self.assertEqual(fact.origin_kind, "UNRESOLVED")
        self.assertEqual(fact.source_expr, "choose(index)")

    def test_legacy_unresolved_answer_hides_expression(self):
        self.assertEqual(
            _legacy_target_value(UNRESOLVED, ["choose(index)"]),
            "UNRESOLVED",
        )
        self.assertEqual(_legacy_target_value(EXTERNAL, ["input_value"]), "input_value")
        self.assertEqual(_legacy_target_value(RUNTIME, ["100"]), "100")

    def test_output_columns_are_appended(self):
        self.assertEqual(FACT_COLUMNS[-2:], ["resolution_status", "value_set_id"])
        answer_index = LEGACY_COLUMNS.index("target_number->ans")
        self.assertEqual(
            LEGACY_COLUMNS[answer_index + 1],
            "target_number->status",
        )
        self.assertEqual(
            LEGACY_COLUMNS[-5:],
            [
                "resolution_status",
                "value_source->path",
                "value_source->line_number",
                "value_source->expression",
                "resolution_reason",
            ],
        )
        self.assertEqual(
            EVIDENCE_COLUMNS[-3:],
            ["resolution_status", "source_expr", "value_set_id"],
        )

    def test_discovery_csv_keeps_old_status_and_adds_semantic_status(self):
        fact = NormalizedDiscoveryFact(
            resolver="valueflow",
            target_function="target",
            target_site_file="main.c",
            target_site_line=10,
            arg_index=1,
            target_expression="choose(index)",
            resource="mfs_file",
            value="100",
            operation="READ",
            source_file="table.c",
            source_line=20,
            source_expr="FILE_A",
            origin_kind="CONST_TABLE",
            resolved_by="SYNTAX",
            link_method="TABLE_LOOKUP",
            path_count=1,
            status="UNRESOLVED",
            resolution_status=RUNTIME,
            value_set_id="set:table",
        )

        payloads = build_discovery_payloads(
            process_name="process",
            source_root=Path(".").resolve(),
            process_root=Path(".").resolve(),
            target_sites=[],
            facts=[fact],
            resolver="valueflow",
        )
        row = next(csv.DictReader(StringIO(payloads["discovery_facts.csv"])))

        self.assertEqual(row["status"], "UNRESOLVED")
        self.assertEqual(row["resolution_status"], RUNTIME)
        self.assertEqual(row["source_expr"], "FILE_A")
        self.assertEqual(row["value_set_id"], "set:table")


if __name__ == "__main__":
    unittest.main()
