"""Phase 2 callback-resolution tests: direct, alias, and macro-wrapped forms."""

import json
import tempfile
import unittest
from pathlib import Path

from call_graph.call_graph import CallGraphBuilder
from helpers.Preprocess.preprocess import Preprocess
from helpers.extract_functions_from_c import get_local_function_definitions
from value_flow.resolver import ValueFlowResolver

REPO_ROOT = Path(__file__).resolve().parent.parent

PMF_CALLBACKS = {
    "pmf_addevent": {
        "prototype": "int pmf_addevent(int, void (*)(PMF_EVNHEAD *, void *), size_t)",
        "func_argument": [2],
        "total_args": 3,
    }
}


def _build(root: Path, files: dict[str, str], callbacks: dict):
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
        function_pointer_args=callbacks,
        file_functions=file_functions,
    )
    builder.build()
    return builder, project_structure, trees


def _records(builder: CallGraphBuilder, function: str, file: str) -> list[dict]:
    caller_id = f"[{file}]{function}"
    records = []
    for site in builder.graph.get(caller_id, []):
        records.extend(site.callback_records)
    return records


class CallbackExtractionTests(unittest.TestCase):
    def test_1_direct_callback_argument(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder, *_ = _build(
                root,
                {
                    "main.c": (
                        "void handler(void) {}\n"
                        "int main(void) {\n"
                        "    pmf_addevent(EVT, handler, 0);\n"
                        "    return 0;\n"
                        "}\n"
                    ),
                    "handler.c": "void handler(void) { target(); }\n",
                },
                PMF_CALLBACKS,
            )
            records = _records(builder, "main", "main.c")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["spelling"], "handler")
        self.assertEqual(records[0]["canonical"], "handler")
        self.assertEqual(records[0]["diagnostic"], "")
        self.assertIsNotNone(records[0]["node"])

    def test_2_address_of_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder, *_ = _build(
                root,
                {"main.c": "int main(void) { pmf_addevent(EVT, &handler, 0); return 0; }\n"},
                PMF_CALLBACKS,
            )
            records = _records(builder, "main", "main.c")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["canonical"], "handler")
        self.assertEqual(records[0]["raw_text"], "&handler")

    def test_3_casted_and_parenthesized_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder, *_ = _build(
                root,
                {
                    "main.c": (
                        "typedef void (*cb_fn)(void);\n"
                        "int main(void) {\n"
                        "    pmf_addevent(EVT, (cb_fn)handler, 0);\n"
                        "    return 0;\n"
                        "}\n"
                    )
                },
                PMF_CALLBACKS,
            )
            records = _records(builder, "main", "main.c")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["canonical"], "handler")

    def test_4_object_like_macro_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder, *_ = _build(
                root,
                {
                    "main.c": (
                        "#define CHA_HANDLER cha702Event\n"
                        "int main(void) {\n"
                        "    pmf_addevent(EVT, CHA_HANDLER, 0);\n"
                        "    return 0;\n"
                        "}\n"
                    )
                },
                PMF_CALLBACKS,
            )
            records = _records(builder, "main", "main.c")
        self.assertEqual(len(records), 1)
        # Both the source spelling and the canonical target are retained.
        self.assertEqual(records[0]["spelling"], "CHA_HANDLER")
        self.assertEqual(records[0]["canonical"], "cha702Event")
        self.assertEqual(records[0]["diagnostic"], "")

    def test_5_registrar_wrapped_by_macro(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder, *_ = _build(
                root,
                {
                    "main.c": (
                        "#define REGISTER(E, CB, D) pmf_addevent(E, CB, D)\n"
                        "int main(void) {\n"
                        "    REGISTER(EVT, handler, 0);\n"
                        "    return 0;\n"
                        "}\n"
                    )
                },
                PMF_CALLBACKS,
            )
            records = _records(builder, "main", "main.c")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["registrar"], "REGISTER")
        self.assertEqual(records[0]["registrar_expanded"], "pmf_addevent")
        self.assertEqual(records[0]["canonical"], "handler")
        self.assertEqual(records[0]["diagnostic"], "")

    def test_6_macro_reordered_arguments_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder, *_ = _build(
                root,
                {
                    "main.c": (
                        # The callback parameter lands in position 1 after the
                        # wrapper reorders the arguments: not provably safe.
                        "#define REGISTER(E, CB, D) pmf_addevent(CB, D, E)\n"
                        "int main(void) {\n"
                        "    REGISTER(EVT, handler, 0);\n"
                        "    return 0;\n"
                        "}\n"
                    )
                },
                PMF_CALLBACKS,
            )
            records = _records(builder, "main", "main.c")
        # A diagnostic record exists; no canonical edge is invented.
        self.assertEqual(len(records), 1)
        self.assertIn("diagnostic", records[0])
        self.assertNotEqual(records[0]["diagnostic"], "")
        self.assertIsNone(records[0]["node"])

    def test_7_token_paste_macro_stays_unresolved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder, *_ = _build(
                root,
                {
                    "main.c": (
                        "#define HAND(E) ev_##E\n"
                        "int main(void) {\n"
                        "    pmf_addevent(EVT, HAND(x), 0);\n"
                        "    return 0;\n"
                        "}\n"
                    )
                },
                PMF_CALLBACKS,
            )
            records = _records(builder, "main", "main.c")
        self.assertEqual(len(records), 1)
        # The pasted name cannot be proven; a diagnostic is recorded and no
        # canonical edge is invented.
        self.assertTrue(records[0]["diagnostic"])
        self.assertIsNone(records[0]["node"])

    def test_8_duplicate_spelling_yields_one_canonical_edge(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder, project_structure, trees = _build(
                root,
                {
                    "main.c": (
                        "int main(void) {\n"
                        "    pmf_addevent(EVT1, handler, 0);\n"
                        "    pmf_addevent(EVT2, &handler, 1);\n"
                        "    return 0;\n"
                        "}\n"
                    ),
                    "handler.c": "void handler(void) { pmf_mfs_open_H(h, 1234); }\n",
                },
                PMF_CALLBACKS,
            )
            # Two registrations, one canonical edge in the resolver.
            resolver = ValueFlowResolver(
                graph=builder.graph,
                registry=builder.node_registry,
                trees=trees,
                project_structure={
                    key: str(value) for key, value in project_structure.items()
                },
                main_file_name="main.c",
                entry_function_name="main",
                entry_points=[("main.c", "main")],
                function_configs={
                    "pmf_mfs_open_H": {
                        "indices": [2],
                        "type": "int",
                        "opens": [],
                        "launch": "NO DATA",
                    }
                },
                macros=builder.macros,
                file_macros={},
                one_hop_resolver=None,
                return_use_resolver=None,
                handle_llm_resolver=None,
                cache_path=None,
                path_cap=10,
                llm_concurrency=1,
            )
            callback_id = "[handler.c]handler"
            synthetic = [
                edge
                for edge in resolver.reverse_callers[callback_id]
                if edge.synthetic_callback
            ]
        # One canonical edge per registration site -- the old extractor
        # appended the plain identifier twice per site.  Both registrations
        # collapse to the single canonical handler.
        self.assertEqual(len(synthetic), 2)
        self.assertEqual({edge.site_id for edge in synthetic}, {edge.site_id for edge in synthetic})
        self.assertEqual(len({edge.site_id for edge in synthetic}), 2)
        self.assertEqual({edge.call_function for edge in synthetic}, {"handler"})
        for edge in synthetic:
            self.assertIsNotNone(edge.callback_meta)
            self.assertEqual(edge.callback_meta["canonical"], "handler")

    def test_9_registration_in_second_lifecycle_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder, *_ = _build(
                root,
                {
                    "main.c": (
                        "int pmf_main_H(void) { return 0; }\n"
                        "int pmf_end_H(void) {\n"
                        "    pmf_addevent(EVT, handler, 0);\n"
                        "    return 0;\n"
                        "}\n"
                    )
                },
                PMF_CALLBACKS,
            )
            records = _records(builder, "pmf_end_H", "main.c")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["canonical"], "handler")


