# Walkthrough — how the value-flow analyzer works, one step at a time

This doc is for someone who has to explain this repo tomorrow and did not have
time to read all of it. It walks the **value-flow resolver**
(`--resolver valueflow`) from the very start to the output, in the order the
code runs, and points at the exact file / function / line doing each job. The
old `legacy` path enumerator is ignored on purpose (it is kept only as a
fallback — see §15).

Read top to bottom once. Then use §19 (cheat-sheet) and §20 (weak spots) in the
meeting.

> Line numbers are from the versions read on 2026-08-30. If a line moved a
> little, search the function name — the names are stable.

---

# PART A — CONCEPTS

## 0. The whole tool in one paragraph

This is a **static analyzer** (reads source, never runs it). You give it:
(1) one or more **processes** (a folder with a `Makefile`), and (2) a list of
**targets** (a function name + which argument of it you care about). It finds
**every place** that function is called, and for each call it figures out
**every value** that argument can be — by reading C source, resolving macros
and enums, following variables back to where they were set, following function
parameters back to every caller, and matching file handles back to the
`open()` that made them. The output is a table of `(call location, argument,
value, where the value came from)`.

Why "value-flow" and not the old way: the old resolver listed **every path**
from `main()` to the target call and asked an LLM about each one. On a big
process that is thousands of paths = thousands of LLM calls. The value-flow
resolver starts **at the target call** and walks **backward**, following only
the edges that actually carry the value we want. Most arguments turn out to be
a literal or a macro right there, so the walk stops immediately and every path
that led there is irrelevant.

## 1. Words this repo uses (plain-English dictionary)

The code and old docs use heavy words. Here is what each means:

| Word | Plain meaning | Code |
| --- | --- | --- |
| **process** | one runnable program = a folder with a `Makefile`. e.g. `dyn600`. | `discover_processes`, `validate_processes` in `project_aware.py` |
| **target / target API / configured function** | a function name we want to trace, listed in a JSON file, with which argument index to trace. | `json_data/mpf_data.json` → `STATE["FUNCTION_TYPES"]` |
| **index / indices** | the 1-based argument position(s) to trace for a target. `"indices": [2]` = trace arg 2. | target JSON |
| **seed** | one *actual written call* to a target function found in the source. `open()` called in 3 spots = 3 seeds. | `Seed`, `value_flow/resolver.py:156`; `_enumerate_seeds:894` |
| **site / call site / IndexedSite** | one exact call in source: file + byte offset + line + the parsed argument expressions. | `IndexedSite`, `value_flow/resolver.py:84` |
| **expression** | one chunk of C code that can supply a value to an argument, e.g. `FILE_NO`, `42`, `p->fileno`. | `Expression`, `value_flow/resolver.py:43` |
| **query** | one small backward question. 4 kinds: `ArgQuery`, `ParamQuery`, `HandleQuery`, `ReturnUseQuery`. | `value_flow/queries.py` |
| **token** | a query's string id, used as the cache key and to join provenance. | `Query.token()` |
| **fact** | one concrete answer for one argument: the value + where it came from (file, line, expression, kind). | `Fact`, `value_flow/queries.py:110` |
| **origin_kind** | the *type* of source: `CONST`, `MACRO`, `CONST_TABLE`, `BOUNDED_SET`, `LLM_CANDIDATE`, `EXTERNAL_DATA`, `UNRESOLVED`, `RECURSIVE`, `EXTERNAL_ENTRY`, `UNKNOWN_INDIRECT`. | `OriginKind`, `value_flow/queries.py:27` |
| **resolution / ResolvedSeed** | one result row = (seed, argument, one fact, its paths). One seed → many resolutions if the arg can be several values. | `ResolvedSeed`, `value_flow/resolver.py:180` |
| **provenance** | "where did this value come from" — the chain of query steps from the source line forward to the target call. | `self.provenance`, `_add_provenance:2440` |
| **path** | one readable route `funcA -> funcB -> target` for a fact. A fact can have many. | `paths_for_fact:2478` |
| **handle** | a pointer to an opened resource, like `&fcb`. Read/close calls take a handle; we trace it back to the `open()`. | `value_flow/handles.py` |
| **reachable** | there is a call path from a known start function (root) to this function. | `_compute_reachability:764` |
| **root / entry point / lifecycle callback** | a function the OS/middleware calls to start the program: `main`, `pmf_main_H`, `pmf_start_H`, `pmf_end_H`, `pmf_term_H`, `pmf_abort_H`. | `ENTRY_FUNCTION_NAMES`, `project_aware.py:125` |
| **callback / registrar** | a function passed as an argument to a "register" function so it runs later. The graph has no plain call edge to it. | `function_callback_info.json` → `FUNCTION_POINTER_ARGS` |
| **launch_via** | how execution got into this code: `FORK`, `EVENT`, `SEMAPHORE`, `MESSAGE`, `TIMER`, `SIGNAL`, `INPUT`. | target `launch` + callback edge `launch_via` |
| **call_number** | for event-driven code, the event id — the 1st argument of `pmf_addevent` / `pmf_addvarevt` in the registration. | `call_number_for`, `value_flow/resolver.py:~2190` |
| **backwalk / reverse walk** | start AT the target call, walk toward callers, following only the value we care about. |  |
| **local backwalk** | fallback: enclosing function is not reachable from a root, but the value is 100% provable inside that same function anyway. Tagged so output never claims reachability. | `_locally_provable:1994` |
| **discovery index** | a comparison-only output format that matches the old `forkproc_checker/index` build so `analysis/step0.py` / `step1.py` can diff them. | `discovery_index.py` |

---

# PART B — THE DATA SHAPES

You asked for the shapes of what we work on. Here they are, field by field.

## 2. Parsed source: `trees`

After parsing, one dict:

```python
trees: dict[str, tuple[TreeSitterTree, bytes]]
#      "dyn600Init.c"  ->  (parsed syntax tree, cleaned source bytes)
```

The short key (`"dyn600Init.c"` or `"Dyn/DynReEneFileDef.h"`) is used
everywhere. The full disk path is in `PROJECT_STRUCTURE[key]`. Source bytes
are kept because we slice them for LLM context and to read exact expression
text.

## 3. Call graph: `graph` + `registry`

Built by `visualizer_export.build_complete_call_graph(...)` (wraps
`call_graph/call_graph.py` `CallGraphBuilder.build`), called at
`project_aware.py:2540`.

```python
registry: dict[str, FunctionNode]   #  unique_id -> the function
graph:    dict[str, list[CallSite]] #  caller unique_id -> every call it makes
```

### `FunctionNode` — a node (`call_graph/data_classes.py:14`)

| field | meaning |
| --- | --- |
| `name` | `"dyn600Init"` |
| `file_name` | short key `"dyn600Init.c"` (empty for external/library functions) |
| `file_path` | absolute path or `None` |
| `is_external` | `True` = not defined in our source (a library function) |
| `is_static` | C `static` (file-local) function |
| `macro_expansion` | another `FunctionNode` — set when the call went through a `#define` wrapper; this is the real function |
| `start_line`, `end_line` | line range of the definition |
| `.unique_id` (property) | `"[dyn600Init.c]dyn600Init"`, or just `name` if external. **This is the key used in `graph` / `registry` / everywhere.** |
| `.label`, `.label_with_line(line, callbacks)` | display strings like `[dyn600Init.c:478]dyn600Init` used in path output and LLM prompts |

### `CallSite` — an edge (`call_graph/data_classes.py`, `CallSite`)

| field | meaning |
| --- | --- |
| `callee` | `FunctionNode` being called |
| `line_number` | line of the call |
| `start_byte`, `end_byte` | exact byte range — makes two calls on the same line distinct |
| `callbacks` | `list[FunctionNode]` — functions passed **as arguments** at this call (old flat form) |
| `callback_records` | `list[dict]` — structured callback info: `{spelling, canonical, registrar, registrar_file, registrar_line, raw_text, start_byte, end_byte, diagnostic}` |

Callbacks are filled only when the callee is a **registrar** listed in
`FUNCTION_POINTER_ARGS` — `call_graph/call_graph.py` `_callback_registrar`
(`:357`), `_extract_callbacks` (`:492`), `_map_registrar_position` (`:460`
— maps a wrapper-macro argument back to the real registrar position).

## 4. The resolver's own working shapes (`value_flow/resolver.py:43-220`)

### `Expression` (`:43`)

```python
Expression(
  text      = "DynReGrpSetFNO",   # exact C text of this argument
  node      = <tree-sitter node>,  # or None for text generated from a macro expansion
  file_name = "dyn600Init.c",
  file_path = "/abs/.../dyn600Init.c",
  line      = 478,
)
```

### `FunctionInfo` (`:63`) — one indexed function definition

```python
FunctionInfo(
  function_id     = "[dyn600Init.c]dyn600Init",
  node            = FunctionNode(...),
  ast_node        = <tree-sitter function_definition>,  # or None if not found
  source          = b"...file bytes...",
  parameters      = ["argc", "argv"],   # formal param NAMES in order
  parameter_nodes = [<node>, <node>],   # for reporting param line numbers
)
```
This is what turns "the variable `fileno` inside `wrapper`" into "parameter 2
of `wrapper`" so we can jump to callers. Built by `_build_function_index`
(`:418`).

