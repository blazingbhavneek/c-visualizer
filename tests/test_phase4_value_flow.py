"""Phase 4 value-flow failure-mode tests: F1 local backwalk, F5 branch arms."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from call_graph.call_graph import CallGraphBuilder
from helpers.Preprocess.preprocess import Preprocess
from helpers.extract_functions_from_c import get_local_function_definitions
from value_flow.resolver import ValueFlowResolver

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

    def test_file_static_handle_stays_translation_unit_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = build_resolver(
                Path(temp),
                {
                    "main.c": (
                        "typedef struct { int x; } Handle;\n"
                        "void open_h(Handle *, int); void read_h(Handle *);\n"
                        "static Handle fcb;\n"
                        "void open_it(void) { open_h(&fcb, 777); }\n"
                        "void use_it(void) { read_h(&fcb); }\n"
                        "int main(void) { open_it(); use_it(); return 0; }\n"
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