OPEN_CONFIG = {
    "pmf_mfs_open_H": {
        "prototype": "int pmf_mfs_open_H(HFID *, int, int, int, int)",
        "indices": [2],
        "type": "int",
        "opens": [],
        "launch": "NO DATA",
    }
}


def _resolve(root: Path, files: dict[str, str], callbacks: dict, configs: dict):
    builder, project_structure, trees = _build(root, files, callbacks)
    resolver = ValueFlowResolver(
        graph=builder.graph,
        registry=builder.node_registry,
        trees=trees,
        project_structure={key: str(value) for key, value in project_structure.items()},
        main_file_name="main.c",
        entry_function_name="main",
        entry_points=[("main.c", "main")],
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
    import asyncio

    records = asyncio.run(resolver.run())
    return resolver, records


class CallbackResolutionTests(unittest.TestCase):
    def test_10_callback_path_reaches_target_with_registrar_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            resolver, records = _resolve(
                root,
                {
                    "main.c": (
                        "int main(void) {\n"
                        "    pmf_addevent(EVT, handler, 0);\n"
                        "    return 0;\n"
                        "}\n"
                    ),
                    "handler.c": (
                        "void handler(void)\n"
                        "{\n"
                        "    HFID h;\n"
                        "    pmf_mfs_open_H(&h, 4099, 0, 0, 0);\n"
                        "}\n"
                    ),
                },
                PMF_CALLBACKS,
                OPEN_CONFIG,
            )

        callback_id = "[handler.c]handler"
        self.assertIn(callback_id, resolver.reachable)
        self.assertIn(callback_id, resolver.callback_only)
        self.assertEqual(resolver.reachability_kind(callback_id), "CALLBACK")
        exact = [
            record
            for record in records
            if record.fact.origin_kind in {"CONST", "MACRO"}
        ]
        self.assertTrue(exact, "callback-reached open must resolve a value")
        self.assertGreater(exact[0].path_count, 0)
        self.assertEqual(exact[0].fact.metadata.get("reachability"), "CALLBACK")
        self.assertEqual(exact[0].fact.metadata.get("canonical_function"), "handler")


class CallbackRegistryTests(unittest.TestCase):
    def test_production_registry_contains_corpus_registrars(self):
        registry = json.loads(
            (REPO_ROOT / "json_data" / "function_callback_info.json").read_text(
                encoding="utf-8"
            )
        )
        for name in ("pmf_addevent", "SimAddSemCallback", "MmiAddEvent"):
            self.assertIn(name, registry)
            self.assertIn(2, registry[name]["func_argument"])


if __name__ == "__main__":
    unittest.main()
