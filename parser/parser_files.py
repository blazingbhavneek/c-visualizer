import multiprocessing
import re
import sys
import textwrap
from functools import partial
from pathlib import Path
from pprint import pprint

from tree_sitter import Language, Parser
from tree_sitter_custom import language

from helpers.time_it import time_it
from state.state import State


class parseFiles:
    def __init__(
        self,
        project_structure: dict[str, str],
        paths: list[list[str]],
        macro_data: dict[str, tuple[str, str, str]],
        file_name_bytes: dict[str, bytes],
    ) -> None:
        self.project_structure = project_structure
        self.paths = paths
        # self.trees = State().get('TREES')
        # self.file_name_bytes = {key:value[1] for key,value in State().get('TREES').items()}
        self.file_name_bytes = file_name_bytes
        self.BLOCKS = r"\[([^\[\]]*)\]"  # to get the file_name..
        self.macros = macro_data
        # self.parser = Parser(Language(language()))

        # self.get_parsed_results()

    def resolve_path(self, file_name: str) -> Path | None:
        if file_name in self.project_structure.keys():
            return Path(self.project_structure[file_name])

        print("The file_name not in project")
        return None

    def _format_code(self, code: str) -> str:
        """Remove excessive blank lines, trailing whitespace, and normalize indentation."""
        lines = code.split("\n")

        # Strip trailing whitespace from each line
        lines = [line.rstrip() for line in lines]

        # Remove leading/trailing blank lines
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

        # Collapse multiple consecutive blank lines into at most one
        formatted = []
        prev_blank = False
        for line in lines:
            is_blank = len(line.strip()) == 0
            if is_blank and prev_blank:
                continue
            formatted.append(line)
            prev_blank = is_blank

        # Dedent (remove common leading whitespace)
        result = textwrap.dedent("\n".join(formatted))
        return result

    def extract_function_parts(
        self, source_code: str | bytes
    ) -> tuple[str, str, str] | None:
        parser = Parser(Language(language()))
        if not isinstance(source_code, bytes):
            # source_code = self.clean_if_else_if_determined(source_code=source_code.encode('utf-8')).encode('utf-8')
            source_code = source_code.encode("latin-1")
            # source_code = source_code.encode('utf-8')
        tree = parser.parse(source_code)
        root = tree.root_node

        def extract(node):
            if node.type == "function_definition":
                body_node = node.child_by_field_name("body")
                header = (
                    source_code[node.start_byte : body_node.start_byte]
                    .decode("latin-1")
                    .strip()
                    + " {"
                )
                body = (
                    source_code[body_node.start_byte + 1 : body_node.end_byte - 1]
                    .decode("latin-1")
                    .strip()
                )
                closing = "}"
                return header, body, closing
            for child in node.children:
                result = extract(child)
                if result:
                    return result
            return None

        result = extract(node=root)
        header = self._format_code(result[0])
        body = self._format_code(result[1])
        # Re-indent body by one level (since it's inside the function)
        body = textwrap.indent(body, "    ")
        return header, body, result[2]

    # region processing the string..
    def process_first_block(self, first_block: str) -> tuple[str, int] | int | str:
        """The format is [file_name:line_number]
        - Possibilities:
        1. [file_name]
        2. [line_numnber]
        3. [file_name:line_number]
        One of them will always be there.."""
        if ":" in first_block:
            # means both are present
            parts = first_block.split(":")
            file_name = parts[0]
            line_number = int(parts[1])
            return (file_name, line_number)
        else:
            # either one is present...
            try:
                int(first_block)
                return int(first_block)
            except Exception as e:
                return first_block

    def process_second_block(self, second_block: str) -> None | tuple[int, int]:
        """
        Only possibilities are:
        - Either no second_block
        - Or [start_line: end_line]
        """
        if not second_block:
            return second_block
        parts = second_block.split(":")
        return (int(parts[0]), int(parts[1]))

    # endregion
    # region read_file trimmed
    def read_files(self, file_path: Path, start_line: int, end_line: int) -> str | None:
        # print("Reading file ", file_path, start_line,end_line)
        # pprint('\n'.join(self.trees[file_path.name][1].decode('latin-1').splitlines()[start_line-1:end_line]))
        # sys.exit()
        return "\n".join(
            self.file_name_bytes[file_path.name]
            .decode("latin-1")
            .splitlines()[start_line - 1 : end_line]
        )

    # endregion
    def process_whole_string(self, node_str: str) -> tuple[any, any, str]:
        """
        Docstring for process_whole_string
        returns the first and second `[]` for that node.
        """
        node_string = node_str
        function_name = re.sub(self.BLOCKS, "", node_string)
        node_string = node_str
        matches = re.finditer(self.BLOCKS, node_string)
        first_block = None
        second_block = None
        for match in matches:
            if not first_block:
                first_block = match.group(1)
            elif not second_block:
                second_block = match.group(1)
        return (first_block, second_block, function_name)

    def clear_comments(self, content: str) -> str:  # clears the commented lines.
        comment_regex = r"(^|\s)(\/\/.*|\/\*[\s\S]*?\*\/)"
        return re.sub(comment_regex, "", content)

    def all_macros_in_file(self, file_name: str):
        STATE = State()
        macros = STATE.get("MACROS")
        file_includes = STATE.get("FILE_INCLUDES")
        constant_macro_regex = (
            r"\(?\b(0x[0-9a-fA-F]+|\d+(\.\d+)?([eE][+-]?\d+)?)[uUlLfF]*\)?"
        )
        # now for this file get the includes and extend the list to all the files' macros...
        macro_dict = {}
        for file in file_includes:
            if file in macros:
                for macro_name in macros[file]:
                    match = re.search(constant_macro_regex, macros[file][macro_name])
                    if match:
                        macro_dict[macro_name] = match.group(1)

        return macro_dict

    def parse_for_path(
        self, path: list[str], get_upper: bool = True
    ) -> tuple[list[str], str]:
        # print('pATHS',path)
        # sys.exit(1)
        intial_context = ""
        all_comments: list[str] = (
            []
        )  # will add comments about macros expansions and callbacks at last.
        all_macro_values: dict[str:str] = {}
        for index, node_str in enumerate(path):
            if any(
                word in node_str for word in ["(macro expansion)", "(accepts callback)"]
            ):
                continue
            first_block, second_block, function_name = self.process_whole_string(
                node_str=node_str
            )

            file_name = line_number_used = None
            first_block_result = self.process_first_block(first_block=first_block)
            if isinstance(first_block_result, tuple):
                file_name = first_block_result[0]

                line_number_used = first_block_result[1]
            elif isinstance(first_block_result, int):
                line_number_used = first_block_result
            else:
                file_name = first_block_result

            start_line = end_line = -1
            second_block_result = self.process_second_block(second_block=second_block)

            if second_block_result and file_name:
                # The terminal node exists only to supply the selected call
                # line for its caller; it contributes no body of its own.
                if index + 1 >= len(path):
                    continue
                start_line = second_block_result[0]
                end_line = second_block_result[1]

                next_node_first_block_result = self.process_first_block(
                    first_block=(self.process_whole_string(node_str=path[index + 1]))[0]
                )

                comment = ""
                if any(
                    word in path[index + 1]
                    for word in ["(macro expansion)", "(accepts callback)"]
                ):
                    # print("MACRO EXPANSION IN NEXT NODE...", path[index+1])
                    next_string = path[index + 1]
                    next_string = re.sub(self.BLOCKS, "", next_string)
                    if "(macro expansion)" in next_string:
                        macro_name = next_string.split(" (macro expansion)-> ")[0]
                        comment = f"//{self.macros[macro_name][2]} -> {self.macros[macro_name][0]}"
                    else:
                        # callback
                        comment = f"//{next_string}"
                    all_comments.append(comment)

                # type_of_next_node = type
                if isinstance(next_node_first_block_result, str):
                    print("There is no line_number in the next node.. Please check.")

                next_node_last_line_used = (
                    next_node_first_block_result[1]
                    if isinstance(next_node_first_block_result, tuple)
                    else next_node_first_block_result
                )  # as it can only be int then.

                # print(start_line,end_line)
                ans = self.extract_function_parts(
                    source_code=self.read_files(
                        file_path=Path(self.project_structure[file_name]),
                        start_line=start_line,
                        end_line=end_line,
                    )
                )
                if ans:
                    header, body, closing = ans
                else:
                    print(
                        "Problem in extracting header,body,closing for this read part."
                    )
                    pprint(
                        self.read_files(
                            file_path=Path(self.project_structure[file_name]),
                            start_line=start_line,
                            end_line=end_line,
                        )
                    )

                if get_upper:
                    function_string = f"{self.read_files(file_path=Path(self.project_structure[file_name]),start_line=start_line,end_line=next_node_last_line_used)}/*CONSIDER THIS CALL*/\n{closing}"
                    included_macros = {
                        name: value
                        for name, value in self.all_macros_in_file(
                            file_name=file_name
                        ).items()
                    }
                    all_macro_values = {**all_macro_values, **included_macros}
                    # if index==0:
                    # pprint(included_macros)
                    # sys.exit()

                else:
                    function_string = f"{header}{self.read_files(file_path=Path(self.project_structure[file_name]),start_line=next_node_last_line_used,end_line=end_line)}"
                    # no need of macros in this case as we only need to analyze the return types in this case.
                intial_context += function_string

        comment = (
            "/*INFO ABOUT MACRO EXPANSIONS AND CALLBACKS.\n"
            if len(all_comments) > 0
            else ""
        )
        comment += "\n".join(all_comments) + "*/" if len(all_comments) > 0 else ""
        filtered_macros = [
            f"//{name}={value}"
            for name, value in all_macro_values.items()
            if name in intial_context
        ]
        comment += "\n".join(filtered_macros) + "\n"
        intial_context = "``` c\n" + comment + intial_context + "\n```"
        return path, self._format_code(code=intial_context)

    @time_it()
    def get_parsed_results(self, get_upper: bool = True) -> list[tuple[list, str]]:
        results: list[tuple[list[str], str]] = []
        with multiprocessing.Pool(
            processes=min(10, multiprocessing.cpu_count())
        ) as pool:
            results = pool.map(
                partial(self.parse_for_path, get_upper=get_upper), self.paths
            )

        return results
        # for path in self.paths:
        #     results.append((path,self.parse_for_path(path=path,get_upper=get_upper)))

        # return results


# [RbtFile.c:132]RbtGetDefine[24:27]
