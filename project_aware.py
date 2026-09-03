# region Imports

import asyncio
import gc
import hashlib
import json
import multiprocessing
import os
import pickle
import re
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from parser.parser_files import parseFiles
from pathlib import Path
from pprint import pprint
from typing import Literal


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from ./.env into os.environ (no override).

    Minimal stdlib-only loader: the project has no python-dotenv dependency.
    Existing environment variables always win, so an explicit shell export
    like TRACER_VF_NO_FORK=0 still beats the .env file.  Comments (#), blank
    lines, an optional leading "export ", and single/double quotes are
    handled.  The file is optional; a missing .env is not an error.
    """
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

import clang.cindex
import ollama
import pandas as pd
from pick import pick
from pydantic import BaseModel

# for highlighting the context which is c code..
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import CLexer

# from rich import print as rprint
from rich.console import Console
from rich.markup import escape
from rich.syntax import Syntax
from rich.tree import Tree
from tqdm import tqdm
from tree_sitter import Language, Parser
from tree_sitter_custom import language

from call_graph.call_graph import orchestrate
from call_graph.data_classes import CallTreeNode, custom_tree
from call_graph.gen_graph import make_graph
from client.llm import (
    OllamaClient,
    TRACER_DEFAULT_BASE_URL,
    TRACER_DEFAULT_MODEL,
)
from helpers.dict_to_csv import (
    save_dict_csv,
)  # will save the generated dictionary (containing the model's output..)
from helpers.extract_functions_from_c import (
    get_local_function_definitions,
)  # (to get function_names from c_files.ss)
from helpers.Preprocess.preprocess import (
    Preprocess,
    extract_all_macros,
    extract_includes,
)
from helpers.time_it import time_it
from function_summaries import SummaryConfig, summarize_collector
from makefile_resolver.makefile_resolver import (
    get_project_preprocessor_flags,
    load_project_structure_cache,
    return_project_mapping,
    save_project_structure_cache,
)
from models import (
    Combined,
    FunctionTokenCount,
    Stats,
    TokenCount,
    aiDetermined,
    outputModel,
    outputModelForReturn,
    TransferAnswerModel,
)
from output_paths import process_results_dir, results_root, target_results_dir
from discovery_index import (
    build_target_site_inventory,
    legacy_answers_to_facts,
    rel_to_source_root,
    resolve_source_root,
    valueflow_records_to_facts,
    write_discovery_index,
)
from aggregate_index import build_aggregate_index
from process_groups import (
    discover_processes,
    load_project_state,
    process_output_names,
    validate_group_name,
    validate_processes,
    write_group_manifest,
)
from state.load_data import load_files
from state.state import State
from tools.tools import (
    set_tool_def,
)  # will set the tools and their definition in the state.
from visualizer_export import (
    VisualizerCollector,
    build_complete_call_graph,
    build_complete_file_functions,
)
from value_flow.outputs import write_outputs, write_trace_logs
from value_flow.resolver import IndexedSite, ValueFlowResolver
from value_flow.transfers import TransferRequest
from typing import Any

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# endregion Imports


# These are externally-invoked process lifecycle callbacks.  They have no
# necessarily visible caller in application source, so each locally defined
# one is a reachability root.  Keep ``main`` and ``pmf_main_H`` first for
# primary-entry compatibility in legacy output.
ENTRY_FUNCTION_NAMES = (
    "main",
    "pmf_main_H",
    "pmf_start_H",
    "pmf_end_H",
    "pmf_term_H",
    "pmf_abort_H",
)


# region Global vars

# set_tool_def()


# STATE = load_files()

comment_regex = r"(^|\s)(\/\/.*|\/\*[\s\S]*?\*\/)"
PROJECT_STRUCTURE = {}

# FUNCTION_POINTER_ARGS =
# logger = logging.getLogger(__name__)
console = Console()

GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
ORANGE = "\033[38;5;208m"  # 38;5;208m is an 8-bit color code for orange
RESET = "\033[0m"

# endregion Global vars

# region HELPERS (Identifying funs to trace and printing trees, dfs.)


## lists function calls only in given code, checks recursively
def extract_function_calls(code: bytes, tree=None) -> list[str]:
    """
    RETURNS A LIST OF FUNCTION CALLED IN THIS CODE.
    """
    if tree is None:
        # Compatibility path for callers that only have source bytes.  The
        # main trace path passes the already-parsed Tree-sitter tree below.
        import tree_sitter_custom as tsc
        from tree_sitter import Language, Parser

        lang = Language(tsc.language())
        parser = Parser(lang)
        tree = parser.parse(code)

    calls: list[str] = []

    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                name = code[func_node.start_byte : func_node.end_byte].decode(
                    "latin-1", errors="replace"
                )
                calls.append(name)
        stack.extend(reversed(node.children))
    return calls

# Scans project source files to identify calls to configured functions from STATE["FUNCTION_TYPES"].
# For each detected function, returns the argument indices and related tracing metadata.
# Header files are skipped since only actual function calls in source files are considered.
def identify_funs_to_trace(
    project_structure: dict[str, str],
    trees: dict,
    name_of_json: str = "json_data/mpf_data.json",
) -> dict[str, dict[str, Any]] | None:
    """
    Identify configured functions that are called in project source files.

    Function trace config is read from State()["FUNCTION_TYPES"].
    Header files are skipped because only source-file calls are scanned.
    """
    state = State()

    functions_to_detect = {
        function_name.strip(): {
            **config,
            "dependent_functions": [
                dependent_function.strip()
                for dependent_function in config.get("dependent_functions", [])
            ],
        }
        for function_name, config in (state.get("FUNCTION_TYPES") or {}).items()
    }

    state.set("FUNCTION_TYPES", functions_to_detect)

    functions_to_trace = {}

    source_files = [
        (file_name, trees[file_name][0], trees[file_name][1])
        for file_name in project_structure
        if not file_name.endswith(".h") and file_name in trees
    ]

    def scan_file(item):
        file_name, tree, source = item
        return file_name, extract_function_calls(source, tree)

    # These scans are independent because each worker only reads one
    # pre-parsed tree.  map() preserves source-file order for deterministic
    # output while keeping the pool deliberately small.
    calls_by_file = {}
    if source_files:
        with ThreadPoolExecutor(
            max_workers=min(8, len(source_files)),
            thread_name_prefix="target-call-scan",
        ) as executor:
            calls_by_file.update(executor.map(scan_file, source_files))

    if not functions_to_detect:
        print("Data 'FUNCTION_TYPES' Not in state.")

    for file_name, _tree, _source in source_files:
        functions_called = calls_by_file[file_name]

        for function_name in functions_to_detect:
            if function_name in functions_called:
                list_of_indices = [
                    index
                    for index in functions_to_detect[function_name].get("indices")
                ]

                get_upper = functions_to_detect[function_name].get("get_upper")

                functions_to_trace[function_name] = {
                    "indices": list_of_indices,
                    "get_upper": get_upper,
                    "dependent_functions": functions_to_detect[function_name].get(
                        "dependent_functions"
                    ),
                }

    return functions_to_trace

# doing dfs on tree to find the path of  dependent_function starting from main, returns bool, and changes str_path inplace for results, curr_path is temp for dfs ops
def dfs_on_path_trees(
    tree_node: custom_tree,
    dependent_function: str,
    str_path: list[str],
    curr_path: list[str],
) -> bool:
    if not tree_node:
        return False

    curr_path.append(tree_node.name)

    found = False

    if tree_node.get_name == dependent_function:
        str_path.clear()
        str_path.extend(curr_path)
        found = True

    for child in tree_node.children:
        if dfs_on_path_trees(child, dependent_function, str_path, curr_path):
            found = True

    curr_path.pop()
    return found

# make a simple call tree with just names, nothing else
def make_tree_custom(node: CallTreeNode) -> custom_tree:
    t = custom_tree(name=node.get_display_label)
    for children in node.children:
        t.add(make_tree_custom(node=children))
    return t

# Builds a tree representation from either a string path or indexed CallTreeNode path.
# For CallTreeNode paths, it converts nodes to custom_tree and extracts the path to dependent_function.
# For string paths, it creates a Rich Tree mainly for display/printing.
def make_tree(
    path: list[str] | tuple[int, list[CallTreeNode]],
    dependent_function: str | None = None,
) -> Tree | custom_tree | tuple[list, int]:
    tree = None
    last_tree = None
    if isinstance(path, tuple):
        index, path_list = path
        for node in path_list:

            # we need to traverse...
            if tree is None:
                tree = make_tree_custom(node=node)
                last_tree = tree
            else:
                child = make_tree_custom(node=node)
                last_tree.add(child)
                last_tree = child
        print(f"PROCESSED TREE FOR PATH NUM_{index+1}")
        # return tree,index
        result_path: list[str] = []
        dfs_on_path_trees(
            tree_node=tree,
            dependent_function=dependent_function,
            str_path=result_path,
            curr_path=[],
        )
        return result_path, index
    else:
        for node in path:
            if isinstance(node, str):
                if tree is None:
                    tree = Tree(escape(node))
                    last_tree = tree
                else:
                    child = Tree(escape(node))
                    last_tree.add(child)
                    last_tree = child

        # console.print(tree)
        return tree

# Prints or processes possible call paths as tree structures.
# If paths contain CallTreeNode objects, it uses multiprocessing to extract dependent-function paths.
# If paths contain strings, it builds and prints Rich Trees for visualization.
@time_it()
def print_or_return_possible_paths_trees(
    paths: list[list[str | CallTreeNode]],
    dependent_function: str | None = None,
    result_path_list: list[list[str]] | None = None,
) -> None | custom_tree:
    # will print rich trees made from the found paths...
    # console.print(paths)
    from functools import partial

    if isinstance(paths[0][0], CallTreeNode):
        with multiprocessing.Pool(
            processes=min(10, multiprocessing.cpu_count())
        ) as pool:
            print("Using multiprocessing for processing paths")
            result_iter = pool.imap(
                partial(make_tree, dependent_function=dependent_function),
                enumerate(paths),
                chunksize=2,
            )
            for result_list, index in result_iter:
                result_path_list.append(result_list)
                # if index%100==0:
                #     gc.collect()
        return None
        # for i,path in enumerate(paths,start = 1):
        #     tree,index = make_tree((i,path))
        #     dependent_path: list[str] = []
        #     dfs_on_path_trees(tree_node=tree,dependent_function=dependent_function,str_path=dependent_path,curr_path=[])
        #     result_path_list.append(dependent_path)
        # return None
    for i, path in enumerate(paths, start=1):
        console.print(f"[bold red]PATH_{i}[/bold red]")
        # console.print(make_tree(path = path))
        console.print(make_tree(path=path))


# endregion

# Builds LLM prompts for static C-code backward tracing.
# Depending on get_upper, it either resolves target function argument values
# or classifies how the target function's return value is used.
# --- AGENT LOGIC ---
def llm_calls(
    project_structure: dict[str, str],
    function_name_to_traced,
    argument_numbers: list[int],
    intial_context: str,
    path: str,
    get_upper: bool = True,
) -> tuple[type[BaseModel], dict[str, any]]:
    STATE = State()
    messages_with_path_without_return = [
        {
            "role": "system",
            "content": """
            You are a **Static Backward Tracer** — a virtual compiler agent whose sole job is to determine the concrete runtime values of specific arguments passed to a target function, by tracing data flow backward through a provided call chain.

            ---

            ## CORE OPERATING PRINCIPLE

            You think like a c-compiler executing in **reverse**: you start at the **target function call-site**, identify which variables feed into the requested argument positions, and chase each variable's value backward through assignments, parameters, and callers — until you hit a **concrete literal value** or exhaust all resolution avenues (in which case you report `UNRESOLVED`).

            ---

            ## STEP-BY-STEP PROCEDURE

            ### Phase 1 — Orient

            1. Read the **CALL_GRAPH** (an ordered sequence of functions from `main()` → … → `target_function`).  
            2. Read the **INITIAL_CONTEXT** (trimmed source bodies of those functions).  
            3. Read any **MACRO INFO** block (expansions / callbacks / constants listed in comments at the top of the context).   
            4. Note which **argument indices** (1-based) of the target function you must resolve.

            ### Phase 2 — Locate the CORRECT Call-Site at EVERY Edge (CRITICAL)

            > **THIS PHASE IS THE MOST COMMON SOURCE OF ERRORS. FOLLOW PRECISELY.**
            > **This applies at EVERY hop in the CALL_GRAPH, not just the final one.**

            Given a CALL_GRAPH: `F1 → F2 → F3 → … → Fn (target)`

            At **each edge** `Fi → Fi+1`, function `Fi`'s body may contain **multiple calls**
            to `Fi+1`. You MUST select the correct call-site at **every such edge** using
            these rules in priority order:

            **RULE A (HIGHEST PRIORITY):**  
            Scan `Fi`'s **ENTIRE** body, from first line to last line, for calls to `Fi+1`
            that bear the annotation:  
            /*CONSIDER THIS CALL*/
            If **ANY** call to `Fi+1` inside `Fi` has this annotation, **select THAT call**
            and **IGNORE every other call** to `Fi+1` within `Fi`. No exceptions.

            > **Example — annotations at MULTIPLE edges:**
            > ```c
            > // CALL_GRAPH: main → DioGetPtr → mpf_mfs_open
            >
            > int main() {
            >     DioDbknr = (SdbDbknr *)DioGetPtr( SDB_FILENO_DBKNR, 0 );
            >     DioDcdef = (SdbDcdef *)DioGetPtr( SDB_FILENO_DCDEF, 0 );
            >     DioHealth = (Health  *)DioGetPtr( FNO_HEALTH, 0 ); /*CONSIDER THIS CALL*/
            > }
            >
            > void *DioGetPtr( int filenum, int sbnum ) {
            >     ret = mpf_mfs_open( &fcb, NULL, filenum, sbnum, 0, MPF_MFS_READLOCK ); /*CONSIDER THIS CALL*/
            > }
            > ```
            >
            > **Edge `main → DioGetPtr`:**  
            >  Select `DioGetPtr( FNO_HEALTH, 0 )` — has annotation.  
            >  NOT `DioGetPtr( SDB_FILENO_DBKNR, 0 )` — first call, not annotated.
            >
            > **Edge `DioGetPtr → mpf_mfs_open`:**  
            >  Select `mpf_mfs_open( &fcb, NULL, filenum, sbnum, 0, MPF_MFS_READLOCK )` — has annotation.
            >
            > Now tracing argument 3 of `mpf_mfs_open`:
            > → `filenum` (arg 3) is a parameter of `DioGetPtr` at index 1
            > → Jump to caller `main`, at the selected call-site: `DioGetPtr( FNO_HEALTH, 0 )`
            > → Arg 1 = `FNO_HEALTH` → macro → resolve via `find_definition` if not in the comments (But finding a value is not guranteed).


            ### Phase 3 — Backward Trace (the core loop)

            For **each** argument index you must resolve, do the following starting at the target call-site:
            current_value ← the expression at that argument position in the call
            current_function ← the caller

            **Repeat:**

            a. **Literal / constant?**  
            → `current_value` is a numeric literal, string literal, enum literal, `NULL`, `true`/`false`, etc.  
            → **Stop. Record this concrete value. Do NOT trace further up.**

            b. **Variable?**  
            → Search **backward** (above the call-site, within `current_function`) for the **last assignment** to this variable before the call.  
            - If found and assigned a **literal** → Stop, record it.  
            - If found and assigned the **return value of a function not in context** → use `find_definition` (see Tool Use below) to inspect that function, then resolve.  
            - If found and assigned **another variable or expression** → set `current_value` to that expression and continue the loop in the same function.  
            - If **not found** (the variable is a **parameter** of `current_function`) → identify which parameter index it is, then jump to the **caller of `current_function`** (next function up the CALL_GRAPH). At the call-site in that caller, pick the expression at the corresponding argument position. Set `current_value` to that expression, set `current_function` to that caller, and continue.

            c. **Macro / preprocessor symbol?**  
            → Check the **MACRO INFO** section first.  
            → If not there, call `find_definition` for the macro name.  
            → Replace with the resolved literal and stop, or mark `UNRESOLVED`.

            d. **Function call / complex expression?**  
            → If the function is in context, trace into it to find the return value.  
            → If not, use `find_definition` to get its definition and inspect.

            e. **Modified by an intervening function call** (e.g., passed by pointer/reference to a function between assignment and use)?  
            → If that modifying function is in context, trace the modification.  
            → If not, use `find_definition` **once** to retrieve it, then trace.

            ### Phase 4 — Macro-Expanded Call Chains

            If the MACRO INFO section states:
            func_a(a,b,c,d) (macro expansion)-> func_b(FILE,a,b,c,d) 
            macro_name = constant value (If any)

            then when the CALL_GRAPH passes through `func_a` → `func_b`, understand that:
            - `func_b`'s 1st argument is `FILE` (injected by the macro).
            - `func_b`'s 2nd argument corresponds to `func_a`'s 1st argument, and so on (shifted by the number of injected args).

            Adjust your argument-index mapping accordingly when crossing this boundary.

            ### Phase 5 — Resolve `call_number`

            After (or during) your trace, scan the **entire provided context only** for any invocation of:
            - `pmf_addevent(...)`, or  
            - `pmd_addvarevt(...)`

            If **either** is present anywhere in the context:
            - Resolve the **1st argument**(Usually a macro or constant use find_definition for resolving) (1-based) of that function call using the exact same backward-tracing procedure above.
            - Report that resolved value as `call_number`.

            If **neither** function appears anywhere in the context:
            - Report `call_number` as `None`.

            ### Phase 6 — Report

            Produce a final structured answer containing:
            - For each requested argument index: the **concrete resolved value** (literal), or `UNRESOLVED`.
            - `call_number`: the resolved 1st-argument value of `pmf_addevent`/`pmd_addvarevt`, or `None`.

            ---

            ## EARLY TERMINATION RULE

            You are **guaranteed** by the call graph that the path from `main()` to the target function is valid. You do **not** need to verify reachability. Therefore:
            - **Stop tracing upward the moment you resolve a value to a concrete literal.**  
            - Do **not** trace all the way to `main()` unless the data dependency genuinely flows that far without being assigned a constant anywhere along the chain.
            - Don't report all the arguments of a given function only those that are asked.


            ---

            ## IMPORTANT CONSTRAINTS (DO's and DON'Ts)

            | # | Rule |
            |---|------|
            | 1 | **All argument indices are 1-based.** `func(a, b, c)` → index 1 = `a`, index 2 = `b`, index 3 = `c`. |
            | 2 | **Never report a macro name or variable name as a final value.** You must resolve to a literal or say `UNRESOLVED`. |
            | 3 | **One `find_definition` call per symbol.** No retries. |
            | 4 | **Follow the CALL_GRAPH path exactly.** Ignore other callers or other paths not in the specified sequence. |
            | 5 | **For multiple calls to the same function within one body**, use the one marked `/*CONSIDER THIS CALL*/`, or the **last** occurrence if unmarked. |
            | 6 | **Macro expansions** that inject/reorder arguments must be accounted for when mapping argument indices across the expansion boundary. |
            | 7 | **Do not guess or hallucinate values.** If resolution is impossible with available information, report `UNRESOLVED`. |
            | 8 | **Show your tracing work** step-by-step (function by function, assignment by assignment) before giving the final answer so the reasoning is auditable. |

            ---

            ### OUTPUT FORMAT
            Report only the final resolved value for each requested ARG_INDEX and the call_number.
            """,
        },
        {
            "role": "user",
            "content": """Backward trace argument numbers **{argument_numbers}**  of function **{function_name_to_traced}** and the call_number if present or else None.
                    (Argument number -1 represents the RETURN VALUE of the function.)
                    **INITIAL CONTEXT:{intial_context}**
                    **CALL_GRAPH**: {path}
                    """,
        },
    ]
    messages_with_path_with_return = [  # only for those function which require their return value's tracing.
        {
            "role": "system",
            "content": """You are a C code backward tracer. You trace the return value of a target function to determine what operation is performed on it at the call site (report only READ, WRITE) and the value of the `call_number`.
            ## WHAT YOU ARE GIVEN
                INITIAL_CONTEXT: Function bodies from main() down to the target function (INITIAL CONTEXT). Lines are trimmed. This is your primary source (BUT YOU CAN USE TOOLS TO RESOLVE MACROS AND SEE FUNCTION BODIES THAT CONSUME THE RETURN VALUE).
                Macro expansions are shown as comments if any.
                CALL_GRAPH: Function call graph — only follow this, always, even if another path exists.
                TRACING METHOD (FOLLOW THIS EXACTLY)

            STEP 1: FIND THE TARGET CALL
            Find the exact line where the target function is called. Identify how its return value is captured (or not) at the call site.

            STEP 2: CLASSIFY THE RETURN VALUE USAGE (CRITICAL)
            At the call site, examine what happens to the return value immediately:

            Classification rules (CHECK IN THIS ORDER):

            NOTHING: The return value is discarded entirely — the call is a standalone statement with no assignment or use. e.g., target_func(a, b);
            READ: The return value is consumed — assigned to a variable, used in a conditional, passed as an argument, compared, or used in any expression. e.g., x = target_func(...), if (target_func(...)), other_func(target_func(...)).
            WRITE: The return value (typically a pointer) is written into — something is stored through it. e.g., *target_func(...) = value;, target_func(...)->field = value;.
            STEP 3: IF THE RETURN VALUE IS ASSIGNED TO A VARIABLE, TRACE FORWARD
            If the return value is assigned to a variable (e.g., ret = target_func(...)), scan the function body from the assignment DOWNWARD to the function exit, looking for how ret is ultimately used. This determines whether the overall operation is READ or WRITE.

            Usage priority (CHECK IN THIS ORDER):

            Passed to another function: consumer(ret) → use tools to read consumer and determine if it reads or writes through ret.
            Dereferenced and written to: *ret = val; or ret->field = val; → WRITE.
            Used in expression/condition/return: if (ret), return ret;, x = ret + 1; → READ.
            **DONT'S**:
            - DON'T LOOK FOR THE FUNCTION BODIES THAT ARE ALREADY GIVEN IN THE COTEXT.
            Also determine the call_number trace which is the  `1st argument of the function **pmf_addevent** or **pmf_addvarevt**` (WHATEVER PRESENT)
            **EXAMPLE**:
            int RbtMfsOpenFunc(...) {
                char *buf;
                buf = target_func(a, b);   // <-- return value captured in buf
                memcpy(dest, buf, len);    // <-- buf is READ here
                // Overall: READ
            }
            int RbtMfsWriteFunc(...) {
                char *ptr;
                ptr = target_func(a, b);   // <-- return value captured in ptr
                *ptr = 0x00;               // <-- ptr is WRITTEN THROUGH here
                // Overall: WRITE
            }

        """,
        },
        {
            "role": "user",
            "content": """DETERMINE THE TYPE OF OPERATION PERFORMED ON THE RETURNED POINT OF FUNCTION {function_name_to_traced} and the call_number if present or else None..
                            Find ALL possible constant values that can reach this argument from main().
                            **INITIAL CONTEXT:{intial_context}**
                            **CALL_GRAPH**: {path}
                            """,
        },
    ]

    messages = (
        messages_with_path_without_return
        if get_upper
        else messages_with_path_with_return
    )

    # region MAKING CLIENT AND SENDING DATA.

    data = {
        "user_prompt": messages[1].get("content"),
        "system_prompt": messages[0].get("content"),
        "tools": STATE.get("TOOL_DEFINITION"),
        "tool_functions": STATE.get(
            "TOOLS"
        ),  # dict of {'function_name': function}  IF TOOLS ARE IN SEPERATE FILE THEN USE getattr(my_tools(MODULE), name) INSTEAD OF GLOBALS},
        "project_structure": project_structure,
        "function_map": STATE.get("FUNCTION_MAP"),
        "output_model": outputModel if get_upper else outputModelForReturn,
    }
    # print(get_upper,'get_upper', outputModel if get_upper else outputModelForReturn)
    client = OllamaClient(data=data)
    # endregion
    # region STARTING TOOL CHAIN AND SENDING PROMPT DATA
    prompt_data = {
        "user_prompt": {
            "argument_numbers": argument_numbers,
            "function_name_to_traced": function_name_to_traced,
            "intial_context": intial_context,
            "path": path,
        },
        "system_prompt": {},
    }

    ans, stats = client.start_tool_chain(prompt_data=prompt_data)
    # ans,stats = client.start_new_tool_chain(prompt_data=prompt_data)
    # endregion

    return ans, stats


def llm_calls_transfer(
    project_structure: dict[str, str], request: TransferRequest
) -> tuple[type[BaseModel], dict[str, any]]:
    """Ask for one strict local transfer on one exact route edge.

    The coordinator owns caller selection and later substitution.  This
    prompt therefore has no legacy ``index:value`` output and cannot directly
    manufacture a final numeric fact.
    """
    state = State()
    route_edges = []
    for edge in request.route.edges:
        marker = " synthetic callback" if edge.synthetic_callback else ""
        route_edges.append(f"{edge.caller_id} -[{edge.site_id}{marker}]-> {edge.callee_id}")
    route_text = "\n".join(route_edges) or "(current function is the route root)"
    binding_text = "\n".join(
        f"target argument {item.target_arg}: {item.text}"
        for item in request.bindings
    ) or "(none)"
    guard_text = "\n".join(request.guards) or "true"
    system_prompt = """
You are a C value-transfer analyst. One question per request: at the
SELECTED OUTGOING CALL, where does each requested argument value come from?

Procedure, in order; STOP at the first step that applies:
1. Read the argument expression in the call.
2. It is a literal, a macro/enum name, or a formal parameter:
   kind "EXPRESSION", expression = it (formal parameters written $1..$N).
3. It is a local variable: find its last assignment before the call and
   repeat step 2 on that value. At most 2 hops; then use step 4.
4. It comes from another function's return value, or step 3 did not finish:
   kind "UNKNOWN" with the unchanged source expression in `expression`.
   A named function call is not EXTERNAL merely because this local question
   cannot follow it; it may have a project-local definition.
5. It enters this source from a formal entry parameter or external/global
   data: kind "EXTERNAL" with that terminal source expression in
   `expression` (never a bare number). Do not analyze other functions. Do
   not follow the call. Do not guess.

A fast EXTERNAL or UNKNOWN is a GOOD answer. Never invent a number.
Never restate the source code in the answer. Keep the whole JSON under
1000 characters, at most 2 evidence items, one source line per snippet.

Output: exactly the TransferAnswer JSON schema.
- arms: one arm in the normal case. More arms only when a branch makes the
  value differ; then set guard to that C condition.
- bindings: one entry per requested target argument (1-based number).
- expression, kind "EXPRESSION": formula over $1..$N, integer/char literals,
  macro/enum names, parentheses, and + - * / % << >> & | ^ ~ ! && ||
  < > <= >= == != . No local variable names.
- expression, kind "EXTERNAL": the source expression text, e.g.
  "Tbl[nIdx].Schfno". Never a literal number.
- expression, kind "UNKNOWN": the unchanged expression that could not be
  followed locally, especially a named function call.
- evidence: 1-2 items. snippet = the exact source line(s) used, copied
  verbatim from CURRENT FUNCTION SOURCE. Nothing else to fill in.

Examples (abridged):
Case A:
  FORMAL PARAMETERS: $1=pFcb $2=iFno $3=iSub
  CALL: mpf_mfs_readrec( &fcb, iSub + 1, &data );
  REQUESTED: target argument 2
  ANSWER:
  {"arms": [{"bindings": [{"target_arg": 2, "kind": "EXPRESSION",
  "expression": "$3 + 1"}], "guard": "true", "evidence":
  [{"file": "x.c", "snippet": "mpf_mfs_readrec( &fcb, iSub + 1, &data );"}]}]}
Case B:
  CALL: mpf_mfs_open_H( &fcb, DynREGetSchfno(nFnoidx), 0, 0, LOCK );
  REQUESTED: target argument 2
  ANSWER:
  {"arms": [{"bindings": [{"target_arg": 2, "kind": "UNKNOWN",
  "expression": "DynREGetSchfno(nFnoidx)"}], "guard": "true", "evidence":
  [{"file": "x.c", "snippet": "mpf_mfs_open_H( &fcb, DynREGetSchfno(nFnoidx), 0, 0, LOCK );"}]}]}
"""
    user_prompt = """
ROUTE:
{route}
TARGET SITE ID: {target_site_id}

CURRENT FUNCTION ID: {function_id}
CURRENT FUNCTION: {function_name}
FORMAL PARAMETERS (1-based): {parameters}
CURRENT FUNCTION SOURCE (starts at file byte {function_start_byte}):
{function_source}

SELECTED OUTGOING CALL ({byte_range}):
{selected_call_text}

REQUESTED CORRELATED BINDINGS:
{bindings}

PENDING GUARDS:
{guards}

Answer ONLY the requested bindings for the selected call, following the
procedure in the system prompt.
MACRO EXPANSION CONTEXT: {macro_context}
"""
    client = OllamaClient(
        data={
            "user_prompt": user_prompt,
            "system_prompt": system_prompt,
            "tools": None,
            "tool_functions": {},
            "timeout": float(os.environ.get("TRACER_VF_TRANSFER_TIMEOUT", "120")),
            "project_structure": project_structure,
            "function_map": state.get("FUNCTION_MAP"),
            "output_model": TransferAnswerModel,
        }
    )
    return client.start_tool_chain(
        prompt_data={
            "user_prompt": {
                "route": route_text,
                "target_site_id": request.route.target_site_id,
                "function_id": request.function_id,
                "function_name": request.function_name,
                "parameters": ", ".join(
                    f"${index}={name}"
                    for index, name in enumerate(request.parameters, start=1)
                ) or "(void)",
                "function_source": request.function_source,
                "function_start_byte": request.function_start_byte,
                "byte_range": (
                    "byte range unknown"
                    if request.selected_call_start_byte < 0
                    or request.selected_call_end_byte < 0
                    else f"{request.selected_call_start_byte}:{request.selected_call_end_byte}"
                ),
                "selected_call_text": request.selected_call_text,
                "bindings": binding_text,
                "guards": guard_text,
                "macro_context": request.macro_context,
            },
            "system_prompt": {},
        }
    )


def llm_endpoint_status(timeout: float = 10.0) -> tuple[bool, str]:
    """Probe the configured OpenAI-compatible endpoint before the resolver runs.

    ``run_with_retry`` spends its full timeout on every query when the endpoint
    is wrong or down, which reads as a hung run rather than a misconfiguration.
    One cheap probe up front turns that into a single clear line.
    """
    from openai import OpenAI

    base_url = os.environ.get("TRACER_LLM_BASE_URL", TRACER_DEFAULT_BASE_URL)
    model = os.environ.get("TRACER_LLM_MODEL", TRACER_DEFAULT_MODEL)
    try:
        client = OpenAI(
            api_key=os.environ.get("TRACER_LLM_API_KEY", "EMPTY"),
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )
        served = [item.id for item in client.models.list().data]
    except Exception as exc:
        return False, f"{base_url} unreachable ({type(exc).__name__}: {exc})"
    if served and model not in served:
        return False, f"{base_url} serves {served}, not configured model {model!r}"
    return True, f"{base_url} model {model}"


# ``fork`` is what this worker has always relied on: the child inherits the
# State() singleton (tools, function map) and the local target needs no
# pickling.  macOS defaults to ``spawn``, where both of those break, so the
# context is selected explicitly rather than left to the platform default.
_RETRY_CONTEXT = multiprocessing.get_context(
    "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
)


def write_unique_path_report(
    *,
    function: str,
    process_name: str,
    all_paths_rows: list[dict],
    invocation_rows: list[dict],
) -> Path:
    """Two-sheet audit workbook: paths considered, and unique target invocations.

    Shared by both resolvers so the file name, sheet names and columns stay
    identical whichever engine produced the rows.
    """
    path_report = target_results_dir(process_name, function) / "unique_paths.xlsx"
    path_report.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path_report, engine="openpyxl") as writer:
        pd.DataFrame(all_paths_rows).to_excel(writer, sheet_name="all_paths", index=False)
        pd.DataFrame(invocation_rows).to_excel(
            writer, sheet_name="unique_target_invocations", index=False
        )
    # print(
    #     f"Unique-path report written to {path_report} "
    #     f"({len(all_paths_rows)} paths; {len(invocation_rows)} target invocations)"
    # )
    return path_report


def run_with_retry(func, args=(), timeout=600, retries=2):
    if not isinstance(args, (tuple, list)):
        args = (args,)

    for attempt in range(retries):
        # Create the pipe inside the loop so each attempt gets a fresh connection
        parent_conn, child_conn = _RETRY_CONTEXT.Pipe()

        def target_wrapper(conn, *func_args):
            try:
                result = func(*func_args)
                conn.send({"status": "success", "data": result})
            except Exception as e:
                conn.send({"status": "error", "data": str(e)})
            finally:
                conn.close()

        process = _RETRY_CONTEXT.Process(
            target=target_wrapper, args=(child_conn, *args)
        )
        process.start()

        process.join(timeout)

        # 1. Handle Timeout
        if process.is_alive():
            print(f"⚠️ Attempt {attempt + 1} timed out. Killing process...")
            process.terminate()
            process.join()
            parent_conn.close()  # Clean up pipe
            continue

        # 2. Retrieve Data Safely
        response = None
        try:
            if parent_conn.poll():
                response = parent_conn.recv()
        except EOFError:
            # This happens if the process dies after poll() but before recv()
            response = None
        finally:
            parent_conn.close()  # Always close the parent end after usage

        # 3. Validation - This fixes the 'NoneType' error
        if response is None:
            print(
                f"❌ Attempt {attempt + 1} failed: Process exited without sending data."
            )
            continue

        if response.get("status") == "success":
            return response.get("data")
        else:
            print(f"❌ Attempt {attempt + 1} failed with error: {response.get('data')}")
            continue

    return None


async def make_llm_calls_for_function(
    function,
    trees: dict,
    functions_identified: dict[str, dict[str, any]],
    answers: dict[str, list[tuple[BaseModel, BaseModel]]],
    main_file_name: str,
    function_pointer_args,
    file_functions,
    project_structure,
    project_path,
    entry_function_name: str = "main",
    entry_points: list[tuple[str, str]] | None = None,
) -> (
    list | None
):  # will return list of dataframes containing all data to be saved in csv.

    if ("(" in function) or (")" in function):
        answers[function] = [
            (
                "Not a valid function_n name:: [ENTER THE FUNCTION NAME WITHOUT '()']",
                None,
            )
        ]
        return None
    print(f"PROCESSING FUNCTION -->{BOLD}{GREEN}", function, f"{RESET}", end="\n\n")
    # region INTIALIZING STATE AND OTHER VARIABLES.
    STATE = State()
    FILE_NAME_BYTES: dict[str, bytes] = {
        key: value[1] for key, value in STATE.get("TREES").items()
    }
    list_indices = functions_identified[function].get("indices")
    get_upper = functions_identified[function].get("get_upper")
    function_answer_csv = []  # where will we store the function's csv rows.

    dependent_functions = list(
        filter(
            lambda x: x in functions_identified,
            functions_identified[function].get("dependent_functions"),
        )
    )  # filtering out the dependent function based on what are in the project.
    check_other_functions = bool(dependent_functions) and (
        dependent_functions[0] != function
    )  # True when this target resolves through a configured open family.
    if check_other_functions:
        # A record API is configured against the WHOLE open family (all four
        # mpf_mfs_open* APIs).  Every configured open is inspected per path
        # further down; this print keeps the full dependency list auditable
        # instead of assuming a single dependent function.
        print(
            "DEPENDENT FUNCTIONS (all configured opens):",
            [
                (open_name, functions_identified.get(open_name, {}).get("indices"))
                for open_name in dependent_functions
            ],
        )
    # return None
    # Keep the legacy per-function token checkpoint beside the other outputs.
    # The old absolute path made the legacy resolver impossible to run from a
    # clean checkout (and prevented the offline parity test from exercising
    # the real legacy entry point).
    stats_json_path = results_root() / "stats" / f"{STATE.get('PROJECT_NAME')}_STATS.json"
    stats_json_path.parent.mkdir(parents=True, exist_ok=True)
    # endregion

    # region INTIALIZING EMPTY TOKEN VARIABLES
    dummy_token = {"Input_tokens": 0, "Output_tokens": 0, "Total_tokens": 0}
    empty_stats = {
        "Tokens": dummy_token,
        "Iterations": 0,
        "Random_tool_calls": 0,
        "Other_tool_errors": 0,
        "Incorrect_details": [],
    }
    # endregion

    def write_json_file(data):
        with open(stats_json_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    # region INTIALIZING THE FUNCTION_DICT
    FUNCTION_DICT: dict[str, any] = {
        function: {
            "Total_Input": 0,
            "Total_Output": 0,
            "Total_Tokens": 0,
            "Each_Path_Tokens": [],
        }
    }
    if stats_json_path.exists():
        with open(stats_json_path, "r", encoding="utf-8") as f:
            loaded_dict = json.load(f)
            FUNCTION_DICT = {**FUNCTION_DICT, **loaded_dict}

    FUNCTION_INPUT_TOKEN = FUNCTION_DICT[function].get("Total_Input", 0)
    FUNCTION_OUTPUT_TOKEN = FUNCTION_DICT[function].get("Total_Output", 0)
    # endregion

    # region FINDING OUT FROM WHICH PART WE NEED TO RESUME
    if FUNCTION_DICT[function]["Each_Path_Tokens"] == []:
        PATH_TO_START_WITH = 1
    else:
        PATH_TO_START_WITH = (
            int(list(FUNCTION_DICT[function]["Each_Path_Tokens"][-1].keys())[0]) + 1
        )
    print("Need to start with the path", PATH_TO_START_WITH)
    # endregion

    # region MAKING CALL_GRAPH AND GETTING DATA
    macro_data = possible_paths_data = None
    call_graph_with_paths = orchestrate(
        project_strcuture=project_structure,
        trees=trees,
        required_func=function,
        main_file_name=main_file_name,
        entry_function_name=entry_function_name,
        entry_points=entry_points,
        function_pointer_args=function_pointer_args,
        file_functions=file_functions,
        return_whole_tree=check_other_functions,  # this will tell if path_nodes will be returned or not.
    )

    if not call_graph_with_paths:
        print(f"{BOLD}{RED}No possible paths for: {GREEN}{function}{RESET}")
        return None
    macro_data, possible_paths_data = call_graph_with_paths

    # A selected process is the only valid trace entry point.  Its paths may
    # traverse linked libraries, but paths rooted in a library must not become
    # independent trace/LLM work for this process.
    target_root = Path(project_path).resolve()

    def starts_in_target_process(path_data) -> bool:
        path = path_data[0][0]
        if not path:
            return False
        first_match = re.match(r"\[([^:\]]+)(?::[^\]]+)?\]", path[0])
        if first_match is None:
            return False
        source_path = project_structure.get(first_match.group(1))
        if source_path is None:
            return False
        try:
            return Path(source_path).resolve().is_relative_to(target_root)
        except OSError:
            return False

    total_candidate_paths = len(possible_paths_data)
    possible_paths_data = [
        path_data
        for path_data in possible_paths_data
        if starts_in_target_process(path_data)
    ]
    if len(possible_paths_data) != total_candidate_paths:
        print(
            "Skipped "
            f"{total_candidate_paths - len(possible_paths_data)} library-rooted path(s) "
            f"outside {target_root}"
        )
    if not possible_paths_data:
        print(f"{BOLD}{RED}No target-rooted paths for: {GREEN}{function}{RESET}")
        return None
    if not macro_data:
        print("For ", function, " no macro data")
    call_graph_determined_datas = [
        path[1] for path in possible_paths_data
    ]  # tuple of [list[str],dict]
    path_nodes: list[list[CallTreeNode]] | None = [
        path[0][1] for path in possible_paths_data if path[0][1] is not None
    ]  # NONE WHEN NO DEPENDENT FUNCTION OTHER THEN ITSSELF.
    path_strs: list[list[str]] = [path[0][0] for path in possible_paths_data]
    collector = STATE.get("VISUALIZER_COLLECTOR")
    if collector is not None:
        collector.capture_call_graph(
            graph=STATE.get("CALL_GRAPH"),
            registry=STATE.get("FUNCTION_REGISTRY"),
            target_function=function,
            trace_paths=path_strs,
        )

    # Keep a readable, pre-LLM audit of the paths considered for this target.
    # Excel is used because CSV has no concept of multiple sheets.
    unique_paths: dict[str, tuple[list[str], dict]] = {}
    for path_data in possible_paths_data:
        nodes, metadata = path_data[0][0], path_data[1]
        unique_paths.setdefault("->".join(nodes), (nodes, metadata))

    all_paths_rows = [
        {
            "path_number": index,
            "target_function": function,
            "node_count": len(nodes),
            "path": path_text,
        }
        for index, (path_text, (nodes, _)) in enumerate(unique_paths.items(), start=1)
    ]
    invocation_paths: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for path_text, (_, metadata) in unique_paths.items():
        target_source = metadata.get("target_name_src")
        invocation_key = (
            function,
            str(getattr(target_source, "path", "unknown")),
            str(getattr(target_source, "line_number", "unknown")),
        )
        invocation_paths[invocation_key].add(path_text)
    invocation_rows = [
        {
            "invocation_number": index,
            "target_function": target_function,
            "target_source_path": source_path,
            "target_source_line": source_line,
            "reachable_unique_path_count": len(reaching_paths),
        }
        for index, ((target_function, source_path, source_line), reaching_paths) in enumerate(
            sorted(invocation_paths.items()), start=1
        )
    ]
    write_unique_path_report(
        function=function,
        process_name=str(STATE.get("PROJECT_NAME") or Path(project_path).name),
        all_paths_rows=all_paths_rows,
        invocation_rows=invocation_rows,
    )
    # print_or_return_possible_paths_trees(paths=path_strs) FOR JUST PRINTING ALL PATH TREES BEFOREHAND FOR OBSERVATION..
    # endregion

    print("TOTAL PATHS FOR THIS FUNCTION: ", len(path_strs))
    # return

    make_graph(
        paths=path_strs
    )  # for storing the this function's call_graph. (mermaid and pyvis)

    # region PARSING FOR THE FUNCTION AND GETTING CONTEXTS FOR ALL PATHS.
    print(f"PARSING FOR FUNCTION -> {function}")
    parser = parseFiles(
        project_structure=project_structure,
        paths=path_strs,
        macro_data=macro_data,
        file_name_bytes=FILE_NAME_BYTES,
    )
    contexts = parser.get_parsed_results(get_upper=get_upper)
    # endregion

    async def run_llm_requests(requests):
        semaphore = asyncio.Semaphore(1)

        async def run_request(key, args):
            async with semaphore:
                try:
                    return key, await asyncio.to_thread(
                        run_with_retry, llm_calls, args
                    )
                except Exception as exc:
                    print(f"LLM request failed for {key}: {exc}")
                    return key, None

        return dict(await asyncio.gather(*(run_request(*request) for request in requests)))

    async def run_llm_pairs(path_requests):
        semaphore = asyncio.Semaphore(1)

        async def run_pair(index, primary_args, dependent_args):
            async with semaphore:
                try:
                    primary_result = (
                        await asyncio.to_thread(run_with_retry, llm_calls, primary_args)
                        if primary_args
                        else None
                    )
                    dependent_result = (
                        await asyncio.to_thread(run_with_retry, llm_calls, dependent_args)
                        if dependent_args is not None
                        and (not primary_args or primary_result)
                        else None
                    )
                    return index, (primary_result, dependent_result)
                except Exception as exc:
                    print(f"LLM requests failed for path {index}: {exc}")
                    return index, (None, None)

        return dict(await asyncio.gather(*(run_pair(*request) for request in path_requests)))

    if check_other_functions and len(path_nodes) > 0:

        # region GETTING DEPENDENT FUNCTION PATH FROM EACH FUNCTION PATH (APPLYING DFS IN IT AND GETTING LAST PATH)
        # A target may be configured against a whole open family (all four
        # mpf_mfs_open* APIs).  Inspect every configured open: for each path,
        # the first open (in configuration order) that the path actually
        # contains is the one the LLM resolves.  This replaces the historical
        # single-dependent assumption without changing what one path costs
        # (still at most one dependent LLM call per path).
        dependent_paths_by_open: dict[str, list[list[str]]] = {}
        for open_name in dependent_functions:
            open_paths: list[list[str]] = []
            print_or_return_possible_paths_trees(
                paths=path_nodes,
                dependent_function=open_name,
                result_path_list=open_paths,
            )  # returns the tree made from the nodes.
            dependent_paths_by_open[open_name] = open_paths

        selected_open: list[str | None] = []
        for position in range(len(path_nodes)):
            selected_open.append(
                next(
                    (
                        open_name
                        for open_name in dependent_functions
                        if dependent_paths_by_open.get(open_name, [])[position]
                    ),
                    None,
                )
            )
        paths_to_dependent = [
            dependent_paths_by_open[open_name][position]
            if (open_name := selected_open[position]) is not None
            else []
            for position in range(len(path_nodes))
        ]
        found_opens = sorted({open_name for open_name in selected_open if open_name})
        # set the paths to dependent in this function ...
        #  endregion

        # region PARSING FOR DEPENDENT FUNCTION
        print(
            "PARSING FOR DEPENDENT FUNCTION -> "
            + (", ".join(found_opens) if found_opens else "(none found on any path)")
        )
        dependent_function_parser = parseFiles(
            project_structure=project_structure,
            paths=paths_to_dependent,
            macro_data=macro_data,
            file_name_bytes=FILE_NAME_BYTES,
        )
        dependent_contexts = dependent_function_parser.get_parsed_results(
            get_upper=True
        )
        # endregion

        path_requests = []
        for index, (path, context) in enumerate(contexts, start=1):
            if index < PATH_TO_START_WITH:
                continue
            path_str = "->".join(
                re.sub(r"\[([^\[\]]*)\]", "", node) for node in path
            )
            primary_args = None
            if STATE.get("FUNCTION_TYPES").get(function, {}).get("type") == "WRITEF/READF":
                primary_args = (
                    project_structure, function, list_indices, context, path_str, get_upper
                )
            new_path, context_new = dependent_contexts[index - 1]
            new_path_str = "->".join(
                re.sub(r"\[([^\[\]]*)\]", "", node) for node in new_path
            )
            open_name = selected_open[index - 1]
            open_config = functions_identified.get(open_name, {}) if open_name else {}
            dependent_args = (
                (
                    project_structure,
                    open_name,
                    open_config.get("indices"),
                    context_new,
                    new_path_str,
                    open_config.get("get_upper"),
                )
                if open_name is not None and open_config.get("indices")
                else None
            )
            path_requests.append((index, primary_args, dependent_args))
        llm_results = await run_llm_pairs(path_requests)

        for index, (path, context) in enumerate(contexts, start=1):
            if index < PATH_TO_START_WITH:
                continue
            call_graph_data = call_graph_determined_datas[
                index - 1
            ]  # data received for this path from call_graph
            # It has [function_name,launch_via,call_function,function_name_src,target_name_src] -> NEEDED process_name(folder_name), type + aidetermined...
            print(f"{BOLD}{GREEN}PROCESS PATH_{index}{RESET}")
            print("-" * 20, "PATH AND CONTEXT", "-" * 20)

            block_regex = r"\[([^\[\]]*)\]"
            path_str = "->".join(
                map(lambda x: re.sub(block_regex, "", x), path)
            )  # path like func_a->func_b ...

            # Per-path source context can be very large.
            # print(highlight(context, CLexer(), TerminalFormatter()))
            print("-" * 56)
            stats_dict1 = None
            # region WHEN WE NEED TO DETERMINE FUNCTION_TYPE LIKE (mpf_mfs_getrec etc)
            if (
                STATE.get("FUNCTION_TYPES").get(function, {}).get("type", "NO DATA")
                == "WRITEF/READF"
            ):
                call_graph_data = {
                    **call_graph_data,
                    "process_name": str(STATE.get("PROJECT_NAME") or Path(project_path).name),
                }
                print(" STEP - 1 DETERMINING THE CALL_TYPE")

                _pair = llm_results.get(index)
                ans = _pair[0] if _pair else None
                if ans:
                    validated_model, stats = ans
                else:
                    # get out of the loop..
                    final_combined_data = {
                        **call_graph_data,
                        "target_number": {
                            "path_str": "->".join(path),
                            "ans": ["UNRESOLVED"],
                        },
                        "call_number": -1,
                        "type": "NO DATA",
                    }
                    tokens = TokenCount(Input_tokens=0, Output_tokens=0, Total_tokens=0)
                    FUNCTION_DICT[function]["Each_Path_Tokens"].append(
                        {index: tokens.model_dump()}
                    )
                    FUNCTION_DICT[function].update(
                        {
                            "Total_Tokens": FUNCTION_INPUT_TOKEN
                            + FUNCTION_OUTPUT_TOKEN,
                            "Total_Output": FUNCTION_OUTPUT_TOKEN,
                            "Total_Input": FUNCTION_INPUT_TOKEN,
                        }
                    )
                    combined_model = Combined.model_validate(final_combined_data)
                    save_dict_csv(data_dict=combined_model.model_dump(), save=True)
                    write_json_file(data=FUNCTION_DICT)
                    answers[function].append(
                        (combined_model, Stats.model_validate(empty_stats))
                    )
                    print(f"DONE WITH PATH {index}")
                    continue

                stats_dict1 = stats.model_dump()
                FUNCTION_INPUT_TOKEN += stats_dict1.get("Tokens").get("Input_tokens")
                FUNCTION_OUTPUT_TOKEN += stats_dict1.get("Tokens").get("Output_tokens")
                validated_model_dict = (
                    validated_model.model_dump()
                )  # will give as dict {'output': str_value...} str_value = arg_number:value,...
                print("VALIDATED MODEL CONVERTED TO DICT")
                console.print(validated_model_dict)
                output_string = validated_model_dict.get("output", "")  # arg_num:value
                call_number = validated_model_dict.get("call_number") or -1
                call_graph_data = {
                    **call_graph_data,
                    "type": output_string,
                    "call_number": call_number,
                    "process_name": str(STATE.get("PROJECT_NAME") or Path(project_path).name),
                }  # determined the type.
            # endregion
            else:
                # region WHEN FUNCTION_TYPE IS ALREADY DECIDED (ONLY CALL_GRAPH DATA CHANGES)
                call_graph_data = {
                    **call_graph_data,
                    "process_name": str(STATE.get("PROJECT_NAME") or Path(project_path).name),
                    "type": STATE.get("FUNCTION_TYPES")
                    .get(function, {})
                    .get("type", "NO DATA"),  # here type is fixed.
                }
            # endregion

            print("NOW RUNNING FOR THE DEPENDENT FUNCTION.")
            new_path, context_new = dependent_contexts[index - 1]
            # print("CONTEXT FOR THE DEPENDENT FUNCTION")
            # print(highlight(context_new, CLexer(), TerminalFormatter()))

            new_path_str = "->".join(
                map(lambda x: re.sub(block_regex, "", x), new_path)
            )
            _pair = llm_results.get(index)
            ans = _pair[1] if _pair else None

            if ans:
                validated_model, stats = ans
            else:
                final_combined_data = {
                    **call_graph_data,
                    "target_number": {
                        "path_str": "->".join(path),
                        "ans": ["UNRESOLVED"],
                    },
                }
                final_combined_data["call_number"] = -1
                combined_model = Combined.model_validate(final_combined_data)
                tokens = TokenCount(Input_tokens=0, Output_tokens=0, Total_tokens=0)
                FUNCTION_DICT[function]["Each_Path_Tokens"].append(
                    {index: tokens.model_dump()}
                )
                FUNCTION_DICT[function].update(
                    {
                        "Total_Tokens": FUNCTION_INPUT_TOKEN + FUNCTION_OUTPUT_TOKEN,
                        "Total_Output": FUNCTION_OUTPUT_TOKEN,
                        "Total_Input": FUNCTION_INPUT_TOKEN,
                    }
                )
                write_json_file(data=FUNCTION_DICT)
                save_dict_csv(data_dict=combined_model.model_dump(), save=True)
                answers[function].append(
                    (combined_model, Stats.model_validate(empty_stats))
                )
                print(f"DONE WITH PATH {index}")
                continue

            validated_model_dict = (
                validated_model.model_dump()
            )  # will give as dict {'output': str_value...} str_value = arg_number:value,...
            stats_dict2 = stats.model_dump()
            FUNCTION_INPUT_TOKEN += stats_dict2.get("Tokens").get("Input_tokens")
            FUNCTION_OUTPUT_TOKEN += stats_dict2.get("Tokens").get("Output_tokens")

            if stats_dict1:
                FUNCTION_DICT[function]["Each_Path_Tokens"].append(
                    {
                        index: {
                            key: (
                                stats_dict1["Tokens"][key] + stats_dict2["Tokens"][key]
                            )
                            for key in stats_dict2["Tokens"]
                        }
                    }
                )
            else:
                FUNCTION_DICT[function]["Each_Path_Tokens"].append(
                    {index: stats_dict2["Tokens"]}
                )

            FUNCTION_DICT[function].update(
                {
                    "Total_Tokens": FUNCTION_INPUT_TOKEN + FUNCTION_OUTPUT_TOKEN,
                    "Total_Output": FUNCTION_OUTPUT_TOKEN,
                    "Total_Input": FUNCTION_INPUT_TOKEN,
                }
            )
            write_json_file(data=FUNCTION_DICT)
            print("VALIDATED MODEL CONVERTED TO DICT")
            console.print(validated_model_dict)

            # extracting data from ai_output.
            output_string = validated_model_dict.get("output", "")  # arg_num:value
            call_number_dependent = validated_model_dict.get("call_number") or -1
            values_found = []
            for elements in output_string.split(","):
                try:
                    file_num = int(elements.split(":")[1])
                    values_found.append(file_num)
                except Exception as e:
                    file_num = "UNRESOLVED"
                    values_found.append(file_num)

            final_combined_data = {
                **call_graph_data,
                "target_number": {"path_str": "->".join(path), "ans": values_found},
            }
            if "call_number" not in final_combined_data:
                final_combined_data = {
                    **final_combined_data,
                    "call_number": call_number_dependent,
                }

            console.print(final_combined_data)
            combined_model = Combined.model_validate(final_combined_data)
            # function_answer_csv.append(save_dict_csv(data_dict=combined_model.model_dump(),save=False))
            save_dict_csv(data_dict=combined_model.model_dump(), save=True)
            answers[function].append((combined_model, stats))
            print(f"DONE WITH PATH {index}")

    else:
        requests = []
        for index, (path, context) in enumerate(contexts, start=1):
            # Targets with no configured argument to trace (pmf launch-only
            # APIs, close APIs) need no LLM call at all.
            if index < PATH_TO_START_WITH or not list_indices:
                continue
            path_str = "->".join(
                re.sub(r"\[([^\[\]]*)\]", "", node) for node in path
            )
            requests.append((
                ("primary", index),
                (project_structure, function, list_indices, context, path_str, get_upper),
            ))
        llm_results = await run_llm_requests(requests)

        for index, (path, context) in enumerate(contexts, start=1):
            if index < PATH_TO_START_WITH:
                continue
            call_graph_data = call_graph_determined_datas[
                index - 1
            ]  # data received for this path from call_graph
            # It has [function_name,launch_via,call_function,function_name_src,target_name_src] -> NEEDED process_name(folder_name), type + aidetermined...
            type_of_func = STATE.get("FUNCTION_TYPES").get(function).get("type")
            call_graph_data = {
                **call_graph_data,
                "process_name": str(STATE.get("PROJECT_NAME") or Path(project_path).name),
                "type": type_of_func if type_of_func else "NO DATA",
            }

            console.print(call_graph_data)  # now need to add the target(list[strs])
            print(f"{BOLD}{GREEN}PROCESS PATH_{index}{RESET}")
            print("-" * 20, "PATH AND CONTEXT", "-" * 20)

            block_regex = r"\[([^\[\]]*)\]"
            path_str = "->".join(map(lambda x: re.sub(block_regex, "", x), path))
            # for i,p in enumerate(path):
            #     path_str += re.sub(block_regex,'',p)
            #     if i<len(path)-1:
            #         path_str+='->'

            # pprint(path_str)
            # Per-path source context can be very large.
            # print(highlight(context, CLexer(), TerminalFormatter()))
            print("-" * 56)
            # in case of targets with no configured argument to trace
            # (pmf launch-only APIs, close APIs): no LLM call needed..
            if not list_indices:
                # then we don't need to call llm..
                launch = STATE.get("FUNCTION_TYPES").get(function).get("launch")
                final_combined_data = {
                    **call_graph_data,
                    "target_number": {
                        "path_str": "->".join(path),
                        "ans": ["NO TARGET"],
                    },
                    "call_number": -1,
                }
                if launch:
                    final_combined_data = {**final_combined_data, "launch_via": launch}
                combined_model = Combined.model_validate(final_combined_data)
                tokens = TokenCount(Input_tokens=0, Output_tokens=0, Total_tokens=0)
                FUNCTION_DICT[function]["Each_Path_Tokens"].append(
                    {index: tokens.model_dump()}
                )
                FUNCTION_DICT[function].update(
                    {
                        "Total_Tokens": FUNCTION_INPUT_TOKEN + FUNCTION_OUTPUT_TOKEN,
                        "Total_Output": FUNCTION_OUTPUT_TOKEN,
                        "Total_Input": FUNCTION_INPUT_TOKEN,
                    }
                )
                save_dict_csv(data_dict=combined_model.model_dump(), save=True)
                # answers[function].append((combined_model,stats))
                write_json_file(data=FUNCTION_DICT)
                console.print(final_combined_data)
                answers[function].append(
                    (combined_model, Stats.model_validate(empty_stats))
                )
                print(f"DONE WITH PATH {index}")
                continue
            ans = llm_results.get(("primary", index))
            if ans:
                validated_model, stats = ans
            else:
                # get out of the loop..
                launch = STATE.get("FUNCTION_TYPES").get(function).get("launch")
                final_combined_data = {
                    **call_graph_data,
                    "target_number": {
                        "path_str": "->".join(path),
                        "ans": ["UNRESOLVED"],
                    },
                    "call_number": -1,
                }
                if "pmf" in function and launch is not None:
                    final_combined_data = {**final_combined_data, "launch_via": launch}
                combined_model = Combined.model_validate(final_combined_data)
                tokens = TokenCount(Input_tokens=0, Output_tokens=0, Total_tokens=0)

                FUNCTION_DICT[function]["Each_Path_Tokens"].append(
                    {index: tokens.model_dump()}
                )
                FUNCTION_DICT[function].update(
                    {
                        "Total_Tokens": FUNCTION_INPUT_TOKEN + FUNCTION_OUTPUT_TOKEN,
                        "Total_Output": FUNCTION_OUTPUT_TOKEN,
                        "Total_Input": FUNCTION_INPUT_TOKEN,
                    }
                )
                write_json_file(data=FUNCTION_DICT)
                save_dict_csv(data_dict=combined_model.model_dump(), save=True)
                # answers[function].append((combined_model,stats))
                answers[function].append(
                    (combined_model, Stats.model_validate(empty_stats).model_dump())
                )
                print(f"DONE WITH PATH {index}")
                continue
            # console.print(stats)
            validated_model_dict = (
                validated_model.model_dump()
            )  #       will give as dict {'output': str_value...} str_value = arg_number:value,...
            print("VALIDATED MODEL CONVERTED TO DICT")
            console.print(validated_model_dict)
            stats_dict = stats.model_dump()
            FUNCTION_INPUT_TOKEN += stats_dict.get("Tokens").get("Input_tokens")
            FUNCTION_OUTPUT_TOKEN += stats_dict.get("Tokens").get("Output_tokens")

            FUNCTION_DICT[function]["Each_Path_Tokens"].append(
                {index: stats_dict["Tokens"]}
            )
            FUNCTION_DICT[function].update(
                {
                    "Total_Tokens": FUNCTION_INPUT_TOKEN + FUNCTION_OUTPUT_TOKEN,
                    "Total_Output": FUNCTION_OUTPUT_TOKEN,
                    "Total_Input": FUNCTION_INPUT_TOKEN,
                }
            )

            write_json_file(data=FUNCTION_DICT)
            # extracting data from ai_output.
            output_string = validated_model_dict.get("output", "")  # arg_num:value
            # print("The final output_string", output_string)

            values_found: list[int | str | Literal["UNRESOLVED"]] = []
            call_number = validated_model_dict.get("call_number") or -1
            splitted = output_string.split(",")
            for elements in splitted:
                first_one = elements.split(":")[0]
                try:
                    if '"' in elements.split(":")[1]:
                        # string
                        values_found.append(elements.split(":")[1].strip('"'))
                    else:
                        file_num = int(elements.split(":")[1].strip('"'))
                        values_found.append(file_num)
                except Exception as e:
                    # values_found.append('UNRESOLVED')\
                    values_found.append(elements.split(":")[1].strip('"'))
            launch = STATE.get("FUNCTION_TYPES").get(function).get("launch")
            final_combined_data = {
                **call_graph_data,
                "target_number": {
                    "path_str": "->".join(path),
                    "ans": values_found if len(values_found) > 0 else ["NO TARGET"],
                },
                "call_number": call_number,
            }
            if "pmf" in function and launch:
                final_combined_data = {**final_combined_data, "launch_via": launch}
            console.print(final_combined_data)
            combined_model = Combined.model_validate(final_combined_data)
            # function_answer_csv.append(save_dict_csv(data_dict=combined_model.model_dump(),save=False))
            save_dict_csv(data_dict=combined_model.model_dump(), save=True)
            answers[function].append((combined_model, stats))
            print(f"DONE WITH PATH {index}")

    return function_answer_csv

async def make_value_flow_calls(
    *,
    graph: dict,
    registry: dict,
    trees: dict,
    functions_identified: dict[str, dict[str, any]],
    answers: dict[str, list[tuple[BaseModel, BaseModel]]],
    main_file_name: str,
    entry_function_name: str = "main",
    entry_points: list[tuple[str, str]] | None = None,
    function_pointer_args: dict,
    file_functions: dict,
    project_structure: dict[str, str],
    project_path: Path,
    include_roots: tuple[str, ...] = (),
    path_cap: int = 100,
    llm_concurrency: int = 10,
) -> list:
    """
    Run the value-flow resolver for every detected target API call in this process.

    This builds target seeds from the complete call graph, walks backward through
    call paths, resolves argument values, writes output artifacts, and appends
    legacy-compatible results into `answers`.
    """

    # NEW VALUE-FLOW PIPELINE (read this before following the helpers below):
    #
    # 1. trace_variable() has already parsed the project and built `graph`.
    # 2. ValueFlowResolver finds every reachable configured target CALL.
    # 3. For each target argument it walks BACKWARD to the value source.
    #    Example: close(handle) -> open(handle, FILE_NO) -> FILE_NO macro.
    # 4. The resolver returns one record per value/path.  This function only
    #    supplies LLM context, writes files, and adapts results for old callers.
    #
    # Important: this is not the old main-to-target path enumerator.  The
    # resolver follows only edges that carry the selected value.
    state = State()
    process_name = str(state.get("PROJECT_NAME") or project_path.name)

    # parseFiles still needs the original file bytes when it prepares an LLM
    # prompt. Tree-sitter trees are already inside `trees`; keep only bytes here.
    # Keep only file bytes from the preprocessed Tree-sitter data.
    # parseFiles uses this to generate source context for LLM prompts.
    file_name_bytes = {key: value[1] for key, value in trees.items()}

    # FUNCTION_TYPES was normalized and saved back into State inside identify_funs_to_trace().
    # We read it again here because functions_identified only contains targets found in this project,
    # but the full State config may also contain richer/default config and dependency function configs.
    # Example: if "mpf_read" is detected and depends on "mpf_open", we trace "mpf_read" as a seed,
    # but also include "mpf_open" config so value-flow can resolve the handle/resource relationship.
    configured = state.get("FUNCTION_TYPES") or {}

    # Value-flow inventory and seed creation use the complete normalized
    # registry. The resolver creates work only for call sites that exist.
    valueflow_configs = {
        name: dict(config) for name, config in configured.items()
    }

    # Aggregated LLM token/query stats for this whole resolver run.
    token_totals = {"Input_tokens": 0, "Output_tokens": 0, "Total_tokens": 0}
    query_stats: list[dict] = []

    # A transfer prompt that has not answered in two minutes is not going to;
    # run_with_retry's 600s default is tuned for the heavier legacy prompts.
    transfer_timeout = int(os.environ.get("TRACER_VF_TRANSFER_TIMEOUT", "120"))
    # P20 (flagged, TRACER_VF_NO_FORK): the transfer prompt is a bounded,
    # side-effect-free API call, so it does not need a forked child per hop --
    # each fork copy-on-writes a parent holding every tree, AST and registry.
    # The fork exists so a hung call can be terminated; llm_calls_transfer now
    # bounds its own request time instead, which makes that unnecessary.
    transfer_no_fork = os.environ.get("TRACER_VF_NO_FORK") == "1"

    def record_stats(kind: str, site: IndexedSite, stats) -> None:
        """
        Record token usage and query metadata for one LLM call.
        `kind` identifies why the LLM was called.
        """
        if stats is None:
            return

        stats_dict = stats.model_dump() if hasattr(stats, "model_dump") else dict(stats)
        tokens = stats_dict.get("Tokens") or {}

        for key in token_totals:
            token_totals[key] += int(tokens.get(key, 0) or 0)

        query_stats.append(
            {
                "kind": kind,
                "call_site_id": site.site_id,
                "function": site.callee_name,
                "stats": stats_dict,
            }
        )

    # Dedicated executor pools keep CPU-side prompt construction and the
    # blocking model waits out of the default asyncio thread pool.  Without
    # this split, a prompt build queued in the shared pool can sit behind
    # threads blocked in run_with_retry's process.join(timeout), and model
    # waits can sit behind prompt builds.  Both pools are shut down in the
    # finally block that guards resolver.run() below.
    loop = asyncio.get_running_loop()
    context_workers = min(4, max(1, os.cpu_count() or 1))
    context_executor = ThreadPoolExecutor(
        max_workers=context_workers, thread_name_prefix="valueflow-context"
    )
    llm_executor = ThreadPoolExecutor(
        max_workers=max(1, llm_concurrency), thread_name_prefix="valueflow-llm"
    )

    def context_for(site: IndexedSite, *, get_upper: bool) -> tuple[list[str], str]:
        """
        Build a small call-path context around one call site.

        This converts resolver site metadata back into the legacy path-label
        format expected by parseFiles and the existing LLM prompts.
        """
        # Convert one resolver call site back to the older label format that
        # parseFiles understands. This exists only for an LLM prompt; it does
        # not decide which value-flow path the resolver follows.
        caller = registry.get(site.caller_id)
        callee = registry.get(site.callee_id) or site.raw_call_site.callee

        if caller is None:
            return [], ""

        path = [caller.label]

        # If the call goes through a macro, include the macro proxy node.
        # This lets parseFiles expose macro expansion info to the LLM.
        if site.macro_name:
            path.append(site.raw_call_site.callee.label_with_line(line=site.line))

        path.append(callee.label_with_line(line=site.line))

        parser = parseFiles(
            project_structure=project_structure,
            paths=[path],
            macro_data=state.get("BUILDER_MACROS") or {},
            file_name_bytes=file_name_bytes,
        )

        _, context = parser.parse_for_path(path, get_upper=get_upper)
        return path, context

    async def run_context(
        site: IndexedSite, *, get_upper: bool
    ) -> tuple[list[str], str]:
        """
        Run the synchronous context_for() builder on the dedicated CPU pool.

        Prompt construction does Tree-sitter work and source slicing.  Running
        it off the event loop lets other seeds make CPU progress while model
        processes are still running, without touching the LLM wait pool.
        """
        return await loop.run_in_executor(
            context_executor, partial(context_for, site, get_upper=get_upper)
        )

    async def resolve_transfer(request: TransferRequest):
        """Run the strict transfer prompt for the resolver's selected edge."""
        print(
            f"{ORANGE}  LLM transfer{RESET} {request.function_file} "
            f"{request.function_name} -> {request.selected_site_id}"
        )
        if transfer_no_fork:
            # Raised exceptions are caught by ValueFlowResolver._await_llm and
            # counted as llm_exception, exactly as a fork failure would be.
            result = await loop.run_in_executor(
                llm_executor, llm_calls_transfer, project_structure, request
            )
        else:
            result = await loop.run_in_executor(
                llm_executor,
                partial(run_with_retry, timeout=transfer_timeout, retries=2),
                llm_calls_transfer,
                (project_structure, request),
            )
        if not result:
            return None
        model, stats = result
        selected = resolver.sites.get(request.selected_site_id)
        if selected is not None:
            record_stats("transfer", selected, stats)
        return model

    async def disabled_transfer(_request: TransferRequest):
        """Keep the strict transfer pipeline usable when the endpoint is down."""
        return None

    async def resolve_return_use(site: IndexedSite, function_name: str) -> str | None:
        """
        Resolve how a function return value is used at this call site.

        This is used for target configs that need return-value tracing instead
        of normal argument tracing.
        """
        # This is separate from argument tracing: it asks whether a returned
        # pointer/result is later used as a READF or WRITEF resource.
        path, context = await run_context(site, get_upper=False)

        if not path:
            return None

        print(
            f"{ORANGE}  LLM return-use{RESET} {site.file_name}:{site.line} "
            f"{function_name}"
        )

        result = await loop.run_in_executor(
            llm_executor,
            run_with_retry,
            llm_calls,
            (
                project_structure,
                function_name,
                [-1],
                context,
                "->".join(re.sub(r"\[([^\[\]]*)\]", "", node) for node in path),
                False,
            ),
        )

        if not result:
            return None

        model, stats = result
        record_stats("return_use", site, stats)

        return (model.model_dump() if hasattr(model, "model_dump") else model).get(
            "output"
        )

    seed_progress = None

    def report_seed(seed, rows, seconds: float) -> None:
        """
        Progress callback passed into ValueFlowResolver.

        Called once per resolved target invocation/seed.
        """
        if seed_progress is not None:
            seed_progress.update(1)

        # values = ", ".join(
        #     f"{row.fact.value} ({row.fact.origin_kind})" for row in rows
        # )
        # print(
        #     f"[{resolved_count[0]}/{len(resolver.seeds)}] {seconds:6.2f}s "
        #     f"{seed.target_function} {seed.site.file_name}:{seed.site.line}"
        #     f" -> {values or 'no target'}"
        # )

    # Check whether the optional LLM endpoint is available.  If it is down,
    # the same route-guided engine remains active with direct source constants
    # and conservative unresolved results for semantic transfers.
    llm_ready, llm_status = llm_endpoint_status()

    print(
        f"{BOLD}{GREEN if llm_ready else ORANGE}VALUE-FLOW LLM "
        f"{'READY' if llm_ready else 'DISABLED (syntax-only run)'}{RESET}: {llm_status}"
    )

    # Cache stores previously answered LLM subqueries for this process.
    # This avoids repeating expensive identical prompts across runs.
    cache_path = process_results_dir(process_name) / "query_cache.json"

    # Hand the prepared project index and the strict transfer/return callbacks
    # to the resolver. From this point, resolver.run() owns tracing.
    try:
        resolver = ValueFlowResolver(
            graph=graph,
            registry=registry,
            trees=trees,
            project_structure=project_structure,
            include_roots=include_roots,
            main_file_name=main_file_name,
            entry_function_name=entry_function_name,
            entry_points=entry_points,
            function_configs=valueflow_configs,
            macros=state.get("BUILDER_MACROS") or {},
            file_macros=state.get("MACROS") or {},
            # Valueflow mode uses only the strict route transfer contract.  The
            # legacy one-hop callback remains available to legacy resolver mode
            # and comparison tests, but is never a numeric fallback here.
            transfer_resolver=resolve_transfer if llm_ready else disabled_transfer,
            transfer_model_id=os.environ.get("TRACER_LLM_MODEL", TRACER_DEFAULT_MODEL),
            # The opaque-grammar flag changes which formulas validate, so an
            # answer cached with it on must never be served with it off.
            transfer_prompt_version="valueflow-transfer-v4"
            + ("-opaque" if os.environ.get("TRACER_VF_GRAMMAR_EXTENDED") == "1" else ""),
            return_use_resolver=resolve_return_use if llm_ready else None,
            cache_path=cache_path,
            path_cap=path_cap,
            llm_concurrency=llm_concurrency,
            progress=report_seed,
        )

        print(
            f"Resolving {len(resolver.seeds)} target invocation(s) "
            f"with LLM concurrency {llm_concurrency}"
        )

        started_at = time.perf_counter()

        # Main resolver execution.
        # Produces fact records: target call + resolved value + paths/evidence.
        with tqdm(
            total=len(resolver.seeds),
            desc="Resolving seeds",
            unit="seed",
            mininterval=0.2,
            dynamic_ncols=True,
        ) as seed_progress:
            records = await resolver.run()

        # Root/reachability state for the discovery index: which functions a
        # recognized root reaches directly, which only through callbacks, and
        # the run-level root diagnostic.
        state.set(
            "RESOLVER_STATE",
            {
                "root_state": str(
                    (state.get("ROOT_DIAGNOSTICS") or {}).get("root_state") or ""
                ),
                "direct_reachable": set(resolver.direct_reachable),
                "reachable": set(resolver.reachable),
            },
        )
    finally:
        # Release both pools even when indexing or resolution raises.  No
        # work is submitted after this point.  cancel_futures drops queued
        # (never-started) work; wait=True still lets already-running
        # run_with_retry calls exit through their existing retry/timeout
        # child-process logic, and the original exception propagates.
        context_executor.shutdown(wait=True, cancel_futures=True)
        llm_executor.shutdown(wait=True, cancel_futures=True)

    run_stats = {
        "resolver": "valueflow",
        "wall_seconds": round(time.perf_counter() - started_at, 3),
        "llm_concurrency": llm_concurrency,
        "seed_count": len(resolver.seeds),
        "fact_count": len(records),
        "answered_query_count": len(resolver.results),
        "llm_query_count": len(query_stats),
        "transfer_request_count": resolver.transfer_request_count,
        "transfer_cache_hits": resolver.transfer_cache_hits,
        "transfer_cache_misses": resolver.transfer_cache_misses,
        "transfer_diagnostics": list(resolver.transfer_diagnostics),
        "transfer_rejections": dict(resolver.transfer_rejections),
        "transfer_prompt_version": resolver.transfer_prompt_version,
        "transfer_model_id": resolver.transfer_model_id,
        "fast_path_seed_count": resolver.fast_path_seed_count,
        "search_seed_count": resolver.search_seed_count,
        "search_state_count": resolver.search_state_count,
        "search_deduplicated_state_count": resolver.search_deduplicated_state_count,
        "search_limit_seed_count": resolver.search_limit_seed_count,
        "search_max_frontier": resolver.search_max_frontier,
        "search_max_depth": resolver.search_max_depth,
        "witness_path_count": resolver.witness_path_count,
        "Tokens": token_totals,
        "queries": query_stats,
    }

    # Write machine-readable resolver outputs.  facts.csv keeps individual
    # values; paths.csv keeps retained source-to-target proof/witness paths; the
    # top-level process CSV is the compatibility feed used by the visualizer.
    # Usually includes fact rows and path rows under the process result folder.
    output_paths = write_outputs(
        records=records,
        resolver=resolver,
        process_name=process_name,
        output_root=results_root(),
        run_stats=run_stats,
    )

    # Write detailed trace/debug logs for each resolved path.
    log_dir = write_trace_logs(
        records=records,
        resolver=resolver,
        process_name=process_name,
        output_root=results_root(),
    )

    # Build the same presentation artifacts that the legacy branch generated:
    # path reports, visualizer traces, and graph diagrams.
    collector = state.get("VISUALIZER_COLLECTOR")

    grouped: dict[str, list] = defaultdict(list)

    for record in records:
        grouped[record.seed.target_function].append(record)

    for target_function, function_records in sorted(grouped.items()):
        drawn = [item.legacy_labels for item in function_records if item.legacy_labels]

        write_unique_path_report(
            function=target_function,
            process_name=process_name,
            all_paths_rows=[
                {
                    "path_number": number,
                    "target_function": target_function,
                    "node_count": len(path),
                    "path": " -> ".join(path),
                }
                for number, path in enumerate(
                    (path for item in function_records for path in item.paths), start=1
                )
            ],
            invocation_rows=[
                {
                    "invocation_number": number,
                    "target_function": target_function,
                    "target_source_path": site_id_rows[0].seed.site.file_path,
                    "target_source_line": site_id_rows[0].seed.site.line,
                    "reachable_unique_path_count": sum(
                        item.path_count for item in site_id_rows
                    ),
                }
                for number, site_id_rows in enumerate(
                    (
                        [
                            item
                            for item in function_records
                            if item.seed.site.site_id == site_id
                        ]
                        for site_id in dict.fromkeys(
                            item.seed.site.site_id for item in function_records
                        )
                    ),
                    start=1,
                )
            ],
        )

        if collector is not None:
            collector.capture_call_graph(
                graph=state.get("CALL_GRAPH"),
                registry=state.get("FUNCTION_REGISTRY"),
                target_function=target_function,
                trace_paths=drawn,
            )

        try:
            make_graph(paths=drawn)
        except Exception as exc:
            # Graph drawing is only a visualization step.
            # Do not fail the whole resolver if drawing breaks.
            print(f"Could not draw the graph for {target_function}: {exc}")

    print(
        f"Value-flow outputs written: {output_paths.facts} and {output_paths.paths} "
        f"({len(resolver.seeds)} target invocations; {len(records)} facts)"
    )

    print(f"Per-path resolution logs: {log_dir}")

    # Persist run-level stats separately for audit/debugging.
    stats_path = process_results_dir(process_name) / "run_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(
        json.dumps(run_stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Legacy compatibility: downstream code expects each answer to include
    # a Combined model and Stats model, even for valueflow results.
    empty_stats = Stats.model_validate(
        {
            "Tokens": {"Input_tokens": 0, "Output_tokens": 0, "Total_tokens": 0},
            "Iterations": 0,
            "Random_tool_calls": 0,
            "Other_tool_errors": 0,
            "Incorrect_details": [],
        }
    )

    for record in records:
        path_string = "->".join(record.legacy_labels)

        combined = Combined.model_validate(
            {
                "call_number": record.call_number,
                "target_number": {
                    "path_str": path_string,
                    "ans": [record.fact.value],
                },
                "process_name": process_name,
                "launch_via": (
                    "NO DATA"
                    if record.seed.local_backwalk
                    else record.seed.launch_via
                ),
                "reachability": (
                    "LOCAL_BACKWALK"
                    if record.seed.local_backwalk
                    else (
                        resolver.reachability_kind(record.seed.site.caller_id)
                        or (record.fact.metadata or {}).get("reachability")
                        or "UNKNOWN"
                    )
                ),
                "call_function": record.seed.call_function,
                "function_name": record.seed.target_function,
                "type": record.operation,
                "function_name_src": {
                    "path": record.seed.function_source_file or project_path,
                    "line_number": str(record.seed.function_source_line),
                },
                "target_name_src": {
                    "path": record.seed.site.file_path,
                    "line_number": str(record.seed.site.line),
                },
            }
        )

        answers[record.seed.target_function].append((combined, empty_stats))

    return records


@time_it()
def trace_variable(
    project_path: Path | str,
    summary_config: SummaryConfig | None = None,
    *,
    index_only: bool = False,
    resolver: Literal["legacy", "valueflow"] = "legacy",
    valueflow_path_cap: int = 100,
    valueflow_concurrency: int = 10,
    source_root: Path | None = None,
):
    STATE = State()
    project_path = Path(project_path)
    process_name = str(STATE.get("PROJECT_NAME") or project_path.name)
    trace_started_at = time.perf_counter()
    summary_seconds = 0.0

    # region pickle caching

    # Reuse the historical project-structure cache by default, but allow
    # deterministic fixture/integration runs to opt out.  The cache is keyed
    # by project name for legacy compatibility, so two temporary projects with
    # the same name must be able to request a fresh mapping.
    USE_PROJECT_STRUCTURE_PICKLE = os.environ.get(
        "VISUALIZER_USE_PROJECT_STRUCTURE_PICKLE", "1"
    ).lower() not in {"0", "false", "no"}

    configured_cache_root = os.environ.get("PROJECT_STRUCTURE_CACHE_ROOT")
    pickle_dir = (
        Path(configured_cache_root).expanduser()
        if configured_cache_root
        else Path(__file__).resolve().parent / "pickle_data/project_structures_pickle"
    )
    pickle_dir.mkdir(exist_ok=True, parents=True)

    # Project names repeat across temporary fixtures and across different
    # source trees.  Include the resolved project path so a cache can never
    # silently point discovery at another checkout with the same name.
    project_key = hashlib.sha256(
        str(project_path.resolve()).encode("utf-8")
    ).hexdigest()[:16]
    project_structure_path = pickle_dir / (
        f"{project_path.name}_{project_key}_include_v6.pkl"
    )

    PROJECT_STRUCTURE = None
    potential_main_files: list[str] | None = None
    # Canonical absolute paths of the Makefile SRCS sources.  Root
    # membership is decided by this path-keyed set, never by basename alone.
    srcs_paths: list[str] | None = None

    cached = None
    if USE_PROJECT_STRUCTURE_PICKLE:
        cached = load_project_structure_cache(project_structure_path)
        if project_structure_path.exists() and cached is None:
            print(
                "WARNING: project-structure cache predates path-keyed SRCS; "
                "re-resolving instead of trusting stale root paths"
            )
    if cached is not None:
        PROJECT_STRUCTURE, potential_main_files, srcs_paths = cached
    else:
        print(
            "PROJECT STRUCTURE NEEDS TO BE RESOLVED. "
            "NO PICKLE FILE OR PICKLE CACHE DISABLED. IT WILL TAKE TIME...."
        )

        # This will make project structure and find all potention main files
        # DEFINITION: Project structure means all the files involved in a project (maybe outside the src folder too)
        # TODO: read this later fully and understand logic
        # sample output
        # PROJECT_STRUCTURE: 
        # {'../COMMON/jac_dbdef.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/jac/../COMMON/jac_dbdef.h'),
        #  'COMMON/Ffe.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/COMMON/Ffe.h'),
        #  'COMMON/type_defc.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/COMMON/type_defc.h'),
        #  'FILE/FFE_MNT.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/FILE/FFE_MNT.h'),
        #  'FILE/KF_NAME.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/FILE/KF_NAME.h'),
        #  'Mmi/Mmi.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/modern/include/Mmi/Mmi.h'),
        #  'Mmi/MmiDateD.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/modern/include/Mmi/MmiDateD.h'),
        #  'Scn/ScnCstmz.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/modern/include/Scn/ScnCstmz.h'),
        #  'svm_ssc_req.c': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm/svm_ssc_req.c'),
        #  'svm_usesw_get.c': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm/svm_usesw_get.c'),
        #  'svm_warnhv_get.c': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm4/svm_warnhv_get.c'),
        #  'svm_wbtn.c': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm/svm_wbtn.c'),
        #  'svmanlys.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm4/svmanlys.h'),
        #  'svmyeq.c': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm/svmyeq.c'),
        #  'table/table.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/modern/include/sedai1/table/table.h'),
        #  'tmm/tmm001_msg.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/tmm/tmm001_msg.h'),
        #  'tmm/tmm002_event.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/tmm/tmm002_event.h'),
        #  'tmm/tmm002_msg.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/tmm/tmm002_msg.h'),
        #  'tmm/tmm003_event.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/tmm/tmm003_event.h'),
        #  'tmm/tmm110d_event.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/tmm/tmm110d_event.h'),
        #  'tmm/tmm840_event.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/tmm/tmm840_event.h'),
        #  'tmm/tmm_msg.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/tmm/tmm_msg.h'),
        #  'usr/usr.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/modern/include/usr/usr.h'),
        #  'usr/usr_in.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/modern/include/usr/usr_in.h'),
        #  'xrs/xrserr.h': PosixPath('/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/modern/include/sedai1/xrs/xrserr.h')}

        # potential_main_files:
        # ['svm001.c', 'svm001_kansi.c', 'svm001_kbtmsg.c', 'svm001_svminit.c']
        PROJECT_STRUCTURE, potential_main_files, srcs_paths = return_project_mapping(
            show=False,
            project_path=project_path,
        )

        # stringify and make into dict
        PROJECT_STRUCTURE = dict(
            sorted(PROJECT_STRUCTURE.items(), key=lambda x: str(x[0]))
        )

        # Save to pickle for later reuse (for prod)
        if USE_PROJECT_STRUCTURE_PICKLE:
            save_project_structure_cache(
                project_structure_path,
                PROJECT_STRUCTURE,
                potential_main_files,
                srcs_paths,
            )

    # endregion pickle caching

    potential_main_files = potential_main_files or []
    srcs_paths = srcs_paths or []

    # Path-keyed process-source membership: canonical absolute path to the
    # PROJECT_STRUCTURE key that holds that file.  Basename membership stays
    # only as a compatibility fallback when no SRCS paths are available.
    srcs_absolute: set[str] = set()
    srcs_membership: dict[str, str] = {}
    for raw_key, raw_path in PROJECT_STRUCTURE.items():
        try:
            resolved = str(Path(raw_path).resolve())
        except (OSError, TypeError):
            continue
        if raw_key in potential_main_files:
            srcs_absolute.add(resolved)
            srcs_membership.setdefault(resolved, raw_key)
    if not srcs_absolute:
        for raw_path in srcs_paths:
            srcs_absolute.add(str(Path(raw_path).resolve()))

    def _is_process_source(key: str, raw_path: str) -> bool:
        try:
            if str(Path(raw_path).resolve()) in srcs_absolute:
                return True
        except (OSError, TypeError):
            pass
        return any(key == x for x in potential_main_files)

    STATE.set("PROJECT_STRUCTURE", PROJECT_STRUCTURE)
    print("THE MAIN FILES ARE: ", potential_main_files)

    # Main Tree-sitter parsing.  Keep the preprocessing macro state tied to
    # this process's Makefile; do not apply one machine-wide -D/-U profile to
    # every project.  The Preprocess fallback is only considered for files
    # whose first parse contains syntax errors.
    # output: dict file:(tree sitter tree, cleaned file contents)
    preprocessor_flags = get_project_preprocessor_flags(project_path)
    preprocessor = Preprocess(
        defines=preprocessor_flags.get("defines", ()),
        undefines=preprocessor_flags.get("undefines", ()),
    )
    expected_entries_by_file = {
        filename: ENTRY_FUNCTION_NAMES for filename in potential_main_files
    }
    trees = preprocessor.preprocess(
        project_structure=PROJECT_STRUCTURE,
        expected_entry_names=expected_entries_by_file,
    )

    STATE.set("TREES", trees)
    STATE.set(
        "PREPROCESSOR_CONFIG",
        {
            **preprocessor_flags,
            "fallback_undefines": preprocessor.config.fallback_undefines,
            "file_metadata": preprocessor.file_metadata,
        },
    )

    # converts all values in PROJECT_STRUCTURE keys to strings
    PROJECT_STRUCTURE = {
        key: str(PROJECT_STRUCTURE[key]) for key in PROJECT_STRUCTURE.keys()
    }

    print("LENGTH OF PROJECT_STRUCTURE", len(PROJECT_STRUCTURE))

    # this was set in main, from json data (see main function)
    FUNCTION_POINTER_ARGS = STATE.get("FUNCTION_POINTER_ARGS")

    # Dict of all functions in a file
    FILE_FUNCTIONS = {}

    # Actual project entry-point file/function, if found.  A process can have
    # several middleware-invoked lifecycle roots; the primary pair remains
    # for compatibility with older output fields.
    main_file_name = None
    entry_function_name = None
    entry_points: list[tuple[str, str]] = []

    # Files that define main() but are not the real detected entry point.
    bad_main_files = []

    # Per-file macro definitions.
    macros = {}

    # Per-file #include relationships.
    file_includes: dict[str, list] = {}

    for files in PROJECT_STRUCTURE.keys():
        # Collect per-file macros and includes for later analysis.
        macros[files] = extract_all_macros(PROJECT_STRUCTURE[files], trees[files][1])
        file_includes[files] = extract_includes(PROJECT_STRUCTURE[files])

        # Headers do not contain project entry-point functions.
        if files.endswith(".h"):
            continue

        # Local function definitions found in this source file.
        # TODO: analyze and clean these helper
        functions = get_local_function_definitions(
            code_bytes=trees[files][1]
        )

        entry_candidates = [name for name in ENTRY_FUNCTION_NAMES if name in functions]
        is_process_source = _is_process_source(files, PROJECT_STRUCTURE[files])

        # Every lifecycle callback implemented by the process is a root.  The
        # Makefile-derived source list prevents shared-library definitions
        # from becoming roots for every consumer process.
        if is_process_source:
            for entry_name in entry_candidates:
                entry_points.append((files, entry_name))

        # Preserve the historical duplicate-main cleanup, but do not delete a
        # library merely because it defines a lifecycle callback name.
        if (
            any(name in {"main", "pmf_main_H"} for name in entry_candidates)
            and not is_process_source
        ):
            bad_main_files.append(files)

        # Store functions found in this file.
        FILE_FUNCTIONS[files] = functions

    # Remove wrong duplicate/test main files from the indexed project.
    # TODO: Find out why this was done, it must happen often to have code for this
    for bad_files in bad_main_files:
        del FILE_FUNCTIONS[bad_files]
        del PROJECT_STRUCTURE[bad_files]
        del trees[bad_files]

    # Select a stable primary entry for legacy fields and display metadata.
    if entry_points:
        main_file_name, entry_function_name = entry_points[0]
        print("Found entry roots", entry_points)

    STATE.set("FILE_FUNCTIONS", FILE_FUNCTIONS)
    STATE.set("FILE_INCLUDES", file_includes)
    STATE.set("MACROS", macros)
    STATE.set("ENTRY_POINTS", entry_points)

    # Root diagnostics: every executable source with a raw accepted root but
    # no parsed root is a ROOT_PARSE_FAILURE; a scope with no accepted root
    # at all is NO_PROCESS_ROOT.  Never leave an empty root list unexplained.
    file_metadata = (
        (STATE.get("PREPROCESSOR_CONFIG") or {}).get("file_metadata") or {}
    )
    root_state = "OK" if entry_points else None
    root_failure_reason = ""
    per_file_root_diagnostics: dict[str, dict[str, object]] = {}
    if not entry_points:
        for files, raw_path in PROJECT_STRUCTURE.items():
            if files.endswith(".h"):
                continue
            meta = file_metadata.get(files, {}) or {}
            raw_candidates = meta.get("root_candidates") or []
            raw_root_names = {
                item["name"]
                for item in raw_candidates
                if item["kind"] in ("definition", "inactive_definition")
            }
            parsed_roots = [n for n in ENTRY_FUNCTION_NAMES if n in FILE_FUNCTIONS.get(files, {})]
            if _is_process_source(files, raw_path):
                if parsed_roots:
                    state = "OK"
                elif raw_root_names:
                    state = "ROOT_PARSE_FAILURE"
                else:
                    state = "NO_ACCEPTED_ROOT"
            else:
                state = "NO_PROCESS_ROOT"
            per_file_root_diagnostics[files] = {
                "state": state,
                "parsed_roots": parsed_roots,
                "raw_root_names": sorted(raw_root_names),
                "root_variant": meta.get("root_variant", ""),
                "root_validation": meta.get("root_validation", ""),
                "root_failure_reason": meta.get("root_failure_reason", ""),
            }
        states = [item["state"] for item in per_file_root_diagnostics.values()]
        if "ROOT_PARSE_FAILURE" in states:
            root_state = "ROOT_PARSE_FAILURE"
            failing = sorted(
                files for files, item in per_file_root_diagnostics.items()
                if item["state"] == "ROOT_PARSE_FAILURE"
            )
            root_failure_reason = "raw_accepted_root_not_parsed_in:" + ",".join(failing)
        elif any(s in ("OK",) for s in states):
            root_state = "OK"
        else:
            root_state = "NO_PROCESS_ROOT"
            root_failure_reason = "no_accepted_root_definition_in_any_process_source"

    root_diagnostics = {
        "root_state": root_state,
        "root_failure_reason": root_failure_reason,
        "accepted_entry_points": [name for _file, name in entry_points],
        "per_file": per_file_root_diagnostics,
        "root_candidates": {
            files: (meta.get("root_candidates") or [])
            for files, meta in file_metadata.items()
            if meta.get("root_candidates")
        },
        "parse_health": {
            "initial_error_files": sum(
                1 for meta in file_metadata.values() if meta.get("initial_has_error")
            ),
            "final_error_files": sum(
                1 for meta in file_metadata.values() if meta.get("final_has_error")
            ),
            "fallback_variant_files": sum(
                1 for meta in file_metadata.values() if meta.get("fallback_used")
            ),
        },
    }
    STATE.set("ROOT_DIAGNOSTICS", root_diagnostics)
    print(f"ROOT DIAGNOSTICS: state={root_state} roots={entry_points}")

    # TODO: analyze this, how is this diff from above? waht this contains etc
    # TODO: We are not using the 3rd and 4th params, then why calc it? Or, further down the line its being made again and used, maybe use it and pass it to there 
    graph, registry, _, _ = build_complete_call_graph(
        project_structure=PROJECT_STRUCTURE,
        trees=trees,
        function_pointer_args=FUNCTION_POINTER_ARGS,
        file_functions=FILE_FUNCTIONS,
    )
    print(f"CALL GRAPH READY ({len(graph)} callers, {len(registry)} functions)")

    # TODO: Do this later
    print("BUILDING VISUALIZER CHECKPOINT")
    print("VISUALIZER: indexing complete file functions")
    complete_file_functions = build_complete_file_functions(trees, FILE_FUNCTIONS)
    print("VISUALIZER: capturing source snapshot")
    collector = VisualizerCollector(
        process_name=process_name,
        process_root=project_path,
        project_structure=PROJECT_STRUCTURE,
        file_functions=complete_file_functions,
        main_file_name=main_file_name,
        entry_function_name=entry_function_name,
        entry_points=entry_points,
        root_diagnostics=STATE.get("ROOT_DIAGNOSTICS"),
        library_functions=set((STATE.get("FUNCTION_MAP") or {}).keys())
        | set((STATE.get("FUNCTION_TYPES") or {}).keys()),
        run_id=STATE.get("TIME"),
    )

    print("VISUALIZER: capturing call graph")
    collector.capture_call_graph(graph=graph, registry=registry)
    STATE.set("VISUALIZER_COLLECTOR", collector)

    print("VISUALIZER: writing checkpoint")
    graph_path = collector.write()
    STATE.set("VISUALIZER_GRAPH_PATH", graph_path)
    print(f"Complete source graph checkpoint written to {graph_path}")

    # TODO: Temporarily disabled for speed, bring it back later for prod
    summary_config = summary_config or SummaryConfig.from_env()
    if summary_config.enabled:
        print("STARTING FUNCTION SUMMARIES")
        summary_started_at = time.perf_counter()
        try:
            summary_report = asyncio.run(summarize_collector(collector, summary_config))
            print(f"Bottom-up function summaries: {summary_report}")
        except Exception as exc:
            print(f"Function summarization unavailable: {exc}")
            for function_data in collector.functions.values():
                if not function_data.get("is_external") and not function_data.get(
                    "summary"
                    ):
                        function_data["summary_error"] = str(exc)
            collector.write()
        finally:
            summary_seconds = time.perf_counter() - summary_started_at

    # If its index only, it means we are only trying to capture source trees, not the unique target parameters, so return early here
    # we already have saved the visualizer in the state
    if index_only:
        return {}

    # This is subset of target functions json, it basically finds all the target funcs 
    # that are actually present in the paths, then only gives the subset here
    # the output shape is same as the json_data/mpf_data.json
    print("IDENTIFYING TARGET FUNCTIONS")
    functions_identified = identify_funs_to_trace(
        project_structure=PROJECT_STRUCTURE,
        trees=trees,
    )

    # ---------------------------------------------------------------
    # Discovery-index setup (shared by both resolvers, plan.md phase 2/3):
    # one exact target call-site inventory built from the parsed trees,
    # plus the compatible index/ artifacts written after tracing.  The
    # inventory and evidence are written even when a resolver fails.
    # ---------------------------------------------------------------
    discovery_spec = STATE.get("TARGET_SPEC")
    if discovery_spec is None:
        # Project-local mpf_data.json runs (fixtures) keep working; without
        # discovery metadata the adapter emits evidence-only output.
        discovery_spec = {
            "targets": STATE.get("FUNCTION_TYPES") or {},
            "version": "mpf_data-local",
            "digest": "",
        }
    resolved_source_root = resolve_source_root(project_path, source_root)
    target_sites = build_target_site_inventory(
        trees=trees,
        functions_identified=functions_identified,
        spec=discovery_spec,
        project_structure=PROJECT_STRUCTURE,
        source_root=resolved_source_root,
        process_root=project_path,
        macros=STATE.get("BUILDER_MACROS") or {},
    )
    print(
        f"TARGET CALL-SITE INVENTORY: {len(target_sites)} discovery argument "
        f"site(s) under {resolved_source_root}"
    )

    file_function_counts: dict[str, int] = {}
    for _file, definitions in FILE_FUNCTIONS.items():
        if definitions:
            rel = rel_to_source_root(
                PROJECT_STRUCTURE.get(_file, _file), resolved_source_root
            )
            file_function_counts[rel] = len(definitions)

    def _write_discovery_index(collected_facts: list) -> None:
        try:
            write_discovery_index(
                output_dir=process_results_dir(process_name) / "index",
                process_name=process_name,
                source_root=resolved_source_root,
                process_root=project_path,
                target_registry_version=str(discovery_spec.get("version", "")),
                target_registry_digest=str(discovery_spec.get("digest", "")),
                target_sites=target_sites,
                facts=collected_facts,
                resolver=resolver,
                run_id=STATE.get("TIME"),
                file_function_counts=file_function_counts,
                preprocessor_config=STATE.get("PREPROCESSOR_CONFIG") or {},
                root_diagnostics=STATE.get("ROOT_DIAGNOSTICS"),
            )
            print(
                f"Discovery index written to "
                f"{process_results_dir(process_name) / 'index'}"
            )
        except Exception as index_exc:
            # A discovery-index failure must not hide the resolver result.
            print(f"Failed to write discovery index: {index_exc}")

    if functions_identified == {} and resolver != "valueflow":
        print(
            f"{BOLD}{RED}NO FUNCTIONS IDENTIFIED IN THE PROJECT {process_name}.{RESET}"
        )
        _write_discovery_index([])
        return {}

    console.print(
        "-" * 10,
        "DETECTED FUNCTIONS NEEDS TO BE TRACED AND THEIR ARG. NUMS.",
        "-" * 10,
    )
    console.print(functions_identified)
    console.print("-" * 60)

    answers: dict[str, list[tuple[BaseModel, BaseModel]]] = defaultdict(list)

    print("This is the main file::", main_file_name)

    # running new modern flow, reverse walk
    discovery_facts: list = []
    try:
        if resolver == "valueflow":
            print("STARTING VALUE-FLOW RESOLUTION")
            records = asyncio.run(
                make_value_flow_calls(
                    graph=graph, # Callsite/FunctionNode custom graph
                    registry=registry, # list of all functions
                    trees=trees, # tree sitter trees
                    functions_identified=functions_identified, # target functiosn in trees
                    answers=answers, # to add answer inplace
                    main_file_name=main_file_name, # starting point
                    entry_function_name=entry_function_name,
                    entry_points=entry_points,
                    function_pointer_args=FUNCTION_POINTER_ARGS,
                    file_functions=FILE_FUNCTIONS,
                    project_structure=PROJECT_STRUCTURE,
                    project_path=project_path,
                    include_roots=tuple(
                        (STATE.get("PREPROCESSOR_CONFIG") or {}).get(
                            "include_dirs", ()
                        )
                    ),
                    path_cap=valueflow_path_cap,
                    llm_concurrency=valueflow_concurrency,
                )
            )
            discovery_facts = valueflow_records_to_facts(
                records,
                target_sites,
                discovery_spec,
                resolved_source_root,
                project_path,
                STATE.get("RESOLVER_STATE"),
            )

        # Fallback to legacy code, resolving for all unique paths in main
        else:
            for function in functions_identified:
                # Legacy path enumerator retained as run-level fallback.
                STATE.set("CURRENT_PROCESSED_FUNCTION", function)

                asyncio.run(
                    make_llm_calls_for_function(
                        function=function,
                        trees=trees,
                        functions_identified=functions_identified,
                        answers=answers,
                        main_file_name=main_file_name,
                        entry_function_name=entry_function_name,
                        entry_points=entry_points,
                        function_pointer_args=FUNCTION_POINTER_ARGS,
                        file_functions=FILE_FUNCTIONS,
                        project_structure=PROJECT_STRUCTURE,
                        project_path=project_path,
                    )
                )
            discovery_facts = legacy_answers_to_facts(
                answers,
                target_sites,
                discovery_spec,
                resolved_source_root,
                project_path,
            )
    except Exception:
        # Whatever evidence was collected still goes to the comparison
        # artifacts; the run error propagates unchanged.
        _write_discovery_index(discovery_facts)
        raise

    _write_discovery_index(discovery_facts)

    # After all the target parameters are resolved, it adds those connections back to the visualizer data
    collector = STATE.get("VISUALIZER_COLLECTOR")
    if collector is not None:
        collector.rehydrate_interactions(
            results_root() / f"{STATE.get('PROJECT_NAME')}.csv",
            {
                function_name: list(config.get("indices") or [])
                for function_name, config in functions_identified.items()
            },
        )

        graph_path = collector.write()
        STATE.set("VISUALIZER_GRAPH_PATH", graph_path)
        print(f"Visualizer graph written to {graph_path}")

    # Add final trace timings after all value-flow output and visualizer work.
    stats_path = process_results_dir(process_name) / "run_stats.json"
    if resolver == "valueflow" and stats_path.is_file():
        run_stats = json.loads(stats_path.read_text(encoding="utf-8"))
        end_to_end_seconds = time.perf_counter() - trace_started_at
        run_stats["end-to-end-time"] = round(end_to_end_seconds, 3)
        run_stats["parsing-time"] = round(
            max(0.0, end_to_end_seconds - summary_seconds), 3
        )
        stats_path.write_text(
            json.dumps(run_stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return answers


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)

    def flush(self):
        for s in self.streams:
            s.flush()


def _write_process_timing(
    process_name: str,
    started_at: float,
    *,
    status: str,
) -> None:
    """Persist outer process timing even when tracing exits early or fails."""
    stats_path = process_results_dir(process_name) / "run_stats.json"
    stats = {}
    if stats_path.is_file():
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            stats = {}

    stats["process_wall_seconds"] = round(time.perf_counter() - started_at, 3)
    stats["process_status"] = status
    try:
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError) as exc:
        # Timing must never hide the original process result or failure.
        print(f"PROCESS TIMING WRITE FAILED for {process_name}: {exc}")


# Run the tracer
if __name__ == "__main__":

    repo_root = Path(__file__).resolve().parent

    # region arg parser and config validation/setting

    argument_parser = argparse.ArgumentParser(
        description="Index one process or a reproducible group of processes."
    )
    process_mode = argument_parser.add_mutually_exclusive_group(required=True)
    process_mode.add_argument(
        "--project",
        type=Path,
        help="Process directory to trace (must contain a Makefile).",
    )
    process_mode.add_argument(
        "--projects",
        type=Path,
        nargs="+",
        help="Explicit process directories to trace sequentially as one group.",
    )
    process_mode.add_argument(
        "--process-folder",
        type=Path,
        help="Discover every Makefile process below this folder and trace them sequentially.",
    )
    process_mode.add_argument(
        "--combine-runs",
        metavar="GROUP_NAME",
        help="Create a group from process snapshots produced by earlier commands.",
    )
    argument_parser.add_argument(
        "--combine-processes",
        nargs="+",
        metavar="PROCESS",
        help="With --combine-runs, limit the group to these process names.",
    )
    argument_parser.add_argument(
        "--run-selection",
        choices=("latest-with-interactions", "latest"),
        default="latest-with-interactions",
        help="Snapshot policy used by --combine-runs (default: latest snapshot containing interactions).",
    )
    argument_parser.add_argument(
        "--group-name",
        help="Name for a list/folder batch group (defaults to a timestamped batch name).",
    )
    argument_parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue with later processes and record failed members in the group manifest.",
    )
    summary_group = argument_parser.add_mutually_exclusive_group()
    summary_group.add_argument(
        "--summarize-functions",
        action="store_true",
        help="Generate bottom-up summaries for every source function.",
    )
    summary_group.add_argument(
        "--skip-function-summaries",
        action="store_true",
        help="Index source/calls without making function-summary LLM calls.",
    )
    argument_parser.add_argument("--summary-model")
    argument_parser.add_argument("--summary-base-url")
    argument_parser.add_argument(
        "--llm-model",
        help="Model name exposed by the OpenAI-compatible vLLM server.",
    )
    argument_parser.add_argument(
        "--llm-base-url",
        help="OpenAI-compatible vLLM base URL, including /v1.",
    )
    argument_parser.add_argument("--llm-api-key")
    argument_parser.add_argument(
        "--wiki-url",
        help=(
            "Full llm-wiki ask URL, e.g. "
            "http://127.0.0.1:8000/llm-wiki/moove/api/ask"
        ),
    )
    argument_parser.add_argument(
        "--wiki-placeholder",
        action="store_true",
        help="Use an explicit no-knowledge wiki placeholder for offline testing.",
    )
    argument_parser.add_argument("--summary-concurrency", type=int)
    argument_parser.add_argument(
        "--index-only",
        action="store_true",
        help="Build the complete code graph (and optional summaries) without target-variable LLM tracing.",
    )
    argument_parser.add_argument(
        "--resolver",
        choices=("valueflow", "legacy"),
        default="legacy",
        help="Target tracing engine. Default legacy until a valueflow run is diffed against it on the real sources.",
    )
    argument_parser.add_argument(
        "--targets",
        type=Path,
        default=None,
        help=(
            "Target spec JSON to use instead of the project-local "
            "json_data/mpf_data.json (replaces FUNCTION_TYPES only). "
            "Comparison runs use target_specs/build_index_targets.json."
        ),
    )
    argument_parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help=(
            "Root that discovery-index paths are relative to. Defaults to the "
            "chukyu root when the process is rooted at <root>/t-*/src/<process>, "
            "otherwise the process root."
        ),
    )
    argument_parser.add_argument(
        "--valueflow-path-cap",
        type=int,
        default=10000,
        help="Maximum provenance paths written per fact; the true count is retained.",
    )
    argument_parser.add_argument(
        "--valueflow-concurrency",
        type=int,
        default=10,
        help="Concurrent value-flow target/LLM queries (default: 10).",
    )

    command_args = argument_parser.parse_args()

    if command_args.llm_model:
        os.environ["TRACER_LLM_MODEL"] = command_args.llm_model
    if command_args.llm_base_url:
        os.environ["TRACER_LLM_BASE_URL"] = command_args.llm_base_url
    if command_args.llm_api_key:
        os.environ["TRACER_LLM_API_KEY"] = command_args.llm_api_key

    # to combine processes you need to combine runs too
    if command_args.combine_processes and not command_args.combine_runs:
        argument_parser.error("--combine-processes requires --combine-runs")

    # validate group name (remove weird chars)
    if command_args.group_name:
        try:
            validate_group_name(command_args.group_name)
        except ValueError as exc:
            argument_parser.error(str(exc))

    # TODO: understand this flow
    if command_args.combine_runs:
        try:
            group_path = write_group_manifest(
                results_root(),
                command_args.combine_runs,
                process_names=command_args.combine_processes,
                policy=command_args.run_selection,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        print(f"Combined process group written to {group_path}")
        print(
            "Open only this group with: "
            f"python frontend/server.py --group {command_args.combine_runs}"
        )
        sys.exit(0)

    # setting for if we doing a (single  process)/(multiple processes)/(whole project with auto discovered processes)
    if command_args.project:
        projects_to_run = [command_args.project.resolve()]
        batch_mode = False
    elif command_args.projects:
        projects_to_run = command_args.projects
        batch_mode = True
    elif command_args.process_folder:
        try:
            # This recursively finds all the "processes" (folders with code) that has a Makefile in it
            # CRITICAL: dont give it a parent folder which has its own makefile to share, otherwise it would start processing it to as a "process"
            # That path is not yet tested
            # TODO: make it more robust
            projects_to_run = discover_processes(command_args.process_folder)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        batch_mode = True

    if command_args.process_folder and not projects_to_run:
        raise SystemExit("No Makefile process directories were found in the selected folder.")

    try:
        projects_to_run = validate_processes(projects_to_run)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    # TODO: Make it reuse stuff from above, llm endpoint, concurrency etc, rather than retaking configs for env etc
    summary_config = SummaryConfig.from_env()

    if command_args.summarize_functions:
        summary_config.enabled = True
    elif command_args.skip_function_summaries:
        summary_config.enabled = False

    if command_args.summary_model:
        summary_config.model = command_args.summary_model
    if command_args.summary_base_url:
        summary_config.base_url = command_args.summary_base_url
    if command_args.wiki_url:
        summary_config.wiki_url = command_args.wiki_url
    if command_args.wiki_placeholder:
        summary_config.wiki_placeholder = True
    if command_args.summary_concurrency:
        summary_config.concurrency = max(1, command_args.summary_concurrency)

    # endregion arg parser and config validation/setting

    # region inits and runs for tracing one target

    # TODO: Come back here and add what they mean contain properly
    graph_paths: list[Path] = []
    failures: list[dict] = []
    process_index_dirs: list[Path] = []
    batch_started_ns = time.time_ns()

    # Fist init of app state
    STATE = State()
    process_names = process_output_names(
        projects_to_run,
        root=command_args.process_folder,
    )

    for project_path in projects_to_run:
        output_process_name = process_names[project_path.resolve()]
        process_started_at = time.perf_counter()
        process_status = "success"

        # First, we try to recursively find "json_data" directory, which contains the target functions 
        # (TODO: Find what other thing it contains)
        # I can see its getting target functions, target function pointers etc, but i need to understand what that means, there is also a function map for parsed explanations of functions
        # i need to check what that is doing too
        json_dir = next(
            (
                candidate / "json_data"
                for candidate in (project_path, *project_path.parents)
                if (candidate / "json_data").is_dir()
            ),
            repo_root / "json_data",
        )

        print(
            f"RUNNING FOR PROJECT {project_path.name}"
            + (
                f" (output name: {output_process_name})"
                if output_process_name != project_path.name
                else ""
            )
        )

        try:

            # set tools in global state here
            set_tool_def()

            STATE = load_project_state(json_dir, targets_path=command_args.targets)
            STATE.set("TIME", f"{datetime.now():%Y%m%d_%H%M%S}")
            STATE.set("PROJECT_NAME", output_process_name)

            summary = trace_variable(
                project_path=project_path,
                summary_config=summary_config,
                index_only=command_args.index_only,
                resolver=command_args.resolver,

                # TODO: Find out what this cap actually does, i think its cap a on how many paths for a unique source to show in results?
                valueflow_path_cap=max(1, command_args.valueflow_path_cap),
                valueflow_concurrency=max(1, command_args.valueflow_concurrency),
                source_root=command_args.source_root,
            )

            # console.print(summary)

            graph_path = STATE.get("VISUALIZER_GRAPH_PATH")
            if graph_path and Path(graph_path).is_file():
                graph_paths.append(Path(graph_path))

        except (Exception, SystemExit) as exc:
            process_status = "failed"
            graph_path = STATE.get("VISUALIZER_GRAPH_PATH")
            if graph_path and Path(graph_path).is_file() and Path(graph_path) not in graph_paths:
                graph_paths.append(Path(graph_path))

            failures.append(
                {
                    "process_name": output_process_name,
                    "source_process_name": project_path.name,
                    "project_root": str(project_path),
                    "error": str(exc),
                }
            )

            if not command_args.continue_on_error:
                raise

            print(f"PROCESS FAILED; CONTINUING: {output_process_name}: {exc}")

        finally:
            _write_process_timing(
                output_process_name,
                process_started_at,
                status=process_status,
            )
            # A resolver may have written its discovery index immediately
            # before reporting an error.  Keep that evidence in the aggregate
            # batch index, but exclude stale output from an earlier run.
            candidate_index = process_results_dir(output_process_name) / "index"
            metadata_path = candidate_index / "index_metadata.json"
            if (
                metadata_path.is_file()
                and metadata_path.stat().st_mtime_ns >= batch_started_ns
                and candidate_index not in process_index_dirs
            ):
                process_index_dirs.append(candidate_index)
            STATE.reset()

    # A batch has two output layers: the existing per-process visualizer and
    # discovery indexes, plus one whole-repository build-index-shaped
    # directory.  The latter is deliberately built after all processes so it
    # can overlay the successful c-visualizer discoveries and rebuild one
    # cross-process graph.
    if batch_mode and (command_args.process_folder or command_args.source_root):
        aggregate_root = (
            command_args.source_root
            or command_args.process_folder
        )
        aggregate_dir = results_root() / "index"
        try:
            build_aggregate_index(
                source_root=aggregate_root,
                output_dir=aggregate_dir,
                process_indexes=process_index_dirs,
                process_count=len(projects_to_run),
                failed_processes=len(failures),
            )
            print(f"Whole-repository index written to {aggregate_dir}")
        except Exception as aggregate_exc:
            print(f"WHOLE-REPOSITORY INDEX FAILED: {aggregate_exc}")
            if not command_args.continue_on_error:
                raise

    if batch_mode or command_args.group_name:
        if not graph_paths:
            raise SystemExit("No graph snapshots were produced; group was not written.")

        batch_stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
        group_name = command_args.group_name or f"batch-{batch_stamp}"

        try:

            # TODO: Check how manifest works and what it stores etc
            group_path = write_group_manifest(
                results_root(),
                group_name,
                graph_paths=graph_paths,
                failures=failures,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        print(f"Combined process group written to {group_path}")
        print(
            "Open only this group with: "
            f"python frontend/server.py --group {group_name}"
        )

    if failures:
        raise SystemExit(
            f"{len(failures)} process(es) failed; successful snapshots were preserved."
        )

    sys.exit(0)
