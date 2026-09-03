"""No-model regression tests for the route-guided transfer engine."""

from __future__ import annotations

import asyncio
import csv
import tempfile
import unittest
from pathlib import Path

from call_graph.call_graph import CallGraphBuilder
from helpers.Preprocess.preprocess import Preprocess
from helpers.extract_functions_from_c import get_local_function_definitions
from models import TransferAnswerModel
from pydantic import ValidationError
from value_flow.outputs import write_outputs
from value_flow.resolver import ValueFlowResolver
from value_flow.status import RUNTIME, UNRESOLVED, classify_records
from value_flow.transfers import (
    FormulaError,
    evaluate_formula,
    make_transfer_cache_key,
    substitute_placeholders,
    validate_formula,
)


def build_resolver(
    root: Path,
    source: str,
    configs: dict,
    transfer,
    *,
    cache_path: Path | None = None,
    entry_points: list[tuple[str, str]] | None = None,
    function_pointer_args: dict | None = None,
) -> ValueFlowResolver:
    path = root / "main.c"
    path.write_text(source, encoding="latin-1")
    project = {"main.c": path}
    trees = Preprocess().preprocess(project_structure=project)
    file_functions = {
        name: get_local_function_definitions(code_bytes=source_bytes)
        for name, (_, source_bytes) in trees.items()
    }
    builder = CallGraphBuilder(
        project_structure=project,
        trees=trees,
        function_pointer_args=function_pointer_args or {},
        file_functions=file_functions,
    )
    return ValueFlowResolver(
        graph=builder.build(),
        registry=builder.node_registry,
        trees=trees,
        project_structure={"main.c": str(path)},
        main_file_name="main.c",
        entry_points=entry_points or [("main.c", "main")],
        function_configs=configs,
        macros=builder.macros,
        file_macros={},
        transfer_resolver=transfer,
        cache_path=cache_path,
    )


def answer_for(request, bindings, *, guard="true", evidence_file="main.c"):
    # Evidence is a verbatim snippet; the resolver locates it itself.
    first_line = request.function_source.lstrip("\n").splitlines()[0].strip()
    return TransferAnswerModel(
        arms=[
            {
                "bindings": bindings,
                "guard": guard,
                "evidence": [
                    {
                        "file": evidence_file,
                        "snippet": first_line,
                    }
                ],
            }
        ]
    )


class TransferUtilityTests(unittest.TestCase):
    def test_placeholder_substitution_is_simultaneous(self):
        self.assertEqual(
            substitute_placeholders("$1 + $10", {1: "one", 10: "ten"}),
            "(one) + (ten)",
        )
        self.assertEqual(
            substitute_placeholders('"$1" + $1', {1: "value"}),
            '"$1" + (value)',
        )

    def test_formula_validation_and_evaluation(self):
        self.assertEqual(
            evaluate_formula("($1 + 1) << 2", {1: 10}),
            (True, 44),
        )
        self.assertEqual(evaluate_formula("1 + (2 * 3)"), (True, 7))
        self.assertEqual(evaluate_formula('"$1"'), (True, "$1"))
        validate_formula(
            "$1 + 1",
            parameter_count=1,
            evidence_texts=("value = p + 1;",),
        )
        with self.assertRaises(FormulaError):
            validate_formula("$3 + 1", parameter_count=2, evidence_texts=("3",))
        with self.assertRaises(FormulaError):
            validate_formula("999", parameter_count=1, evidence_texts=("4013",))
        with self.assertRaises(FormulaError):
            validate_formula(
                "unknown_local",
                parameter_count=1,
                evidence_texts=("unknown_local",),
            )

    def test_transfer_models_forbid_loose_fields_and_empty_answers(self):
        with self.assertRaises(ValidationError):
            TransferAnswerModel.model_validate({"arms": [], "value": "999"})

    def test_cache_key_excludes_route_prefix(self):
        common = dict(
            prompt_version="v1",
            model_id="model",
            function_id="[main.c]Y",
            function_source="void Y(int p) { X(p + 1); }",
            selected_site_id="main.c:20",
            selected_site_source="X(p + 1)",
            bindings=(),
            guards=(),
            macro_digest="macro",
        )
        self.assertEqual(make_transfer_cache_key(**common), make_transfer_cache_key(**common))


