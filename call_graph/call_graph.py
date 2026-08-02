import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, List, Optional, Set, Tuple

import clang.cindex
from ollama import Client
from rich import print as rprint
from rich.console import Console
from rich.tree import Tree

from call_graph.ai_fallback import fallbackAi
from call_graph.data_classes import CallSite, CallTreeNode, FunctionNode
from helpers.extract_functions_from_c import get_local_function_definitions
from models import Src  # model to store the file_path and the file_numbers...
from state.state import State

# =====================t=======================================================
# DATA STRUCTURES
# ============================================================================
console = Console()
FILE_NAME_REGEX = r"\[(.*?)\]"
line_number_regex = r"\[\d+:\d+\]$"
GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
ORANGE = "\033[38;5;208m"
RESET = "\033[0m"
# FILE_FUNCTIONS: dict[str,dict[str,any]] = {}


class CallGraphBuilder:
    def __init__(
        self,
        project_structure: Dict[str, str],
        trees: dict[str, tuple],  # filename, tuple[tree,clean code bytes]
        function_pointer_args: dict[str, dict[str, any]] | None = None,
        file_functions: dict[str, dict[str, any]] | None = None,
    ):
        self.project_structure = project_structure
        self.project_key_by_path = {
            str(Path(path).resolve()): key for key, path in project_structure.items()
        }

        self.fp_args_map = function_pointer_args if function_pointer_args else {}

        self.global_funcs: Dict[str, Tuple[str, Any]] = (
            {}
        )  # func_name, (file_path,function_node)
        # self.static_funcs: Dict[str, Dict[str, Any]] = {} # file_path, {func_name,func_node} (THIS IS BECAUSE STATIC FUNCS ARE FILE SPECIFIC.)
        self.static_funcs: Dict[str, Dict[str, Any]] = defaultdict(dict)
        # self.file_trees: Dict[str, Any] = {}
        self.file_trees: dict[str, tuple] = trees
        self.graph: Dict[str, List[FunctionNode]] = defaultdict(list)
        # self.graph: dict[str,list[CallSite]] = {defa}
        self.node_registry: Dict[str, FunctionNode] = {}
        self.macros: Dict[str, tuple[str, str, str]] = (
            {}
        )  # macrofunction_name, (resolved_function, file_path where its expanded (.h), macrofunction's whole string like ab(a,b,c))
        # self.macros_non_func = Dict[str,tuple[str,str]] = {}# macro's name, value, file_name
        self.macro_expansion_to_file: dict[str, str] = (
            {}
        )  # macro func , str abs path of the file in which its defined.
        self.file_functions = file_functions

    def _get_expanded_macro_name(self, macro_name: str) -> Optional[str]:
        if macro_name not in self.macros:
            return None
        visited = set()

        current_name = macro_name
        while current_name in self.macros and current_name not in visited:
            visited.add(current_name)
            replacement = self.macros[current_name][0]
            # Macro replacement text is not always valid standalone C. Parsing
            # it with the native Tree-sitter binding can corrupt its state, so
            # extract the first called identifier directly instead.
            call_match = re.search(r"\b([A-Za-z_]\w*)\s*\(", replacement)
            if call_match:
                return call_match.group(1)

            identifier_match = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*", replacement)
            if identifier_match:
                current_name = identifier_match.group(1)
                continue
            break

        return None

    def _extract_function_name(self, func_def_node) -> Optional[str]:
        declarator = func_def_node.child_by_field_name("declarator")
        if not declarator:
            return None
        curr = declarator
        while curr:
            if curr.type == "identifier":
                return curr.text.decode("latin-1")
            found_child = False
            for child in curr.children:
                if child.type in (
                    "function_declarator",
                    "pointer_declarator",
                    "parenthesized_declarator",
                    "identifier",
                ):
                    curr = child
                    found_child = True
                    break
            if not found_child:
                break
        return None

    def _is_static_function(self, func_def_node) -> bool:
        for child in func_def_node.children:
            if child.type == "storage_class_specifier" and b"static" in child.text:
                return True
        return False

    def _collect_definitions(self):
        for filename, filepath_str in self.project_structure.items():
            filepath = Path(filepath_str)
            if filepath.suffix not in (".c", ".h"):
                continue
            elif not filepath.exists():
                print(f"Error: file path {filepath} not found.")
                continue

            try:
                if not filename in self.file_trees:
                    print("FILE NAME NOT IN FILE TREES..")
                source = self.file_trees[filename][1]
                source_text = source.decode("latin-1", errors="replace")

                # libclang already supplies the exact definition ranges used by
                # the source call walker. Do not create/traverse a second native
                # Tree-sitter tree here: the local custom binding can crash while
                # it is repeatedly initialized for every target API.
                for name, function_info in (self.file_functions or {}).get(
                    filename, {}
                ).items():
                    start_line = function_info.get("start_line", 0)
                    end_line = function_info.get("end_line", start_line)
                    definition = "\n".join(
                        source_text.splitlines()[start_line - 1 : end_line]
                    )
                    declaration = definition.split("{", 1)[0]
                    if re.search(r"\bstatic\b", declaration):
                        self.static_funcs[str(filepath)][name] = function_info
                    else:
                        self.global_funcs[name] = (str(filepath), function_info)

                if filepath.suffix == ".h":
                    macro_pattern = re.compile(
                        r"^\s*#\s*define\s+([A-Za-z_]\w*)(\s*\([^\n]*?\))?([^\n]*(?:\\\\\n[^\n]*)*)",
                        re.MULTILINE,
                    )
                    for match in macro_pattern.finditer(source_text):
                        macro_name, parameters, macro_value = match.groups()
                        macro_signature = macro_name + (parameters or "")
                        self.macros[macro_name] = (
                            macro_value.replace("\\\n", "").strip(),
                            str(filepath),
                            macro_signature,
                        )

            except Exception as e:
                print(f"Warning: Failed to process {filepath}: {e}", file=sys.stderr)

    def _get_or_create_node(
        self,
        name: str,
        caller_file: str,
        is_external: bool = False,
        is_static: bool = False,
    ) -> FunctionNode:
        file_path_str = str(caller_file)
        definition_file_path = file_path_str
        def_file_name = self.project_key_by_path.get(
            str(Path(file_path_str).resolve()), Path(file_path_str).name
        )

        if not is_external:
            if (
                file_path_str in self.static_funcs
                and name in self.static_funcs[file_path_str]
            ):
                is_static = True
                definition_file_path = file_path_str
                def_file_name = self.project_key_by_path.get(
                    str(Path(file_path_str).resolve()), Path(file_path_str).name
                )
            elif name in self.global_funcs:
                is_static = False
                definition_file_path = self.global_funcs[name][0]
                def_file_name = self.project_key_by_path.get(
                    str(Path(definition_file_path).resolve()),
                    Path(definition_file_path).name,
                )
            else:
                is_external = True

        node = FunctionNode(
            name=name,
            file_name=def_file_name,
            file_path=definition_file_path,
            is_external=is_external,
            is_static=is_static,
        )

        # ✅ FIX: Use def_file_name (where the function is DEFINED),
        #         not file_name (where the function is CALLED FROM)
        if (
            def_file_name in self.file_functions
            and name in self.file_functions[def_file_name]
        ):
            node.start_line = self.file_functions[def_file_name][name]["start_line"]
            node.end_line = self.file_functions[def_file_name][name].get(
                "end_line", -1
            )

        if node.unique_id not in self.node_registry:
            self.node_registry[node.unique_id] = node
        else:
            return self.node_registry[node.unique_id]

        return node

    def _resolve_callee(self, callee_name: str, caller_file: str) -> FunctionNode:
        expanded_macro_name = self._get_expanded_macro_name(callee_name)

        if expanded_macro_name:
            macro_def_file = self.macros.get(callee_name, ("", caller_file))[1]
            macro_def_filename = Path(macro_def_file).name
            # if macro_def_file.endswith('.h'):
            #     macro_def_file =

            macro_node = FunctionNode(
                name=callee_name,
                file_path=macro_def_file,
                file_name=macro_def_filename,
                is_external=True,
            )
            file_path_of_macro = self.macro_expansion_to_file.get(
                expanded_macro_name, None
            )

            target_node = self._get_or_create_node(
                expanded_macro_name,
                file_path_of_macro if file_path_of_macro else macro_def_file,
            )
            macro_node.macro_expansion = target_node

            if macro_node.unique_id not in self.node_registry:
                self.node_registry[macro_node.unique_id] = macro_node
            else:
                return self.node_registry[macro_node.unique_id]

            return macro_node

        return self._get_or_create_node(callee_name, caller_file)

    def _extract_arg_function_name(self, arg_node) -> Optional[str]:
        """
        Extract a function-name identifier from a call argument,
        unwrapping casts like (void*)Func, parens like (Func),
        and address-of like &Func.
        """
        if arg_node.type == "identifier":
            return arg_node.text.decode("latin-1")

        # (void*)FuncName  →  cast_expression  →  value is the inner expr
        if arg_node.type == "cast_expression":
            value = arg_node.child_by_field_name("value")
            if value:
                return self._extract_arg_function_name(value)

        # (FuncName)  →  parenthesized_expression
        if arg_node.type == "parenthesized_expression":
            for child in arg_node.children:
                if child.type not in ("(", ")"):
                    return self._extract_arg_function_name(child)

        # &FuncName  →  unary_expression with operator '&'
        if arg_node.type == "unary_expression":
            operand = arg_node.child_by_field_name("argument")
            if operand:
                return self._extract_arg_function_name(operand)

        return None

    def _process_function_body(
        self, func_node, caller_name: str, caller_file: str, is_static: bool
    ):
        caller_node = self._get_or_create_node(
            caller_name, caller_file, is_static=is_static
        )
        body = func_node.child_by_field_name("body")
        if not body:
            return

        stack = [body]
        while stack:
            node = stack.pop()
            if node.type == "call_expression":
                func_node_expr = node.child_by_field_name("function")
                if func_node_expr and func_node_expr.type == "identifier":
                    callee_name = func_node_expr.text.decode("latin-1")
                    callee_node = self._resolve_callee(callee_name, caller_file)
                    line_number = node.start_point.row + 1

                    # ── Create call-site ────────────────────────────────
                    call_site = CallSite(callee=callee_node, line_number=line_number)
                    self.graph[caller_node.unique_id].append(call_site)

                    # ── Function-pointer argument handling ──────────────
                    if callee_name in self.fp_args_map:
                        arg_indices = self.fp_args_map[callee_name].get(
                            "func_argument", []
                        )
                        if arg_indices:
                            args_node = node.child_by_field_name("arguments")
                            if args_node:
                                for idx, arg_child in enumerate(
                                    args_node.children, start=1
                                ):
                                    # if arg_child.text.decode('latin-1')=='Dio800dMdInfo':
                                    #     print('We have encountered the function.')
                                    if idx / 2 in arg_indices:
                                        if arg_child.type == "identifier":
                                            arg_func_name = arg_child.text.decode(
                                                "latin-1"
                                            )
                                            print(
                                                "Argument function name", arg_func_name
                                            )
                                            arg_func_node = self._resolve_callee(
                                                callee_name=arg_func_name,
                                                caller_file=caller_file,
                                            )
                                            # ✅ Attach to THIS call-site only
                                            call_site.callbacks.append(arg_func_node)
                                            # ❌ REMOVED:
                                            # self.graph[callee_node.unique_id].append(...)
                                            # callee_node.callbacks = ...
                                        arg_func_name = self._extract_arg_function_name(
                                            arg_child
                                        )
                                        if arg_func_name:
                                            print(
                                                "Argument function name", arg_func_name
                                            )
                                            arg_func_node = self._resolve_callee(
                                                callee_name=arg_func_name,
                                                caller_file=caller_file,
                                            )
                                            call_site.callbacks.append(arg_func_node)
                else:
                    line = node.start_point.row + 1
                    indirect_node = FunctionNode(
                        name="indirect_call", file_name="", is_external=True
                    )
                    self.graph[caller_node.unique_id].append(
                        CallSite(callee=indirect_node, line_number=line)
                    )

            for child in reversed(node.children):
                stack.append(child)

    @staticmethod
    def _call_arguments(source: str, opening_paren: int) -> str | None:
        """Return the text inside a call's matching parentheses."""
        depth = 0
        quote = None
        escaped = False
        for index in range(opening_paren, len(source)):
            char = source[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in ('"', "'"):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return source[opening_paren + 1 : index]
        return None

    @staticmethod
    def _split_arguments(argument_text: str) -> list[str]:
        """Split C call arguments while preserving nested expressions."""
        arguments, start, depth = [], 0, 0
        quote = None
        escaped = False
        for index, char in enumerate(argument_text):
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in ('"', "'"):
                quote = char
            elif char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif char == "," and depth == 0:
                arguments.append(argument_text[start:index].strip())
                start = index + 1
        arguments.append(argument_text[start:].strip())
        return arguments

    def _process_function_source(
        self,
        source_bytes: bytes,
        caller_name: str,
        caller_file: str,
        is_static: bool,
    ) -> None:
        """Build call sites from a libclang-bounded function source slice.

        The Tree-sitter binding is retained for preprocessing/definition
        collection, but its node walker is avoided here: on some local builds
        it segfaults while traversing a call expression.
        """
        caller_node = self._get_or_create_node(
            caller_name, caller_file, is_static=is_static
        )
        file_name = Path(caller_file).name
        function_info = (self.file_functions or {}).get(file_name, {}).get(caller_name)
        if not function_info:
            return

        start_line = function_info.get("start_line")
        end_line = function_info.get("end_line")
        if not start_line or not end_line:
            return

        lines = source_bytes.decode("latin-1", errors="replace").splitlines(
            keepends=True
        )
        function_source = "".join(lines[start_line - 1 : end_line])
        opening_brace = function_source.find("{")
        if opening_brace == -1:
            return
        body_source = function_source[opening_brace + 1 :]
        body_start_line = start_line + function_source[: opening_brace + 1].count("\n")

        # Preserve line positions while preventing call-like text in strings
        # from being interpreted as a real call.
        searchable_source = re.sub(
            r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
            lambda match: re.sub(r"[^\n]", " ", match.group(0)),
            body_source,
        )
        call_pattern = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
        c_keywords = {"if", "for", "while", "switch", "return", "sizeof"}

        for match in call_pattern.finditer(searchable_source):
            callee_name = match.group(1)
            if callee_name in c_keywords:
                continue
            line_number = body_start_line + body_source[: match.start()].count("\n")
            prefix = searchable_source[max(0, match.start() - 2) : match.start()]
            if prefix in {"->", "."}:
                callee_node = FunctionNode(
                    name="indirect_call", file_name="", is_external=True
                )
            else:
                callee_node = self._resolve_callee(callee_name, caller_file)

            call_site = CallSite(callee=callee_node, line_number=line_number)
            self.graph[caller_node.unique_id].append(call_site)

            callback_config = self.fp_args_map.get(callee_name, {})
            callback_indices = callback_config.get("func_argument", [])
            argument_text = self._call_arguments(body_source, match.end() - 1)
            if not callback_indices or argument_text is None:
                continue
            arguments = self._split_arguments(argument_text)
            for argument_index in callback_indices:
                if argument_index > len(arguments):
                    continue
                argument = arguments[argument_index - 1].strip()
                # The legacy walker intentionally did not follow &callback.
                if argument.startswith("&"):
                    continue
                identifiers = re.findall(r"\b([A-Za-z_]\w*)\b", argument)
                if not identifiers:
                    continue
                callback_name = identifiers[-1]
                if callback_name in {"NULL", "void"}:
                    continue
                # Preserve the legacy duplicate branch for a bare callback.
                callback_count = 2 if re.fullmatch(r"[A-Za-z_]\w*", argument) else 1
                for _ in range(callback_count):
                    call_site.callbacks.append(
                        self._resolve_callee(callback_name, caller_file)
                    )

    def build(self) -> Dict[str, List[CallSite]]:
        console.print("[bold yellow]BUILDING CALL_GRAPH[/bold yellow]")
        console.print(f"[yellow]PHASE 1:[/yellow] COLLECTING FUNCTION DEFINITIONS")
        # print("Phase 1: Collecting function definitions...", file=sys.stderr)
        self._collect_definitions()
        # pprint(self.macros)
        # sys.exit()
        print(
            f"  FOUND {len(self.global_funcs)} GLOBAL, {sum(len(f) for f in self.static_funcs.values())} STATIC",
            file=sys.stderr,
        )

        for macro in self.macros.keys():
            resolved_func = self._get_expanded_macro_name(macro)
            if resolved_func in self.global_funcs.keys():
                self.macro_expansion_to_file[resolved_func] = self.global_funcs[
                    resolved_func
                ][0]

            # if resolved_func == 'RbtMfsGetRecNoLockFunc':
            #     print(macro,self.macro_expansion_to_file[resolved_func])

        # print('Assigning the macro functions their file_names in which they were defined..')

        console.print(f"[yellow]PHASE 2:[/yellow] RESOLVING CALL SITES")
        # print("Phase 2: Resolving call sites...", file=sys.stderr)
        for filename, (tree, source_bytes) in self.file_trees.items():
            filepath = str(self.project_structure[filename])
            if filepath in self.static_funcs:
                for name, node in self.static_funcs[filepath].items():
                    self._process_function_source(source_bytes, name, filepath, True)

            for name, (def_file, node) in self.global_funcs.items():
                if def_file == filepath:
                    self._process_function_source(source_bytes, name, def_file, False)
        console.print(f"[bold green]CALL GRAPH BUILT[/bold green]\n")
        return self.graph

    def get_entry_points(self) -> List[str]:
        return [
            node.unique_id
            for node in self.node_registry.values()
            if node.name == "main"
        ]


def build_call_trees(
    graph: Dict[str, List[CallSite]], registry: Dict[str, FunctionNode]
) -> Dict[str, CallTreeNode]:
    trees: Dict[str, CallTreeNode] = {}

    def _build_recursive(
        func_id: str,
        visited: Set[str],
        line_num: int | None = None,
        callbacks: list[FunctionNode] | None = None,
    ) -> CallTreeNode:

        if func_id not in registry:
            fallback = FunctionNode(name=func_id, file_name="", is_external=True)
            return CallTreeNode(
                fallback, called_line_number=line_num, callbacks=callbacks or []
            )

        if func_id in visited:
            return CallTreeNode(
                registry[func_id],
                called_line_number=line_num,
                callbacks=callbacks or [],
            )

        visited.add(func_id)
        node = CallTreeNode(
            registry[func_id], called_line_number=line_num, callbacks=callbacks or []
        )

        if func_id in graph:
            for call_site in graph[func_id]:
                callee_fn = call_site.callee

                if callee_fn.macro_expansion:
                    macro_tree_node = CallTreeNode(
                        callee_fn,
                        called_line_number=call_site.line_number,
                        callbacks=call_site.callbacks,
                    )
                    target_id = callee_fn.macro_expansion.unique_id
                    target_child = _build_recursive(
                        target_id, visited.copy(), call_site.line_number
                    )
                    macro_tree_node.add_child(target_child)
                    node.add_child(macro_tree_node)
                else:
                    # ── THE FIX: one branch per callback ────────────
                    if call_site.callbacks:
                        for cb in call_site.callbacks:
                            child_node = _build_recursive(
                                callee_fn.unique_id,
                                visited.copy(),
                                call_site.line_number,
                                callbacks=[cb],  # ← single callback
                            )
                            node.add_child(child_node)
                    else:
                        child_node = _build_recursive(
                            callee_fn.unique_id,
                            visited.copy(),
                            call_site.line_number,
                        )
                        node.add_child(child_node)

        # Inject callback subtrees for THIS instance
        if callbacks:
            for cb_func in callbacks:
                cb_child = _build_recursive(cb_func.unique_id, visited.copy(), line_num)
                node.add_child(cb_child)

        return node

    # Include isolated definitions as one-node trees.  They cannot appear below
    # main, but they still belong to the complete source index/unreached shelf.
    for func_id in registry:
        if func_id not in trees:
            trees[func_id] = _build_recursive(func_id, set(), None)

    return trees


def get_fn_name(name: str) -> str:
    return re.sub(FILE_NAME_REGEX, "", name)


def dfs_for_finding_path(
    node: CallTreeNode,
    required_func: str,
    paths: list[list[str | CallTreeNode]],
    curr_path: list[str | CallTreeNode],
    return_whole_tree: bool = False,
) -> None:
    if not node:
        return

    # re.sub(FILE_NAME_REGEX,'',required_func)
    # print('without line number', re.sub(line_number_regex,'',))
    curr_path.append(node.get_display_label if not return_whole_tree else node)

    if node.func_node.name == required_func:
        # curr_path.append(node.get_display_label if not return_whole_tree else node)
        paths.append(curr_path[:])
        # visited_set.add(node)
        curr_path.pop()
        return

    for child in node.children:
        dfs_for_finding_path(
            node=child,
            required_func=required_func,
            paths=paths,
            curr_path=curr_path,
            return_whole_tree=return_whole_tree,
        )
    # visited_set.add(node)
    curr_path.pop()
    return


def find_highest_parent_of_node(
    tree_objects: dict[str, CallTreeNode], function_name: str
):
    def return_parent_key(fn_name: str) -> str | None:
        fn_name = get_fn_name(fn_name)
        for nodes in tree_objects.keys():
            if get_fn_name(nodes) == fn_name:
                continue
            paths = []
            dfs_for_finding_path(
                node=tree_objects[nodes],
                required_func=fn_name,
                paths=paths,
                curr_path=[],
            )
            if len(paths) > 0:
                return nodes
        return None

    highest_parent_keys = []
    function_name = get_fn_name(function_name)
    for nodes in tree_objects.keys():
        if get_fn_name(nodes) == function_name:
            continue
        paths: list[list[str]] = []
        dfs_for_finding_path(
            node=tree_objects[nodes],
            required_func=function_name,
            paths=paths,
            curr_path=[],
        )
        if len(paths) > 0:
            parent = return_parent_key(fn_name=get_fn_name(nodes))
            if parent is None:
                highest_parent_keys.append(nodes)
            else:
                continue

    return highest_parent_keys


def ensure_call_graph(
    project_structure: dict[str, str],
    trees: dict,
    function_pointer_args: dict | None = None,
    file_functions: dict[str, dict[str, Any]] | None = None,
) -> tuple[
    dict[str, list[CallSite]],
    dict[str, FunctionNode],
    dict[str, CallTreeNode],
    dict[str, tuple[str, str, str]],
]:
    """Build/cache the complete graph independently of any target API path."""
    state = State()
    graph = state.get("CALL_GRAPH")
    registry = state.get("FUNCTION_REGISTRY")
    tree_objects = state.get("TREE_OBJECTS")
    macros = state.get("BUILDER_MACROS")
    if graph is not None and registry is not None and tree_objects is not None:
        return graph, registry, tree_objects, macros or {}

    builder = CallGraphBuilder(
        project_structure=project_structure,
        trees=trees,
        function_pointer_args=function_pointer_args,
        file_functions=file_functions,
    )
    graph = builder.build()
    registry = builder.node_registry
    tree_objects = build_call_trees(graph, registry)
    macros = builder.macros
    state.set("CALL_GRAPH", graph)
    state.set("FUNCTION_REGISTRY", registry)
    state.set("TREE_OBJECTS", tree_objects)
    state.set("BUILDER_MACROS", macros)
    return graph, registry, tree_objects, macros


def orchestrate(
    project_strcuture: dict[str, str],
    trees: dict,
    required_func: str,
    main_file_name: str,
    function_pointer_args: dict = None,
    file_functions: dict[str, dict[str, any]] = None,
    return_whole_tree: bool = False,
) -> (
    tuple[
        dict[str, tuple[str, str, str]],
        list[tuple[tuple[list[str], list[CallTreeNode] | None], dict]],
    ]
    | None
):
    paths: list = []

    # for call_grahp determined data.
    BLOCK_REGEX = r"\[([^\[\]]*)\]"
    _, _, tree_objects, macro_data = ensure_call_graph(
        project_structure=project_strcuture,
        trees=trees,
        function_pointer_args=function_pointer_args,
        file_functions=file_functions,
    )
    if not macro_data:
        print("NO MACROS EXTRACTED>>>>....")
    print(len(macro_data))

    paths_with_data: list[tuple[tuple[list[str], list[CallTreeNode] | None], dict]] = []
    main_key = f"[{main_file_name}]main"

    if main_key in tree_objects.keys():
        node = tree_objects[main_key]
        # rprint("\n=== Call Tree for Main ===")
        # console.print(node.to_rich_tree())
        # print("oTHER TREE...")
        # another_node = tree_objects[other_key]
        # console.print(another_node.to_rich_tree())

        paths: list[list[str | CallTreeNode]] = []

        search_target = required_func

        dfs_for_finding_path(
            node=node,
            required_func=search_target,
            paths=paths,
            curr_path=[],
            return_whole_tree=False,
        )
        if return_whole_tree:
            path_trees: list[list[CallTreeNode]] = []
            dfs_for_finding_path(
                node=node,
                required_func=search_target,
                paths=path_trees,
                curr_path=[],
                return_whole_tree=True,
            )

        console.print(paths)
        if len(paths) > 0:
            print("\n=== Paths Found ===")
            # pprint(paths)
            for ind, p in enumerate(paths):
                print(f"Processing the path {ind+1} in call_graph")
                call_graph_determined: dict[str, any] = {}
                call_graph_determined["function_name"] = required_func
                last_index_where_file_present = -1
                for index, node in enumerate(p):
                    first_block = re.match(BLOCK_REGEX, node).group(1)
                    try:
                        line_no = int(first_block)
                    except Exception as e:
                        last_index_where_file_present = index

                    if (
                        index < len(p) - 1
                        and "(macro expansion)" not in node
                        and len(re.findall(BLOCK_REGEX, node)) != 2
                    ):  # means accepts callbacks
                        callback_accepting_function = re.sub(
                            BLOCK_REGEX, "", node
                        ).split(" (accepts callback)-> ")[0]
                        print("CALLBACK ACCEPTING INFO", callback_accepting_function)

                        call_graph_determined["launch_via"] = (
                            State()
                            .get("FUNCTION_TYPES")
                            .get(callback_accepting_function, {})
                            .get("launch", "NO DATA")
                        )
                        print(
                            "LAUNCH VIA OF CALLBACK ACCEPTING FUNCTION",
                            call_graph_determined["launch_via"],
                        )
                        # call_graph_determined['launch_via'] = State().get('FUNCTION_TYPES').get(callback_accepting_function,{}).get('launch','NO DATA')
                        call_graph_determined["call_function"] = (
                            f"{re.sub(BLOCK_REGEX,'',p[index+1])}"  # basically the next function in the graph passed on as an event.
                        )

                        first_block = (
                            re.match(BLOCK_REGEX, p[index + 1]).group(1).split(":")
                        )
                        call_graph_determined["function_name_src"] = Src(
                            path=Path(
                                project_strcuture.get(first_block[0], "no function src")
                            ),
                            line_number=first_block[1] if len(first_block) > 1 else -1,
                        )
                        break
                    elif index == len(p) - 1:
                        call_graph_determined["launch_via"] = "FORK"
                        call_graph_determined["call_function"] = "main"
                        first_block = re.match(BLOCK_REGEX, p[0]).group(1).split(":")
                        call_graph_determined["function_name_src"] = Src(
                            path=Path(project_strcuture.get(first_block[0])),
                            line_number="-1 (Main function)",
                        )

                        last_node_file_path = Path(
                            project_strcuture.get(
                                re.match(BLOCK_REGEX, p[last_index_where_file_present])
                                .group(1)
                                .split(":")[0]
                            )
                        )
                        call_graph_determined["target_name_src"] = Src(
                            path=last_node_file_path,
                            line_number=re.match(BLOCK_REGEX, node).group(1),
                        )

                if "target_name_src" not in call_graph_determined:
                    last_index_where_file_present = -1
                    for ind, node in reversed(list(enumerate(p))):
                        first_block = re.match(BLOCK_REGEX, node).group(1)
                        try:
                            line_no = int(first_block)
                        except Exception as e:
                            last_index_where_file_present = ind
                            break

                    second_last_node_file_path = Path(
                        project_strcuture.get(
                            re.match(
                                BLOCK_REGEX,
                                (
                                    p[last_index_where_file_present]
                                    if last_index_where_file_present != -1
                                    else "[nofile.c]func[a:b]"
                                ),
                            )
                            .group(1)
                            .split(":")[0],
                            "No target_name src file_path",
                        )
                    )
                    call_graph_determined["target_name_src"] = Src(
                        path=second_last_node_file_path,
                        line_number=re.match(BLOCK_REGEX, p[-1]).group(1),
                    )

                paths_with_data.append(
                    (
                        (p, path_trees[ind] if return_whole_tree else None),
                        call_graph_determined,
                    )
                )
            return macro_data, paths_with_data
        else:
            return None
    return None


# ============================================================================
# AI ASSISTANT
# ============================================================================


if __name__ == "__main__":
    import atexit
    import sys
    from datetime import datetime

    class Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, data):
            for s in self.streams:
                s.write(data)

        def flush(self):
            for s in self.streams:
                s.flush()

    logfile = f"{datetime.now():%Y%m%d_%H%M%S}_call_graph.txt"
    log = open(logfile, "w", buffering=1)
    sys.stdout = Tee(sys.__stdout__, log)
    sys.stderr = Tee(sys.__stderr__, log)

    # region INPUTS.
    PROJECT_STRUCTURE = {
        "apl_getmode.c": "/home/seigyo/c_repo/c_repo/src/apl110d/apl_getmode.c",
        "apl_in.h": "/home/seigyo/c_repo/c_repo/src/headers/apl_in.h",
        "main.c": "/home/seigyo/c_repo/c_repo/src/apl110d/main.c",
        "mpf_com.h": "/home/seigyo/c_repo/c_repo/src/headers/mpf_com.h",
        "mpf_mfs.h": "/home/seigyo/c_repo/c_repo/src/headers/mpf_mfs.h",
        "mpf_mfs_err.h": "/home/seigyo/c_repo/c_repo/src/headers/mpf_mfs_err.h",
        "pmf.h": "/home/seigyo/c_repo/c_repo/src/headers/pmf.h",
    }
    # PROJECT_STRUCTURE = {
    # 'apl_in.h': '/home/seigyo/c_repo/c_repo/src/headers/apl_in.h',
    # 'main.c': '/home/seigyo/c_repo/c_repo/src/apl100d/main.c',
    # 'mpf_com.h': '/home/seigyo/c_repo/c_repo/src/headers/mpf_com.h',
    # 'mpf_mfs.h': '/home/seigyo/c_repo/c_repo/src/headers/mpf_mfs.h',
    # 'mpf_mfs_err.h': '/home/seigyo/c_repo/c_repo/src/headers/mpf_mfs_err.h',
    # 'pmf.h': '/home/seigyo/c_repo/c_repo/src/headers/pmf.h'
    # }
    # endregion
    # Build Logical Trees
    function_pointer_path = (
        Path(__file__).parent.parent / "json_data/function_callback_info.json"
    )
    with open(function_pointer_path, "r") as f:
        FUNCTION_POINTER_ARGS = json.load(f)

    # region caching the functions in each c file
    FILE_FUNCTIONS = {}
    for files in PROJECT_STRUCTURE.keys():
        if files.endswith(".h"):
            continue

        file_path = PROJECT_STRUCTURE[files]
        functions = get_local_function_definitions(file_path=file_path)
        FILE_FUNCTIONS[files] = functions

    # pprint(FILE_FUNCTIONS)
    # endregion

    console.print(
        (
            orchestrate(
                project_strcuture=PROJECT_STRUCTURE,
                required_func="pmf_addevent",
                main_file_name="main.c",
                function_pointer_args=FUNCTION_POINTER_ARGS,
                file_functions=FILE_FUNCTIONS,
            )
        )[1]
    )
    # paths = orchestrate(project_strcuture=PROJECT_STRUCTURE,required_func='mpf_mfs_open',)
    # builder = CallGraphBuilder(PROJECT_STRUCTURE, function_pointer_args=FUNCTION_POINTER_ARGS)
    # graph = builder.build()
    # # pprint(graph)
    # tree_objects = build_call_trees(graph, builder.node_registry)
    # print(builder.macros['RbtMfsGetRecNoLock'])
    # # pprint(tree_objects['pmf_addevent'])

    # main_key = '[rbt110dMain.c]main'
    # if main_key in tree_objects.keys():
    #     node = tree_objects[main_key]
    #     rprint("\n=== Call Tree for Main ===")
    #     # rprint(node.to_rich_tree())

    #     paths: list[list[str]] = []
    #     curr_path: list[str] = []

    #     search_target = 'mpf_mfs_open'

    #     dfs_for_finding_path(node=node, required_func=search_target, paths=paths, curr_path=[])
    #     print(paths)
    #     if len(paths) > 0:
    #         print("\n=== Paths Found ===")
    #         for p in paths:
    #             print(" -> ".join(p))
    #     else:
    #         function_map = None
    #         import pickle
    #         try:
    #             with open('pickle_data/function_map.pkl','rb') as f:
    #                 function_map=pickle.load(f)
    #         except FileNotFoundError:
    #             pass

    #         ob = fallbackAi(project_structure=PROJECT_STRUCTURE,tree_objects=tree_objects,target_func=search_target,function_map=function_map)
    #         parent_keys = find_highest_parent_of_node(tree_objects=tree_objects,function_name=search_target)
    #         PATH_STRS=[]
    #         for keys in parent_keys:
    #             paths = []
    #             dfs_for_finding_path(node=tree_objects[keys],required_func=search_target,paths=paths,curr_path=[])
    #             if len(paths)>0:
    #                 path_strs = ['==>>'.join(path) for path in paths]
    #                 PATH_STRS.append(path_strs[0])

    #         string_path = ','.join(PATH_STRS)
    #         print("Path supplied are: ", string_path)
    #         completed_path = ob.complete_path(string_path)
    #         print(completed_path)

    # else:
    #     print("Main function not found.")
