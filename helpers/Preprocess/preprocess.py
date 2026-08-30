import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Dict

import tree_sitter_custom as tsc
from tree_sitter import Language, Parser, Tree

from state.state import State


def _macro_name(value: str) -> str:
    """Return a macro name from ``NAME``, ``-DNAME`` or ``-UNAME``."""
    value = str(value).strip()
    if value.startswith(("-D", "-U")):
        value = value[2:]
    return value.split("=", 1)[0].strip()


def _macro_definition(value: str) -> str:
    """Return ``NAME`` or ``NAME=value`` without a leading ``-D``."""
    value = str(value).strip()
    return value[2:] if value.startswith("-D") else value


@dataclass(frozen=True)
class PreprocessorConfig:
    """The macro state used to clean one process's C sources.

    ``unifdef`` deliberately leaves unknown conditionals in place.  That is
    useful for source inspection, but it can leave mutually exclusive legacy
    declarations in the input tree.  The compatibility undefines are only
    tried after a first parse reports errors; they never override a macro
    explicitly supplied by the Makefile.
    """

    defines: tuple[str, ...] = ()
    undefines: tuple[str, ...] = ()
    fallback_undefines: tuple[str, ...] = ("_NO_PROTO", "NOP")

    @classmethod
    def from_flags(
        cls,
        defines: Iterable[str] = (),
        undefines: Iterable[str] = (),
        fallback_undefines: Iterable[str] = ("_NO_PROTO", "NOP"),
    ) -> "PreprocessorConfig":
        return cls(
            defines=tuple(
                dict.fromkeys(
                    _macro_definition(item)
                    for item in defines
                    if str(item).strip()
                )
            ),
            undefines=tuple(
                dict.fromkeys(
                    _macro_name(item)
                    for item in undefines
                    if str(item).strip()
                )
            ),
            fallback_undefines=tuple(
                dict.fromkeys(
                    _macro_name(item)
                    for item in fallback_undefines
                    if str(item).strip()
                )
            ),
        )

    def unifdef_args(self, *, fallback: bool = False) -> list[str]:
        args = [f"-D{name}" for name in self.defines]
        args.extend(f"-U{name}" for name in self.undefines)
        if fallback:
            defined = {_macro_name(name) for name in self.defines}
            explicitly_undefined = {_macro_name(name) for name in self.undefines}
            args.extend(
                f"-U{name}"
                for name in self.fallback_undefines
                if name not in defined and name not in explicitly_undefined
            )
        return list(dict.fromkeys(args))


# ---------------------------------------------------------------------------
# Raw root-candidate scanner (diagnostics, not authority).
#
# The scanner inspects source bytes for accepted entry-name patterns and
# reports what a parser could not recover.  It can trigger another
# preprocessing attempt and explain a failure, but a raw pattern match never
# becomes a reachable graph root by itself: a parsed function definition with
# a body remains mandatory for normal reachability.
# ---------------------------------------------------------------------------