### `IndexedSite` (`:84`) — the main working unit

| field | meaning |
| --- | --- |
| `site_id` | `"dyn600Init.c:18234"` = file + start_byte. Stable id. |
| `caller_id` | unique_id of the function that contains this call |
| `callee_id`, `callee_name` | the function being called (after macro expansion) |
| `file_name`, `file_path`, `line` | where the call is written |
| `start_byte`, `end_byte` | exact range |
| `ast_node` | tree-sitter `call_expression` node |
| `source` | file bytes of the caller |
| `arguments` | `list[Expression]` positioned for the **expanded** callee — used when tracing parameters through the graph |
| `target_arguments` | `list[Expression]` exactly as written at the source call — used when the target is a function-like macro |
| `raw_call_site` | the smaller `CallSite` from the graph builder |
| `macro_name` | set if the source called a macro that expands to the real callee |
| `macro_args_unmapped` | `True` when the macro adds/reorders arguments so positions can't be trusted → forces the macro/LLM fallback (`_resolve_across_macro`) |
| `.argument(n)` / `.target_argument(n)` | 1-based getters, return `None` if out of range |
| `.is_configured_macro_target` | `macro_name == callee_name` |

Built by `_build_call_index` (`:618`). Macro argument mapping is done by
`_macro_call_arguments` (`:539`) — it actually substitutes the macro
parameters into the macro body, re-parses it with tree-sitter, and finds the
real call, so `#define FOO(a,b) bar(FILE, a, b)` maps correctly; it returns
`reliable=False` for token-paste (`##`), stringify (`#`), variadic, or arity
mismatch, which sets `macro_args_unmapped`.

### `CallerEdge` (`:138`) — one caller→callee link for backward walking

```python
CallerEdge(
  caller_id, callee_id, site_id,
  synthetic_callback = False,   # True = made from callback registration, not real C syntax
  launch_via         = "",      # "EVENT" etc, carried by a callback edge
  call_function      = "",      # canonical handler name for a callback edge
  callback_meta      = None,    # registrar provenance dict
)
```
Stored in `self.reverse_callers[callee_id]` (who calls me) and
`self.forward_edges[caller_id]` (who I call).

### `Seed` (`:156`) — one target call to trace

```python
Seed(
  site                 = IndexedSite(...),
  target_function      = "mpf_mfs_open_H",
  config               = {"indices":[2], "handle_index":1, "type":"OPENMF", ...},
  launch_via           = "FORK",
  call_function        = "dyn600Init",
  function_source_file = "/abs/.../dyn600Init.c",
  function_source_line = "-1 (Main function)" | "<lineno>" | "-1 (Local backwalk)",
  local_backwalk       = False,   # True = enclosing function not root-reachable, value still provable locally
)
```

### `ResolvedSeed` (`:180`) — one result row

```python
ResolvedSeed(
  seed, arg_index,
  fact             = Fact(...),
  operation        = "OPENMF" | "READF" | "WRITEF" | ...,
  call_number      = "2003" | None,
  paths            = [["pmf_main_H", "dyn600Init", "mpf_mfs_open_H"], ...],
  path_count       = 4,          # true count; paths list may be capped
  paths_truncated  = False,
  query_token      = "...",
  seconds          = 0.12,       # inclusive time of this fact's query chain
  legacy_labels    = [...],      # first path in old [file:line]name grammar
  legacy_paths     = [[...], ...],
)
```

## 5. `value_flow/queries.py` — the questions and the answers (read this file, it's small)

The whole reverse walk is made of these 4 query objects + `Fact` + one LLM
answer type. Every query has `.token()` → a compact JSON string used as the
cache key and provenance node id.

### `ArgQuery(call_site_id, arg_index, target=False)` (`:44`)

> "At **this one call**, what was passed in position N?"

- `arg_index` is **1-based** (matches the JSON config).
- `target=True` means "use the source-macro argument positions"
  (`site.target_argument(n)`); `target=False` uses expanded positions
  (`site.argument(n)`), used when climbing through ordinary calls.
- token: `["ARG", "<site_id>", <n>]` or `["ARG", "<site_id>", <n>, "TARGET"]`.
- Answered by `_resolve_argument` (`:~1050`) → `_resolve_expression`.

### `ParamQuery(function_id, param_index)` (`:64`)

> "What can **parameter N** of this function be?" → answer = ask every caller.

- token: `["PARAM", "<function_id>", <n>]`.
- Answered by `_resolve_parameter` (`:~1650`): for each non-callback edge in
  `reverse_callers[function_id]`, make an `ArgQuery(edge.site_id, n)` and
  union all the facts. If the function has **no callers at all**, it returns
  one `Fact(origin_kind="EXTERNAL_ENTRY", value=<param name>)` — meaning
  "this value enters from outside our code".

### `HandleQuery(call_site_id, arg_index, target=False)` (`:78`)

> "Which configured `open()` created the handle used at this read/close?"

- `arg_index` is the handle argument position; **`0` means the handle was
  ambiguous** (we could not tell which argument is the handle).
- token: `["HANDLE", "<site_id>", <n>]` (+ `"TARGET"`).
- Answered by `_resolve_handle` (`:~1810`).

### `ReturnUseQuery(call_site_id)` (`:97`)

> "Is the thing this call returns used for **reading** or **writing**?"

- Only used for configs with `"type": "WRITEF/READF"` (e.g. `scf_file_access`).
- token: `["RETURN_USE", "<site_id>"]`.
- Answered by `_resolve_return_use` (`:~2118`): syntax first
  (`_syntactic_return_use`), LLM only if the AST can't tell.

### `Fact` (`:110`) — the answer for one argument

| field | meaning |
| --- | --- |
| `value` | the resolved value as a string: `"3917"`, `"dyn600"`, `"NULL"` |
| `origin_kind` | see table below |
| `source_file`, `source_line`, `source_expr` | where the value was found (e.g. the `#define` line, or the literal) |
| `origin_query` | token of the query that found it (root of the provenance chain) |
| `source_site_id` | stable id of the source location |
| `resolved_by` | `"SYNTAX"` or `"LLM"` |
| `link_method` | how the value was linked: `""`, `VARTRACE`, `PARAM_CALLER`, `LOCAL_BACKWALK`, `TABLE_LOOKUP`, `WRAPPER_WRITE`, `STRING_LITERAL`, `MACRO_EXPANSION`, `LLM` |
| `metadata` | dict with extra structured proof for tables / wrapper writes / string flow / callback info |
| `.source_key` (property) | `(file, line, expr, kind, value, site_id)` — used to dedupe facts |

### `OriginKind` values (`:27`) — what each means

| value | meaning | trusted as exact? |
| --- | --- | --- |
| `CONST` | literal (`42`, `"abc"`, `NULL`) or a visible enum constant | yes |
| `MACRO` | resolved through a `#define` chain to a literal | yes |
| `CONST_TABLE` | one element of a proven constant array (`tbl[i]`) — one row per element | as evidence, not one exact path |
| `BOUNDED_SET` | a small finite set of possible values (multi-arm, string set, wrapper write) | as a set |
| `LLM_CANDIDATE` | the model suggested this value | never for the exact index |
| `EXTERNAL_ENTRY` | value enters as a parameter of a function that has no callers | no |
| `EXTERNAL_DATA` | value comes from outside code (config file, DB, network, a field read) | no |
| `UNKNOWN_INDIRECT` | call through a function pointer / unfollowable | no |
| `RECURSIVE` | the walk hit a cycle | no |
| `UNRESOLVED` | could not resolve, and nothing better to say (`HANDLE_AMBIGUOUS`, missing arg) | no |

### `OneHopAnswer` (`:148`) — the LLM's reply for one expression

```python
OneHopAnswer(
  kind        = "VALUE" | "PARAM" | "EXTERNAL" | "UNRESOLVED",
  value       = "3917" | None,
  param_index = 2 | None,       # only for kind="PARAM": keep tracing this parameter
  source_expr = "..." | None,
)
```

---

# PART C — THE PIPELINE, STEP BY STEP

## 6. Top-level flow

```
project_aware.py  __main__   (~line 2793)
  parse CLI  ->  pick process(es)  ->  load target JSON into STATE
  for each process:
      load_project_state(json_dir, targets_path)          process_groups.py
      trace_variable(project_path, resolver="valueflow")   project_aware.py:2191
        |
        |-- 3.  resolve Makefile        -> PROJECT_STRUCTURE, main files, include dirs, -D/-U
        |-- 4.  preprocess + tree-sitter -> trees
        |-- 5.  find entry points + callbacks -> entry_points, root diagnostics
        |-- 6.  build call graph        -> graph, registry
        |-- 7.  write visualizer snapshot (graph.json)   [--index-only stops here]
        |-- 8.  identify_funs_to_trace  -> functions_identified
        |-- 9.  build_target_site_inventory  (discovery-index scaffold)
        |-- 10. make_value_flow_calls(...)               project_aware.py:1597
        |         ValueFlowResolver(...).run()           value_flow/resolver.py
        |         write facts.csv / paths.csv / <process>.csv / logs / summary.md
        |-- 11. valueflow_records_to_facts -> write discovery index
        |-- 12. collector.rehydrate_interactions -> update graph.json
  (batch modes) write group manifest / aggregate index
```

### CLI process-selection modes (`project_aware.py:2800-2960`)

