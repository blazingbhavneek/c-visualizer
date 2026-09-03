"""Phase 4 value-flow failure-mode tests: F1 local backwalk, F5 branch arms."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from call_graph.call_graph import CallGraphBuilder
from helpers.Preprocess.preprocess import Preprocess
from helpers.extract_functions_from_c import get_local_function_definitions
from value_flow.resolver import ValueFlowResolver
from value_flow.status import RESOLVED, RUNTIME, UNRESOLVED, classify_records

OPEN_CONFIG = {
    "type": "OPENF",
    "indices": [2],
    "handle_index": 1,
    "dependent_functions": [],
    "launch": "NO DATA",
}
READ_CONFIG = {
    "type": "READF",
    "indices": [],
    "handle_index": 1,
    "dependent_functions": ["open_h"],
}
CLOSE_CONFIG = {
    "type": "CLOSEF",
    "indices": [],
    "dependent_functions": [],
}


def build_resolver(
    root: Path,
    files: dict[str, str],
    configs: dict,
    *,
    entry_points: list[tuple[str, str]] | None = None,
    transfer_resolver=None,
):
    project_structure = {}
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="latin-1")
        project_structure[name] = path
    trees = Preprocess().preprocess(project_structure=project_structure)
    file_functions = {
        name: get_local_function_definitions(code_bytes=source)
        for name, (_, source) in trees.items()
    }
    builder = CallGraphBuilder(
        project_structure=project_structure,
        trees=trees,
        function_pointer_args={},
        file_functions=file_functions,
    )
    graph = builder.build()
    resolver = ValueFlowResolver(
        graph=graph,
        registry=builder.node_registry,
        trees=trees,
        project_structure={key: str(value) for key, value in project_structure.items()},
        main_file_name="main.c",
        entry_function_name="main",
        entry_points=entry_points or [("main.c", "main")],
        function_configs=configs,
        macros=builder.macros,
        file_macros={},
        one_hop_resolver=None,
        return_use_resolver=None,
        handle_llm_resolver=None,
        cache_path=None,
        path_cap=10,
        llm_concurrency=1,
        transfer_resolver=transfer_resolver,
    )
    return resolver


class LocalBackwalkTests(unittest.TestCase):
    def test_unreachable_function_open_with_literal_recovers_value(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": "int main(void) { return 0; }\n",
                    "orphan.c": (
                        "void orphan(void)\n"
                        "{\n"
                        "    Handle h;\n"
                        "    open_h(&h, 4099);\n"
                        "}\n"
                    ),
                    "proto.h": "void open_h(Handle *h, int file_no);\n",
                },
                {"open_h": OPEN_CONFIG},
            )
            records = asyncio.run(resolver.run())

        backwalk = [
            record for record in records if record.fact.link_method == "LOCAL_BACKWALK"
        ]
        self.assertEqual(
            {record.fact.value for record in backwalk}, {"4099"}
        )
        self.assertEqual(
            {record.seed.launch_via for record in backwalk}, {"LOCAL_BACKWALK"}
        )
        # The value carries a source path, not an invented one.
        self.assertGreater(backwalk[0].path_count, 0)

    def test_unreachable_function_handle_binds_to_same_function_open(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": "int main(void) { return 0; }\n",
                    "orphan.c": (
                        "void orphan(void)\n"
                        "{\n"
                        "    Handle h;\n"
                        "    open_h(&h, 2345);\n"
                        "    read_h(&h);\n"
                        "}\n"
                    ),
                    "proto.h": (
                        "void open_h(Handle *h, int file_no);\n"
                        "void read_h(Handle *h);\n"
                    ),
                },
                {"open_h": OPEN_CONFIG, "read_h": READ_CONFIG},
            )
            records = asyncio.run(resolver.run())

        backwalk = [
            record
            for record in records
            if record.seed.target_function == "read_h"
            and record.fact.link_method == "LOCAL_BACKWALK"
        ]
        self.assertEqual({record.fact.value for record in backwalk}, {"2345"})

    def test_different_fcb_open_does_not_bind(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": "int main(void) { return 0; }\n",
                    "orphan.c": (
                        "void orphan(void)\n"
                        "{\n"
                        "    Handle h1;\n"
                        "    Handle h2;\n"
                        "    open_h(&h1, 1111);\n"
                        "    read_h(&h2);\n"
                        "}\n"
                    ),
                    "proto.h": (
                        "void open_h(Handle *h, int file_no);\n"
                        "void read_h(Handle *h);\n"
                    ),
                },
                {"open_h": OPEN_CONFIG, "read_h": READ_CONFIG},
            )
            records = asyncio.run(resolver.run())

        read_facts = [
            record for record in records if record.seed.target_function == "read_h"
        ]
        # h2 has no same-function open; the nearby h1 open must not bind.
        self.assertNotIn("1111", {record.fact.value for record in read_facts})

    def test_closed_fcb_does_not_bind(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": "int main(void) { return 0; }\n",
                    "orphan.c": (
                        "void orphan(void)\n"
                        "{\n"
                        "    Handle h;\n"
                        "    open_h(&h, 1234);\n"
                        "    close_h(&h);\n"
                        "    read_h(&h);\n"
                        "}\n"
                    ),
                    "proto.h": (
                        "void open_h(Handle *h, int file_no);\n"
                        "void read_h(Handle *h);\n"
                        "void close_h(Handle *h);\n"
                    ),
                },
                {
                    "open_h": OPEN_CONFIG,
                    "read_h": READ_CONFIG,
                    "close_h": CLOSE_CONFIG,
                },
            )
            records = asyncio.run(resolver.run())

        read_facts = [
            record
            for record in records
            if record.seed.target_function == "read_h"
            and record.fact.link_method == "LOCAL_BACKWALK"
        ]
        # The matching open was closed before the target: no backwalk value.
        self.assertEqual(read_facts, [])

    def test_same_named_local_handles_stay_in_their_own_functions(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "void first(void) { Handle fcb; open_h(&fcb, 11); read_h(&fcb); }\n"
                        "void second(void) { Handle fcb; open_h(&fcb, 22); read_h(&fcb); }\n"
                        "int main(void) { first(); second(); return 0; }\n"
                    )
                },
                {"open_h": OPEN_CONFIG, "read_h": READ_CONFIG},
            )
            records = asyncio.run(resolver.run())

        by_function = {}
        for record in records:
            if record.seed.target_function == "read_h":
                by_function.setdefault(record.seed.site.caller_id, set()).add(
                    record.fact.value
                )
        self.assertEqual(
            set(map(frozenset, by_function.values())),
            {frozenset({"11"}), frozenset({"22"})},
        )

    def test_handle_backwalk_limit_is_reported_as_unresolved(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("literal open should not need transfer")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "void worker(Handle *h) { read_h(h); }\n"
                        "int main(void) { Handle h; open_h(&h, 55); worker(&h); return 0; }\n"
                    )
                },
                {"open_h": OPEN_CONFIG, "read_h": READ_CONFIG},
                transfer_resolver=transfer_must_not_run,
            )
            resolver.search_state_cap = 1
            records = asyncio.run(resolver.run())

        read_record = next(
            record for record in records if record.seed.target_function == "read_h"
        )
        self.assertEqual(read_record.fact.value, "UNRESOLVED")
        self.assertEqual(
            read_record.fact.metadata["termination_reason"],
            "SEARCH_LIMIT_REACHED",
        )
        self.assertTrue(read_record.fact.metadata["search_truncated"])
        self.assertEqual(resolver.search_limit_seed_count, 1)

    def test_handle_and_value_backwalk_share_one_per_seed_state_budget(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("literal opens should not need transfer")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "void worker(Handle *h) { read_h(h); }\n"
                        "void left(void) { Handle h; open_h(&h, 11); worker(&h); }\n"
                        "void right(void) { Handle h; open_h(&h, 22); worker(&h); }\n"
                        "int main(void) { left(); right(); return 0; }\n"
                    )
                },
                {"open_h": OPEN_CONFIG, "read_h": READ_CONFIG},
                transfer_resolver=transfer_must_not_run,
            )
            resolver.search_state_cap = 4
            records = asyncio.run(resolver.run())

        reads = [
            record for record in records if record.seed.target_function == "read_h"
        ]
        self.assertEqual(resolver.search_state_count, resolver.search_state_cap)
        self.assertEqual(resolver.search_limit_seed_count, 1)
        self.assertIn("UNRESOLVED", {record.fact.value for record in reads})
        self.assertEqual(
            {classify_records(reads)[id(record)].status for record in reads},
            {UNRESOLVED},
        )

    def test_reachable_function_stays_direct_not_backwalk(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "void called(void);\n"
                        "int main(void) { called(); return 0; }\n"
                    ),
                    "worker.c": (
                        "void called(void)\n"
                        "{\n"
                        "    Handle h;\n"
                        "    open_h(&h, 4321);\n"
                        "}\n"
                    ),
                    "proto.h": "void open_h(Handle *h, int file_no);\n",
                },
                {"open_h": OPEN_CONFIG},
            )
            records = asyncio.run(resolver.run())

        self.assertTrue(records)
        self.assertNotIn(
            "LOCAL_BACKWALK", {record.fact.link_method for record in records}
        )


class BranchArmUnionTests(unittest.TestCase):
    def _open_after_chain(self, arms: str) -> dict[str, str]:
        return {
            "main.c": (
                "int main(void)\n"
                "{\n"
                "    Handle h;\n"
                "    int fno;\n"
                f"    {arms}\n"
                "    open_h(&h, fno);\n"
                "    return 0;\n"
                "}\n"
            ),
            "proto.h": "void open_h(Handle *h, int file_no);\n",
        }

    def test_three_way_if_else_if_else_keeps_middle_arm(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                self._open_after_chain(
                    "if (a)\n"
                    "        fno = 2512;\n"
                    "    else if (b)\n"
                    "        fno = 2519;\n"
                    "    else\n"
                    "        fno = 2525;"
                ),
                {"open_h": OPEN_CONFIG},
            )
            records = asyncio.run(resolver.run())
        self.assertEqual(
            {record.fact.value for record in records}, {"2512", "2519", "2525"}
        )

    def test_four_arm_chain_keeps_every_arm(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                self._open_after_chain(
                    "if (a)\n"
                    "        fno = 1;\n"
                    "    else if (b)\n"
                    "        fno = 2;\n"
                    "    else if (c)\n"
                    "        fno = 3;\n"
                    "    else\n"
                    "        fno = 4;"
                ),
                {"open_h": OPEN_CONFIG},
            )
            records = asyncio.run(resolver.run())
        self.assertEqual(
            {record.fact.value for record in records}, {"1", "2", "3", "4"}
        )

    def test_later_added_arm_survives(self):
        # A second if/else added after the original chain reassigns the
        # variable in both arms; the live set is exactly its two arms.
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                self._open_after_chain(
                    "if (a)\n"
                    "        fno = 10;\n"
                    "    else\n"
                    "        fno = 20;\n"
                    "    if (d)\n"
                    "        fno = 30;\n"
                    "    else\n"
                    "        fno = 40;"
                ),
                {"open_h": OPEN_CONFIG},
            )
            records = asyncio.run(resolver.run())
        self.assertEqual(
            {record.fact.value for record in records}, {"30", "40"}
        )

    def test_missing_else_stays_conservative(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                self._open_after_chain(
                    "if (a)\n"
                    "        fno = 2512;\n"
                    "    else if (b)\n"
                    "        fno = 2519;"
                ),
                {"open_h": OPEN_CONFIG},
            )
            records = asyncio.run(resolver.run())
        # No else: an earlier value may still reach the use; the syntax
        # resolver must not invent a closed set (no LLM is configured).
        self.assertNotEqual(
            {record.fact.value for record in records}, {"2512", "2519"}
        )
        statuses = classify_records(records)
        self.assertEqual(
            {statuses[id(record)].status for record in records},
            {UNRESOLVED},
        )

    def test_plain_if_else_union_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                self._open_after_chain(
                    "if (a)\n"
                    "        fno = 1;\n"
                    "    else\n"
                    "        fno = 2;"
                ),
                {"open_h": OPEN_CONFIG},
            )
            records = asyncio.run(resolver.run())
        self.assertEqual({record.fact.value for record in records}, {"1", "2"})


class RemainingPhase4Tests(unittest.TestCase):
    def test_guarded_macro_remains_resolved(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "#define FILE_NO 2818\n"
                        "void target(int value);\n"
                        "int main(void) { if (runtime_mode) target(FILE_NO); return 0; }\n"
                    )
                },
                {"target": {"type": "READF", "indices": [1]}},
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(records[0].fact.value, "2818")
        self.assertTrue(records[0].fact.metadata["guards"])
        self.assertEqual(classify_records(records)[id(records[0])].status, RESOLVED)

    def test_no_target_and_runtime_input_are_local_terminal_facts(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("local terminal values should bypass the model")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "long read(int, void *, unsigned long);\n"
                        "void target(long value); void marker(void);\n"
                        "int main(void) { char data[8]; target(read(0, data, 8)); marker(); return 0; }\n"
                    )
                },
                {
                    "target": {"type": "READF", "indices": [1]},
                    "marker": {"type": "CLOSEF", "indices": []},
                },
                transfer_resolver=transfer_must_not_run,
            )
            resolver.routes_for_seed = lambda _seed: (_ for _ in ()).throw(
                AssertionError("local terminal values must not enumerate routes")
            )
            records = asyncio.run(resolver.run())

        runtime = next(
            record for record in records if record.seed.target_function == "target"
        )
        no_target = next(
            record for record in records if record.seed.target_function == "marker"
        )
        self.assertEqual(classify_records([runtime])[id(runtime)].status, RUNTIME)
        self.assertEqual(runtime.fact.origin_kind, "RUNTIME_DATA")
        self.assertTrue(runtime.fact.metadata["trace_complete"])
        self.assertEqual(runtime.fact.metadata["termination_reason"], "RUNTIME_INPUT")
        self.assertEqual(no_target.fact.value, "NO TARGET")
        self.assertEqual(resolver.fast_path_seed_count, 2)

    def test_undefined_symbol_is_unresolved(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "void target(int value);\n"
                        "int main(void) { target(undefined_value); return 0; }\n"
                    )
                },
                {"target": {"type": "READF", "indices": [1]}},
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(records[0].fact.value, "UNRESOLVED")
        self.assertEqual(classify_records(records)[id(records[0])].status, UNRESOLVED)
        self.assertFalse(records[0].fact.metadata["trace_complete"])

    def test_macro_lookup_uses_active_include_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "active.h": "#define FILE_NO 4120\n",
                    "archive.h": "#define FILE_NO 9910\n",
                    "main.c": (
                        '#include "active.h"\n'
                        "void target(int value);\n"
                        "int main(void) { target(FILE_NO); return 0; }\n"
                    ),
                },
                {"target": {"type": "READF", "indices": [1]}},
            )
            records = asyncio.run(resolver.run())

        self.assertEqual({record.fact.value for record in records}, {"4120"})
        self.assertEqual(records[0].fact.origin_kind, "MACRO")

    def test_const_table_return_is_bounded_and_source_backed(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "static const int FILES[] = {100, 200};\n"
                        "int choose(int i) { return FILES[i]; }\n"
                        "void target(int value);\n"
                        "int main(void) { target(choose(unknown)); return 0; }\n"
                    )
                },
                {"target": {"type": "READF", "indices": [1]}},
            )
            records = asyncio.run(resolver.run())

        self.assertEqual({record.fact.value for record in records}, {"100", "200"})
        self.assertTrue(all(record.fact.origin_kind == "CONST_TABLE" for record in records))
        self.assertTrue(all(record.fact.link_method == "TABLE_LOOKUP" for record in records))
        self.assertEqual({record.fact.metadata["table_symbol"] for record in records}, {"FILES"})

    def test_route_transfer_uses_configured_static_struct_table(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("source-backed table should bypass the model")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef struct Row { int value; int other; } Row;\n"
                        "static Row ROWS[] = {{100, 900}, {200, 901}};\n"
                        "int DynREGetSchfno(int i) { return ROWS[i].value; }\n"
                        "void target(int value);\n"
                        "int main(void) { target(DynREGetSchfno(runtime_index)); return 0; }\n"
                    )
                },
                {"target": {"type": "READF", "indices": [1]}},
                transfer_resolver=transfer_must_not_run,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual({record.fact.value for record in records}, {"100", "200"})
        self.assertTrue(
            all(record.fact.origin_kind == "CONST_TABLE" for record in records)
        )
        self.assertTrue(
            all(record.fact.link_method == "TABLE_LOOKUP" for record in records)
        )
        self.assertEqual(len({record.fact.metadata["set_id"] for record in records}), 1)
        statuses = classify_records(records)
        self.assertEqual({statuses[id(record)].status for record in records}, {RUNTIME})

    def test_route_transfer_selects_literal_struct_table_index(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("literal table lookup should bypass the model")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef struct Row { int value; int other; } Row;\n"
                        "static Row ROWS[] = {{100, 900}, {200, 901}};\n"
                        "int DynREGetSchfno(int i) { return ROWS[i].value; }\n"
                        "void target(int value);\n"
                        "int main(void) { target(DynREGetSchfno(0)); return 0; }\n"
                    )
                },
                {"target": {"type": "READF", "indices": [1]}},
                transfer_resolver=transfer_must_not_run,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual([record.fact.value for record in records], ["100"])
        self.assertEqual(records[0].fact.origin_kind, "CONST_TABLE")
        self.assertEqual(classify_records(records)[id(records[0])].status, RESOLVED)

    def test_configured_local_array_lookup_preserves_file_value(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("source-backed local table should bypass the model")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void mpf_mfs_openm(Handle *, void *, int, int, int);\n"
                        "void Dxi_UpTbnFileOpen(Handle *h, int onsub, int selector) {\n"
                        "  int files[2] = {701, 702};\n"
                        "  mpf_mfs_openm(h, 0, files[selector], 0, 0);\n"
                        "}\n"
                        "int main(void) { Handle h; Dxi_UpTbnFileOpen(&h, 0, 0); Dxi_UpTbnFileOpen(&h, 0, 1); return 0; }\n"
                    )
                },
                {
                    "mpf_mfs_openm": {
                        "type": "OPENF", "indices": [3],
                        "handle_index": 1, "dependent_functions": []
                    }
                },
                transfer_resolver=transfer_must_not_run,
            )
            records = asyncio.run(resolver.run())

        opens = [record for record in records if record.seed.target_function == "mpf_mfs_openm"]
        self.assertEqual({record.fact.value for record in opens}, {"701", "702"})
        self.assertNotIn("0", {record.fact.value for record in opens})
        self.assertNotIn("1", {record.fact.value for record in opens})
        self.assertTrue(all(record.fact.origin_kind == "CONST_TABLE" for record in opens))
        self.assertTrue(all(record.fact.link_method == "TABLE_LOOKUP" for record in opens))

    def test_configured_local_array_mutation_stays_unresolved(self):
        async def transfer_returns_nothing(_request):
            return None

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void mpf_mfs_openm(Handle *, void *, int, int, int);\n"
                        "void Dxi_UpTbnFileOpen(Handle *h, int onsub, int selector) {\n"
                        "  int files[2] = {701, 702};\n"
                        "  files[0] = 999;\n"
                        "  mpf_mfs_openm(h, 0, files[selector], 0, 0);\n"
                        "}\n"
                        "int main(void) { Handle h; Dxi_UpTbnFileOpen(&h, 0, 0); return 0; }\n"
                    )
                },
                {
                    "mpf_mfs_openm": {
                        "type": "OPENF", "indices": [3],
                        "handle_index": 1, "dependent_functions": []
                    }
                },
                transfer_resolver=transfer_returns_nothing,
            )
            records = asyncio.run(resolver.run())

        opens = [record for record in records if record.seed.target_function == "mpf_mfs_openm"]
        self.assertTrue(opens)
        self.assertTrue(all(record.fact.value == "UNRESOLVED" for record in opens))

    def test_configured_local_array_selector_reaches_caller_literals(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("literal selector definitions should bypass the model")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void mpf_mfs_openm(Handle *, void *, int, int, int);\n"
                        "void Dxi_UpTbnFileOpen(Handle *h, int selector) {\n"
                        "  int files[2] = {701, 702};\n"
                        "  mpf_mfs_openm(h, 0, files[selector], 0, 0);\n"
                        "}\n"
                        "void caller(Handle *h, int mode) {\n"
                        "  int selector;\n"
                        "  if (mode) selector = 1; else selector = 0;\n"
                        "  Dxi_UpTbnFileOpen(h, selector);\n"
                        "}\n"
                        "int main(void) { Handle h; caller(&h, runtime_mode); return 0; }\n"
                    )
                },
                {
                    "mpf_mfs_openm": {
                        "type": "OPENF", "indices": [3],
                        "handle_index": 1, "dependent_functions": []
                    }
                },
                transfer_resolver=transfer_must_not_run,
            )
            records = asyncio.run(resolver.run())

        opens = [record for record in records if record.seed.target_function == "mpf_mfs_openm"]
        self.assertEqual({record.fact.value for record in opens}, {"701", "702"})
        self.assertTrue(all(record.fact.link_method == "TABLE_LOOKUP" for record in opens))

    def test_string_writes_union_into_forkproc_name(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "void strcpy(char *, const char *);\n"
                        "void pmf_forkprocbs_H(const char *, const char *);\n"
                        "int main(void) {\n"
                        "  char name[16];\n"
                        "  if (mode) strcpy(name, \"ECS-A\");\n"
                        "  else strcpy(name, \"ECS-B\");\n"
                        "  pmf_forkprocbs_H(\"host\", name);\n"
                        "  return 0;\n"
                        "}\n"
                    )
                },
                {
                    "pmf_forkprocbs_H": {
                        "type": "FORKF", "indices": [2], "dependent_functions": []
                    }
                },
            )
            records = asyncio.run(resolver.run())

        self.assertEqual({record.fact.value for record in records}, {"\"ECS-A\"", "\"ECS-B\""})
        self.assertTrue(all(record.fact.origin_kind == "BOUNDED_SET" for record in records))
        self.assertTrue(all(record.fact.metadata["buffer"] == "name" for record in records))

    def test_string_macro_writes_union_into_forkproc_name(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        '#define PROC_A "dxi500d"\n'
                        '#define PROC_B "dxi501d"\n'
                        "void strcpy(char *, const char *);\n"
                        "void pmf_forkprocbs_H(const char *, const char *);\n"
                        "int main(void) { char name[16];\n"
                        "  if (mode) strcpy(name, PROC_A);\n"
                        "  else strcpy(name, PROC_B);\n"
                        '  pmf_forkprocbs_H("host", name); return 0; }\n'
                    )
                },
                {
                    "pmf_forkprocbs_H": {
                        "type": "FORKF", "indices": [2], "dependent_functions": []
                    }
                },
            )
            records = asyncio.run(resolver.run())

        self.assertEqual(
            {record.fact.value for record in records}, {"\"dxi500d\"", "\"dxi501d\""}
        )

    def test_switch_assignment_preserves_values_from_before_switch(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("switch reaching definitions should be syntax-only")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "int main(int kind, int mode) { Handle h; int file_no;\n"
                        "  if (kind == 1) file_no = 10;\n"
                        "  else if (kind == 2) file_no = 20; else file_no = 30;\n"
                        "  switch (mode) { case 1: file_no = 40; break;\n"
                        "    case 2: return 0; default: break; }\n"
                        "  open_h(&h, file_no); read_h(&h); return 0; }\n"
                    )
                },
                {"open_h": OPEN_CONFIG, "read_h": READ_CONFIG},
                transfer_resolver=transfer_must_not_run,
            )
            records = asyncio.run(resolver.run())

        for target in ("open_h", "read_h"):
            self.assertEqual(
                {
                    record.fact.value
                    for record in records
                    if record.seed.target_function == target
                },
                {"10", "20", "30", "40"},
            )

    def test_transfer_search_reuses_syntax_proven_open_values(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("proven opening values should bypass transfer")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "int main(int mode, int use) { Handle h; int file_no;\n"
                        "  if (mode) file_no = 10; else file_no = 20;\n"
                        "  open_h(&h, file_no);\n"
                        "  if (use) read_h(&h); return 0; }\n"
                    )
                },
                {"open_h": OPEN_CONFIG, "read_h": READ_CONFIG},
                transfer_resolver=transfer_must_not_run,
            )
            records = asyncio.run(resolver.run())

        reads = [record for record in records if record.seed.target_function == "read_h"]
        self.assertEqual({record.fact.value for record in reads}, {"10", "20"})

    def test_terminating_else_does_not_erase_branch_values(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "void target(int value);\n"
                        "int main(int mode) { int value;\n"
                        "  if (mode == 0) value = 701;\n"
                        "  else if (mode == 1) value = 723;\n"
                        "  else if (mode == 2) value = 727; else return -1;\n"
                        "  target(value); return 0; }\n"
                    )
                },
                {"target": {"type": "READF", "indices": [1]}},
            )
            records = asyncio.run(resolver.run())

        self.assertEqual({record.fact.value for record in records}, {"701", "723", "727"})

    def test_safe_local_array_uses_finite_selector_values(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("local constant table should be syntax-only")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "int main(int mode) { Handle h; int files[2] = {2503, 2513};\n"
                        "  int selected = 0; if (mode) selected = 1;\n"
                        "  open_h(&h, files[selected]); read_h(&h); return 0; }\n"
                    )
                },
                {"open_h": OPEN_CONFIG, "read_h": READ_CONFIG},
                transfer_resolver=transfer_must_not_run,
            )
            records = asyncio.run(resolver.run())

        for target in ("open_h", "read_h"):
            self.assertEqual(
                {
                    record.fact.value
                    for record in records
                    if record.seed.target_function == target
                },
                {"2503", "2513"},
            )

    def test_unknown_global_array_selector_stays_unresolved(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("an unproven table selector must not reach the model")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "globals.c": (
                        "#define Q_A 702\n#define Q_B 703\n#define Q_C 724\n"
                        "int queues[] = {Q_A, Q_B, Q_C};\n"
                    ),
                    "main.c": (
                        "extern int queues[]; void target(int value);\n"
                        "int main(int index) { target(queues[index + 0]); return 0; }\n"
                    ),
                },
                {"target": {"type": "QUEUEF", "indices": [1]}},
                transfer_resolver=transfer_must_not_run,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual({record.fact.value for record in records}, {"UNRESOLVED"})

    def test_global_array_uses_proven_loop_and_assignment_indices(self):
        async def transfer_must_not_run(_request):
            raise AssertionError("proven table indices should be syntax-only")

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "globals.c": "int queues[] = {702, 703, 724, 725, 728, 729};\n",
                    "main.c": (
                        "extern int queues[]; void target(int value);\n"
                        "int main(int mode) { int i; int selected = 0;\n"
                        "  for (i = 0; i < 3; i++) {\n"
                        "    if (mode == i) { selected = i; break; }\n"
                        "  }\n"
                        "  target(queues[(selected * 2) + 1]);\n"
                        "  for (i = 0; i < 2; i++) {\n"
                        "    target(queues[i + 2]);\n"
                        "    target(queues[(selected * 2) + i]);\n"
                        "  }\n"
                        "  return 0; }\n"
                    ),
                },
                {"target": {"type": "QUEUEF", "indices": [1]}},
                transfer_resolver=transfer_must_not_run,
            )
            records = asyncio.run(resolver.run())

        by_line = {}
        for record in records:
            by_line.setdefault(record.seed.site.line, set()).add(record.fact.value)
        self.assertEqual(by_line[6], {"703", "725", "729"})
        self.assertEqual(by_line[8], {"724", "725"})
        self.assertEqual(by_line[9], {"702", "703", "724", "725", "728", "729"})
        self.assertTrue(
            all(classify_records(records)[id(record)].status == RUNTIME for record in records)
        )

    def test_mutated_global_array_is_not_treated_as_constant(self):
        async def transfer_returns_nothing(_request):
            return None

        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "globals.c": (
                        "int queues[] = {702, 703};\n"
                        "void change(void) { queues[0] = 999; }\n"
                    ),
                    "main.c": (
                        "extern int queues[]; void target(int value);\n"
                        "int main(int index) { target(queues[index]); return 0; }\n"
                    ),
                },
                {"target": {"type": "QUEUEF", "indices": [1]}},
                transfer_resolver=transfer_returns_nothing,
            )
            records = asyncio.run(resolver.run())

        self.assertEqual({record.fact.value for record in records}, {"UNRESOLVED"})

    def test_switch_error_close_does_not_kill_open(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef int Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "void close_h(Handle *);\n"
                        "int main(int mode) { Handle h; open_h(&h, 2554);\n"
                        "  switch (mode) { case 0: break; default:\n"
                        "    close_h(&h); return -1; }\n"
                        "  read_h(&h); return 0; }\n"
                    )
                },
                {
                    "open_h": OPEN_CONFIG,
                    "read_h": READ_CONFIG,
                    "close_h": CLOSE_CONFIG,
                },
            )
            records = asyncio.run(resolver.run())

        reads = [record for record in records if record.seed.target_function == "read_h"]
        self.assertEqual({record.fact.value for record in reads}, {"2554"})

    def test_checked_wrapper_write_kills_initializer(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef struct { int x; } Handle;\n"
                        "void open_h(Handle *, int);\n"
                        "int ChaGetFileInfo(int, int, int *, int *);\n"
                        "int main(void) { Handle h; int fno = 0; int sv = 0;\n"
                        "  int rc = ChaGetFileInfo(0, 0, &fno, &sv);\n"
                        "  if (rc == -1) return 1;\n"
                        "  open_h(&h, fno); return 0;\n"
                        "}\n"
                    ),
                    "cha.c": (
                        "static const int TM[] = {301, 302};\n"
                        "static const int SV[] = {401, 402};\n"
                        "int ChaGetFileInfo(int a, int b, int *tm, int *sv) {\n"
                        "  *tm = TM[a]; *sv = SV[b]; return 0;\n"
                        "}\n"
                    ),
                },
                {
                    "open_h": {
                        "type": "OPENF", "indices": [2],
                        "handle_index": 1, "dependent_functions": []
                    },
                    "ChaGetFileInfo": {
                        "type": "READF", "indices": [], "dependent_functions": []
                    },
                },
            )
            records = asyncio.run(resolver.run())

        opens = [record for record in records if record.seed.target_function == "open_h"]
        self.assertEqual({record.fact.value for record in opens}, {"301", "302"})
        self.assertNotIn("0", {record.fact.value for record in opens})
        self.assertTrue(all(record.fact.link_method == "WRAPPER_WRITE" for record in opens))

    def test_nested_wrapper_table_write_is_runtime_not_initializer(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef struct { int x; } Handle;\n"
                        "void open_h(Handle *, int);\n"
                        "int ChaGetFileInfo(int, int, int *, int *);\n"
                        "int main(void) { Handle h; int fno = 0; int sv = 0;\n"
                        "  int rc = ChaGetFileInfo(1, 1, &fno, &sv);\n"
                        "  if (rc == -1) return 1;\n"
                        "  open_h(&h, fno); return 0;\n"
                        "}\n"
                    ),
                    "cha.c": (
                        "static const int TM[2][2] = {{301, 302}, {303, 304}};\n"
                        "int ChaGetFileInfo(int a, int b, int *tm, int *sv) {\n"
                        "  *tm = TM[a][b]; *sv = TM[a][b]; return 0;\n"
                        "}\n"
                    ),
                },
                {
                    "open_h": OPEN_CONFIG,
                    "ChaGetFileInfo": {
                        "type": "READF", "indices": [], "dependent_functions": []
                    },
                },
            )
            records = asyncio.run(resolver.run())

        opens = [record for record in records if record.seed.target_function == "open_h"]
        self.assertEqual({record.fact.value for record in opens}, {"fno"})
        self.assertTrue(all(record.fact.origin_kind == "RUNTIME_DATA" for record in opens))
        self.assertNotIn("0", {record.fact.value for record in opens})

    def test_error_branch_close_does_not_kill_open(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef struct { int x; } Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "void close_h(Handle *);\n"
                        "int main(int failed) { Handle h; open_h(&h, 777);\n"
                        "  if (failed) { close_h(&h); return 1; }\n"
                        "  read_h(&h); return 0;\n"
                        "}\n"
                    )
                },
                {
                    "open_h": OPEN_CONFIG,
                    "read_h": READ_CONFIG,
                    "close_h": CLOSE_CONFIG,
                },
            )
            records = asyncio.run(resolver.run())

        reads = [record for record in records if record.seed.target_function == "read_h"]
        self.assertEqual({record.fact.value for record in reads}, {"777"})

    def test_file_static_handle_stays_translation_unit_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef struct { int x; } Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "void close_h(Handle *);\n"
                        "static Handle fcb;\n"
                        "void open_it(int failed) { open_h(&fcb, 777);\n"
                        "  if (failed) { close_h(&fcb); return; } }\n"
                        "void use_it(void) { read_h(&fcb); }\n"
                        "int main(void) { open_it(0); use_it(); return 0; }\n"
                    ),
                    "other.c": (
                        "typedef struct { int x; } Handle;\n"
                        "static Handle fcb;\n"
                        "void unrelated(void) { open_h(&fcb, 888); }\n"
                    ),
                },
                {
                    "open_h": {
                        "type": "OPENF", "indices": [2],
                        "handle_index": 1, "dependent_functions": []
                    },
                    "read_h": {
                        "type": "READF", "indices": [],
                        "handle_index": 1, "dependent_functions": ["open_h"]
                    },
                    "close_h": CLOSE_CONFIG,
                },
            )
            records = asyncio.run(resolver.run())

        reads = [record for record in records if record.seed.target_function == "read_h"]
        self.assertEqual({record.fact.value for record in reads}, {"777"})

    def test_pointer_parameter_maps_each_caller(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef struct { int x; } Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "void consume(Handle *p) { read_h(p); }\n"
                        "void one(void) { Handle a; open_h(&a, 111); consume(&a); }\n"
                        "void two(void) { Handle b; open_h(&b, 222); consume(&b); }\n"
                        "int main(void) { one(); two(); return 0; }\n"
                    )
                },
                {
                    "open_h": {
                        "type": "OPENF", "indices": [2],
                        "handle_index": 1, "dependent_functions": []
                    },
                    "read_h": {
                        "type": "READF", "indices": [],
                        "handle_index": 1, "dependent_functions": ["open_h"]
                    },
                },
            )
            records = asyncio.run(resolver.run())

        reads = [record for record in records if record.seed.target_function == "read_h"]
        self.assertEqual({record.fact.value for record in reads}, {"111", "222"})


if __name__ == "__main__":
    unittest.main()