def scan_root_candidates(source: bytes, names: Iterable[str]) -> list[dict[str, object]]:
    """Report accepted-name patterns found in raw source bytes.

    Returns a deterministic list of records with keys ``name``, ``kind``
    (``definition``, ``prototype``, ``call``, or ``inactive_definition``),
    and ``line``.  A definition is active or inactive depending on the
    enclosing preprocessor branch state (``#if 0``, ``#ifdef`` without a
    matching define state are treated as inactive-unknown only for the
    simplest ``#if 0`` case; all other branches are reported active with
    their conditional depth so callers can correlate with the macro state).
    """
    candidates: list[dict[str, object]] = []
    name_patterns = {
        raw_name.strip(): re.compile(
            rb"(?<![A-Za-z0-9_])"
            + re.escape(raw_name.strip().encode("latin-1"))
            + rb"\s*\(([^)]*)\)\s*([;{]?)"
        )
        for raw_name in names
        if raw_name.strip()
    }

    for raw_name, pattern in name_patterns.items():
        name = raw_name.strip()

        lines = source.splitlines(keepends=True)
        active = True
        branch_stack: list[tuple[bool, bool]] = []

        for line_number, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith(b"#"):
                directive = stripped[1:].split(maxsplit=1)[0].decode(
                    "latin-1", errors="replace"
                )
                if directive in ("if", "ifdef"):
                    branch_stack.append((active, active))
                    if directive == "if":
                        # ``#if 0`` starts a provably inactive region; other
                        # conditions stay as observed (unifdef keeps them).
                        tail = stripped[1:].decode("latin-1", errors="replace")
                        active = active and not bool(re.match(r"if\s+0\b", tail))
                elif directive == "else":
                    if branch_stack:
                        parent_active, _branch = branch_stack[-1]
                        active = parent_active
                elif directive == "endif":
                    if branch_stack:
                        parent_active, _branch = branch_stack.pop()
                        active = parent_active
                elif directive == "elif":
                    active = False
                continue

            # Skip preprocessor continuation of non-branch directives is not
            # needed for root patterns; match the name as a whole word.
            for match in pattern.finditer(line):
                # Look ahead for an opening brace within the next few lines
                # to distinguish definitions from prototypes/calls.
                terminator = match.group(2)
                kind: str
                if terminator == b"{":
                    kind = "definition"
                elif terminator == b";":
                    kind = (
                        "call"
                        if _call_context(line[: match.start()])
                        else "prototype"
                    )
                else:
                    kind = _classify_definition_or_call(lines, line_number - 1, match.end())

                if not active and kind in ("definition",):
                    kind = "inactive_definition"

                candidates.append(
                    {"name": name, "kind": kind, "line": line_number}
                )

    candidates.sort(key=lambda item: (item["name"], item["line"]))
    return candidates


def _call_context(prefix: bytes) -> bool:
    """True when a ``name();`` match sits in an expression, not a declaration."""
    for hint in (b"return ", b"=", b"(", b",", b"?", b":", b"&&", b"||"):
        if hint in prefix:
            return True
    return False


def _classify_definition_or_call(lines: list[bytes], start_index: int, offset: int) -> str:
    """Peek ahead: a brace before any statement terminator means definition.

    K&R definitions declare parameter types on the following lines before the
    brace; ANSI definitions may place the brace on a later line.  A ``;`` or
    a new statement-ending token before the brace means call/prototype.
    """
    scan_from = offset
    current = lines[start_index]
    window = current[scan_from:]
    for index in range(start_index + 1, min(start_index + 8, len(lines))):
        window += lines[index]
        if b"}" in window:
            return "call" if _statement_ended(window) else "definition"
    if b"{" in window:
        return "definition"
    return "call" if _statement_ended(window) else "prototype"


def _statement_ended(window: bytes) -> bool:
    """Return True when a statement terminator appears before any brace."""
    brace = window.find(b"{")
    semi = window.find(b";")
    return semi != -1 and (brace == -1 or semi < brace)


def validate_root_tree(tree: Tree, names: Iterable[str]) -> dict[str, object]:
    """Score parsed accepted-root definitions in one tree.

    A definition counts only when it has a function body (a prototype or a
    declaration does not qualify).  Returns ``found`` (names with a usable
    definition), ``prototype_only`` (names seen only as declarations),
    and ``missing`` (expected names with no parsed definition or prototype).
    """
    expected = [name.strip() for name in names if name.strip()]
    if not expected:
        return {"found": [], "prototype_only": [], "missing": []}

    definitions: set[str] = set()
    prototypes: set[str] = set()
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            body = node.child_by_field_name("body")
            name = _declarator_identifier(declarator)
            if name in expected and body is not None:
                definitions.add(name)
        elif node.type in ("declaration", "function_declarator"):
            # K&R: the declarator holds the name; a bare declaration of a
            # function is a prototype, not a root.
            declarator = node.child_by_field_name("declarator")
            name = _declarator_identifier(declarator)
            if node.type == "declaration" and name in expected:
                prototypes.add(name)
        stack.extend(node.children)

    found = sorted(definitions)
    prototype_only = sorted(prototypes - definitions)
    missing = sorted(set(expected) - definitions - prototypes)
    return {
        "found": found,
        "prototype_only": prototype_only,
        "missing": missing,
    }


