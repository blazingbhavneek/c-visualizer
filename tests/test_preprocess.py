import tempfile
import unittest
from pathlib import Path

from helpers.Preprocess.preprocess import Preprocess
from makefile_resolver.makefile_resolver import get_project_preprocessor_flags


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


if __name__ == "__main__":
    unittest.main()
