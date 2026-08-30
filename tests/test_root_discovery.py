"""Phase 1 root-discovery tests: deterministic, robust, diagnosed roots."""

import pickle
import tempfile
import unittest
from pathlib import Path

from helpers.Preprocess.preprocess import (
    Preprocess,
    scan_root_candidates,
    validate_root_tree,
)
from makefile_resolver.makefile_resolver import (
    load_project_structure_cache,
    return_project_mapping,
    save_project_structure_cache,
)

from project_aware import ENTRY_FUNCTION_NAMES


def _preprocess(name: str, source: bytes, **kwargs):
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / name
        path.write_bytes(source)
        processor = Preprocess(**kwargs)
        result = processor.preprocess(
            file_path=path,
            expected_entry_names=ENTRY_FUNCTION_NAMES,
        )
        assert result is not None
        tree, cleaned = result
        return tree, cleaned, processor.file_metadata[name]


class RootDiscoveryTests(unittest.TestCase):
    def test_single_main_root(self):
        tree, _, metadata = _preprocess(
            "a.c",
            b"#include <stdio.h>\n\nint main(void)\n{\n    init_proc();\n    return 0;\n}\n",
        )
        validation = validate_root_tree(tree, ENTRY_FUNCTION_NAMES)
        self.assertEqual(validation["found"], ["main"])
        self.assertEqual(metadata["accepted_entry_points"], ["main"])
        self.assertEqual(metadata["root_validation"], "accepted")
        self.assertEqual(metadata["root_variant"], "normal")
        self.assertFalse(metadata["fallback_used"])
        self.assertEqual(metadata["root_failure_reason"], "")

    def test_pmf_main_and_end_in_same_file(self):
        tree, _, metadata = _preprocess(
            "b.c",
            b"int pmf_main_H(void)\n{\n    return 0;\n}\n\nint pmf_end_H(void)\n{\n    return 0;\n}\n",
        )
        self.assertEqual(
            metadata["accepted_entry_points"], ["pmf_end_H", "pmf_main_H"]
        )
        self.assertEqual(metadata["root_validation"], "accepted")

    def test_all_four_pmf_roots_in_one_process(self):
        source = b""
        for name in ("pmf_start_H", "pmf_end_H", "pmf_term_H", "pmf_abort_H"):
            source += (
                f"int {name}(void)\n{{\n    return 0;\n}}\n\n"
            ).encode("latin-1")
        tree, _, metadata = _preprocess("c.c", source)
        validation = validate_root_tree(tree, ENTRY_FUNCTION_NAMES)
        self.assertEqual(
            validation["found"],
            ["pmf_abort_H", "pmf_end_H", "pmf_start_H", "pmf_term_H"],
        )
        self.assertEqual(metadata["root_validation"], "accepted")

    def test_dual_kr_and_ansi_no_proto_source(self):
        tree, cleaned, metadata = _preprocess(
            "dyn730Main.c",
            (
                "#ifdef _NO_PROTO\n"
                "int main(argc, argv)\n"
                "        int argc;\n"
                "        char *argv[];\n"
                "#else\n"
                "int main(int argc, char *argv[])\n"
                "#endif\n"
                "{\n"
                "    dyn730Initialize();\n"
                "}\n"
            ).encode("latin-1"),
        )
        self.assertFalse(tree.root_node.has_error)
        self.assertTrue(metadata["fallback_used"])
        self.assertEqual(metadata["accepted_entry_points"], ["main"])
        self.assertEqual(metadata["root_variant"], "fallback_guarded")
        self.assertIn("-U_NO_PROTO", metadata["unifdef_args"])
        self.assertEqual(
            metadata["variants_tried"], ["normal", "fallback_guarded"]
        )

    def test_split_nop_conditional(self):
        tree, cleaned, metadata = _preprocess(
            "cha100dMain.c",
            (
                "int pmf_main_H(void)\n"
                "{\n"
                "    if (tick)\n"
                "    {\n"
                "#ifdef NOP\n"
                "        if (old)\n"
                "#endif\n"
                "        if (new)\n"
                "        {\n"
                "            cha100Init();\n"
                "        }\n"
                "    }\n"
                "    return 0;\n"
                "}\n"
            ).encode("latin-1"),
        )
        self.assertFalse(tree.root_node.has_error)
        self.assertTrue(metadata["fallback_used"])
        self.assertIn("-UNOP", metadata["unifdef_args"])
        self.assertEqual(metadata["accepted_entry_points"], ["pmf_main_H"])

    def test_explicit_makefile_macro_state_wins(self):
        tree, _, metadata = _preprocess(
            "clean.c",
            (
                "#ifdef PROJECT_MODE\n"
                "int main(void) { return 0; }\n"
                "#else\n"
                "int helper(void) { return 1; }\n"
                "#endif\n"
            ).encode("latin-1"),
            defines=("PROJECT_MODE",),
            undefines=("NOP",),
        )
        self.assertFalse(metadata["fallback_used"])
        self.assertEqual(metadata["unifdef_args"], ["-DPROJECT_MODE", "-UNOP"])
        self.assertEqual(metadata["accepted_entry_points"], ["main"])

    def test_prototype_only_accepted_name_is_not_a_root(self):
        tree, _, metadata = _preprocess(
            "proto.c",
            b"extern int main(void);\n\nint helper(void)\n{\n    return main();\n}\n",
        )
        validation = validate_root_tree(tree, ENTRY_FUNCTION_NAMES)
        self.assertEqual(validation["found"], [])
        self.assertEqual(validation["prototype_only"], ["main"])
        self.assertEqual(metadata["root_validation"], "failed")
        self.assertIn("prototype_only", metadata["root_failure_reason"])
        # A call to an accepted name is a raw candidate, never a root.
        kinds = [item["kind"] for item in metadata["root_candidates"]]
        self.assertIn("call", kinds)
        self.assertNotIn("definition", kinds)

    def test_non_utf8_source_bytes_keep_root_and_call_line(self):
        # SJIS bytes (0x93 0x95 0x8f 0x81 ...) in a comment and string.
        source = (
            b"/* comment \x93\x95\x8f\x81 */\n"
            b"int main(void)\n"
            b"{\n"
            b"    const char *label = \"\x93\x95\x8f\x81\";\n"
            b"    dyn730Initialize(label);\n"
            b"    return 0;\n"
            b"}\n"
        )
        tree, cleaned, metadata = _preprocess("utf8.c", source)
        self.assertFalse(tree.root_node.has_error)
        self.assertEqual(metadata["accepted_entry_points"], ["main"])
        self.assertEqual(metadata["root_validation"], "accepted")
        self.assertIn(b"dyn730Initialize", cleaned)
        # Byte offsets preserved: cleaned keeps the original length layout.
        self.assertEqual(cleaned.count(b"\n"), source.count(b"\n"))

    def test_malformed_candidate_produces_diagnostics_not_false_root(self):
        source = (
            b"int main(void)\n"
            b"(\n"
            b"{\n"
            b"    broken(\n"
            b"}\n"
        )
        tree, _, metadata = _preprocess("bad.c", source)
        self.assertEqual(metadata["root_validation"], "failed")
        self.assertIn("main", metadata["root_failure_reason"])
        candidates = {item["name"] for item in metadata["root_candidates"]}
        self.assertIn("main", candidates)

    def test_raw_scanner_reports_inactive_definition(self):
        source = (
            b"#if 0\n"
            b"int main(void)\n"
            b"{\n"
            b"    return 0;\n"
            b"}\n"
            b"#endif\n"
        )
        candidates = scan_root_candidates(source, ("main",))
        kinds = [item["kind"] for item in candidates]
        self.assertIn("inactive_definition", kinds)


