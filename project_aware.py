# region Imports

import asyncio
import gc
import json
import multiprocessing
import os
import pickle
import re
import subprocess
import sys
import time
from collections import defaultdict
from parser.parser_files import parseFiles
from pathlib import Path
from pprint import pprint
from typing import Literal

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
from tree_sitter import Language, Parser
from tree_sitter_custom import language

from call_graph.call_graph import orchestrate
from call_graph.data_classes import CallTreeNode, custom_tree
from call_graph.gen_graph import make_graph
from client.llm import OllamaClient
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
from makefile_resolver.makefile_resolver import return_project_mapping
from models import (
    Combined,
    FunctionTokenCount,
    Stats,
    TokenCount,
    aiDetermined,
    outputModel,
    outputModelForReturn,
    outputModelOneHop,
)
from output_paths import process_results_dir, results_root, target_results_dir
from process_groups import (
    discover_processes,
    load_project_state,
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
from value_flow.queries import OneHopAnswer
from value_flow.resolver import IndexedSite, ValueFlowResolver
from typing import Any

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# endregion Imports


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
def extract_function_calls(code: bytes) -> list[str]:
    """
    RETURNS A LIST OF FUNCTION CALLED IN THIS CODE.
    """
    # import from tree_sitter_customustompp as tsc
    import tree_sitter_custom as tsc
    from tree_sitter import Language, Parser

    lang = Language(tsc.language())
    parser = Parser(lang)
    tree = parser.parse(code)

    calls: list[str] = []

    def traverse(node):
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                name = code[func_node.start_byte : func_node.end_byte].decode(
                    "latin-1", errors="replace"
                )
                calls.append(name)

        for child in node.children:
            traverse(child)

    traverse(tree.root_node)
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

    if not functions_to_detect:
        print("Data 'FUNCTION_TYPES' Not in state.")

    for file_name in project_structure:
        if file_name.endswith(".h"):
            continue

        bytes_content = trees[file_name][1]
        functions_called = extract_function_calls(bytes_content)

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


def llm_calls_one_hop(
    project_structure: dict[str, str],
    function_name_to_trace: str,
    argument_number: int,
    initial_context: str,
    expression: str,
) -> tuple[type[BaseModel], dict[str, any]]:
    """Resolve one call-site expression without asking for a main-to-target path."""
    state = State()
    data = {
        "user_prompt": """
Where does argument {argument_number} of {function_name_to_trace} get its value?
The expression at that position is: {expression}

INITIAL_CONTEXT:
{initial_context}
""",
        "system_prompt": """
You are a conservative C value-flow analyser. You answer ONE question about ONE
call site: where the named argument's value comes from. Do not follow callers of
the enclosing function -- that hop is handled for you.

Answer with a JSON object using EXACTLY these field names:

  kind         one of "VALUE", "PARAM", "EXTERNAL", "UNRESOLVED"
  value        the concrete literal, when kind is "VALUE"
  param_index  the 1-based parameter position, when kind is "PARAM"
  source_expr  the expression the value came from (always useful)

How to choose kind:

- "VALUE": the expression resolves to a concrete literal here. This includes a
  macro that expands to a literal, and a call to a function whose body you can
  read that returns a literal or macro. USE find_definition to read any function
  or macro you do not already see in the context -- a call you have not looked
  at is NOT automatically external.
    {{"kind": "VALUE", "value": "0x1002", "source_expr": "pick_file()"}}

- "PARAM": the value arrives unchanged as a parameter of the enclosing function.
  Give its 1-based position.
    {{"kind": "PARAM", "param_index": 1, "source_expr": "file_no"}}

- "EXTERNAL": the value genuinely originates outside the program -- a message or
  packet field, user input, a device/socket read, or a global written by another
  process. Only after find_definition has failed to reach a literal.
    {{"kind": "EXTERNAL", "source_expr": "msg->file_no"}}

- "UNRESOLVED": you cannot tell.

If several control-flow paths reach the call with different values, do not pick
the last textual assignment; answer "UNRESOLVED" instead.
""",
        "tools": state.get("TOOL_DEFINITION"),
        "tool_functions": state.get("TOOLS"),
        "project_structure": project_structure,
        "function_map": state.get("FUNCTION_MAP"),
        "output_model": outputModelOneHop,
    }
    client = OllamaClient(data=data)
    return client.start_tool_chain(
        prompt_data={
            "user_prompt": {
                "argument_number": argument_number,
                # start_tool_chain reads this key when it re-prompts for a
                # schema-valid answer; str.format ignores the unused extra.
                "argument_numbers": [argument_number],
                "function_name_to_trace": function_name_to_trace,
                "initial_context": initial_context,
                "expression": expression,
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

    base_url = os.environ.get("TRACER_LLM_BASE_URL", "http://175.28.230.22:54062/v1")
    model = os.environ.get("TRACER_LLM_MODEL", "gemma-4-31B")
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
    print(
        f"Unique-path report written to {path_report} "
        f"({len(all_paths_rows)} paths; {len(invocation_rows)} target invocations)"
    )
    return path_report


def run_with_retry(func, args=(), timeout=180, retries=2):
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
    )  # assuming that after filtering we are left only with one function
    dependent_function_indices = None
    dependent_function_get_upper = None
    if check_other_functions:
        dependent_function_indices = functions_identified.get(
            dependent_functions[0]
        ).get("indices")
        dependent_function_get_upper = functions_identified.get(
            dependent_functions[0]
        ).get("get_upper")
        print(
            "DEPENDENT_FUNCTION_INDICES",
            dependent_function_indices,
            "GET_UPPER",
            dependent_function_get_upper,
        )
    # return None
    stats_json_path = Path(
        f"/home/seigyo/c_repo/c_repo/results/csv_results/stats/{STATE.get('PROJECT_NAME')}_STATS.json"
    )
    (stats_json_path.parent / "stats").mkdir(parents=True, exist_ok=True)
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
        process_name=Path(project_path).name,
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
        semaphore = asyncio.Semaphore(20)

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
        semaphore = asyncio.Semaphore(20)

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
                        if not primary_args or primary_result
                        else None
                    )
                    return index, (primary_result, dependent_result)
                except Exception as exc:
                    print(f"LLM requests failed for path {index}: {exc}")
                    return index, (None, None)

        return dict(await asyncio.gather(*(run_pair(*request) for request in path_requests)))

    if len(path_nodes) > 0:

        # region GETTING DEPENDENT FUNCTION PATH FROM EACH FUNCTION PATH (APPLYING DFS IN IT AND GETTING LAST PATH)
        paths_to_dependent: list[list[str]] = []
        print_or_return_possible_paths_trees(
            paths=path_nodes,
            dependent_function=dependent_functions[0],
            result_path_list=paths_to_dependent,
        )  # returns the tree made from the nodes.
        # set the paths to dependent in this function ...
        #  endregion

        # region PARSING FOR DEPENDENT FUNCTION
        print(f"PARSING FOR DEPENDENT FUNCTION -> {dependent_functions[0]}")
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
            path_requests.append((
                index,
                primary_args,
                (
                    project_structure,
                    dependent_functions[0],
                    dependent_function_indices,
                    context_new,
                    new_path_str,
                    dependent_function_get_upper,
                ),
            ))
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
                    "process_name": Path(project_path).name,
                }
                print(" STEP - 1 DETERMINING THE CALL_TYPE")

                ans = llm_results[index][0]
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
                    "process_name": Path(project_path).name,
                }  # determined the type.
            # endregion
            else:
                # region WHEN FUNCTION_TYPE IS ALREADY DECIDED (ONLY CALL_GRAPH DATA CHANGES)
                call_graph_data = {
                    **call_graph_data,
                    "process_name": Path(project_path).name,
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
            ans = llm_results[index][1]

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
            if index < PATH_TO_START_WITH or ("pmf" in function and len(list_indices) == 0):
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
                "process_name": Path(project_path).name,
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
            if (
                "pmf" in function and len(list_indices) == 0
            ):  # in case of pmf functions and no list_indices.
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
            ans = llm_results[("primary", index)]
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
    function_pointer_args: dict,
    file_functions: dict,
    project_structure: dict[str, str],
    project_path: Path,
    path_cap: int = 100,
    llm_concurrency: int = 20,
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
    process_name = project_path.name

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

    # Build the small resolver configuration for THIS project.
    # Start with only functions actually detected in this project.
    # This avoids resolving every configured API from the JSON/state.
    valueflow_configs = {
        name: dict(configured.get(name, config))
        for name, config in functions_identified.items()
    }

    # A read/close API can depend on an open/create/register API.  Keep those
    # dependency configs even when the open API was not itself a direct target.
    # Add those dependency configs too, even if they were not direct seeds.
    for config in functions_identified.values():
        for dependency in config.get("dependent_functions") or []:
            if dependency in configured:
                valueflow_configs.setdefault(dependency, dict(configured[dependency]))

    # Aggregated LLM token/query stats for this whole resolver run.
    token_totals = {"Input_tokens": 0, "Output_tokens": 0, "Total_tokens": 0}
    query_stats: list[dict] = []

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

    async def resolve_one_hop(
        site: IndexedSite, argument_number: int, expression: str
    ) -> OneHopAnswer | None:
        """
        Resolve one argument expression at a specific call site.

        Example: for `foo(x)`, resolve what `x` means at that call location.
        """
        # The resolver reaches this callback only after its cheap syntax rules
        # could not explain the expression (literal/macro/local assignment/etc).
        path, context = context_for(site, get_upper=True)

        if not path:
            return None

        print(
            f"{ORANGE}  LLM one-hop{RESET} {site.file_name}:{site.line} "
            f"{site.callee_name} arg {argument_number} -> {expression!r}"
        )

        # First try the strict one-hop prompt/schema.  It answers only this
        # one expression: VALUE, PARAM, EXTERNAL, or UNRESOLVED.
        # It is designed for small local expression resolution.
        result = await asyncio.to_thread(
            run_with_retry,
            llm_calls_one_hop,
            (
                project_structure,
                site.callee_name,
                argument_number,
                context,
                expression,
            ),
        )

        if result:
            model, stats = result
            record_stats("one_hop", site, stats)

            model_data = model.model_dump() if hasattr(model, "model_dump") else model

            try:
                return OneHopAnswer(**model_data)
            except (TypeError, ValueError):
                pass

        # If the strict one-hop parser fails, retry using the older prompt.
        # This keeps valueflow compatible with cases the newer schema rejects.
        fallback = await asyncio.to_thread(
            run_with_retry,
            llm_calls,
            (
                project_structure,
                site.callee_name,
                [argument_number],
                context,
                "->".join(re.sub(r"\[([^\[\]]*)\]", "", node) for node in path),
                True,
            ),
        )

        if not fallback:
            return None

        model, stats = fallback
        record_stats("legacy_subproblem_fallback", site, stats)

        output = (model.model_dump() if hasattr(model, "model_dump") else model).get(
            "output", ""
        )

        # Legacy output is expected as comma-separated "index:value" pairs.
        # Extract only the requested argument number.
        for item in output.split(","):
            if ":" not in item:
                continue

            index, value = item.split(":", 1)

            if index.strip() != str(argument_number):
                continue

            cleaned = value.strip().strip('"')

            # Ignore control/status words if the model echoed them as values.
            if cleaned and cleaned.upper() not in {
                "UNRESOLVED",
                "EXTERNAL",
                "PARAM",
                "VALUE",
                "NO TARGET",
            }:
                return OneHopAnswer(kind="VALUE", value=cleaned)

        return None

    async def resolve_return_use(site: IndexedSite, function_name: str) -> str | None:
        """
        Resolve how a function return value is used at this call site.

        This is used for target configs that need return-value tracing instead
        of normal argument tracing.
        """
        # This is separate from argument tracing: it asks whether a returned
        # pointer/result is later used as a READF or WRITEF resource.
        path, context = context_for(site, get_upper=False)

        if not path:
            return None

        print(
            f"{ORANGE}  LLM return-use{RESET} {site.file_name}:{site.line} "
            f"{function_name}"
        )

        result = await asyncio.to_thread(
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

    async def resolve_handle_with_llm(
        site: IndexedSite, argument_number: int, dependencies: tuple[str, ...]
    ) -> list[OneHopAnswer] | None:
        """
        Resolve handle-style relationships using dependency/open-family functions.

        Example: a target uses a handle, and the handle may have been created by
        one of the configured dependent functions.
        """
        # Normal handle matching is syntactic: find the earlier open using the
        # same fcb/handle variable. This callback is only the last fallback.
        path, context = context_for(site, get_upper=True)

        if not path:
            return None

        dependency_text = ", ".join(dependencies)

        result = await asyncio.to_thread(
            run_with_retry,
            llm_calls_one_hop,
            (
                project_structure,
                site.callee_name,
                max(1, argument_number),
                context,
                f"handle binding for argument {argument_number}; resolve the configured open family {dependency_text}",
            ),
        )

        if not result:
            return None

        model, stats = result
        record_stats("handle_link", site, stats)

        data = model.model_dump() if hasattr(model, "model_dump") else model

        try:
            answer = OneHopAnswer(**data)
        except (TypeError, ValueError):
            return None

        return [answer] if answer.kind == "VALUE" else None

    resolved_count = [0]

    def report_seed(seed, rows, seconds: float) -> None:
        """
        Progress callback passed into ValueFlowResolver.

        Called once per resolved target invocation/seed.
        """
        resolved_count[0] += 1

        values = ", ".join(
            f"{row.fact.value} ({row.fact.origin_kind})" for row in rows
        )

        print(
            f"[{resolved_count[0]}/{len(resolver.seeds)}] {seconds:6.2f}s "
            f"{seed.target_function} {seed.site.file_name}:{seed.site.line}"
            f" -> {values or 'no target'}"
        )

    # The resolver is useful without an LLM.  It can still resolve literals,
    # macros, assignments, parameters, and many handle bindings syntactically.
    # Check whether the optional LLM endpoint is available.
    # If unavailable, resolver still runs syntax/static-only paths.
    llm_ready, llm_status = llm_endpoint_status()

    print(
        f"{BOLD}{GREEN if llm_ready else ORANGE}VALUE-FLOW LLM "
        f"{'READY' if llm_ready else 'DISABLED (syntax-only run)'}{RESET}: {llm_status}"
    )

    # Cache stores previously answered LLM subqueries for this process.
    # This avoids repeating expensive identical prompts across runs.
    cache_path = process_results_dir(process_name) / "query_cache.json"

    # Hand the prepared project index and the three optional LLM callbacks to
    # the actual value resolver. From this point, resolver.run() owns tracing.
    resolver = ValueFlowResolver(
        graph=graph,
        registry=registry,
        trees=trees,
        project_structure=project_structure,
        main_file_name=main_file_name,
        function_configs=valueflow_configs,
        macros=state.get("BUILDER_MACROS") or {},
        file_macros=state.get("MACROS") or {},
        one_hop_resolver=resolve_one_hop if llm_ready else None,
        return_use_resolver=resolve_return_use if llm_ready else None,
        handle_llm_resolver=resolve_handle_with_llm if llm_ready else None,
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
    records = await resolver.run()

    run_stats = {
        "resolver": "valueflow",
        "wall_seconds": round(time.perf_counter() - started_at, 3),
        "llm_concurrency": llm_concurrency,
        "seed_count": len(resolver.seeds),
        "fact_count": len(records),
        "answered_query_count": len(resolver.results),
        "llm_query_count": len(query_stats),
        "Tokens": token_totals,
        "queries": query_stats,
    }

    # Write machine-readable resolver outputs.  facts.csv keeps individual
    # values; paths.csv keeps every source-to-target provenance chain; the
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
                "launch_via": record.seed.launch_via,
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
    valueflow_concurrency: int = 20,
):
    STATE = State()
    project_path = Path(project_path)

    # region pickle caching

    # Toggle this FALSE during debugging/testing, otherwise it might use same tree made when parser/targets were not set correctly
    USE_PROJECT_STRUCTURE_PICKLE = True

    pickle_dir = Path(__file__).resolve().parent / "pickle_data/project_structures_pickle"
    pickle_dir.mkdir(exist_ok=True, parents=True)

    project_structure_path = pickle_dir / f"{STATE.get('PROJECT_NAME')}_include_v5.pkl"

    PROJECT_STRUCTURE = None
    potential_main_files: list[str] | None = None

    if USE_PROJECT_STRUCTURE_PICKLE and project_structure_path.exists():
        import pickle

        with open(project_structure_path, "rb") as f:
            PROJECT_STRUCTURE, potential_main_files = pickle.load(f)
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
        # {'../COMMON/jac_dbdef.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/jac/../COMMON/jac_dbdef.h'),
        #  'COMMON/Ffe.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/COMMON/Ffe.h'),
        #  'COMMON/type_defc.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/COMMON/type_defc.h'),
        #  'FILE/FFE_MNT.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/FILE/FFE_MNT.h'),
        #  'FILE/KF_NAME.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/FILE/KF_NAME.h'),
        #  'Mmi/Mmi.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/modern/include/Mmi/Mmi.h'),
        #  'Mmi/MmiDateD.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/modern/include/Mmi/MmiDateD.h'),
        #  'Scn/ScnCstmz.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/modern/include/Scn/ScnCstmz.h'),
        #  'svm_ssc_req.c': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm/svm_ssc_req.c'),
        #  'svm_usesw_get.c': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm/svm_usesw_get.c'),
        #  'svm_warnhv_get.c': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm4/svm_warnhv_get.c'),
        #  'svm_wbtn.c': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm/svm_wbtn.c'),
        #  'svmanlys.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm4/svmanlys.h'),
        #  'svmyeq.c': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm/svmyeq.c'),
        #  'table/table.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/modern/include/sedai1/table/table.h'),
        #  'tmm/tmm001_msg.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/tmm/tmm001_msg.h'),
        #  'tmm/tmm002_event.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/tmm/tmm002_event.h'),
        #  'tmm/tmm002_msg.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/tmm/tmm002_msg.h'),
        #  'tmm/tmm003_event.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/tmm/tmm003_event.h'),
        #  'tmm/tmm110d_event.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/tmm/tmm110d_event.h'),
        #  'tmm/tmm840_event.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/tmm/tmm840_event.h'),
        #  'tmm/tmm_msg.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/include/tmm/tmm_msg.h'),
        #  'usr/usr.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/modern/include/usr/usr.h'),
        #  'usr/usr_in.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/modern/include/usr/usr_in.h'),
        #  'xrs/xrserr.h': PosixPath('/home/seigyo/c_repo/c_repo/SoudenKeisei/SoudenKeisei/modern/include/sedai1/xrs/xrserr.h')}

        # potential_main_files:
        # ['svm001.c', 'svm001_kansi.c', 'svm001_kbtmsg.c', 'svm001_svminit.c']
        PROJECT_STRUCTURE, potential_main_files = return_project_mapping(
            show=False,
            project_path=project_path,
        )

        # stringify and make into dict
        PROJECT_STRUCTURE = dict(
            sorted(PROJECT_STRUCTURE.items(), key=lambda x: str(x[0]))
        )

        # Save to pickle for later reuse (for prod)
        if USE_PROJECT_STRUCTURE_PICKLE:
            import pickle

            with open(project_structure_path, "wb") as f:
                pickle.dump((PROJECT_STRUCTURE, potential_main_files), f)

    # endregion pickle caching

    potential_main_files = potential_main_files or []

    STATE.set("PROJECT_STRUCTURE", PROJECT_STRUCTURE)
    print("THE MAIN FILES ARE: ", potential_main_files)

    # main tree sitter parsing
    # output: dict file:(tree sitter tree, cleaned file contents)
    # TODO: Anaylyze logic later
    trees = Preprocess().preprocess(
        project_structure=PROJECT_STRUCTURE
    )

    STATE.set("TREES", trees)

    # converts all values in PROJECT_STRUCTURE keys to strings
    PROJECT_STRUCTURE = {
        key: str(PROJECT_STRUCTURE[key]) for key in PROJECT_STRUCTURE.keys()
    }

    print("LENGTH OF PROJECT_STRUCTURE", len(PROJECT_STRUCTURE))

    # this was set in main, from json data (see main function)
    FUNCTION_POINTER_ARGS = STATE.get("FUNCTION_POINTER_ARGS")

    # Dict of all functions in a file
    FILE_FUNCTIONS = {}

    # Actual project entry-point file, if found.
    main_file_name = None

    # Files that define main() but are not the real detected entry point.
    bad_main_files = []

    # Per-file macro definitions.
    macros = {}

    # Per-file #include relationships.
    file_includes: dict[str, list] = {}

    for files in PROJECT_STRUCTURE.keys():
        # Collect per-file macros and includes for later analysis.
        macros[files] = extract_all_macros(PROJECT_STRUCTURE[files])
        file_includes[files] = extract_includes(PROJECT_STRUCTURE[files])

        # Headers do not contain project entry-point functions.
        if files.endswith(".h"):
            continue

        # Local function definitions found in this source file.
        # TODO: analyze and clean these helper
        functions = get_local_function_definitions(
            code_bytes=trees[files][1]
        )

        # Keep the real main file from the detected potential main files.
        if "main" in functions.keys() and any(files == x for x in potential_main_files):
            main_file_name = files
            print("Found main file", main_file_name)

        # Mark extra/wrong main() files for removal.
        if "main" in functions and not any(files == x for x in potential_main_files):
            bad_main_files.append(files)

        # Store functions found in this file.
        FILE_FUNCTIONS[files] = functions

    # Remove wrong duplicate/test main files from the indexed project.
    # TODO: Find out why this was done, it must happen often to have code for this
    for bad_files in bad_main_files:
        del FILE_FUNCTIONS[bad_files]
        del PROJECT_STRUCTURE[bad_files]
        del trees[bad_files]

    STATE.set("FILE_FUNCTIONS", FILE_FUNCTIONS)
    STATE.set("FILE_INCLUDES", file_includes)
    STATE.set("MACROS", macros)

    # TODO: analyze this, how is this diff from above? waht this contains etc
    # TODO: We are not using the 3rd and 4th params, then why calc it? Or, further down the line its being made again and used, maybe use it and pass it to there 
    graph, registry, _, _ = build_complete_call_graph(
        project_structure=PROJECT_STRUCTURE,
        trees=trees,
        function_pointer_args=FUNCTION_POINTER_ARGS,
        file_functions=FILE_FUNCTIONS,
    )

    # TODO: Do this later
    collector = VisualizerCollector(
        process_name=project_path.name,
        process_root=project_path,
        project_structure=PROJECT_STRUCTURE,
        file_functions=build_complete_file_functions(trees, FILE_FUNCTIONS),
        main_file_name=main_file_name,
        library_functions=set((STATE.get("FUNCTION_MAP") or {}).keys())
        | set((STATE.get("FUNCTION_TYPES") or {}).keys()),
        run_id=STATE.get("TIME"),
    )

    collector.capture_call_graph(graph=graph, registry=registry)
    STATE.set("VISUALIZER_COLLECTOR", collector)

    graph_path = collector.write()
    STATE.set("VISUALIZER_GRAPH_PATH", graph_path)
    print(f"Complete source graph checkpoint written to {graph_path}")

    # TODO: Temporarily disabled for speed, bring it back later for prod
    # summary_config = summary_config or SummaryConfig.from_env()
    # if summary_config.enabled:
    #     try:
    #         summary_report = asyncio.run(summarize_collector(collector, summary_config))
    #         print(f"Bottom-up function summaries: {summary_report}")
    #     except Exception as exc:
    #         print(f"Function summarization unavailable: {exc}")
    #         for function_data in collector.functions.values():
    #             if not function_data.get("is_external") and not function_data.get(
    #                 "summary"
    #             ):
    #                 function_data["summary_error"] = str(exc)
    #         collector.write()

    # If its index only, it means we are only trying to capture source trees, not the unique target parameters, so return early here
    # we already have saved the visualizer in the state
    if index_only:
        return {}

    # This is subset of target functions json, it basically finds all the target funcs 
    # that are actually present in the paths, then only gives the subset here
    # the output shape is same as the json_data/mpf_data.json
    functions_identified = identify_funs_to_trace(
        project_structure=PROJECT_STRUCTURE,
        trees=trees,
    )

    if functions_identified == {}:
        print(
            f"{BOLD}{RED}NO FUNCTIONS IDENTIFIED IN THE PROJECT {project_path.name}.{RESET}"
        )
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
    if resolver == "valueflow":
        asyncio.run(
            make_value_flow_calls(
                graph=graph, # Callsite/FunctionNode custom graph
                registry=registry, # list of all functions
                trees=trees, # tree sitter trees
                functions_identified=functions_identified, # target functiosn in trees
                answers=answers, # to add answer inplace
                main_file_name=main_file_name, # starting point
                function_pointer_args=FUNCTION_POINTER_ARGS,
                file_functions=FILE_FUNCTIONS,
                project_structure=PROJECT_STRUCTURE,
                project_path=project_path,
                path_cap=valueflow_path_cap,
                llm_concurrency=valueflow_concurrency,
            )
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
                    function_pointer_args=FUNCTION_POINTER_ARGS,
                    file_functions=FILE_FUNCTIONS,
                    project_structure=PROJECT_STRUCTURE,
                    project_path=project_path,
                )
            )

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
        "--valueflow-path-cap",
        type=int,
        default=10000,
        help="Maximum provenance paths written per fact; the true count is retained.",
    )
    argument_parser.add_argument(
        "--valueflow-concurrency",
        type=int,
        default=10,
        help="Concurrent value-flow model queries (default 1, so the run is watchable).",
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

    # Fist init of app state
    STATE = State()

    for project_path in projects_to_run:

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

        print(f"RUNNING FOR PROJECT {project_path.name}")

        try:

            # set tools in global state here
            set_tool_def()

            STATE = load_project_state(json_dir)
            STATE.set("TIME", f"{datetime.now():%Y%m%d_%H%M%S}")
            STATE.set("PROJECT_NAME", project_path.name)

            summary = trace_variable(
                project_path=project_path,
                summary_config=summary_config,
                index_only=command_args.index_only,
                resolver=command_args.resolver,

                # TODO: Find out what this cap actually does, i think its cap a on how many paths for a unique source to show in results?
                valueflow_path_cap=max(1, command_args.valueflow_path_cap),
                valueflow_concurrency=max(1, command_args.valueflow_concurrency),
            )

            console.print(summary)

            graph_path = STATE.get("VISUALIZER_GRAPH_PATH")
            if graph_path and Path(graph_path).is_file():
                graph_paths.append(Path(graph_path))

        except (Exception, SystemExit) as exc:
            graph_path = STATE.get("VISUALIZER_GRAPH_PATH")
            if graph_path and Path(graph_path).is_file() and Path(graph_path) not in graph_paths:
                graph_paths.append(Path(graph_path))

            failures.append(
                {
                    "process_name": project_path.name,
                    "project_root": str(project_path),
                    "error": str(exc),
                }
            )

            if not command_args.continue_on_error:
                raise

            print(f"PROCESS FAILED; CONTINUING: {project_path.name}: {exc}")

        finally:
            STATE.reset()

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
