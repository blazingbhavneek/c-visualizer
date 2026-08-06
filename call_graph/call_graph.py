import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, List, Optional, Set, Tuple

from rich.console import Console
from tree_sitter import Language, Parser
from tree_sitter_custom import language

from call_graph.data_classes import CallSite, CallTreeNode, FunctionNode
from helpers.extract_functions_from_c import get_local_function_definitions
from models import Src
from state.state import State


console = Console()

FILE_NAME_REGEX = r"\[(.*?)\]"


class CallGraphBuilder:
    def __init__(
        self,
        project_structure: Dict[str, str],
        trees: dict[str, tuple],
        function_pointer_args: dict[str, dict[str, Any]] | None = None,
        file_functions: dict[str, dict[str, Any]] | None = None,
    ):
        self.project_structure = project_structure
        self.fp_args_map = function_pointer_args if function_pointer_args else {}

        try:
            self.C_LANGUAGE = Language(language())
        except Exception as e:
            raise RuntimeError(f"Failed to load Tree-sitter C grammar: {e}")

        self.parser = Parser(self.C_LANGUAGE)

        self.global_funcs: Dict[str, Tuple[str, Any]] = {}
        self.static_funcs: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self.file_trees: dict[str, tuple] = trees
        self.graph: Dict[str, List[CallSite]] = defaultdict(list)
        self.node_registry: Dict[str, FunctionNode] = {}

        # macro_name -> expansion, definition file, macro signature
        self.macros: Dict[str, tuple[str, str, str]] = {}

        # resolved function name -> source file where the function is defined
        self.macro_expansion_to_file: dict[str, str] = {}

        self.file_functions = file_functions

    def _get_expanded_macro_name(self, macro_name: str) -> Optional[str]:
        """
        Resolve a macro expansion to a direct function call if possible.
        Follows chained macro aliases and stops on cycles.
        """
        if macro_name not in self.macros:
            return None

        visited = set()
        current_name = macro_name

        while current_name in self.macros and current_name not in visited:
            visited.add(current_name)
            replacement = self.macros[current_name][0]

            try:
                tree = self.parser.parse(replacement.encode("latin-1"))
                root = tree.root_node

                if root.type == "identifier":
                    current_name = root.text.decode("latin-1")
                    continue

                stack = [root]
                while stack:
                    node = stack.pop()

                    if node.type == "call_expression":
                        func = node.child_by_field_name("function")
                        if func and func.type == "identifier":
                            return func.text.decode("latin-1")

                    for child in reversed(node.children):
                        stack.append(child)

                break

            except Exception:
                break

        return None

    def _extract_function_name(self, func_def_node) -> Optional[str]:
        """Extract the identifier from a Tree-sitter function definition node."""
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
        """Return True when a function definition has static storage."""
        for child in func_def_node.children:
            if child.type == "storage_class_specifier" and b"static" in child.text:
                return True

        return False

    def _collect_definitions(self):
        """
        Collect global/static function definitions and header macro definitions.
        Uses pre-parsed Tree-sitter trees from self.file_trees.
        """

        for filename, filepath_str in self.project_structure.items():
            filepath = Path(filepath_str)

            if filepath.suffix not in (".c", ".h"):
                continue

            if not filepath.exists():
                print(f"Error: file path {filepath} not found.")
                continue

            try:
                if filename not in self.file_trees:
                    print("FILE NAME NOT IN FILE TREES..")
                    continue

                tree = self.file_trees[filename][0]
                source = self.file_trees[filename][1]
                stack = [tree.root_node]

                while stack:
                    node = stack.pop()

                    if node.type == "function_definition":
                        name = self._extract_function_name(node)

                        if name:
                            is_static = self._is_static_function(node)

                            if is_static:
                                self.static_funcs[str(filepath)][name] = node
                            else:
                                self.global_funcs[name] = (str(filepath), node)

                    if filepath.suffix == ".h":
                        if node.type in ("preproc_def", "preproc_function_def"):
                            name_node = node.child_by_field_name("name")
                            value_node = node.child_by_field_name("value")

                            if name_node:
                                if node.type == "preproc_function_def":
                                    params_node = node.child_by_field_name("parameters")
                                    start_byte = name_node.start_byte
                                    end_byte = (
                                        params_node.end_byte
                                        if params_node
                                        else name_node.end_byte
                                    )
                                    macro_signature = source[
                                        start_byte:end_byte
                                    ].decode("latin-1")
                                else:
                                    macro_signature = name_node.text.decode("latin-1")

                                macro_value = (
                                    value_node.text.decode("latin-1")
                                    if value_node
                                    else ""
                                )

                                macro_name = name_node.text.decode("latin-1")
                                self.macros[macro_name] = (
                                    macro_value,
                                    str(filepath),
                                    macro_signature,
                                )

                    for child in reversed(node.children):
                        stack.append(child)

            except Exception as e:
                print(f"Warning: Failed to process {filepath}: {e}", file=sys.stderr)


    def _get_or_create_node(
        self,
        name: str,
        caller_file: str,
        is_external: bool = False,
        is_static: bool = False,
    ) -> FunctionNode:
        """
        Resolve function metadata and return a stable FunctionNode instance.
        Static functions are resolved per caller file; globals are resolved project-wide.
        """
        file_path_str = str(caller_file)
        file_name = Path(caller_file).name
        def_file_name = file_name

        if not is_external:
            if (
                file_path_str in self.static_funcs
                and name in self.static_funcs[file_path_str]
            ):
                is_static = True
                def_file_name = file_name
            elif name in self.global_funcs:
                is_static = False
                def_file_name = Path(self.global_funcs[name][0]).name
            else:
                is_external = True

        node = FunctionNode(
            name=name,
            file_name=def_file_name,
            file_path=file_path_str,
            is_external=is_external,
            is_static=is_static,
        )

        if def_file_name.endswith(".c"):
            if (
                self.file_functions
                and def_file_name in self.file_functions
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
        """
        Resolve normal calls and macro-backed calls.
        Macro nodes point to their resolved expansion target when available.
        """
        expanded_macro_name = self._get_expanded_macro_name(callee_name)

        if expanded_macro_name:
            macro_def_file = self.macros.get(callee_name, ("", caller_file))[1]
            macro_def_filename = Path(macro_def_file).name

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
        Extract callback function names from arguments.
        Handles identifiers, casts, parentheses, and address-of expressions.
        """
        if arg_node.type == "identifier":
            return arg_node.text.decode("latin-1")

        if arg_node.type == "cast_expression":
            value = arg_node.child_by_field_name("value")
            if value:
                return self._extract_arg_function_name(value)

        if arg_node.type == "parenthesized_expression":
            for child in arg_node.children:
                if child.type not in ("(", ")"):
                    return self._extract_arg_function_name(child)

        if arg_node.type == "unary_expression":
            operand = arg_node.child_by_field_name("argument")
            if operand:
                return self._extract_arg_function_name(operand)

        return None

    def _process_function_body(
        self,
        func_node,
        caller_name: str,
        caller_file: str,
        is_static: bool,
    ):
        """Walk a function body and record direct, indirect, and callback calls."""
        caller_node = self._get_or_create_node(
            caller_name,
            caller_file,
            is_static=is_static,
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

                    call_site = CallSite(
                        callee=callee_node,
                        line_number=line_number,
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                    )

                    self.graph[caller_node.unique_id].append(call_site)

                    if callee_name in self.fp_args_map:
                        arg_indices = self.fp_args_map[callee_name].get(
                            "func_argument", []
                        )

                        if arg_indices:
                            args_node = node.child_by_field_name("arguments")

                            if args_node:
                                for idx, arg_child in enumerate(
                                    args_node.children,
                                    start=1,
                                ):
                                    if idx / 2 in arg_indices:
                                        if arg_child.type == "identifier":
                                            arg_func_name = arg_child.text.decode(
                                                "latin-1"
                                            )
                                            print(
                                                "Argument function name",
                                                arg_func_name,
                                            )
                                            arg_func_node = self._resolve_callee(
                                                callee_name=arg_func_name,
                                                caller_file=caller_file,
                                            )
                                            call_site.callbacks.append(arg_func_node)

                                        arg_func_name = self._extract_arg_function_name(
                                            arg_child
                                        )

                                        if arg_func_name:
                                            print(
                                                "Argument function name",
                                                arg_func_name,
                                            )
                                            arg_func_node = self._resolve_callee(
                                                callee_name=arg_func_name,
                                                caller_file=caller_file,
                                            )
                                            call_site.callbacks.append(arg_func_node)

                else:
                    line = node.start_point.row + 1
                    indirect_node = FunctionNode(
                        name="indirect_call",
                        file_name="",
                        is_external=True,
                    )
                    self.graph[caller_node.unique_id].append(
                        CallSite(
                            callee=indirect_node,
                            line_number=line,
                            start_byte=node.start_byte,
                            end_byte=node.end_byte,
                        )
                    )

            for child in reversed(node.children):
                stack.append(child)

    def build(self) -> Dict[str, List[CallSite]]:
        """Build and return the call graph."""
        console.print("[bold yellow]BUILDING CALL_GRAPH[/bold yellow]")
        console.print("[yellow]PHASE 1:[/yellow] COLLECTING FUNCTION DEFINITIONS")

        self._collect_definitions()

        print(
            (
                f"  FOUND {len(self.global_funcs)} GLOBAL, "
                f"{sum(len(f) for f in self.static_funcs.values())} STATIC"
            ),
            file=sys.stderr,
        )

        for macro in self.macros.keys():
            resolved_func = self._get_expanded_macro_name(macro)

            if resolved_func in self.global_funcs.keys():
                self.macro_expansion_to_file[resolved_func] = self.global_funcs[
                    resolved_func
                ][0]

        console.print("[yellow]PHASE 2:[/yellow] RESOLVING CALL SITES")

        for filename in self.file_trees:
            filepath = str(self.project_structure[filename])

            if filepath in self.static_funcs:
                for name, node in self.static_funcs[filepath].items():
                    self._process_function_body(node, name, filepath, True)

            for name, (def_file, node) in self.global_funcs.items():
                if def_file == filepath:
                    self._process_function_body(node, name, def_file, False)

        console.print("[bold green]CALL GRAPH BUILT[/bold green]\n")
        return self.graph

    def get_entry_points(self) -> List[str]:
        """Return registered main function nodes."""
        return [
            node.unique_id
            for node in self.node_registry.values()
            if node.name == "main"
        ]


def build_call_trees(
    graph: Dict[str, List[CallSite]],
    registry: Dict[str, FunctionNode],
) -> Dict[str, CallTreeNode]:
    """Convert the flat call graph into recursive call tree objects."""
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
                fallback,
                called_line_number=line_num,
                callbacks=callbacks or [],
            )

        if func_id in visited:
            return CallTreeNode(
                registry[func_id],
                called_line_number=line_num,
                callbacks=callbacks or [],
            )

        visited.add(func_id)

        node = CallTreeNode(
            registry[func_id],
            called_line_number=line_num,
            callbacks=callbacks or [],
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
                        target_id,
                        visited.copy(),
                        call_site.line_number,
                    )

                    macro_tree_node.add_child(target_child)
                    node.add_child(macro_tree_node)

                else:
                    if call_site.callbacks:
                        for cb in call_site.callbacks:
                            child_node = _build_recursive(
                                callee_fn.unique_id,
                                visited.copy(),
                                call_site.line_number,
                                callbacks=[cb],
                            )
                            node.add_child(child_node)
                    else:
                        child_node = _build_recursive(
                            callee_fn.unique_id,
                            visited.copy(),
                            call_site.line_number,
                        )
                        node.add_child(child_node)

        if callbacks:
            for cb_func in callbacks:
                cb_child = _build_recursive(
                    cb_func.unique_id,
                    visited.copy(),
                    line_num,
                )
                node.add_child(cb_child)

        return node

    for func_id in graph:
        if func_id not in trees:
            trees[func_id] = _build_recursive(func_id, set(), None)

    return trees


def get_fn_name(name: str) -> str:
    """Remove the leading file block from a display label."""
    return re.sub(FILE_NAME_REGEX, "", name)


def dfs_for_finding_path(
    node: CallTreeNode,
    required_func: str,
    paths: list[list[str | CallTreeNode]],
    curr_path: list[str | CallTreeNode],
    return_whole_tree: bool = False,
) -> None:
    """Collect all paths from a tree node to the required function."""
    if not node:
        return

    curr_path.append(node.get_display_label if not return_whole_tree else node)

    if node.func_node.name == required_func:
        paths.append(curr_path[:])
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

    curr_path.pop()


def find_highest_parent_of_node(
    tree_objects: dict[str, CallTreeNode],
    function_name: str,
):
    """Find top-level tree roots that eventually reach the given function."""
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

    return highest_parent_keys


def orchestrate(
    project_strcuture: dict[str, str],
    trees: dict,
    required_func: str,
    main_file_name: str,
    function_pointer_args: dict = None,
    file_functions: dict[str, dict[str, Any]] = None,
    return_whole_tree: bool = False,
) -> (
    tuple[
        dict[str, tuple[str, str, str]],
        list[tuple[tuple[list[str], list[CallTreeNode] | None], dict]],
    ]
    | None
):
    """
    Build or reuse call trees, search paths from main to required_func,
    and attach source metadata for downstream consumers.
    """
    BLOCK_REGEX = r"\[([^\[\]]*)\]"

    tree_objects = State().get("TREE_OBJECTS", None)
    macro_data = State().get("BUILDER_MACROS", None)

    if tree_objects is None:
        builder = CallGraphBuilder(
            project_structure=project_strcuture,
            trees=trees,
            function_pointer_args=function_pointer_args,
            file_functions=file_functions,
        )

        graph = builder.build()
        tree_objects = build_call_trees(graph, builder.node_registry)

        State().set("TREE_OBJECTS", tree_objects)

        if not builder.macros:
            print("NO MACROS EXTRACTED>>>>....")

        State().set("BUILDER_MACROS", builder.macros)
        macro_data = builder.macros

        print(len(builder.macros))

    paths_with_data: list[tuple[tuple[list[str], list[CallTreeNode] | None], dict]] = []
    main_key = f"[{main_file_name}]main"

    if main_key in tree_objects.keys():
        node = tree_objects[main_key]
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

        if len(paths) > 0:
            print("\n=== Paths Found ===")

            for ind, p in enumerate(paths):
                print(f"Processing the path {ind + 1} in call_graph")

                call_graph_determined: dict[str, Any] = {}
                call_graph_determined["function_name"] = required_func

                last_index_where_file_present = -1

                for index, node in enumerate(p):
                    first_block = re.match(BLOCK_REGEX, node).group(1)

                    try:
                        int(first_block)
                    except Exception:
                        last_index_where_file_present = index

                    if (
                        index < len(p) - 1
                        and "(macro expansion)" not in node
                        and len(re.findall(BLOCK_REGEX, node)) != 2
                    ):
                        callback_accepting_function = re.sub(
                            BLOCK_REGEX,
                            "",
                            node,
                        ).split(" (accepts callback)-> ")[0]

                        print(
                            "CALLBACK ACCEPTING INFO",
                            callback_accepting_function,
                        )

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

                        call_graph_determined["call_function"] = (
                            f"{re.sub(BLOCK_REGEX, '', p[index + 1])}"
                        )

                        first_block = (
                            re.match(BLOCK_REGEX, p[index + 1]).group(1).split(":")
                        )

                        call_graph_determined["function_name_src"] = Src(
                            path=Path(
                                project_strcuture.get(
                                    first_block[0],
                                    "no function src",
                                )
                            ),
                            line_number=first_block[1]
                            if len(first_block) > 1
                            else -1,
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
                                re.match(
                                    BLOCK_REGEX,
                                    p[last_index_where_file_present],
                                )
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
                            int(first_block)
                        except Exception:
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

        return None

    return None


if __name__ == "__main__":
    DEBUG = True

    from datetime import datetime

    class Tee:
        """Write stdout/stderr to both terminal and a log file."""
        def __init__(self, *streams):
            self.streams = streams

        def write(self, data):
            for stream in self.streams:
                stream.write(data)

        def flush(self):
            for stream in self.streams:
                stream.flush()

    logfile = f"{datetime.now():%Y%m%d_%H%M%S}_call_graph.txt"
    log = open(logfile, "w", buffering=1)

    sys.stdout = Tee(sys.__stdout__, log)
    sys.stderr = Tee(sys.__stderr__, log)

    PROJECT_STRUCTURE = {
        "apl_getmode.c": Path(
            "/home/seigyo/c_repo/c_repo/src/src_analysis/src/libapl/apl_getmode.c"
        ),
        "apl_in.h": Path(
            "/home/seigyo/c_repo/c_repo/src/src_analysis/include/apl_in.h"
        ),
        "main.c": Path(
            "/home/seigyo/c_repo/c_repo/src/src_analysis/src/apl110d/main.c"
        ),
        "mpf_com.h": Path(
            "/home/seigyo/c_repo/c_repo/src/moove_header/mpf_com.h"
        ),
        "mpf_mfs.h": Path(
            "/home/seigyo/c_repo/c_repo/src/moove_header/mpf_mfs.h"
        ),
        "mpf_mfs_err.h": Path(
            "/home/seigyo/c_repo/c_repo/src/moove_header/mpf_mfs_err.h"
        ),
        "pmf.h": Path(
            "/home/seigyo/c_repo/c_repo/src/moove_header/pmf.h"
        ),
    }

    from helpers.Preprocess.preprocess import Preprocess

    trees = Preprocess().preprocess(project_structure=PROJECT_STRUCTURE)

    function_pointer_path = (
        Path(__file__).parent.parent / "json_data/function_callback_info.json"
    )

    with open(function_pointer_path, "r") as f:
        FUNCTION_POINTER_ARGS = json.load(f)

    FILE_FUNCTIONS = {}

    for file_name, file_path in PROJECT_STRUCTURE.items():
        if file_name.endswith(".h"):
            continue

        with open(file_path, "rb") as f:
            code_bytes = f.read()

        functions = get_local_function_definitions(
            code_bytes=code_bytes,
            file_name=file_name,
        )

        FILE_FUNCTIONS[file_name] = functions

    console.print(
        (
            orchestrate(
                project_strcuture=PROJECT_STRUCTURE,
                required_func="pmf_addevent",
                main_file_name="main.c",
                function_pointer_args=FUNCTION_POINTER_ARGS,
                file_functions=FILE_FUNCTIONS,
                trees=trees,
            )
        )[1]
    )