| flag | meaning |
| --- | --- |
| `--project DIR` | one process |
| `--projects A B C` | fixed list, run one by one, pinned into one group |
| `--process-folder ROOT` | walk `ROOT`, every folder with a `Makefile` = a process (`discover_processes`), run all |
| `--combine-runs NAME` | don't analyze; stitch already-made snapshots into a group |
| `--targets FILE` | use a versioned target spec instead of `json_data/mpf_data.json` |
| `--source-root DIR` | root that discovery-index paths are relative to |
| `--resolver valueflow` | use this engine (default is still `legacy`) |
| `--valueflow-concurrency N` | concurrent seed/LLM work (default 10) |
| `--valueflow-path-cap N` | max provenance paths written per fact (true count kept) |
| `--index-only` | build graph + snapshot, skip all target tracing |

List/folder modes reset global state between processes (`STATE.reset()`) and
write an immutable group manifest under `visualizer/groups/<group>/runs/...`
(`process_groups.py` `write_group_manifest`).

### Where the target list comes from

- `project_aware.py:2884`: walk **up** from the process folder looking for a
  `json_data/` directory; fall back to the repo's own `json_data/`.
- `state/load_data.py` `load_json_files`:
  - `mpf_data.json` → `STATE["FUNCTION_TYPES"]`
  - `function_callback_info.json` → `STATE["FUNCTION_POINTER_ARGS"]`
  - `combined_data.json` → `STATE["FUNCTION_MAP"]` (english notes about
    library functions, for LLM context / summaries)
- with `--targets`: `target_spec.py` `load_target_spec` (rejects duplicate
  keys, computes a sha256 `digest`) then `validate_target_spec` checks it
  against the 39-target build-index/wrapper contract (`EXPECTED_TARGETS`,
  `OPEN_POSITIONS`, etc.). A typo there is fatal so the target set can't
  silently shrink.

### One target entry, explained (`test_scada/json_data/mpf_data.json`)

```json
"scf_file_read": {
  "type": "READF", "launch": "FORK", "indices": [],
  "handle_index": 1, "get_upper": true,
  "dependent_functions": ["scf_file_open"]
}
```

| key | meaning |
| --- | --- |
| `type` | operation label copied into output (`Combined.type` in `models.py`) |
| `launch` | default `launch_via` when there is no callback |
| `indices` | 1-based argument positions to trace. Empty = this API carries no value argument of its own |
| `handle_index` | which argument is the resource handle |
| `dependent_functions` | other configured functions this one is linked to. For a *read*, these are the *open* APIs — we resolve the open's value, not this call's |
| `get_upper` | LLM-context hint: include caller bodies above the call (`true`) or only the return-type region (`false`) |
| `close_functions` | (build-index specs) the close APIs that end a handle binding |
| `discovery` | (build-index specs) comparison-only: maps each arg to an operation/lock name for the discovery index |

The example target we follow through this doc:

```c
mpf_mfs_open_H( &fcb, DynReGrpSetFNO, 0, 0, MPF_MFS_READLOCK );
//               ^arg1 handle          ^arg2 = the FNO we want
```
config: `{"type":"OPENMF", "launch":"FORK", "indices":[2], "handle_index":1,
"dependent_functions":[]}`.

---

## 7. Step: resolve the Makefile

**What:** find the process `Makefile`; from it get (a) the `.c` files this
process compiles, (b) the `-I` include directories, (c) the `-D`/`-U` macro
flags.

**Why:** one repo, many processes, shared headers. We must parse only this
process's files and resolve its `#include`s through its own include path.
Macro flags decide which `#if` branches are even active.

**Where:**
- `makefile_resolver/makefile_resolver.py` — `MakefileContext`,
  `return_project_mapping(project_path=...)`. Returns
  `(PROJECT_STRUCTURE, potential_main_files, srcs_paths)`.
  - `PROJECT_STRUCTURE`: `dict` short-key → absolute path, for **every** file
    involved (source + all headers, even outside `src/`).
  - `potential_main_files`: this process's own `.c` files (the Makefile SRCS).
  - `srcs_paths`: canonical absolute paths of those.
- `makefile_resolver/extract_includes.py` — `IncludeIndex`: filename → path
  and `"driver/spi.h"` → path lookups so include resolution is O(1).
- `get_project_preprocessor_flags(project_path)` (called
  `project_aware.py:2321`) reads `CPPFLAGS`, `CFLAGS`, `CCFLAGS`, `CDEFS`,
  `DEFS`, `DEFINES` and extracts `-D` / `-U` (linker flags are ignored).

**Cache:** `project_aware.py:2210-2290` pickles the result to
`pickle_data/project_structures_pickle/<name>_<pathhash>_include_v6.pkl`. Key
includes the absolute project path + Makefile/source fingerprint, so a stale
cache copied from another PC is detected and rebuilt
(`load_project_structure_cache` returns `None` → re-resolve). Disable with
`VISUALIZER_USE_PROJECT_STRUCTURE_PICKLE=0`.

---

## 8. Step: preprocess + parse (tree-sitter)

**What:** for each file, run `unifdef` (blanks inactive `#if` branches, keeps
line numbers), then parse with the tree-sitter C grammar. Output = `trees`.

**Why:** we need a real syntax tree; dead `#if 0` code must not pollute the
graph; byte offsets and line numbers must stay exact so results point at real
source.

**Where:** `helpers/Preprocess/preprocess.py` —
`Preprocess(defines=..., undefines=...)`,
`.preprocess(project_structure=..., expected_entry_names=...)`. Called
`project_aware.py:2327`.

**Compatibility fallback:** if a file's first parse has syntax errors, retry
with `-U_NO_PROTO -UNOP` (unless the Makefile set those on purpose). Keep the
retry only if it has fewer parse errors **and** still contains an expected
entry function. Documented in `analysis/change_name_for_purpose.md`. Reason:
old K&R dual `main` definitions (`#ifdef _NO_PROTO`) and `#ifdef NOP` split
`if` statements were breaking the parser and making live code look dead — see
`analysis/step0_report.md` §5.1 (80 of 225 `UNREACHABLE` records were this).

Per-file metadata (flags used, fallback yes/no, error counts before/after,
raw root candidates) is stored in
`STATE["PREPROCESSOR_CONFIG"]["file_metadata"]` and feeds the root
diagnostics.

---

## 9. Step: entry points and callbacks

**What:** decide where the program can start, so "is this target call
reachable?" has an answer.

**Where (entry points):** `project_aware.py:2405-2450`.
- `ENTRY_FUNCTION_NAMES` (`project_aware.py:125`): `main`, `pmf_main_H`,
  `pmf_start_H`, `pmf_end_H`, `pmf_term_H`, `pmf_abort_H`. Same set in
  `call_graph/call_graph.py` `get_entry_points`.
- Only a file that is one of this process's own SRCS (`_is_process_source`)
  can hold a root, so a shared library that defines `pmf_start_H` does not
  become a root for every process that links it.
- `entry_points: list[(file, func)]` — **every** lifecycle callback this
  process implements is a root, not just `main`.
- A file that defines `main`/`pmf_main_H` but is **not** a process source is
  deleted from the index as a bad duplicate (`bad_main_files`,
  `project_aware.py:2430`).

**Root diagnostics** (`project_aware.py:2460-2530`): if no root is found, each
source file is classified — `OK`, `ROOT_PARSE_FAILURE` (raw source has the
root but the parser lost it), `NO_ACCEPTED_ROOT`, `NO_PROCESS_ROOT`. Stored
as `STATE["ROOT_DIAGNOSTICS"]`. This is why an `UNREACHABLE` result can be
explained later.

**Where (callbacks):** `call_graph/call_graph.py`.
- `_callback_registrar(callee_name)` (`:357`): is this call to a registrar?
  Checks `FUNCTION_POINTER_ARGS` for the name or its macro expansion.
- `_extract_callbacks(...)` (`:492`): reads the argument at the configured
  position (`{"func_argument": [2]}` = arg 2), canonicalizes it through safe
  macro aliases (`_resolve_value_alias`, `:364`), and appends a
  `callback_record` to the `CallSite`. Wrapper-macro cases go through
  `_map_registrar_position` (`:460`).
- The registrar list is data: `json_data/function_callback_info.json` (test
  copy `test_scada/json_data/function_callback_info.json`):
  ```json
  { "scf_evt_register": {"func_argument":[2]},
    "scf_timer_start":  {"func_argument":[3]}, ... }
  ```

```
scf_evt_register("ALARM", 12, dyn600AlarmCB);
                             ^^^^^^^^^^^^^  arg 2 (0-based in JSON? no: 1-based position 3 here is example)
            -> callback_record { canonical: "dyn600AlarmCB", registrar: "scf_evt_register", ... }
```

The **synthetic edge** for that callback is added later, inside the resolver
(`_build_callback_edges`, `value_flow/resolver.py:701`), as a `CallerEdge`
with `synthetic_callback=True`, `launch_via` from the registrar's config, and
`callback_meta` carrying the registrar provenance.

---

## 10. Step: build the call graph + visualizer snapshot

`build_complete_call_graph(...)` → `graph`, `registry` (shapes in §3).