class DuplicateBasenameAndCacheTests(unittest.TestCase):
    def _make_project(self, root: Path) -> Path:
        project = root / "src" / "proc1"
        project.mkdir(parents=True)
        library = root / "src" / "libroot"
        library.mkdir(parents=True)
        (project / "Makefile").write_text(
            "SRCS = main.c\nLIBS = -llibroot.a\n", encoding="latin-1"
        )
        (project / "main.c").write_text(
            "int main(void)\n{\n    proc1Work();\n    return 0;\n}\n",
            encoding="latin-1",
        )
        (project / "work.c").write_text(
            "void proc1Work(void)\n{\n}\n", encoding="latin-1"
        )
        # Library file shares the basename with the executable source.
        (library / "main.c").write_text(
            "int main(void)\n{\n    libMain();\n    return 0;\n}\n",
            encoding="latin-1",
        )
        (library / "libmain.c").write_text(
            "void libMain(void)\n{\n}\n", encoding="latin-1"
        )
        return project

    def test_duplicate_basename_executable_and_library(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._make_project(Path(temp_dir))
            structure, main_files, srcs_paths = return_project_mapping(
                show=False, project_path=project
            )

        executable_key = "main.c"
        self.assertIn(executable_key, structure)
        self.assertEqual(
            Path(structure[executable_key]).resolve(),
            (project / "main.c").resolve(),
        )
        # The library duplicate survives under a qualified key instead of
        # overwriting the executable source.
        qualified = "libroot/main.c"
        self.assertIn(qualified, structure)
        self.assertEqual(
            Path(structure[qualified]).resolve(),
            (project.parent / "libroot" / "main.c").resolve(),
        )
        self.assertEqual(main_files, ["main.c"])
        self.assertEqual(
            [str(Path(p).resolve()) for p in srcs_paths],
            [str((project / "main.c").resolve())],
        )

    def test_stale_cache_without_srcs_paths_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cache.pkl"
            # Current cache round-trips all three members.
            save_project_structure_cache(path, {"main.c": "x"}, ["main.c"], ["/a"])
            loaded = load_project_structure_cache(path)
            self.assertEqual(loaded, ({"main.c": "x"}, ["main.c"], ["/a"]))

            # Old two-tuple cache must be rejected, not read.
            with open(path, "wb") as f:
                pickle.dump(({"main.c": "x"}, ["main.c"]), f)
            self.assertIsNone(load_project_structure_cache(path))

            with open(path, "wb") as f:
                pickle.dump(b"garbage", f)
            self.assertIsNone(load_project_structure_cache(path))


if __name__ == "__main__":
    unittest.main()