class RouteTransferTests(unittest.TestCase):
    def test_source_backed_output_producer_is_runtime_and_shared_in_flight(self):
        source = (
            "typedef int Handle;\n"
            "void fill_file_no(int *out);\n"
            "void open_h(Handle *handle, int file_no);\n"
            "void write_h(Handle *handle);\n"
            "int main(void) {\n"
            "  int file_no; Handle handle;\n"
            "  fill_file_no(&file_no);\n"
            "  open_h(&handle, file_no);\n"
            "  write_h(&handle);\n"
            "  return 0;\n"
            "}\n"
        )
        calls = []

        async def transfer(_request):
            calls.append(1)
            await asyncio.sleep(0.01)
            return {
                "arms": [
                    {
                        "bindings": [
                            {
                                "target_arg": 2,
                                "kind": "UNKNOWN",
                                "expression": "fill_file_no(&file_no)",
                            }
                        ],
                        "guard": "true",
                        "evidence": [
                            {
                                "file": "main.c",
                                "snippet": "fill_file_no(&file_no);",
                            }
                        ],
                    }
                ]
            }

        configs = {
            "open_h": {
                "type": "OPENF",
                "indices": [2],
                "handle_index": 1,
                "dependent_functions": [],
            },
            "write_h": {
                "type": "WRITEF",
                "indices": [],
                "handle_index": 1,
                "dependent_functions": ["open_h"],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory), source, configs, transfer
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(calls, [1])
        self.assertEqual(resolver.transfer_request_count, 1)
        self.assertEqual(resolver.transfer_cache_hits, 1)
        self.assertEqual(len(records), 2)
        statuses = classify_records(records)
        self.assertEqual(
            {statuses[id(record)].status for record in records}, {RUNTIME}
        )
        for record in records:
            self.assertEqual(record.fact.value, "file_no")
            self.assertEqual(record.fact.origin_kind, "RUNTIME_DATA")
            self.assertEqual(record.fact.source_line, 7)
            self.assertEqual(record.fact.source_expr, "fill_file_no(&file_no)")
            self.assertEqual(
                record.fact.metadata["termination_reason"], "RUNTIME_PRODUCER"
            )

    def test_direct_literal_and_macro_do_not_request_a_transfer(self):
        source = (
            "#define FILE_NO 4013\n"
            "void X(int value);\n"
            "int main(void) { X(17); X(FILE_NO); return 0; }\n"
        )
        calls = []

        async def transfer(request):
            calls.append(request)
            return None

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            # The helper deliberately supplies file macros separately because
            # this unit fixture does not run project-wide State setup.
            resolver.file_macros = {"main.c": {"FILE_NO": "4013"}}
            records = asyncio.run(resolver.run())

        self.assertEqual({record.fact.value for record in records}, {"17", "4013"})
        self.assertEqual(calls, [])
        self.assertEqual(resolver.fast_path_seed_count, 2)

    def test_queue_wrapper_parameter_uses_backward_search_without_route_enumeration(self):
        source = (
            "void Dac_EnqSem(void *cpu, int qno);\n"
            "void dispatch(int qno) { Dac_EnqSem(0, qno); }\n"
            "int main(void) { dispatch(77); return 0; }\n"
        )

        async def transfer_must_not_run(_request):
            raise AssertionError("a bare formal parameter needs no model transfer")

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {
                    "Dac_EnqSem": {
                        "type": "QUEUEF",
                        "launch": "FORK",
                        "indices": [2],
                        "get_upper": True,
                        "dependent_functions": [],
                        "semantic_wrapper": True,
                        "canonical_target": "mpf_mfs_addque",
                    }
                },
                transfer_must_not_run,
            )
            resolver.routes_for_seed = lambda _seed: (_ for _ in ()).throw(
                AssertionError("bounded search must not enumerate routes")
            )
            records = asyncio.run(resolver.run())

        self.assertEqual([record.fact.value for record in records], ["77"])
        self.assertEqual(resolver.search_seed_count, 1)

    def test_composes_nested_arithmetic_and_stops_at_constant_caller(self):
        source = (
            "void X(int value);\n"
            "void Y(int p) { X((p + 1) << 2); }\n"
            "void Z(void) { Y(10); }\n"
            "int main(void) { Z(); return 0; }\n"
        )
        calls = []

        async def transfer(request):
            calls.append(request)
            return answer_for(
                request,
                [{"target_arg": 1, "kind": "EXPRESSION", "expression": "(($1 + 1) << 2)"}],
            )

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            resolver.routes_for_seed = lambda _seed: (_ for _ in ()).throw(
                AssertionError("normal resolution must not enumerate routes")
            )
            records = asyncio.run(resolver.run())

        self.assertEqual([record.fact.value for record in records], ["44"])
        self.assertEqual([request.function_name for request in calls], ["Y"])
        self.assertEqual(records[0].fact.link_method, "LLM_TRANSFER")
        self.assertEqual(records[0].fact.metadata["reachability"], "DIRECT_ROOT")

    def test_ten_callers_share_one_local_transfer(self):
        source = (
            "void X(int value);\n"
            "void Y(int p) { X(p + 1); }\n"
            "int main(void) { Y(0); Y(1); Y(2); Y(3); Y(4); "
            "Y(5); Y(6); Y(7); Y(8); Y(9); return 0; }\n"
        )
        calls = []

        async def transfer(request):
            calls.append(request)
            return answer_for(
                request,
                [{"target_arg": 1, "kind": "EXPRESSION", "expression": "$1 + 1"}],
            )

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(len(records), 10)
        self.assertEqual({record.fact.value for record in records}, {str(i) for i in range(1, 11)})
        self.assertEqual(len(calls), 1)
        self.assertEqual(resolver.transfer_cache_hits, 0)
        self.assertGreaterEqual(resolver.search_state_count, 11)

    def test_search_state_cap_is_visible_and_blocks_resolution(self):
        source = (
            "void X(int value);\n"
            "void Y(int p) { X(p + 1); }\n"
            "int main(void) { Y(4); return 0; }\n"
        )

        async def transfer(request):
            return answer_for(
                request,
                [{"target_arg": 1, "kind": "EXPRESSION", "expression": "$1 + 1"}],
            )

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            resolver.search_state_cap = 1
            resolver.routes_for_seed = lambda _seed: (_ for _ in ()).throw(
                AssertionError("bounded search must not enumerate routes")
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(resolver.search_limit_seed_count, 1)
        self.assertEqual(classify_records(records)[id(records[0])].status, UNRESOLVED)
        self.assertTrue(records[0].fact.metadata["search_truncated"])
        self.assertEqual(
            records[0].fact.metadata["termination_reason"],
            "SEARCH_LIMIT_REACHED",
        )

    def test_search_depth_cap_is_visible_and_blocks_resolution(self):
        source = (
            "void X(int value);\n"
            "void Y(int p) { X(p); }\n"
            "void Z(int q) { Y(q); }\n"
            "int main(void) { Z(4); return 0; }\n"
        )

        async def transfer(request):
            return answer_for(
                request,
                [{"target_arg": 1, "kind": "EXPRESSION", "expression": "$1"}],
            )

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            resolver.search_depth_cap = 1
            records = asyncio.run(resolver.run())

        self.assertEqual(resolver.search_limit_seed_count, 1)
        self.assertEqual(classify_records(records)[id(records[0])].status, UNRESOLVED)
        self.assertEqual(
            records[0].fact.metadata["termination_reason"],
            "SEARCH_LIMIT_REACHED",
        )

    def test_diamond_routes_collapse_to_one_semantic_state(self):
        source = (
            "void X(int value);\n"
            "void leaf(int p) { X(p); }\n"
            "void left(int p) { leaf(p); }\n"
            "void right(int p) { leaf(p); }\n"
            "void join(int p) { left(p); right(p); }\n"
            "int main(void) { join(4); return 0; }\n"
        )

        async def transfer(request):
            return answer_for(
                request,
                [{"target_arg": 1, "kind": "EXPRESSION", "expression": "$1"}],
            )

        observations = []
        for _ in range(3):
            with tempfile.TemporaryDirectory() as directory:
                resolver = build_resolver(
                    Path(directory),
                    source,
                    {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                    transfer,
                )
                resolver.routes_for_seed = lambda _seed: (_ for _ in ()).throw(
                    AssertionError("bounded search must not enumerate routes")
                )
                records = asyncio.run(resolver.run())
                observations.append(
                    (
                        [record.fact.value for record in records],
                        resolver.search_state_count,
                        resolver.search_deduplicated_state_count,
                    )
                )

        self.assertEqual(observations[0], observations[1])
        self.assertEqual(observations[1], observations[2])
        self.assertEqual(observations[0][0], ["4"])
        self.assertGreater(observations[0][2], 0)

    def test_transfer_cache_survives_a_new_resolver(self):
        source = (
            "void X(int value);\n"
            "void Y(int p) { X(p + 1); }\n"
            "int main(void) { Y(4); return 0; }\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "cache.json"
            first_calls = []

            async def first_transfer(request):
                first_calls.append(request)
                return answer_for(
                    request,
                    [{"target_arg": 1, "kind": "EXPRESSION", "expression": "$1 + 1"}],
                )

            first = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                first_transfer,
                cache_path=cache_path,
            )
            self.assertEqual(asyncio.run(first.run())[0].fact.value, "5")
            self.assertEqual(len(first_calls), 1)

            async def cached_transfer(_request):
                raise AssertionError("validated transfer should come from cache")

            second = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                cached_transfer,
                cache_path=cache_path,
            )
            self.assertEqual(asyncio.run(second.run())[0].fact.value, "5")

        self.assertGreaterEqual(second.transfer_cache_hits, 1)

    def test_correlated_arguments_never_form_cross_pairs(self):
        source = (
            "void X(int a, int b);\n"
            "void Y(int a, int b) { X(a, b); }\n"
            "int main(void) { Y(1, 10); Y(2, 20); return 0; }\n"
        )

        async def transfer(request):
            return answer_for(
                request,
                [
                    {"target_arg": 1, "kind": "EXPRESSION", "expression": "$1"},
                    {"target_arg": 2, "kind": "EXPRESSION", "expression": "$2"},
                ],
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resolver = build_resolver(
                root,
                source,
                {"X": {"type": "READF", "indices": [1, 2], "dependent_functions": []}},
                transfer,
            )
            records = asyncio.run(resolver.run())
            output = write_outputs(
                records=records,
                resolver=resolver,
                process_name="process",
                output_root=root / "out",
            )
            with output.legacy.open(encoding="utf-8-sig", newline="") as handle:
                legacy = list(csv.DictReader(handle))

        self.assertEqual(
            {row["target_number->ans"] for row in legacy},
            {"1_10", "2_20"},
        )
        self.assertNotIn("1_20", {row["target_number->ans"] for row in legacy})
        self.assertNotIn("2_10", {row["target_number->ans"] for row in legacy})

    def test_complete_local_branch_set_uses_fast_path_without_transfer(self):
        source = (
            "void X(int value);\n"
            "void Y(int mode) { int value; if (mode) value = 100; "
            "else value = 200; X(value); }\n"
            "int main(void) { Y(1); return 0; }\n"
        )

        calls = []

        async def transfer(request):
            calls.append(request)
            # The evidence must cover the values the formulas cite (100, 200).
            evidence = [{"file": "main.c", "snippet": "if (mode) value = 100; else value = 200; X(value);"}]
            return {
                "arms": [
                    {
                        "bindings": [{"target_arg": 1, "kind": "EXPRESSION", "expression": "100"}],
                        "guard": "$1 != 0",
                        "evidence": evidence,
                    },
                    {
                        "bindings": [{"target_arg": 1, "kind": "EXPRESSION", "expression": "200"}],
                        "guard": "$1 == 0",
                        "evidence": evidence,
                    },
                ]
            }

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual({record.fact.value for record in records}, {"100", "200"})
        self.assertEqual(calls, [])
        self.assertEqual(resolver.fast_path_seed_count, 1)
        self.assertTrue(all(record.fact.metadata["guards"] for record in records))
        statuses = classify_records(records)
        self.assertEqual({statuses[id(record)].status for record in records}, {"RUNTIME"})
        self.assertEqual(
            len({statuses[id(record)].value_set_id for record in records}),
            1,
        )

    def test_consumer_branch_filters_owning_open_arms(self):
        source = (
            "typedef int Handle;\n"
            "void open_h(Handle *, int);\n"
            "void read_h(Handle *);\n"
            "void worker(int mode) {\n"
            "  Handle h; int fno;\n"
            "  if (mode) fno = 100; else fno = 200;\n"
            "  open_h(&h, fno);\n"
            "  if (mode) read_h(&h); else read_h(&h);\n"
            "}\n"
            "int main(void) { return 0; }\n"
        )

        async def transfer(_request):
            evidence = [
                {
                    "file": "main.c",
                    "snippet": "if (mode) fno = 100; else fno = 200;",
                }
            ]
            return {
                "arms": [
                    {
                        "bindings": [
                            {"target_arg": 2, "kind": "EXPRESSION", "expression": "100"}
                        ],
                        "guard": "$1 != 0",
                        "evidence": evidence,
                    },
                    {
                        "bindings": [
                            {"target_arg": 2, "kind": "EXPRESSION", "expression": "200"}
                        ],
                        "guard": "$1 == 0",
                        "evidence": evidence,
                    },
                ]
            }

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {
                    "open_h": {
                        "type": "OPENF",
                        "indices": [2],
                        "handle_index": 1,
                    },
                    "read_h": {
                        "type": "READF",
                        "indices": [],
                        "handle_index": 1,
                        "dependent_functions": ["open_h"],
                    },
                },
                transfer,
            )
            records = asyncio.run(resolver.run())

        consumer_values = {}
        for record in records:
            if record.seed.target_function == "read_h":
                consumer_values.setdefault(record.seed.site.site_id, set()).add(
                    record.fact.value
                )
        self.assertEqual(
            sorted(consumer_values.values(), key=lambda values: min(values)),
            [{"100"}, {"200"}],
        )

    def test_handle_consumer_uses_the_exact_owning_open(self):
        source = (
            "typedef int Handle;\n"
            "void open_h(Handle *handle, int file_no);\n"
            "void read_h(Handle *handle);\n"
            "int main(void) { Handle h1; Handle h2; open_h(&h1, 41); "
            "open_h(&h2, 42); read_h(&h2); return 0; }\n"
        )

        async def transfer(_request):
            raise AssertionError("literal open values should not need a transfer")

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {
                    "open_h": {
                        "type": "OPENF",
                        "indices": [2],
                        "handle_index": 1,
                        "dependent_functions": [],
                    },
                    "read_h": {
                        "type": "READF",
                        "indices": [],
                        "handle_index": 1,
                        "dependent_functions": ["open_h"],
                    },
                },
                transfer,
            )
            records = asyncio.run(resolver.run())

        read_values = {
            record.fact.value
            for record in records
            if record.seed.target_function == "read_h"
        }
        self.assertEqual(read_values, {"42"})
        self.assertTrue(
            all(
                record.fact.link_method == "VARTRACE"
                for record in records
                if record.seed.target_function == "read_h"
            )
        )

    def test_invalid_model_number_becomes_unresolved(self):
        source = "void X(int value); int main(void) { X(pick()); return 0; }\n"

        async def transfer(request):
            return answer_for(
                request,
                [{"target_arg": 1, "kind": "EXPRESSION", "expression": "999"}],
            )

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(records[0].fact.origin_kind, "UNRESOLVED")
        self.assertEqual(records[0].fact.value, "UNRESOLVED")

    def test_invalid_evidence_and_identifiers_never_become_values(self):
        source = "void X(int value); int main(void) { X(pick()); return 0; }\n"

        async def transfer(request):
            return {
                "arms": [
                    {
                        "bindings": [
                            {
                                "target_arg": 1,
                                "kind": "EXPRESSION",
                                "expression": "unknown_local + 999",
                            }
                        ],
                        "guard": "true",
                        "evidence": [
                            {
                                "file": "does-not-exist.c",
                                "snippet": "X(value);",
                            }
                        ],
                    }
                ]
            }

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(records[0].fact.value, "UNRESOLVED")
        self.assertEqual(resolver.transfer_cache, {})

    def test_external_binding_cannot_smuggle_a_numeric_answer(self):
        source = "void X(int value); int main(void) { X(pick()); return 0; }\n"

        async def transfer(_request):
            return {
                "arms": [
                    {
                        "bindings": [
                            {"target_arg": 1, "kind": "EXTERNAL", "expression": "999"}
                        ],
                        "guard": "true",
                        "evidence": [{"file": "main.c", "snippet": "X(pick());"}],
                    }
                ]
            }

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(records[0].fact.value, "UNRESOLVED")

    def test_unfindable_evidence_becomes_unresolved(self):
        source = "void X(int value); int main(void) { X(pick()); return 0; }\n"

        async def transfer(_request):
            return {
                "arms": [
                    {
                        "bindings": [
                            {"target_arg": 1, "kind": "EXPRESSION", "expression": "1"}
                        ],
                        "guard": "true",
                        "evidence": [
                            {
                                "file": "main.c",
                                "snippet": "a line that does not exist in the file",
                            }
                        ],
                    }
                ]
            }

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(records[0].fact.value, "UNRESOLVED")

    def test_root_formal_is_external_entry_without_extra_model_hop(self):
        source = (
            "void X(int value);\n"
            "void Y(int value) { X(value); }\n"
            "int main(int argc, char **argv) { Y(argc); return 0; }\n"
        )
        calls = []

        async def transfer(request):
            calls.append(request.function_name)
            return answer_for(
                request,
                [{"target_arg": 1, "kind": "EXPRESSION", "expression": "$1"}],
            )

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(calls, [])
        self.assertEqual(records[0].fact.value, "argc")
        self.assertEqual(records[0].fact.origin_kind, "EXTERNAL_ENTRY")

    def test_callback_route_keeps_registration_metadata(self):
        source = (
            "void X(int value);\n"
            "void handler(void) { X(123); }\n"
            "int main(void) { pmf_addevent(EVT, handler, 0); return 0; }\n"
        )

        async def transfer(_request):
            raise AssertionError("direct callback target literal needs no transfer")

        with tempfile.TemporaryDirectory() as directory:
            resolver = build_resolver(
                Path(directory),
                source,
                {"X": {"type": "READF", "indices": [1], "dependent_functions": []}},
                transfer,
                function_pointer_args={
                    "pmf_addevent": {
                        "func_argument": [2],
                        "total_args": 3,
                    }
                },
            )
            records = asyncio.run(resolver.run())

        self.assertEqual([record.fact.value for record in records], ["123"])
        self.assertEqual(records[0].fact.metadata["reachability"], "CALLBACK")
        self.assertEqual(records[0].fact.metadata["canonical"], "handler")


if __name__ == "__main__":
    unittest.main()