def _declarator_identifier(node) -> str | None:
    if node is None:
        return None
    if node.type == "identifier":
        return node.text.decode("latin-1")
    for child in node.children:
        if child.type in (
            "function_declarator",
            "pointer_declarator",
            "parenthesized_declarator",
            "identifier",
        ):
            name = _declarator_identifier(child)
            if name:
                return name
    return None


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
    def __init__(
        self,
        *,
        defines: Iterable[str] = (),
        undefines: Iterable[str] = (),
        fallback_undefines: Iterable[str] = ("_NO_PROTO", "NOP"),
    ):
        self.language = Language(tsc.language())
        self.parser = Parser(self.language)
        self.config = PreprocessorConfig.from_flags(
            defines=defines,
            undefines=undefines,
            fallback_undefines=fallback_undefines,
        )
        self.file_metadata: dict[str, dict[str, object]] = {}

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

    def _run_unifdef(self, code: bytes, *, fallback: bool = False) -> bytes:
        """
        Clean inactive/preprocessor conditional blocks with unifdef.
        Keeps line structure stable where possible.
        """
        command = [
            "unifdef",
            "-t",
            "-k",
            "-b",
            *self.config.unifdef_args(fallback=fallback),
        ]

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

    @staticmethod
    def _tree_health(tree: Tree) -> tuple[bool, int]:
        """Return ``(has_error, error_node_count)`` for a parsed tree."""
        errors = 0
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type == "ERROR" or bool(getattr(node, "is_missing", False)):
                errors += 1
            stack.extend(node.children)
        return bool(getattr(tree.root_node, "has_error", False)), errors

    @staticmethod
    def _function_definition_names(tree: Tree) -> set[str]:
        """Extract definition names without invoking a second parser."""

        def name_from_declarator(node) -> str | None:
            if node.type == "identifier":
                return node.text.decode("latin-1", errors="replace")
            for child in node.children:
                if child.type in {
                    "function_declarator",
                    "pointer_declarator",
                    "parenthesized_declarator",
                    "identifier",
                }:
                    name = name_from_declarator(child)
                    if name:
                        return name
            return None

        names: set[str] = set()
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type == "function_definition":
                declarator = node.child_by_field_name("declarator")
                if declarator is not None:
                    name = name_from_declarator(declarator)
                    if name:
                        names.add(name)
            stack.extend(node.children)
        return names

    def _clean_file_content(
        self,
        path: Path,
        *,
        expected_entry_names: Iterable[str] = (),
    ) -> tuple[Tree, bytes, dict[str, object]] | None:
        """Apply the correct cleanup path for .h and .c files."""
        content = path.read_bytes()

        if path.suffix == ".h":
            cleaned = self.remove_comments(content)
            tree = self.parser.parse(cleaned)
            has_error, error_count = self._tree_health(tree)
            return tree, cleaned, {
                "fallback_used": False,
                "initial_has_error": has_error,
                "final_has_error": has_error,
                "initial_error_count": error_count,
                "final_error_count": error_count,
                "unifdef_args": [],
            }

        if path.suffix == ".c":
            content_no_comments = self.remove_comments(content)
            initial_content = self._run_unifdef(content_no_comments)
            initial_tree = self.parser.parse(initial_content)
            initial_has_error, initial_errors = self._tree_health(initial_tree)

            expected = [name for name in expected_entry_names if name.strip()]

            # Candidate 1: the actual Makefile macro state.
            variants: list[tuple[str, bytes, Tree, bool, int]] = [
                ("normal", initial_content, initial_tree, initial_has_error, initial_errors)
            ]

            # A potential entry source needs a guarded-compatibility attempt
            # whenever the expected root is missing or malformed in the
            # initial tree, even when the tree reports no parse error: a file
            # can parse cleanly while the root definition or its body was
            # lost (duplicate prototype under an inactive legacy branch).
            initial_validation = (
                validate_root_tree(initial_tree, expected) if expected else None
            )
            raw_candidates = (
                scan_root_candidates(content, expected) if expected else []
            )
            raw_recovered = {
                item["name"]
                for item in raw_candidates
                if item["kind"] in ("definition", "inactive_definition")
            }
            tree_missing_raw_root = bool(
                expected
                and initial_validation is not None
                and (raw_recovered - set(initial_validation["found"]))
            )
            needs_variant = bool(
                initial_has_error
                or (initial_validation is not None and not initial_validation["found"])
                or tree_missing_raw_root
            )

            if needs_variant:
                fallback_content = self._run_unifdef(
                    content_no_comments, fallback=True
                )
                fallback_tree = self.parser.parse(fallback_content)
                fallback_has_error, fallback_errors = self._tree_health(fallback_tree)
                variants.append(
                    (
                        "fallback_guarded",
                        fallback_content,
                        fallback_tree,
                        fallback_has_error,
                        fallback_errors,
                    )
                )

            def _selection_key(variant):
                _, _, tree, has_error, errors = variant
                validation = validate_root_tree(tree, expected) if expected else None
                score = len(validation["found"]) if validation else 0
                return (-score, 1 if has_error else 0, errors, variant[0])

            variants.sort(key=_selection_key)
            variant_name, selected_content, selected_tree, selected_has_error, selected_errors = variants[0]
            trial_order = ["normal"] + (["fallback_guarded"] if needs_variant else [])

            final_has_error, final_errors = self._tree_health(selected_tree)
            final_validation = (
                validate_root_tree(selected_tree, expected) if expected else None
            )

            if expected and final_validation is not None and not final_validation["found"]:
                unrecovered = raw_recovered - set(final_validation["found"]) - set(
                    final_validation["prototype_only"]
                )
                if unrecovered:
                    root_failure_reason = "raw_accepted_definition_not_recovered:" + ",".join(
                        f"{name}@{next(item['line'] for item in raw_candidates if item['name'] == name and item['kind'] in ('definition', 'inactive_definition'))}"
                        for name in sorted(unrecovered)
                    )
                elif final_validation["prototype_only"]:
                    root_failure_reason = (
                        "accepted_name_is_prototype_only:"
                        + ",".join(final_validation["prototype_only"])
                    )
                else:
                    root_failure_reason = "no_accepted_root_definition"
            else:
                root_failure_reason = ""

            metadata = {
                "fallback_used": variant_name != "normal",
                "initial_has_error": initial_has_error,
                "final_has_error": final_has_error,
                "initial_error_count": initial_errors,
                "final_error_count": final_errors,
                "unifdef_args": self.config.unifdef_args(fallback=variant_name != "normal"),
                "root_candidates": raw_candidates,
                "accepted_entry_points": (
                    list(final_validation["found"]) if final_validation else []
                ),
                "root_variant": variant_name,
                "root_validation": (
                    "accepted" if final_validation and final_validation["found"] else "failed"
                ) if expected else "not_an_entry_source",
                "root_failure_reason": root_failure_reason if expected else "",
                "variants_tried": trial_order,
            }
            return selected_tree, selected_content, metadata

        return None

    def preprocess(
        self,
        project_structure: Dict[str, Path] | None = None,
        file_path: Path | None = None,
        expected_entry_names: Iterable[str]
        | Mapping[str, Iterable[str]] = (),
    ) -> Dict[str, tuple[Tree, bytes]] | tuple[Tree, bytes] | None:
        """
        Clean and parse either one file or all files in project_structure.
        Returns Tree-sitter trees with their cleaned source bytes.
        """
        if file_path:
            file_path = Path(file_path)

            if not file_path.exists():
                return None

            cleaned = self._clean_file_content(
                file_path,
                expected_entry_names=(
                    expected_entry_names.get(file_path.name, ())
                    if isinstance(expected_entry_names, Mapping)
                    else expected_entry_names
                ),
            )

            if cleaned is None:
                return None

            tree, clean_content, metadata = cleaned
            self.file_metadata[file_path.name] = metadata
            return tree, clean_content

        if project_structure is None:
            return None

        processed_trees: Dict[str, tuple[Tree, bytes]] = {}

        for filename, path in project_structure.items():
            path = Path(path)

            if not path.exists():
                continue

            cleaned = self._clean_file_content(
                path,
                expected_entry_names=(
                    expected_entry_names.get(filename, ())
                    if isinstance(expected_entry_names, Mapping)
                    else expected_entry_names
                ),
            )

            if cleaned is None:
                continue

            tree, clean_content, metadata = cleaned
            processed_trees[filename] = (tree, clean_content)
            self.file_metadata[filename] = metadata

        return processed_trees
