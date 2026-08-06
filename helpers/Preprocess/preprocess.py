import subprocess
from pathlib import Path
from typing import Dict

import tree_sitter_custom as tsc
from tree_sitter import Language, Parser, Tree

from state.state import State


def extract_all_macros(filepath: str | Path) -> dict[str, str]:
    """Extract object-like and function-like macros from a C/header file."""
    filepath = Path(filepath)

    with open(filepath, "rb") as f:
        source_code = f.read()

    parser = Parser(Language(tsc.language()))
    tree = parser.parse(source_code)

    results: dict[str, str] = {}

    def walk_tree(node):
        if node.type in {"preproc_def", "preproc_function_def"}:
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")

            if name_node and value_node:
                name = source_code[
                    name_node.start_byte : name_node.end_byte
                ].decode("latin-1")

                value = source_code[
                    value_node.start_byte : value_node.end_byte
                ].decode("latin-1")

                # Normalize multiline macro values.
                results[name] = (
                    value.replace("\\\n", "")
                    .replace("\\\r\n", "")
                    .strip()
                )

        for child in node.children:
            walk_tree(child)

    walk_tree(tree.root_node)
    return results


def extract_includes(filepath: str | Path) -> list[str]:
    """Extract raw include targets like stdio.h or local_header.h."""
    filepath = Path(filepath)

    STATE = State()
    trees = STATE.get("TREES") or {}

    if filepath.name not in trees:
        return []

    tree = trees[filepath.name][0]
    source_code = trees[filepath.name][1]

    include_paths: list[str] = []

    def walk(node):
        if node.type == "preproc_include":
            path_node = node.child_by_field_name("path")

            if path_node:
                raw_path = source_code[
                    path_node.start_byte : path_node.end_byte
                ].decode("latin-1")

                include_paths.append(raw_path.strip('<">'))

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return include_paths


class Preprocess:
    def __init__(self):
        self.language = Language(tsc.language())
        self.parser = Parser(self.language)

    def remove_comments(self, code: bytes) -> bytes:
        """Replace comments with spaces while preserving byte offsets/newlines."""
        tree = self.parser.parse(code)
        comment_ranges: list[tuple[int, int]] = []

        def collect_comments(node):
            if node.type == "comment":
                comment_ranges.append((node.start_byte, node.end_byte))

            for child in node.children:
                collect_comments(child)

        collect_comments(tree.root_node)

        if not comment_ranges:
            return code

        comment_ranges.sort(key=lambda item: item[0])

        result = bytearray()
        pos = 0

        for start, end in comment_ranges:
            result.extend(code[pos:start])

            for byte in code[start:end]:
                if byte == ord("\n"):
                    result.append(byte)
                else:
                    result.append(ord(" "))

            pos = end

        result.extend(code[pos:])
        return bytes(result)

    def _run_unifdef(self, code: bytes) -> bytes:
        """
        Clean inactive/preprocessor conditional blocks with unifdef.
        Keeps line structure stable where possible.
        """
        command = ["unifdef", "-t", "-k", "-b"]

        try:
            process = subprocess.run(
                command,
                input=code,
                capture_output=True,
                check=False,
            )

            # unifdef: 0 = no changes, 1 = changes made, 2 = error.
            if process.returncode == 2:
                print(
                    "Warning: unifdef encountered an error: "
                    f"{process.stderr.decode(errors='ignore')}"
                )
                return code

            return process.stdout

        except FileNotFoundError:
            print("Error: 'unifdef' command not found. Please install it.")
            return code

    def _clean_file_content(self, path: Path) -> bytes | None:
        """Apply the correct cleanup path for .h and .c files."""
        content = path.read_bytes()

        if path.suffix == ".h":
            return self.remove_comments(content)

        if path.suffix == ".c":
            content_no_comments = self.remove_comments(content)
            return self._run_unifdef(content_no_comments)

        return None

    def preprocess(
        self,
        project_structure: Dict[str, Path] | None = None,
        file_path: Path | None = None,
    ) -> Dict[str, tuple[Tree, bytes]] | tuple[Tree, bytes] | None:
        """
        Clean and parse either one file or all files in project_structure.
        Returns Tree-sitter trees with their cleaned source bytes.
        """
        if file_path:
            file_path = Path(file_path)

            if not file_path.exists():
                return None

            clean_content = self._clean_file_content(file_path)

            if clean_content is None:
                return None

            tree = self.parser.parse(clean_content)
            return tree, clean_content

        if project_structure is None:
            return None

        processed_trees: Dict[str, tuple[Tree, bytes]] = {}

        for filename, path in project_structure.items():
            path = Path(path)

            if not path.exists():
                continue

            clean_content = self._clean_file_content(path)

            if clean_content is None:
                continue

            tree = self.parser.parse(clean_content)
            processed_trees[filename] = (tree, clean_content)

        return processed_trees
