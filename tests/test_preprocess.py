import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers.Preprocess.preprocess import Preprocess, extract_all_macros
from makefile_resolver.extract_includes import (
    extract_includes as extract_makefile_includes,
    resolve as resolve_includes,
)
from makefile_resolver.makefile_resolver import get_project_preprocessor_flags
from project_aware import extract_function_calls


class PreprocessConfigurationTests(unittest.TestCase):
    def _preprocess(self, name: str, source: str, **kwargs):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / name
            path.write_text(source, encoding="latin-1")
            processor = Preprocess(**kwargs)
            result = processor.preprocess(
                file_path=path,
                expected_entry_names=("main", "pmf_main_H"),
            )
            self.assertIsNotNone(result)
            tree, cleaned = result
            return tree, cleaned, processor.file_metadata[name]

    def test_legacy_dual_main_uses_guarded_fallback(self):
        tree, cleaned, metadata = self._preprocess(
            "dyn730Main.c",
            """\
#ifdef _NO_PROTO
int main(argc, argv)
        int argc;
        char *argv[];
#else
int main(int argc, char *argv[])
#endif
{
    dyn730Initialize(argbuf);
}
""",
        )

        self.assertFalse(tree.root_node.has_error)
        self.assertIn(b"int main(int argc, char *argv[])", cleaned)
        self.assertTrue(metadata["fallback_used"])
        self.assertGreater(metadata["initial_error_count"], 0)
        self.assertEqual(metadata["final_error_count"], 0)
        self.assertIn("-U_NO_PROTO", metadata["unifdef_args"])

    def test_split_conditional_if_uses_guarded_fallback(self):
        tree, cleaned, metadata = self._preprocess(
            "cha100dMain.c",
            """\
int pmf_main_H(void)
{
    if (pmf_time.sec % 10 == 0)
    {
#ifdef NOP
        if (exe_time.TimDat != now_time.TimDat)
#endif
        if (ChaForkTm.TimDat != now_time.TimDat)
        {
            cha100Init();
        }
    }
    return 0;
}
""",
        )

        self.assertFalse(tree.root_node.has_error)
        self.assertIn(b"cha100Init", cleaned)
        self.assertTrue(metadata["fallback_used"])
        self.assertIn("-UNOP", metadata["unifdef_args"])

    def test_explicit_makefile_macro_state_is_not_overridden(self):
        tree, _, metadata = self._preprocess(
            "clean.c",
            """\
#ifdef PROJECT_MODE
int main(void) { return 0; }
#else
int helper(void) { return 1; }
#endif
""",
            defines=("PROJECT_MODE",),
            undefines=("NOP",),
        )

        self.assertFalse(tree.root_node.has_error)
        self.assertFalse(metadata["fallback_used"])
        self.assertEqual(metadata["unifdef_args"], ["-DPROJECT_MODE", "-UNOP"])

    def test_header_inactive_macro_branch_is_removed(self):
        tree, cleaned, _ = self._preprocess(
            "defs.h",
            "#if 0\n#define FILE_NO 11\n#else\n#define FILE_NO 15\n#endif\n",
        )

        self.assertFalse(tree.root_node.has_error)
        self.assertNotIn(b"FILE_NO 11", cleaned)
        self.assertIn(b"FILE_NO 15", cleaned)

    def test_makefile_flags_are_extracted_without_linker_flags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "Makefile").write_text(
                "CPPFLAGS = -DPROJECT_MODE -DVALUE=3\n"
                "CFLAGS += -UOLD_STYLE -O2\n"
                "LIBS = -lOLD\n",
                encoding="latin-1",
            )

            flags = get_project_preprocessor_flags(project)

        self.assertEqual(flags["defines"], ("PROJECT_MODE", "VALUE=3"))
        self.assertEqual(flags["undefines"], ("OLD_STYLE",))

    def test_deep_ast_walkers_do_not_use_python_recursion(self):
        depth = 1200
        source = (
            '#include "deep.h"\n'
            "#define DEEP_VALUE 7\n"
            "void target(void);\n"
            "int main(void) {"
            + "{" * depth
            + "/* marker */ target();"
            + "}" * depth
            + "return DEEP_VALUE;}\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "deep.c"
            path.write_text(source, encoding="latin-1")

            self.assertEqual(extract_all_macros(path)["DEEP_VALUE"], "7")
            self.assertIn("#include \"deep.h\"", extract_makefile_includes(path))
            cleaned = Preprocess().remove_comments(source.encode("latin-1"))
            self.assertIn("target", extract_function_calls(cleaned))

    def test_failed_include_preprocess_is_treated_as_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "main.c"
            path.write_text("int main(void) { return 0; }\n", encoding="latin-1")
            with patch(
                "makefile_resolver.extract_includes.extract_includes",
                return_value=None,
            ):
                combined, dependencies = resolve_includes(
                    {"main.c": path}, include_dirs=[]
                )

        self.assertEqual(combined, {"main.c": path})
        self.assertEqual(dependencies, {"main.c": []})


if __name__ == "__main__":
    unittest.main()
