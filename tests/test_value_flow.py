import asyncio
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from call_graph.call_graph import CallGraphBuilder
from helpers.Preprocess.preprocess import Preprocess
from helpers.extract_functions_from_c import get_local_function_definitions
from value_flow.outputs import write_outputs
from value_flow.queries import OneHopAnswer, ParamQuery, ReturnUseQuery
from value_flow.resolver import ValueFlowResolver


class ValueFlowTests(unittest.TestCase):
    def build_resolver(
        self,
        root: Path,
        files: dict[str, str],
        configs: dict,
        *,
        callbacks: dict | None = None,
        one_hop=None,
        return_use=None,
        path_cap: int = 100,
        cache_path: Path | None = None,
        main_file_name: str = "main.c",
        entry_function_name: str = "main",
        entry_points: list[tuple[str, str]] | None = None,
        include_roots: tuple[Path, ...] = (),
        path_overrides: dict[str, Path] | None = None,
    ) -> ValueFlowResolver:
        project_structure = {}
        for name, source in files.items():
            path = (path_overrides or {}).get(name, root / name)
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
            function_pointer_args=callbacks or {},
            file_functions=file_functions,
        )
        graph = builder.build()
        file_macros = {}
        for name, source in files.items():
            macros = {}
            for line in source.splitlines():
                parts = line.strip().split(maxsplit=2)
                if len(parts) == 3 and parts[:1] == ["#define"]:
                    macros[parts[1]] = parts[2]
            file_macros[name] = macros
        return ValueFlowResolver(
            graph=graph,
            registry=builder.node_registry,
            trees=trees,
            project_structure={
                key: str(value) for key, value in project_structure.items()
            },
            include_roots=include_roots,
            main_file_name=main_file_name,
            entry_function_name=entry_function_name,
            entry_points=entry_points,
            function_configs=configs,
            macros=builder.macros,
            file_macros=file_macros,
            one_hop_resolver=one_hop,
            return_use_resolver=return_use,
            path_cap=path_cap,
            cache_path=cache_path,
        )

    def test_literal_macro_and_parameter_flow_are_syntax_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            called = []

            async def one_hop(*args):
                called.append(args)
                return None

            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "defs.h": "#define FILE_NO 42\n",
                    "main.c": (
                        '#include "defs.h"\n'
                        "void target(int value);\n"
                        "void wrapper(int value) { target(value); target(value); }\n"
                        "int main(void) { wrapper(FILE_NO); target(7); return 0; }\n"
                    ),
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                one_hop=one_hop,
            )
            records = asyncio.run(resolver.run())

            self.assertEqual({record.fact.value for record in records}, {"42", "7"})
            self.assertTrue(
                all(record.fact.origin_kind in {"MACRO", "CONST"} for record in records)
            )
            self.assertEqual(called, [])
            self.assertEqual(len(resolver.seeds), 3)
            self.assertEqual(len({seed.site.site_id for seed in resolver.seeds}), 3)
            parameter_token = ParamQuery("[main.c]wrapper", 1).token()
            self.assertIn(parameter_token, resolver.results)

    def test_macro_resolution_is_memoized_per_source_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "defs.h": "#define FILE_NO 42\n",
                    "main.c": (
                        '#include "defs.h"\n'
                        "void target(int value);\n"
                        "int main(void) { target(FILE_NO); return 0; }\n"
                    ),
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
            )
            calls = 0
            original = resolver._all_macros

            def counted(file_name=None):
                nonlocal calls
                calls += 1
                return original(file_name)

            resolver._all_macros = counted
            first = resolver._resolve_macro("FILE_NO", "main.c")
            second = resolver._resolve_macro("FILE_NO", "main.c")

            self.assertEqual(first, second)
            self.assertEqual(first[0], "42")
            self.assertEqual(calls, 1)

    def test_enum_constants_are_resolved_without_llm(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            called = []

            async def one_hop(*args):
                called.append(args)
                return OneHopAnswer(kind="VALUE", value="999")

            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "defs.h": (
                        "enum FileNos { BASE = 3909, NEXT, "
                        "ALIAS = BASE + 3, HEX = 0xF };\n"
                    ),
                    "main.c": (
                        '#include "defs.h"\n'
                        "typedef struct { int value; } Handle;\n"
                        "void open_h(Handle *h, int file_no);\n"
                        "void read_h(Handle *h);\n"
                        "int main(void) { Handle h; "
                        "open_h(&h, NEXT); read_h(&h); return 0; }\n"
                    ),
                },
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
                one_hop=one_hop,
            )
            records = asyncio.run(resolver.run())

            self.assertEqual(resolver.enum_values["NEXT"][0], "3910")
            self.assertEqual(resolver.enum_values["ALIAS"][0], "3912")
            self.assertEqual(
                {
                    record.fact.value
                    for record in records
                    if record.seed.target_function in {"open_h", "read_h"}
                },
                {"3910"},
            )
            self.assertTrue(
                all(
                    record.fact.resolved_by == "SYNTAX"
                    for record in records
                    if record.fact.value == "3910"
                )
            )
            self.assertEqual(called, [])

    def test_enum_resolution_uses_included_header_not_archive_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            called = []

            async def one_hop(*args):
                called.append(args)
                return OneHopAnswer(kind="VALUE", value="1021")

            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "active/types.h": (
                        "enum FileNos { DynReCtlInfFNO = 3918 };\n"
                    ),
                    "active/api.h": '#include "active/types.h"\n',
                    "archive/types.h": (
                        "enum FileNos { DynReCtlInfFNO = 1021 };\n"
                    ),
                    "main.c": (
                        '#include "active/api.h"\n'
                        "void target(int value);\n"
                        "int main(void) { target(DynReCtlInfFNO); return 0; }\n"
                    ),
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                one_hop=one_hop,
            )
            records = asyncio.run(resolver.run())

            self.assertEqual(records[0].fact.value, "3918")
            self.assertEqual(records[0].fact.origin_kind, "CONST")
            self.assertEqual(records[0].fact.resolved_by, "SYNTAX")
            self.assertEqual(called, [])

    def test_include_root_resolves_bare_project_map_key_with_duplicate_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            include_root = root / "include"
            current_header = include_root / "Dyn" / "Foo.h"
            archive_header = root / "archive" / "Dyn" / "Foo.h"
            resolver = self.build_resolver(
                root,
                {
                    "Foo.h": "enum FileNos { CURRENT_FNO = 1234 };\n",
                    "archive/Foo.h": "enum FileNos { CURRENT_FNO = 9999 };\n",
                    "main.c": (
                        "#include <Dyn/Foo.h>\n"
                        "void target(int value);\n"
                        "int main(void) { target(CURRENT_FNO); return 0; }\n"
                    ),
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                include_roots=(include_root,),
                path_overrides={
                    "Foo.h": current_header,
                    "archive/Foo.h": archive_header,
                },
            )

            records = asyncio.run(resolver.run())

            self.assertEqual(resolver.include_graph["main.c"], ("Foo.h",))
            self.assertEqual(records[0].fact.value, "1234")
            self.assertEqual(records[0].fact.resolved_by, "SYNTAX")

    def test_unrelated_nearby_open_is_not_a_handle_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "typedef struct { int value; } Handle;\n"
                        "void open_h(Handle *h, int file_no);\n"
                        "void read_h(Handle *h);\n"
                        "int main(void) { Handle a; Handle b; Handle c;\n"
                        "  open_h(&a, 10); open_h(&b, 20); read_h(&c);\n"
                        "  return 0; }\n"
                    )
                },
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
            )
            records = asyncio.run(resolver.run())
            read_records = [
                record
                for record in records
                if record.seed.target_function == "read_h"
            ]

            self.assertEqual(len(read_records), 1)
            self.assertEqual(read_records[0].fact.origin_kind, "UNRESOLVED")
            self.assertEqual(read_records[0].fact.value, "UNRESOLVED")
            self.assertEqual(read_records[0].fact.source_expr, "HANDLE_AMBIGUOUS")
            self.assertNotEqual(read_records[0].fact.link_method, "LEGACY_PROXIMITY")

    def test_llm_value_is_a_candidate_not_an_exact_fact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            async def one_hop(*args):
                return OneHopAnswer(kind="VALUE", value="999")

            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "void target(int value);\n"
                        "int main(void) { int input; target(input); return 0; }\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                one_hop=one_hop,
            )
            records = asyncio.run(resolver.run())

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].fact.value, "999")
            self.assertEqual(records[0].fact.origin_kind, "LLM_CANDIDATE")
            self.assertEqual(records[0].fact.resolved_by, "LLM")

    def test_configured_wrapper_macro_keeps_target_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "api.h": "#define target_wrapper(value) target_impl(-1, (value))\n",
                    "main.c": (
                        '#include "api.h"\n'
                        "void target_impl(int value, int mode);\n"
                        "int main(void) { target_wrapper(7); return 0; }\n"
                    ),
                },
                {
                    "target_wrapper": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
            )

            records = asyncio.run(resolver.run())

            self.assertEqual(len(resolver.seeds), 1)
            self.assertEqual(resolver.seeds[0].target_function, "target_wrapper")
            self.assertEqual(resolver.seeds[0].site.callee_id, "target_impl")
            self.assertEqual(records[0].fact.value, "7")

    def test_nonstandard_process_entry_is_reachable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "entry.c": (
                        "void target(int value);\n"
                        "int pmf_main_H(void) { target(7); return 0; }\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                main_file_name="entry.c",
                entry_function_name="pmf_main_H",
            )

            records = asyncio.run(resolver.run())

            self.assertEqual(len(resolver.reachable), 2)
            self.assertEqual(len(resolver.seeds), 1)
            self.assertEqual(records[0].fact.value, "7")
            self.assertEqual(records[0].seed.call_function, "pmf_main_H")

    def test_all_defined_lifecycle_entries_are_reachable_roots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "entry.c": (
                        "void target(int value);\n"
                        "int pmf_main_H(void) { target(7); return 0; }\n"
                        "int pmf_end_H(void) { target(8); return 0; }\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                main_file_name="entry.c",
                entry_function_name="pmf_main_H",
                entry_points=[
                    ("entry.c", "pmf_main_H"),
                    ("entry.c", "pmf_end_H"),
                ],
            )

            records = asyncio.run(resolver.run())

            self.assertEqual({record.fact.value for record in records}, {"7", "8"})
            self.assertEqual(len(resolver.seeds), 2)
            self.assertEqual(len(resolver.reachable), 3)

    def test_callback_edges_are_deduplicated_and_external_parameters_are_named(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "typedef void (*Handler)(int);\n"
                        "void register_cb(int event, Handler handler);\n"
                        "void target(int value);\n"
                        "void callback(int event) { target(event); }\n"
                        "int main(void) { register_cb(1, callback); return 0; }\n"
                    )
                },
                {
                    "register_cb": {
                        "type": "EVENT",
                        "indices": [],
                        "launch": "EVENT",
                        "dependent_functions": [],
                    },
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    },
                },
                callbacks={"register_cb": {"func_argument": [2]}},
            )
            records = asyncio.run(resolver.run())
            target = [
                record for record in records if record.seed.target_function == "target"
            ]

            self.assertEqual(len(target), 1)
            self.assertEqual(target[0].fact.origin_kind, "EXTERNAL_ENTRY")
            self.assertEqual(target[0].fact.value, "event")
            self.assertEqual(target[0].seed.launch_via, "EVENT")
            callback_id = "[main.c]callback"
            callback_edges = [
                edge
                for edge in resolver.reverse_callers[callback_id]
                if edge.synthetic_callback
            ]
            self.assertEqual(len(callback_edges), 1)

    def test_if_else_local_assignments_keep_both_reaching_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "void target(int value);\n"
                        "void wrapper(int mode) {\n"
                        "  int value;\n"
                        "  if (mode) value = 100; else value = 200;\n"
                        "  target(value);\n"
                        "}\n"
                        "int main(void) { wrapper(1); return 0; }\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
            )
            records = asyncio.run(resolver.run())

            self.assertEqual({record.fact.value for record in records}, {"100", "200"})
            self.assertTrue(
                all(record.fact.origin_kind == "CONST" for record in records)
            )

    def test_handle_parameter_branch_and_reopen_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "typedef struct { int value; } Handle;\n"
                        "void open_h(Handle *h, int file_no);\n"
                        "void read_h(Handle *h);\n"
                        "void close_h(Handle *h);\n"
                        "void worker(Handle *h) { read_h(h); }\n"
                        "int main(int argc, char **argv) {\n"
                        "  Handle a; Handle b;\n"
                        "  if (argc) open_h(&a, 10); else open_h(&a, 20);\n"
                        "  read_h(&a);\n"
                        "  open_h(&b, 30); close_h(&b); open_h(&b, 40); read_h(&b);\n"
                        "  open_h(&a, 50); worker(&a);\n"
                        "  return argv != 0;\n"
                        "}\n"
                    )
                },
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
                    "close_h": {
                        "type": "CLOSEF",
                        "indices": [],
                        "handle_index": 1,
                        "dependent_functions": ["open_h"],
                    },
                },
            )
            records = asyncio.run(resolver.run())
            reads = [
                record for record in records if record.seed.target_function == "read_h"
            ]
            values_by_line = {}
            for record in reads:
                values_by_line.setdefault(record.seed.site.line, set()).add(
                    record.fact.value
                )

            self.assertIn({"10", "20"}, values_by_line.values())
            self.assertIn({"40"}, values_by_line.values())
            self.assertIn({"10", "20", "50"}, values_by_line.values())
            self.assertTrue(
                all(record.fact.link_method == "VARTRACE" for record in reads)
            )

    def test_return_use_is_cached_per_call_site(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            calls = []

            async def return_use(site, function):
                calls.append(site.site_id)
                return "WRITEF"

            # A discarded return value is the case the AST cannot classify, so
            # this is what reaches the LLM. The pointer-write case below must
            # NOT reach it: syntax already answers that one for free.
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "int *load_ptr(int id);\n"
                        "int main(void) { load_ptr(3); return 0; }\n"
                    )
                },
                {
                    "load_ptr": {
                        "type": "WRITEF/READF",
                        "indices": [],
                        "dependent_functions": [],
                    }
                },
                return_use=return_use,
            )
            seed = resolver.seeds[0]

            first, second = asyncio.run(
                self._resolve_twice(resolver, ReturnUseQuery(seed.site.site_id))
            )
            self.assertEqual(first[0].value, "WRITEF")
            self.assertEqual(second[0].value, "WRITEF")
            self.assertEqual(calls, [seed.site.site_id])

    def test_return_use_written_through_pointer_needs_no_llm(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            calls = []

            async def return_use(site, function):
                calls.append(site.site_id)
                return "READF"

            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "int *load_ptr(int id);\n"
                        "int main(void) { int *p = load_ptr(3); *p = 4; return 0; }\n"
                    )
                },
                {
                    "load_ptr": {
                        "type": "WRITEF/READF",
                        "indices": [],
                        "dependent_functions": [],
                    }
                },
                return_use=return_use,
            )
            seed = resolver.seeds[0]
            facts = asyncio.run(resolver.resolve(ReturnUseQuery(seed.site.site_id)))
            self.assertEqual(facts[0].value, "WRITEF")
            self.assertEqual(calls, [])

    def test_persisted_query_cache_is_reused_and_source_fingerprinted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / "cache" / "queries.json"
            source = {
                "main.c": (
                    "struct Input { int value; };\n"
                    "void target(int value);\n"
                    "int main(int argc, char **argv) {\n"
                    "  struct Input *input = (struct Input *)argv;\n"
                    "  target(input->value); return argc;\n"
                    "}\n"
                )
            }
            calls = []

            async def first_answer(site, index, expression):
                calls.append(expression)
                return OneHopAnswer(kind="EXTERNAL", value=expression)

            configs = {
                "target": {
                    "type": "READF",
                    "indices": [1],
                    "dependent_functions": [],
                }
            }
            first = self.build_resolver(
                root,
                source,
                configs,
                one_hop=first_answer,
                cache_path=cache_path,
            )
            first_records = asyncio.run(first.run())

            async def should_not_run(*args):
                raise AssertionError("persisted query was recomputed")

            second = self.build_resolver(
                root,
                source,
                configs,
                one_hop=should_not_run,
                cache_path=cache_path,
            )
            second_records = asyncio.run(second.run())

            self.assertEqual(calls, ["input->value"])
            self.assertEqual(second_records[0].fact, first_records[0].fact)

    async def _resolve_twice(self, resolver, query):
        return await asyncio.gather(resolver.resolve(query), resolver.resolve(query))

    def test_outputs_have_stable_facts_paths_and_legacy_feed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            resolver = self.build_resolver(
                root,
                {
                    "main.c": "void target(int value); int main(void) { target(9); return 0; }\n"
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                path_cap=1,
            )
            records = asyncio.run(resolver.run())
            output = write_outputs(
                records=records,
                resolver=resolver,
                process_name="process",
                output_root=root / "results",
            )

            with output.facts.open(encoding="utf-8-sig", newline="") as handle:
                facts = list(csv.DictReader(handle))
            with output.paths.open(encoding="utf-8-sig", newline="") as handle:
                paths = list(csv.DictReader(handle))
            with output.legacy.open(encoding="utf-8-sig", newline="") as handle:
                legacy = list(csv.DictReader(handle))
            self.assertEqual(len(facts), 1)
            self.assertEqual(paths[0]["fact_id"], facts[0]["fact_id"])
            self.assertEqual(facts[0]["resolution_status"], "RESOLVED")
            self.assertEqual(facts[0]["value_set_id"], "")
            self.assertEqual(legacy[0]["target_number->ans"], "9")
            self.assertEqual(legacy[0]["target_number->status"], "RESOLVED")
            self.assertEqual(legacy[0]["target_name_src->line_number"], "1")

    def test_provenance_counts_all_value_paths_when_rows_are_capped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "void target(int value);\n"
                        "void inner(int value) { target(value); }\n"
                        "void outer(int value) { inner(value); inner(value); }\n"
                        "int main(void) { outer(5); return 0; }\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                path_cap=1,
            )
            records = asyncio.run(resolver.run())

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].fact.value, "5")
            self.assertEqual(records[0].path_count, 2)
            self.assertEqual(len(records[0].paths), 1)
            self.assertTrue(records[0].paths_truncated)

    def test_deep_provenance_chain_is_stack_safe(self):
        resolver = object.__new__(ValueFlowResolver)
        resolver.path_cap = 1
        resolver.provenance = {
            f"q{index}": {f"q{index + 1}"} for index in range(1500)
        }
        resolver.query_labels = {}
        fact = SimpleNamespace(origin_query="q0")

        paths, count, truncated = resolver._provenance_token_paths(fact, "q1500")

        self.assertEqual(count, 1)
        self.assertFalse(truncated)
        self.assertEqual(len(paths[0]), 1501)
        self.assertEqual(len(resolver.provenance_tokens(fact, "q1500")), 1501)

    def test_dense_provenance_graph_is_counted_without_enumerating_every_path(self):
        iterations = {"count": 0}

        class CountedParents(set):
            def __iter__(self):
                iterations["count"] += 1
                if iterations["count"] > 500:
                    raise AssertionError("provenance paths were enumerated")
                return super().__iter__()

        resolver = object.__new__(ValueFlowResolver)
        resolver.path_cap = 1
        layers = 40
        provenance = {"q0": CountedParents({"a0", "b0"})}
        for index in range(layers - 1):
            parents = CountedParents({f"a{index + 1}", f"b{index + 1}"})
            provenance[f"a{index}"] = parents
            provenance[f"b{index}"] = CountedParents(parents)
        provenance[f"a{layers - 1}"] = CountedParents({"end"})
        provenance[f"b{layers - 1}"] = CountedParents({"end"})
        resolver.provenance = provenance
        resolver.query_labels = {}
        fact = SimpleNamespace(origin_query="q0")

        paths, count, truncated = resolver._provenance_token_paths(fact, "end")

        self.assertEqual(count, 2**layers)
        self.assertTrue(truncated)
        self.assertEqual(len(paths), 1)
        self.assertEqual(resolver.provenance_tokens(fact, "end")[-1], "end")

    def test_legacy_output_emits_each_materialized_value_path_separately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            resolver = self.build_resolver(
                root,
                {
                    "main.c": (
                        "void target(int value);\n"
                        "void inner(int value) { target(value); }\n"
                        "void outer(int value) { inner(value); inner(value); }\n"
                        "int main(void) { outer(5); return 0; }\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
            )
            records = asyncio.run(resolver.run())
            output = write_outputs(
                records=records,
                resolver=resolver,
                process_name="process",
                output_root=root / "results",
            )

            with output.legacy.open(encoding="utf-8-sig", newline="") as handle:
                legacy = list(csv.DictReader(handle))
            self.assertEqual(len(legacy), 2)
            self.assertEqual({row["target_number->ans"] for row in legacy}, {"5"})

    def test_legacy_output_combines_target_arguments_with_underscore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            resolver = self.build_resolver(
                root,
                {
                    "main.c": (
                        "void set_sem(const char *process, int index);\n"
                        "int main(void) { set_sem(\"svm300d\", 0); }\n"
                    )
                },
                {
                    "set_sem": {
                        "type": "SEMAPHORE",
                        "indices": [1, 2],
                        "dependent_functions": [],
                    }
                },
            )
            records = asyncio.run(resolver.run())
            output = write_outputs(
                records=records,
                resolver=resolver,
                process_name="process",
                output_root=root / "results",
            )

            with output.legacy.open(encoding="utf-8-sig", newline="") as handle:
                legacy = list(csv.DictReader(handle))
            self.assertEqual(len(legacy), 1)
            self.assertEqual(legacy[0]["target_number->ans"], "svm300d_0")

    def test_handle_consumer_resolves_once_for_multiple_open_families(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "void open_a(int *handle, int file_no);\n"
                        "void open_b(int *handle, int file_no);\n"
                        "void close_h(int *handle);\n"
                        "int main(void) { int handle; open_a(&handle, 42); close_h(&handle); }\n"
                    )
                },
                {
                    "open_a": {
                        "type": "OPENF",
                        "indices": [2],
                        "dependent_functions": [],
                    },
                    "open_b": {
                        "type": "OPENF",
                        "indices": [2],
                        "dependent_functions": [],
                    },
                    "close_h": {
                        "type": "CLOSEF",
                        "indices": [],
                        "handle_index": 1,
                        "dependent_functions": ["open_a", "open_b"],
                    },
                },
            )
            records = asyncio.run(resolver.run())
            closes = [
                record
                for record in records
                if record.seed.target_function == "close_h"
            ]

            self.assertEqual(len(closes), 1)
            self.assertEqual(closes[0].arg_index, 1)
            self.assertEqual(closes[0].fact.value, "42")

    def test_extended_scada_fixture_matches_handle_ground_truth(self):
        repo = Path(__file__).resolve().parents[1]
        fixture = repo / "test_scada"
        selected = [
            fixture / "src" / "main.c",
            fixture / "src" / "value_flow_cases.c",
            *(fixture / "headers").glob("*.h"),
        ]
        project_structure = {path.name: path for path in selected}
        trees = Preprocess().preprocess(project_structure=project_structure)
        file_functions = {
            name: get_local_function_definitions(code_bytes=source)
            for name, (_, source) in trees.items()
        }
        callback_config = json.loads(
            (fixture / "json_data" / "function_callback_info.json").read_text()
        )
        all_configs = json.loads((fixture / "json_data" / "mpf_data.json").read_text())
        selected_names = {
            "scf_file_open",
            "scf_file_read",
            "scf_file_write",
            "scf_file_close",
            "scf_file_access",
            "scf_evt_register",
        }
        configs = {name: all_configs[name] for name in selected_names}
        builder = CallGraphBuilder(
            project_structure=project_structure,
            trees=trees,
            function_pointer_args=callback_config,
            file_functions=file_functions,
        )
        graph = builder.build()

        async def external(site, index, expression):
            return None

        return_use_calls = []

        async def write_use(site, function):
            return_use_calls.append(site.line)
            return "WRITEF"

        resolver = ValueFlowResolver(
            graph=graph,
            registry=builder.node_registry,
            trees=trees,
            project_structure={
                name: str(path) for name, path in project_structure.items()
            },
            main_file_name="main.c",
            function_configs=configs,
            macros=builder.macros,
            one_hop_resolver=external,
            return_use_resolver=write_use,
        )
        records = asyncio.run(resolver.run())
        case_reads = [
            record
            for record in records
            if record.seed.target_function == "scf_file_read"
            and record.seed.site.file_name == "value_flow_cases.c"
        ]
        values_by_line = {}
        for record in case_reads:
            values_by_line.setdefault(record.seed.site.line, set()).add(
                record.fact.value
            )

        self.assertIn({"0x1003", "0x1004"}, values_by_line.values())
        self.assertIn({"0x1006"}, values_by_line.values())
        self.assertIn({"0x1007"}, values_by_line.values())
        external_records = [
            record
            for record in case_reads
            if record.fact.origin_kind == "EXTERNAL_ENTRY"
        ]
        self.assertEqual(
            {record.fact.value for record in external_records}, {"event_no"}
        )
        access = [
            record
            for record in records
            if record.seed.target_function == "scf_file_access"
        ]
        syntactic = [record for record in access if record.fact.origin_kind == "MACRO"]
        self.assertEqual({record.operation for record in syntactic}, {"WRITEF"})
        self.assertEqual({record.fact.value for record in syntactic}, {"0x1007"})

        llm_required = [
            record
            for record in access
            if record.fact.source_expr == "vf_pick_file()"
        ]
        self.assertTrue(llm_required, "opaque-call case should survive as LLM work")
        self.assertEqual(
            {record.fact.origin_kind for record in llm_required}, {"UNRESOLVED"}
        )
        self.assertEqual({record.fact.value for record in llm_required}, {"UNRESOLVED"})
        self.assertEqual({record.operation for record in llm_required}, {"WRITEF"})

        # Syntax first: the pointer-write site must never reach the LLM, while
        # the discarded return -- which the AST cannot classify -- must.
        self.assertEqual(
            set(return_use_calls),
            {record.seed.site.line for record in llm_required},
        )
        self.assertTrue(
            set(return_use_calls).isdisjoint(
                {record.seed.site.line for record in syntactic}
            )
        )
        self.assertTrue(
            all(record.fact.link_method == "VARTRACE" for record in case_reads)
        )

    def test_argument_injecting_macro_is_remapped_not_read_positionally(self):
        """OPEN_TAG(a,b) -> tag_open_impl(7,a,b) shifts every index by one.

        Reading position 2 of the unexpanded call yields 0; the expanded
        function's position 2 is really the macro's first argument, 0x99.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "api.h": "#define OPEN_TAG(a, b) tag_open_impl(7, a, b)\n",
                    "main.c": (
                        '#include "api.h"\n'
                        "int tag_open_impl(int file_no, int tag, int mode);\n"
                        "int main(void) { OPEN_TAG(0x99, 0); return 0; }\n"
                    ),
                },
                {
                    "tag_open_impl": {
                        "type": "OPENF",
                        "indices": [2],
                        "dependent_functions": [],
                    }
                },
            )
            records = asyncio.run(resolver.run())
            values = {record.fact.value for record in records}
            self.assertIn("0x99", values)
            self.assertNotIn("0", values)

    def test_unmappable_macro_reports_unknown_instead_of_a_wrong_position(self):
        """Token pasting cannot be modelled textually, so refuse to guess."""
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "api.h": "#define PASTE_TAG(a, b) tag_open_impl(7, a ## b, 0)\n",
                    "main.c": (
                        '#include "api.h"\n'
                        "int tag_open_impl(int file_no, int tag, int mode);\n"
                        "int main(void) { PASTE_TAG(0x11, 22); return 0; }\n"
                    ),
                },
                {
                    "tag_open_impl": {
                        "type": "OPENF",
                        "indices": [2],
                        "dependent_functions": [],
                    }
                },
            )
            records = asyncio.run(resolver.run())
            self.assertTrue(records)
            self.assertEqual(
                {record.fact.origin_kind for record in records}, {"UNKNOWN_INDIRECT"}
            )
            # The unexpanded position 2 is "22"; it must not surface as a value.
            self.assertNotIn("22", {record.fact.value for record in records})


if __name__ == "__main__":
    unittest.main()
