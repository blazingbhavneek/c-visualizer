import unittest
from pathlib import Path

from parser.parser_files import parseFiles
from state.state import State


class ParserPathTests(unittest.TestCase):
    def test_terminal_target_function_is_not_parsed_as_a_caller(self):
        main_source = b"int main(void) { return target_api(7); }\n"
        api_source = b"int target_api(int value) { return value; }\n"
        state = State()
        state.reset()
        state.set("MACROS", {})
        state.set("FILE_INCLUDES", {})
        parser = parseFiles(
            project_structure={
                "main.c": str(Path("/fixture/main.c")),
                "api.c": str(Path("/fixture/api.c")),
            },
            paths=[
                [
                    "[main.c]main[1:1]",
                    "[api.c:1]target_api[1:1]",
                ]
            ],
            macro_data={},
            file_name_bytes={"main.c": main_source, "api.c": api_source},
        )

        path, context = parser.parse_for_path(parser.paths[0], get_upper=True)
        state.reset()

        self.assertEqual(path[-1], "[api.c:1]target_api[1:1]")
        self.assertIn("int main", context)
        self.assertIn("target_api(7)", context)


if __name__ == "__main__":
    unittest.main()