Then `VisualizerCollector` (`visualizer_export.py`) writes a self-contained
`graph.json` under
`results/csv_results/visualizer/<process>/runs/<timestamp>/graph.json`:
every function's exact source slice, every call edge, the `main` id, and the
list of functions not reachable from `main` (frontend "unreached shelf").

`--index-only` returns here (`project_aware.py` `if index_only: return {}`).

`identify_funs_to_trace` (`project_aware.py:192`): scan every non-header file
for calls to configured function names (`extract_function_calls` walks the
tree for `call_expression`). Returns `functions_identified` — the subset of
the target JSON that actually appears in this process, same shape as the JSON.
If empty → "NO FUNCTIONS IDENTIFIED", write an empty discovery index, done.

---

# PART D — THE RESOLVER

Everything below is `ValueFlowResolver` in `value_flow/resolver.py`,
constructed at `project_aware.py:1981` inside `make_value_flow_calls`.

## 11. Resolver construction and index build (`__init__`, `:273`)

Inputs: `graph`, `registry`, `trees`, `project_structure`, `entry_points`,
`function_configs` (the per-process target config, **plus** the configs of
any `dependent_functions` even if those were not themselves targets —
`make_value_flow_calls` builds this at `project_aware.py:1652`), `macros`
(`BUILDER_MACROS`), `file_macros` (`MACROS`), the 3 optional LLM callbacks,
`cache_path`, `path_cap`, `llm_concurrency`, `progress`.

A **cache fingerprint** is computed over `RESOLVER_VERSION`
(`"valueflow-roots-callbacks-phase4-v3"`, `:38`) + file_macros + enum_values
+ every file's bytes + function_configs. If it changes, the old
`query_cache.json` is dropped — so a semantics change never reuses stale
facts (e.g. facts made by the old proximity fallback).

Build order (printed to console, `:405-430`):

| # | method | line | builds |
| --- | --- | --- | --- |
| 1 | `_build_include_lookup_indexes` | `:2611` | O(1) filename/path lookups for include resolution |
| 2 | `_build_include_graph` | `:2644` | per-file `#include` → resolved-file edges. Exact-key then exact-path then unique-basename match; ambiguous = left unresolved (safer than importing the wrong header copy). `_collect_include_diagnostics` records unresolved includes. |
| 3 | `_build_enum_index` | `:2737` | every integer enum constant, per file and globally. Evaluates the small C integer-expression subset (`_evaluate_enum_expression`, `:2856` — literals, identifiers, `+ - * / % << >> & | ^ ~ ! unary`, and `NAME = prev+1` auto-increment). A name with **conflicting** values across files is dropped (`enum_ambiguities`) — a wrong exact value is worse than none. |
| 4 | `_build_function_index` | `:418` | `self.functions: dict[id, FunctionInfo]` (AST + param names) |
| 5 | `_build_file_static_index` | `:465` | file-scope `static` variable names per file (for a `static FCB` opened in one function, used in another) |
| 6 | `_build_call_index` | `:618` | every `CallSite` → `IndexedSite`; fills `self.sites`, `self.sites_by_caller`, `self.reverse_callers`, `self.forward_edges` |
| 7 | `_build_callback_edges` | `:701` | synthetic callback `CallerEdge`s |
| 8 | `_compute_reachability` | `:764` | BFS from `entry_points` over forward edges |
| 9 | `_enumerate_seeds` | `:894` | the list of target calls to resolve |
| 10 | `_load_cache` | `:942` | load `query_cache.json` if fingerprint matches |

### 11a. Reachability (`_compute_reachability`, `:764`)

```
entry_ids = ["[file]func" for (file,func) in entry_points if in registry]
(no entry_ids at all  ->  reachable = {} , everything is UNREACHABLE)

BFS 1 over ALL forward edges (incl. synthetic callback)  -> self.reachable
BFS 2 over forward edges, SKIPPING synthetic callback    -> self.direct_reachable
self.callback_only = reachable - direct_reachable
```

`reachability_kind(func_id)` → `"DIRECT_ROOT"` / `"CALLBACK"` / `""`.
`callback_metadata(func_id)` (`:808`) BFS's again to find the first callback
registration on the path to that function and returns its registrar
provenance (merged into the fact's metadata later).

`_launch_metadata(func_id)` (`:848`): BFS from roots; the first synthetic
callback edge on the path sets `launch_via` + `call_function` + source
file/line. This is how a fact ends up labeled `EVENT` vs `FORK`.

### 11b. Seed enumeration (`_enumerate_seeds`, `:894`)

For every `IndexedSite` whose `callee_name` is a configured target:

- **enclosing function reachable** → normal `Seed`. `launch_via` /
  `call_function` / source file+line from `_launch_metadata`. If the config
  has no `indices` but has a `launch` (process/event APIs with no value arg),
  keep that `launch`.
- **not reachable** → only make a seed if `_locally_provable(site)` (§13d)
  is true. That seed gets `launch_via="LOCAL_BACKWALK"`,
  `function_source_line="-1 (Local backwalk)"`, `local_backwalk=True`.
- **not reachable and not locally provable** → **no seed**. The target call
  becomes an `UNREACHABLE` row in the discovery index (see
  `analysis/step0_report.md` §5).

---

## 12. The scheduler (`run`, `:~2300`)

```
limit   = clamp(len(seeds), 2, llm_concurrency*2)
queue   = asyncio.Queue(maxsize=limit)
producer: push (index, seed) for every seed, then `limit` None sentinels
workers: `limit` tasks, each: pull item -> await _resolve_seed(seed)
                                       -> rows_by_seed[index] = rows
                                       -> progress(seed, rows, seconds)
if any worker raises -> record first_error, other workers drain queue but do nothing,
                        cancel all, re-raise
records = flatten rows_by_seed in ORIGINAL seed order (not completion order)
persist_cache()  ;  return _deduplicate_records(records)
```

All workers run on one event loop, so shared state (`results`, `in_flight`,
provenance, caches) is never touched by threads. When a worker is blocked
awaiting an LLM reply, other workers keep doing CPU-side tracing.
Concurrent LLM calls are separately capped by `self._llm_gate`
(`asyncio.Semaphore(llm_concurrency)`, used in `_await_llm`).

### `_resolve_seed(seed)` (`:~2360`)

```
operation = config["type"] or "NO DATA"
if operation == "WRITEF/READF":
    operation = resolve(ReturnUseQuery(site))   # READF / WRITEF / UNRESOLVED

handle_query = handle_query_for_seed(seed)      # not None iff config has dependent_functions
if handle_query:  queries = [handle_query]
elif config["indices"]:  queries = [ArgQuery(site, i, target=True) for i in indices]
else:  # no indices, no handle -> "NO TARGET"
    return one ResolvedSeed with Fact(value="NO TARGET", origin_kind="CONST")

for (arg_index, query) in queries:
    facts = resolve(query)                      # cached per token
    for fact in facts:
        if seed.local_backwalk and kind != UNRESOLVED:  fact.link_method = "LOCAL_BACKWALK"
        if callback_metadata(caller):                    fact.metadata |= callback_meta
        call_number = call_number_for(caller, provenance_functions(fact, query))
        rows.append(_resolved_seed(seed, arg_index, fact, operation, call_number, query))
```

So one seed → one query (usually) → several facts → several `ResolvedSeed`
rows.

### `resolve(query, stack)` — the caching front door

- `token = query.token()`
- if `token in stack` → return `_cycle_fact` (origin_kind `RECURSIVE`)
- if `token in self.results` → return cached facts
- else: single-flight via `self.in_flight[token]` future + `self._query_lock`
  so two workers asking the same question compute it once
- `_resolve_uncached` dispatches by query type
- store `self.results[token]`, record `self.timings[token]` (seconds
  inclusive of sub-queries, whether any sub-fact was `resolved_by=="LLM"`)

---

## 13. `_resolve_expression` — the priority ladder (the heart)

Given one `Expression` (e.g. `DynReGrpSetFNO`), tries these **in order**,
returns the first that produces facts (`value_flow/resolver.py`, method
`_resolve_expression`, right after `_resolve_across_macro`):

```
raw   = expression.text.strip()
value = strip_outer_parens(raw)         # "((x))" -> "x"   value_flow/handles.py

1.  _literal(value)?                     -> Fact(CONST)                         RETURN
      number / string / char / NULL / true / false / nullptr   (_literal, :2957)

2.  _resolve_table_expression(...)       -> [Fact(CONST_TABLE), ...] or None    RETURN if not None
      the expression is a call `foo(i)` and foo is a proven constant-table wrapper

3.  _resolve_macro(value, file)?         -> Fact(MACRO or CONST)                RETURN
      #define chain to a literal, OR a visible enum constant
      (CONST if it's an enum name, MACRO if it's a #define)

4.  if value is a plain identifier:
    4a. _wrapper_output_facts(site, value)   -> [Fact(CONST_TABLE/BOUNDED_SET)]  RETURN if not None
          value was written by an earlier `writes_table` wrapper call (e.g. ChaGetFileInfo(&value))
          AND a success-guard (`if (rc == -1) return;`) proves the write happened
    4b. _local_string_facts(site, value)     -> [Fact(CONST/BOUNDED_SET)]        RETURN if not None
          value is a local char buffer filled by `= "..."` / strcpy / bounded strncpy
    4c. parameter?  value in function.parameters  AND  _parameter_fast_path_safe
          -> ParamQuery(caller_id, k)  -> recurse into every caller           RETURN
    4d. local assignment?  _local_reaching_definitions(site, value)
          -> for each reaching definition expr, recurse _resolve_expression   RETURN if any

5.  _call_one_hop(site, query, raw)      -> ask the LLM (if enabled)
      answer VALUE    -> Fact(LLM_CANDIDATE, resolved_by=LLM)
      answer PARAM    -> ParamQuery(caller_id, param_index) -> recurse
      answer EXTERNAL -> Fact(EXTERNAL_DATA, resolved_by=LLM)
      answer UNRESOLVED / no LLM -> fall through

6.  give up:
      "(*" in raw  ->  Fact(UNKNOWN_INDIRECT)      (call through a pointer)
      else         ->  Fact(EXTERNAL_DATA)          (plain field/var read)
```

### 13a. Constant tables (steps 2 and 4a)

Rules live in `value_flow/value_rules.py` `DEFAULT_VALUE_RULES`:

```python
"DynREGetSchfno":     {"kind": "return_table"},   # returns tbl[i]
"Dxi_UpTbnFileOpen":  {"kind": "writes_table"},   # writes tbl[i] into an output arg
"ChaGetFileInfo":     {"kind": "writes_table", "output_args": [3,4], "error_values": ["-1"]},
```
Extra project rules can be added via the resolver constructor
(`value_rules=`), then `merge_value_rules`.

- `_resolve_table_expression` (`:1247`): the argument itself is a call
  `foo(i)`. `_table_values_for_function` (`:1303`) finds a
  `subscript_expression` (`tbl[i]`) inside `foo` that is in a `return`
  (for `return_table`) or in an assignment to an output parameter
  (`writes_table`). `_constant_table_values` (`:1378`) then reads the array
  declaration — must be `static const` with an `initializer_list` where every
  element is a literal or a resolvable macro; otherwise it bails
  (no partial tables). Each element → one `Fact(origin_kind="CONST_TABLE")`
  with `link_method="TABLE_LOOKUP"` and `metadata` = `{table_file,
  table_line, table_symbol, index_expression, bound, set_id, wrapper}`.
- `_wrapper_output_facts` (`:1429`): the argument is a plain variable that
  was **written** by an earlier `writes_table` wrapper call in the same
  function (`ChaGetFileInfo(1, sub, &iOpenFileNo, &iOpenSubNo)`).
  `_wrapper_output_values` (`:1473`) matches which wrapper parameter is our
  variable and reads that table. `_wrapper_success_guard` (`:1519`) requires
  proof the write happened: either the call is inside an `if(...)` whose body
  `return`s, or the pattern `rc = wrapper(...); if (rc == -1) return;`. This
  is the F4 fix — without the guard the resolver used to fall back to the
  variable's `= 0` initializer and report a wrong `0`.

### 13b. Macros and enums (step 3)

`_resolve_macro(name, file_name)` (`:2984`):
1. `_visible_enum_index(file_name)` (`:2829`) — enum constants visible from
   that file's include chain (`_visible_files` = the file + transitive
   `#include`s in BFS order, `:2723`). If the name is ambiguous there →
   return `None` (don't guess). If it's a known enum constant → return
   `(value, file, line)`.
2. `_all_macros(file_name)` (`:2965`) — `#define`s visible from that include
   chain (builder macros whose definition file is visible + per-file
   `MACROS`). Follow the `#define A B`, `#define B 3917` chain until a
   literal; if a link is not an identifier, bail.
3. `_macro_line` (`:3012`) re-reads the header to find the exact `#define`
   line for the fact's `source_line`.

**This is the include-graph-aware part.** `DynReGrpSetFNO` resolves to the
**current** `3917` from the active `DynReEneFileDef.h`, not `3917` vs a stale
`1077` from an archived copy of the same header — because the archived copy
is not in `dyn600Init.c`'s include chain. See `analysis/step0_report.md` §3.

### 13c. Local reaching definitions + branch merge (step 4d)

`_local_reaching_definitions(site, name)` (`:3051`):
- collect every `assignment_expression` / `init_declarator` to `name` that is
  **before** the target call (`node.start_byte < site.start_byte`).
- sort by position, take the **latest**.
- if that latest assignment is **not** inside an `if` that closes before the
  call → return just `[latest]`.
- if it **is** inside an `if` chain: walk up through the enclosing
  `if / else if / else` (`else_clause` wrapper handling), find the chain
  root, and call `_collect_branch_values(chain_root, candidates)` (`:3132`)
  — this returns the assigned value from **every live arm** (recursing into
  `else if` links). If **any arm has no else / no assignment**, it bails to
  the conservative single-value answer.

```c
if      (myshu==1) fno = DXI_FNO_INITMNG2;   // 2519
else if (myshu==2) fno = DXI_FNO_INITMNG3;   // 2525
else               fno = DXI_FNO_INITMNG;    // 2512
... mpf_mfs_open_H(&fcb, fno, ...);
```
→ `_collect_branch_values` returns all three expressions → 3 facts
`{2519, 2525, 2512}`. (`subagents/agent_final_report.md` F5 was a bug where
the middle arm was dropped; the else-if chain-walk here is the fix.)

`_parameter_fast_path_safe(function, name, before_byte)` (`:3023`): only take
the fast "it's a parameter, jump to callers" path if `name` is **not**
reassigned, incremented, or address-taken (`&name`) before the call —
otherwise fall to reaching-definitions which is more careful.

### 13d. Local-backwalk provability (`_locally_provable`, `:1994`)

Used only to decide whether an **unreachable** function's target call still
gets a seed. `_locally_provable_checked` (`:2007`) →
`_locally_provable_argument` → `_expression_locally_provable` (`:2059`):
accepts **only** literal, visible macro, or a variable whose every reaching
definition is itself locally provable (recursive). For handle targets: the
handle must bind to exactly one same-function open, whose every index arg is
locally provable. **No** cross-function edges, **no** proximity, **no** LLM.
So the value is source-valid *if the function runs* — it does not claim the
function runs.

---

## 14. `_resolve_parameter` — fanning out to callers (`:~1650`)

```
info    = self.functions[function_id]
callers = [e for e in reverse_callers[function_id] if not e.synthetic_callback]

if not callers:
    return [ Fact(value=<param name>, origin_kind="EXTERNAL_ENTRY",
                  source_line=<param line>) ]        # value enters from outside our code

facts = []
for edge in sorted(callers, by site_id):
    child = ArgQuery(edge.site_id, param_index)      # ordinary (non-target) positions
    _add_provenance(child, this ParamQuery)
    for f in resolve(child):
        facts.append(f  with  link_method = f.link_method or "PARAM_CALLER",
                              metadata += {parameter_caller, caller_reachable})
return facts
```

Note: callback edges are **excluded** here — a parameter value cannot flow in
through a callback registration. `caller_reachable` in metadata lets a
downstream reader see if a contributing caller was itself reachable.

The walk climbs until each branch hits a literal / macro / a function with no
callers (→ `EXTERNAL_ENTRY`) / a cycle (→ `RECURSIVE`). Only value-carrying
edges are followed, which is the whole speed argument vs the legacy
enumerator.

---

## 15. `_resolve_handle` — read/close → back to open (`:~1810`)

`handle_query_for_seed(seed)` (`:1776`): the config's `dependent_functions`
(minus itself, keeping only configured ones) are the "open family".
`_handle_candidates(site, deps)` (`:1740`): use the explicit `handle_index`
if set; else find which argument position(s) of this call match (by
`normalise_handle`) an argument of an earlier open-family call in the same
function. If exactly one → that index; if 0 or >1 → `arg_index = 0`
(ambiguous, but still a query so a visible `HANDLE_AMBIGUOUS` fact can come
out).

`normalise_handle(expr)` (`value_flow/handles.py`): `&fcb`, `(fcb)`,
`(FCB*)&fcb`, `fcb[slot]` all → `"fcb"`. But `ctx->fcb` stays `ctx->fcb`
(struct field identity kept), and `p->fcb` ≠ `p->other`.

`_resolve_handle` order:

```
root = normalise_handle(handle argument text)

1. same-function binding:  _binding_opens(caller_id, root, before=site.start_byte, deps)  (:1956)
     = open-family calls in this function, using the same root, BEFORE this call,
       AFTER the last close() of that same root.
   -> for each such open, ArgQuery(open.site_id, index, target=True) for its config indices
   -> facts, link_method = "VARTRACE"

2. root is a PARAMETER of this function:
   -> for every non-callback caller edge: HandleQuery(edge.site_id, param_index)
      (recurse: which open made the handle the caller passed in?)
   -> link_method = "PARAM_CALLER", metadata += {parameter_caller, caller_reachable}

3. root is a global / struct field / file-static:
     ( "->" in root  or  "." in root  or  not a local var  or  file-static )
   -> search opens with matching root in EVERY reachable function
      (for file-static: only functions in the same file)
   -> link_method = "VARTRACE"

4. LLM handle fallback:  handle_llm_resolver(site, arg_index, deps)
   -> Fact(LLM_CANDIDATE, link_method="LLM")

5. nothing:  Fact(UNRESOLVED, value="HANDLE_AMBIGUOUS")
```

`_proximity_opens` (`:1928`) — the old "just use the nearest open in an
ancestor function" heuristic — is **deliberately not called**. Comment at
`:1928` explains: proximity is not ownership; it manufactured false exact
values (the SVM records). Kept only so old debug callers don't crash.

---

## 16. Return-use and call_number

### `_syntactic_return_use(site)` (`:2118`)

Look at the AST parent of the call:
- call result is on the **left** of an assignment → `WRITEF`
- `x = call(...)` where `x` is a plain identifier →
  `_classify_later_pointer_use(site, x, after)` (`:2172`): scan later in the
  function for `*x = ...` or `x->... = ...` → `WRITEF`, else `READF`
- `type *p = call(...)` → same later-use check
- `*call(...) = ...` / `call(...)->f = ...` → `WRITEF`
- anything else (bare statement, condition, nested) → `None` → ask the LLM

`_resolve_return_use` caches per site in `self._operation_cache`.

### `call_number_for(function_id, preferred_functions)` (`:~2190`)

Event id for event-driven code = the **1st argument of `pmf_addevent` /
`pmf_addvarevt` / `pmd_addvarevt`** (or `scf_evt_post` / `scf_var_evt`, or
any configured name matching `*addevent*` / `*addvarevt*` / `*evt_post` /
`*var_evt`). Search order:
1. the target's own function, then the functions on the fact's provenance
   chain (`preferred_functions`, if reachable),
2. then BFS backward through reachable callers.

`_call_number_in_function` (`:~2260`): find the first such event call in that
function, `resolve(ArgQuery(event_site, 1))`, prefer a `CONST`/`MACRO` fact.
Result cached in `self._call_number_cache`.

---

## 17. When the LLM is used, and every outcome

The resolver runs fully **without** an LLM (literals, macros, enums, local
assignments, parameters, most handle bindings are pure syntax).
`llm_endpoint_status()` (`project_aware.py:727`) checks the endpoint once;
if down, the 3 callbacks are passed as `None` and the ladder just skips
step 5.

`_await_llm(callback, *args)` (`:~1700`): wraps every call in the
`self._llm_gate` semaphore (cap = `llm_concurrency`) and a `try/except` — a
model/transport failure degrades **that one query** to its syntactic answer,
never aborts the run.

### Callback 1 — one-hop expression (`resolve_one_hop`, `project_aware.py:~1740`)

Called from `_call_one_hop` (`:~1730`), only after ladder steps 1–4 failed.

1. `run_context(site, get_upper=True)` builds a small source slice around the
   call (see §18).
2. First tries the **strict one-hop** prompt (`llm_calls_one_hop`,
   `project_aware.py:660`) → schema `outputModelOneHop` (`models.py:29`) →
   `OneHopAnswer`.
3. If that parse fails, retries the **legacy** prompt (`llm_calls`,
   `project_aware.py:373`) and pulls just the requested `index:value` pair
   out of its comma-separated `output`.

| `OneHopAnswer.kind` | resolver does | fact |
| --- | --- | --- |
| `VALUE` | take it | `Fact(origin_kind="LLM_CANDIDATE", resolved_by="LLM")` — evidence only, never exact index |
| `PARAM` (+`param_index`) | `ParamQuery(caller_id, param_index)` → recurse into callers | whatever that resolves to (can be a real `MACRO`/`CONST`) |
| `EXTERNAL` | value from outside code | `Fact(origin_kind="EXTERNAL_DATA", resolved_by="LLM")` |
| `UNRESOLVED` / none | fall through to ladder step 6 | `Fact(EXTERNAL_DATA` or `UNKNOWN_INDIRECT)` |

The legacy system prompt (`project_aware.py:373-560`) is a long
"static backward tracer" spec: read the CALL_GRAPH, pick the call marked
`/*CONSIDER THIS CALL*/` at every hop, trace literal → variable → parameter
→ macro, stop at the first literal, also resolve `call_number` from
`pmf_addevent`. It has a `find_definition` tool (one call per symbol).

### Callback 2 — return use (`resolve_return_use`)

Only for `type: "WRITEF/READF"`. Uses the "with return" branch of
`llm_calls` (`project_aware.py:560-620`, schema `outputModelForReturn`).
Answer `READF` / `WRITEF` / `UNRESOLVED`.

### Callback 3 — handle link (`resolve_handle_with_llm`)

Last resort in `_resolve_handle` step 4. Asks the one-hop model to name the
open-family binding. `VALUE` → `LLM_CANDIDATE` fact.

### Cache

Every resolved query token → `self.results`, persisted to
`<process>/query_cache.json` (`persist_cache`, `:969`; schema_version 2 +
fingerprint). Reused next run unless sources / target config / resolver
version changed.

**Meeting rule:** anything from the model has `origin_kind == "LLM_CANDIDATE"`
or `resolved_by == "LLM"`. The discovery / comparison index only trusts
`CONST` / `MACRO` / syntactic facts. `PARAM` answers are the exception — they
send the walk back to real source, and what it finds there can be exact.

---

## 18. LLM context building (`parser/parser_files.py`)

`make_value_flow_calls` turns one `IndexedSite` back into the old
`[file:line]name` path-label list (`context_for`, `project_aware.py:~1707`),
then `parseFiles(...).parse_for_path(path, get_upper=...)` builds the source
slice:

- For each function on the path, read its body between the relevant lines,
  split into `header / body / closing` (`extract_function_parts`).
- The exact call the walk cares about is marked with a
  `/*CONSIDER THIS CALL*/` comment so the model uses that call site and
  ignores sibling calls to the same function.
- `get_upper=True` (default, from the target's `get_upper`): include caller
  bodies **above** the call, plus a `//name=value` list of every constant
  macro used in the slice, plus `/*INFO ABOUT MACRO EXPANSIONS AND
  CALLBACKS*/` comments. Used for argument tracing.
- `get_upper=False`: only the region from the call to the function end —
  enough to see what happens to the return value. Used for return-use.

CPU-side prompt building runs on a dedicated `context_executor` pool and the
blocking model wait on a separate `llm_executor` pool so they don't block
each other or the event loop (`project_aware.py:~1690`).

---

# PART E — PROVENANCE, DEDUPE, OUTPUT

## 19. Provenance — how "where did this come from" is tracked

`self.provenance: dict[str, set[str]]` maps **child token → set of parent
tokens**, i.e. "the child answered a question the parent needed". Direction
is source→target. Filled by `_add_provenance(child, parent)` (`:2440`) every
time the ladder recurses (parameter jump, local assignment, handle open,
LLM PARAM).

`_label_query(query)` (`:2447`): human label per token —
`[file:line]caller->callee arg N`, `func.param2(name)`, `[file:line]callee
return`.

`_provenance_token_paths(fact, destination)` (`:2493`): start at
`fact.origin_query`, walk **forward** through `provenance` until reaching the
target query token.
- `count_paths` (memoized) = the true number of distinct routes — this is
  `path_count` in the output, even when the list below is capped.
- `collect` gathers actual paths, stopping at `self.path_cap`
  (`--valueflow-path-cap`, default 10000).
- if `count == 0` (no recorded chain, e.g. a literal right at the target) →
  `count = 1`, path = `[destination]`.

`paths_for_fact` (`:2478`) → label paths; `legacy_paths_for_fact` (`:2566`)
→ same paths rendered in the old `FunctionNode.label` grammar
(`_legacy_labels_for_tokens`, `:2571`) because the wiki/chat layer can only
parse that grammar. `provenance_tokens` (`:2539`) → one chain, ordered
source→target, used for the per-fact log and for `_provenance_functions`
(`:2590`, the caller list handed to `call_number_for`).

## 20. Dedupe (`:3226`, `:3233`)

- `_deduplicate_facts`: key = `source_key + (link_method, resolved_by)`.
  Same value from the same source line via the same method = one fact.
- `_deduplicate_records`: key = `(site_id, arg_index, fact.source_key,
  operation, launch_via)`. On a collision the paths / legacy_paths are
  merged, `path_count` summed, `paths_truncated` OR-ed.
- `fact_id(record, process_name)` (`:3264`): `"fact:" + sha1(process, target,
  site_id, arg_index, *source_key)[:20]` — stable id joining `facts.csv` and
  `paths.csv`.

## 21. Output files (`value_flow/outputs.py` `write_outputs`, `:216`)

Under `results/csv_results/visualizer/<process>/` (legacy feed at
`results/csv_results/` root):

| file | one row per | key columns / notes | code |
| --- | --- | --- | --- |
| `facts.csv` | (target call, argument, source value) — **the answer** | `fact_id`, `process_name`, `function_name`, `target_site_file`, `target_site_line`, `target_site_id`, `arg_index`, `value`, `origin_kind`, `source_file`, `source_line`, `source_expr`, `type`, `launch_via`, `call_function`, `call_number`, `link_method`, `metadata` (JSON), `path_count`, `resolved_by` | `FACT_COLUMNS`, `value_flow/outputs.py:17` |
| `paths.csv` | one source→target route for a fact | `fact_id`, `path_index`, `path` (`a -> b -> c`), `path_length` | `PATH_COLUMNS` |
| `<process>.csv` (root) | values combined per target **invocation**, old format the visualizer + wiki read | `process_name`, `function_name`, `target_number->ans`, `call_number`, `target_number->path_str`, `launch_via`, `call_function`, `type`, `function_name_src->path/line`, `target_name_src->path/line` | `LEGACY_COLUMNS`, `_legacy_rows` (`:88`) |
| `truncated_paths.log` | facts that hit the path cap (empty = good) | | |
| `summary.md` | run stats table + origins breakdown + slowest resolutions + "what each file is" | | end of `write_outputs` |
| `logs/000_summary.log` | every fact, slowest first, model-call count | | `write_trace_logs`, `:150` |
| `logs/<n>_<target>.log` | one resolution: target→source, timed per step, `LLM`/`SYNTAX` per step | | `write_trace_logs` |
| `query_cache.json` | resolved query tokens, reused next run | | `persist_cache` |
| `run_stats.json` | seeds, queries answered, model calls, tokens, wall time, end-to-end + parsing time | | `project_aware.py` after `resolver.run()` + at end of `trace_variable` |

### `_legacy_rows` (`value_flow/outputs.py:88`) — how multi-arg targets combine

Groups records by `(site_id, operation, launch_via, call_function,
call_number)`. For a target with **several** configured indices (e.g.
`scf_tag_write` indices `[2,3]`), it takes the cartesian **product** of each
index's possible (record, path) choices and writes one row per combination,
with `target_number->ans` = the values joined by `_` (e.g. `svm300d_0`).
Different source paths stay as different rows.

### One `facts.csv` row for our example

```
fact_id        = fact:1a2b3c...
process_name   = dyn600
function_name  = mpf_mfs_open_H
target_site_file / line = /abs/.../dyn600Init.c : 478
target_site_id = dyn600Init.c:18234
arg_index      = 2
value          = 3917
origin_kind    = MACRO           # or CONST if DynReGrpSetFNO is an enum constant
source_file / line = /abs/.../Dyn/DynReEneFileDef.h : 209
source_expr    = DynReGrpSetFNO
type           = OPENMF
launch_via     = FORK
call_function  = dyn600Init
call_number    = NA
link_method    =                 # blank for a direct macro; VARTRACE / PARAM_CALLER / LOCAL_BACKWALK / TABLE_LOOKUP / ...
metadata       = {}
path_count     = 4
resolved_by    = SYNTAX
```

## 22. Back into the visualizer + the discovery index

- `collector.rehydrate_interactions(<process>.csv, {func: indices})`
  (`project_aware.py`, end of `trace_variable`) reads the legacy CSV back and
  adds producer/consumer / file-access edges onto `graph.json`.
- **Discovery index** (comparison mode, `--targets` spec with a `discovery`
  block): `valueflow_records_to_facts(records, target_sites, spec, ...)` then
  `discovery_index.py` `write_discovery_index` → `<process>/index/` with 16
  JSON artifacts + `discovery_facts.csv`. Built even if the resolver raised
  (evidence is kept). Folder/list runs also produce an aggregate
  `results/index/` (`aggregate_index.py`).
- `analysis/step0.py` (direct literal/macro only) and `analysis/step1.py`
  (indirect: variables, params, handles, tables, LLM) diff
  `discovery_facts.csv` against the old `forkproc_checker/index` build.
  Read-only, never run the pipeline. `analysis/analysis_handoff.md` has the
  canonical input paths and the current counts.

---

# PART F — WORKED EXAMPLES

## 23. Full trace of the example (macro, easy case)

```
TARGET  mpf_mfs_open_H arg 2   at  dyn600Init.c:478

Step 3  Makefile: SRCS has dyn600Init.c ; -I dirs ; -DNOP
        makefile_resolver/makefile_resolver.py return_project_mapping
Step 4  preprocess+parse -> trees["dyn600Init.c"] = (tree, bytes)   (no fallback needed)
Step 5  entry_points = [("dyn600Main.c", "pmf_main_H")]
        dyn600Init registered via pmf_addevent? -> synthetic callback edge if so
Step 6  graph: registry["[dyn600Init.c]dyn600Init"] ; edge to mpf_mfs_open_H at byte 18234
Step 11 resolver indexes:
          enum index: DynReEneFileDef.h  DynReGrpSetFNO = 3917
          IndexedSite "dyn600Init.c:18234"  callee mpf_mfs_open_H
          reachable? pmf_main_H -> ... -> dyn600Init : YES (direct_reachable)
          seed: launch_via=FORK, call_function=dyn600Init
Step 12 _resolve_seed:
          config indices=[2], no dependent_functions
          -> ArgQuery(site, 2, target=True)
          _resolve_expression("DynReGrpSetFNO"):
            1 literal?   no
            2 table?     no
            3 macro/enum? YES -> _visible_enum_index("dyn600Init.c")
                              -> DynReEneFileDef.h:209  DynReGrpSetFNO -> "3917"  (CONST, it's an enum)
          Fact(value="3917", origin_kind=CONST, source=DynReEneFileDef.h:209,
               source_expr="DynReGrpSetFNO", resolved_by=SYNTAX, link_method="")
        no provenance recursion happened -> path_count via count_paths = 0 -> forced to 1
        paths_for_fact: count_paths from roots to this site = 4 real routes
Step 21 facts.csv row (arg_index=2, value=3917, CONST) ; logs/001_*.log
        <process>.csv row ; graph.json rehydrated
```

## 24. Same call, but the FNO is a wrapper parameter (fan-out case)

```c
// dyn600Init.c
void dyn600OpenOne(int fileno) {
    mpf_mfs_open_H(&fcb, fileno, 0, 0, MPF_MFS_READLOCK);   // <- seed, arg 2 = fileno
}
void dyn600Init(void) {
    dyn600OpenOne(DynReGrpSetFNO);   // 3917
    dyn600OpenOne(DynReCtlStaFNO);   // 3919
    dyn600OpenOne(nOpt ? 3940 : 3951);
}
```

```
ArgQuery(open_site, 2, target)
  _resolve_expression("fileno")
    literal? no ; table? no ; macro? no
    identifier -> is "fileno" a parameter of dyn600OpenOne?  YES, param 1
      _parameter_fast_path_safe? (fileno never reassigned/&-taken) YES
      -> ParamQuery("[dyn600Init.c]dyn600OpenOne", 1)     _add_provenance(child, ArgQuery)
         _resolve_parameter:
           callers = 3 edges (the 3 dyn600OpenOne(...) calls)
           edge 1: ArgQuery(call1_site, 1) -> _resolve_expression("DynReGrpSetFNO") -> CONST 3917
           edge 2: ArgQuery(call2_site, 1) -> CONST 3919
           edge 3: ArgQuery(call3_site, 1) -> _resolve_expression("nOpt ? 3940 : 3951")
                     not a literal/macro/identifier -> LLM one-hop or -> EXTERNAL_DATA
                     (a ternary of two literals: the one-hop model typically returns
                      one VALUE; without LLM it's EXTERNAL_DATA raw text)
         -> facts: [3917, 3919, (3940/3951 or raw)]   each link_method="PARAM_CALLER"
-> 3 (or 4) ResolvedSeed rows for ONE seed. facts.csv gets 3-4 rows, same target_site_id.
paths.csv: each fact has paths like  pmf_main_H -> dyn600Init -> dyn600OpenOne -> mpf_mfs_open_H
```

Key point for the meeting: we did **3 argument resolutions**, not "every path
from `main` to those 3 call sites". If 500 paths reach `dyn600Init`, still 3.

## 25. Handle case (read → open)

```c
mpf_mfs_open_H(&fcb, DynRePfmSetFNO, 0, 0, MPF_MFS_WRITELOCK);   // FNO = 3940
...
mpf_mfs_updaterecm(&fcb, rec);            // <- SEED: config type RECF, dependent_functions=[open family]
mpf_mfs_close(&fcb);
```

```
handle_query_for_seed: deps = open family present in config
  _handle_candidates(updaterecm_site, deps):
    config handle_index = 1 -> [1]
  HandleQuery(updaterecm_site, 1, target=True)

_resolve_handle:
  root = normalise_handle("&fcb") = "fcb"
  1. _binding_opens(caller, "fcb", before=updaterecm.start_byte, deps):
       opens of the same "fcb" before this call, after the last close of "fcb"
       -> the mpf_mfs_open_H at the top   (the close is AFTER, so it doesn't cut it)
     for that open: config indices = [2]
       ArgQuery(open_site, 2, target=True) -> _resolve_expression("DynRePfmSetFNO")
         -> macro/enum -> 3940 (CONST)
     Fact(value="3940", link_method="VARTRACE")
```

Every read/update/close on `&fcb` between that open and its close resolves to
the **same** open → same value, one real backwalk (cached by token).

## 26. Local backwalk (unreachable function)

`dif901IntDll.c:200`:
```c
static void dif901LoadScl(void) {          // no caller reaches this from any root
    mpf_mfs_open(&fcb, NULL, DifSclDllDbNo, 0, 0, MPF_MFS_READLOCK);
    mpf_mfs_readrec(&fcb, ...);             // <- target site
}
```

```
_enumerate_seeds: caller "[dif901IntDll.c]dif901LoadScl" not in self.reachable
  _locally_provable(readrec_site):
    deps = open family ; _handle_candidates -> [1] ; _binding_opens -> exactly the open above
    open indices = [3] (mpf_mfs_open) ; _locally_provable_argument(open, 3):
      "DifSclDllDbNo" -> visible macro? YES -> provable
  -> seed created, launch_via="LOCAL_BACKWALK", local_backwalk=True

_resolve_seed: HandleQuery -> _resolve_handle step 1 -> open arg 3 -> macro -> Fact(MACRO)
  seed.local_backwalk -> fact.link_method = "LOCAL_BACKWALK"
```

Output: a real value, but `launch_via=LOCAL_BACKWALK` and
`function_source_line="-1 (Local backwalk)"` tell you we could not prove the
function runs. In the discovery index this is still distinct from a
root-reachable fact. This path is the fix for ~400 of the misses in
`subagents/agent_final_report.md`.

---

# PART G — REFERENCE

## 27. Cheat-sheet: "which file does X"

| Question | File / function |
| --- | --- |
| Pick which processes to run | `project_aware.py` `__main__` argparse (~`2793`); `discover_processes`, `validate_processes` |
| Where targets are defined | `json_data/mpf_data.json` (or `--targets target_specs/build_index_targets.json`); `state/load_data.py` `load_json_files`; `target_spec.py` `load_target_spec` / `validate_target_spec` |
| Which `.c` files belong to a process | `makefile_resolver/makefile_resolver.py` `return_project_mapping` |
| Header / include resolution | `makefile_resolver/extract_includes.py` `IncludeIndex`; resolver-side `_build_include_graph` `value_flow/resolver.py:2644`, `_resolve_include:2697` |
| Preprocess + parse | `helpers/Preprocess/preprocess.py` `Preprocess.preprocess` + tree-sitter |
| `_NO_PROTO` / `NOP` fallback, why live code looked dead | `analysis/change_name_for_purpose.md`; `analysis/step0_report.md` §5.1 |
| Node / edge shapes | `call_graph/data_classes.py` (`FunctionNode`, `CallSite`) |
| Call graph build | `call_graph/call_graph.py` `CallGraphBuilder.build`; wrapper `visualizer_export.build_complete_call_graph` |
| Entry-point name list | `project_aware.py:125` `ENTRY_FUNCTION_NAMES`; `call_graph/call_graph.py` `get_entry_points` |
| Callback / function-pointer registrars | `json_data/function_callback_info.json`; `call_graph/call_graph.py` `_callback_registrar:357`, `_extract_callbacks:492`, `_map_registrar_position:460`; resolver `_build_callback_edges:701` |
| Reachability (3 buckets) | `value_flow/resolver.py:764` `_compute_reachability` |
| Query / Fact shapes | `value_flow/queries.py` |
| Seed = unique target invocation | `value_flow/resolver.py:156` `Seed`; `:894` `_enumerate_seeds` |
| The backward value ladder | `value_flow/resolver.py` `_resolve_expression` |
| Wrapper → caller fan-out | `value_flow/resolver.py:~1650` `_resolve_parameter` (`ParamQuery`) |
| Handle → open matching | `value_flow/resolver.py:1776` `handle_query_for_seed`; `_resolve_handle:~1810`; `_binding_opens:1956`; `value_flow/handles.py` `normalise_handle` |
| Constant-table / wrapper-write / string rules | `value_flow/value_rules.py`; `_resolve_table_expression:1247`, `_wrapper_output_facts:1429`, `_local_string_facts:1566` |
| Macro / enum resolution (include-aware) | `value_flow/resolver.py` `_resolve_macro:2984`, `_visible_enum_index:2829`, `_evaluate_enum_expression:2856`, `_all_macros:2965` |
| Branch merge (`if/else if/else`) | `value_flow/resolver.py:3051` `_local_reaching_definitions`, `:3132` `_collect_branch_values` |
| Local backwalk fallback | `value_flow/resolver.py:1994` `_locally_provable` |
| Return use (READ/WRITE) | `value_flow/resolver.py:2118` `_syntactic_return_use`, `:2172` `_classify_later_pointer_use` |
| Event id (`call_number`) | `value_flow/resolver.py:~2190` `call_number_for` |
| Scheduler | `value_flow/resolver.py` `run` (producer/consumer), `_resolve_seed`, `resolve` |
| When the LLM is used | `project_aware.py:373` `llm_calls`, `:660` `llm_calls_one_hop`, `:727` `llm_endpoint_status`; callbacks wired at `:1981`; `_await_llm`, `_call_one_hop` in resolver |
| LLM context slice | `parser/parser_files.py` `parseFiles.parse_for_path`; `context_for` in `project_aware.py:~1707` |
| Provenance / paths | `value_flow/resolver.py:2440` `_add_provenance`, `:2493` `_provenance_token_paths`, `:2478` `paths_for_fact` |
| Dedupe / fact id | `value_flow/resolver.py:3226` `_deduplicate_facts`, `:3233` `_deduplicate_records`, `:3264` `fact_id` |
| Output columns | `value_flow/outputs.py` `FACT_COLUMNS` / `PATH_COLUMNS` / `LEGACY_COLUMNS`; `_legacy_rows:88`; `write_trace_logs:150` |
| Back into visualizer | `visualizer_export.py` `VisualizerCollector.rehydrate_interactions` |
| Discovery index / comparison | `discovery_index.py` `write_discovery_index`; `aggregate_index.py`; `analysis/step0.py`, `analysis/step1.py`; `analysis/analysis_handoff.md` |
| Cost comparison legacy vs valueflow | `compare_resolvers.py` |

## 28. Result vocabulary you might be asked about

| term | precise meaning here |
| --- | --- |
| **site** | exact absolute file + line of the target call |
| **resolution** | one concrete value reported for one site |
| **distinct value** | a value counted once globally, ignoring site |
| **direct CONST/MACRO** | the target argument itself is a literal / named macro / named enum (Step 0) |
| **indirect value-flow case** | argument is a variable, helper parameter, handle, field, array element, expression (Step 1) |
| **UNREACHABLE** | no path from a recognized root to the enclosing function; `path_count = 0`; **not** "the call was not found" |
| **OPEN_LOCK** | discovery-index operation name for an open-family FNO argument; the concrete READ/WRITE comes from the call's lock argument |

## 29. Known weak spots (from `subagents/agent_final_report.md`, `analysis/step0_report.md`)

1. **`UNREACHABLE` ≠ "we missed the call".** The 225-record audit
   (`step0_report.md` §5): 85 genuinely dead code, 80 parser corruption on
   old K&R files, 52 live-via-callback that static BFS doesn't cross, 8
   cross-process. Zero ordinary discovery misses. The `LOCAL_BACKWALK` seed
   path + the `_NO_PROTO`/`NOP` preprocess fallback recover many.
2. **Constant tables / wrapper helpers** (`DynREGetSchfno`, `ChaGetFileInfo`,
   `Dxi_UpTbnFileOpen`) resolve to a bounded set **only if a rule exists** in
   `value_flow/value_rules.py`. Otherwise `EXTERNAL` / `UNREACHABLE`.
   ~125–130 sites in the audit.
3. **Direct macro not emitted** (~150–170 sites, F3). Some active headers are
   SJIS-encoded; if the macro/enum index mis-reads one in an include chain, a
   direct constant silently fails to resolve while the handle still links.
   Check `_build_enum_index` / `_all_macros` if a known constant comes back
   unresolved.
4. **Overapproximation — stale `0` initializer** (F4, ~10 sites, all one
   file). Fixed by `_wrapper_success_guard`; if a `writes_table` wrapper has
   no rule, the guard can't fire.
5. **Multi-arm `else if`** once dropped the middle arm (F5). The chain-walk in
   `_local_reaching_definitions` / `_collect_branch_values` is the fix; still
   worth a regression check on 3+ arm chains.
6. **Pointer-parameter handles / file-static FCBs** (F6/F7) — handled by
   `_resolve_handle` steps 2 and 3, but depends on the in-tree caller list
   being complete; cross-process callers are not seen.
7. **String flow to `forkproc(name)`** (F8) — `_local_string_facts` covers
   `= "..."` / `strcpy` / bounded `strncpy` of a local buffer; anything
   fancier is `EXTERNAL`.
8. **LLM values are hints.** `origin_kind=LLM_CANDIDATE` / `resolved_by=LLM`
   never enter the exact comparison index. Precision of the syntactic facts
   in the audit was ~100% (only 10 wrong values in ~1,959 sites, all F4).

## 30. Things named in the code you may get asked about

| name | what it is |
| --- | --- |
| `RESOLVER_VERSION` (`value_flow/resolver.py:38`) | cache-busting string; bump = old `query_cache.json` ignored |
| `STATE` / `State()` (`state/state.py`) | process-global dict; reset between processes in batch mode |
| `BUILDER_MACROS` vs `MACROS` | `BUILDER_MACROS` = macros with a known constant value + definition file (from the makefile/preproc pass); `MACROS` = per-file `#define` text |
| `FUNCTION_MAP` (`combined_data.json`) | pre-written english notes about library functions, fed to the LLM |
| `get_upper` | per-target flag: does the LLM need caller bodies above the call, or just the return region |
| `models.py` `Combined` | the old per-invocation output object (`type`, `launch_via`, `call_function`, `target_number->ans`, source locations) the visualizer/wiki consume |
| `visualizer/groups/<group>/runs/<ts>/group.json` | immutable manifest tying a group to the exact per-process snapshots |
| `--index-only` | graph + snapshot only, no target tracing, no daemon-resource interactions |
