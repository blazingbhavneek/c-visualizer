# Repository report

## What this repository is for

This is a project-aware, LLM-assisted **static tracer for C programs**.  It is
not a C compiler or a general-purpose source indexer.  Its main task is to
answer questions such as:

- Which calls from `main()` can reach a configured API?
- Along each reachable path, what constant values reach selected arguments?
- Is a file/queue API being used for an open, read, write, save, load, enqueue,
  dequeue, or related operation?
- Was the path launched directly, through a callback/event, a fork, a message,
  a semaphore, a timer, etc.?

`project_aware.py` is the application entry point.  For each target API named
in external configuration it resolves the source/header closure, builds a call
tree rooted at `main`, extracts only the relevant function fragments, and asks
a local Ollama model to trace values backwards.  It validates and records the
result with Pydantic models and writes CSV, graph, log, and statistics outputs.
The output model contains fields such as process name, launch mechanism, target
values, source locations, call/event number, and operation type.

The API names and classifications embedded in prompts and models (`mpf_mfs_*`,
`pmf_addevent`, `pmd_addvarevt`, file and queue operations) show that the
intended use is analysing a particular family of applications/framework APIs,
rather than discovering arbitrary C business semantics.  The hard-coded source
roots (`src_analysis`, `src_rbt`, and `src_wh/wh-dio`) and library names
(`libapl`, `libRbt`, `libdio`) reinforce that this was built for a specific,
large legacy codebase or closely related codebases.

## How it works

1. The Makefile resolver reads a relatively simple Makefile variable model
   (`SRCS`, `INCLUDE`, `LIBS`, and recursive `include` directives) to identify
   initial C source files and include directories.
2. The include resolver follows quoted/angle-bracket includes transitively and
   retains reachable `.c` and `.h` files.
3. Preprocessing removes comments.  For `.c` files it also runs `unifdef` while
   preserving line positions, then parses the resulting bytes with Tree-sitter.
4. `libclang` extracts function definitions and line ranges.  Tree-sitter
   extracts calls, macros, call-site lines, and configured callback arguments.
5. The call-graph builder distinguishes file-local `static` functions from
   global ones; it can represent simple function-like macro expansion and
   registered callbacks as extra path nodes.
6. The LLM receives a trimmed, annotated source slice for each path plus two
   tools: look up a symbol and read a limited source/header snippet.  It returns
   resolved values or `UNRESOLVED`.  The program saves each structured result.

## The intended C code

The expected input is a makefile-based **C** application with a conventional
`main()` and sources/headers reachable from `SRCS`, `INCLUDE`, and `LIBS`.
The most suitable projects are procedural, multi-file, C89/C99-style or later
C programs whose control flow can be approximated from direct calls and a small
configured set of callback-registration functions.  It is particularly aimed
at legacy, macro-heavy systems C/application code with custom file, queue, and
event APIs—not at C++.

The parser can accept a wider syntactic range than the analyzer can understand:

| Area | Accepted by the grammar |
| --- | --- |
| Standard C | C99 is its stated base; it also has syntax for `_Atomic`, `_Alignas`, `_Generic`, `thread_local`, `nullptr`, and modern attributes. |
| Preprocessor | Includes, object/function macros, conditionals, and multiline directives. |
| GNU/Clang extensions | `__attribute__`, `__extension__`, GNU `asm`, `typeof`-style macro/type contexts, compound literals, and common GNU spellings. |
| Microsoft extensions | `__declspec`, calling conventions such as `__stdcall`/`__cdecl`, pointer modifiers, and SEH forms (`__try`, `__except`, `__finally`). |
| Older C | K&R/implicit-`int` function-definition alternatives and old-style parameter lists. |

This is syntactic acceptance, not proof that the analysis handles every feature
semantically.  The call-graph pass only resolves a `call_expression` whose
callee is a plain identifier.  Calls through function pointers, fields,
arbitrary expressions, virtual-dispatch-like patterns, or macro expansions
that cannot be reduced to a direct named call are incomplete or become
`indirect_call`.  Function pointers work only where their registration APIs and
argument positions have been listed in external callback configuration.

## The custom Tree-sitter component

`tree-sitter-c/` is a vendored Tree-sitter C grammar at version **0.24.1**.  It
identifies itself as grammar `c`; its README describes the upstream C grammar
as adapted from C99.  The repository-specific customization is the Python
distribution/binding name:

- upstream-style grammar package: `tree-sitter-c`
- Python distribution: `tree-sitter-custom`
- Python import used by the analyzer: `tree_sitter_custom`

`setup.py` compiles the generated C parser (`src/parser.c`) with a tiny Python
binding that exposes `tree_sitter_c()` as `language()`.  This isolates the
bundled parser from an installed package named `tree_sitter_c`; it does **not**
add domain-specific nodes or syntax.  The project-specific interpretation of
macros, callbacks, file APIs, and event APIs is implemented in the Python code
that walks the generic Tree-sitter nodes.

## Practical constraints and caveats

- Runtime configuration is required but is not present in this checkout:
  `state/load_data.py` expects `json_data/mpf_data.json`,
  `json_data/function_callback_info.json`, and a function-map data file.  Those
  define which APIs and argument positions are traced.
- It assumes `.c` and `.h` files, often decodes source as Latin-1, and expects
  `unifdef`, `libclang`, and an Ollama service.  It does not reproduce the
  actual compiler command line or all Makefile logic, so build flags and
  conditional compilation may differ from the real build.
- The Makefile resolver is intentionally narrow and contains environment- and
  path-specific defaults.  It will not reliably model complex Make functions,
  generated source, multiple build configurations, or unrelated build systems.
- The mapping uses filenames as keys in several places.  Projects with
  duplicate basenames in different directories can be confused.
- Macro call expansion is limited: the call-graph builder collects macro
  definitions from headers and follows a macro only when it resolves to a
  direct identifier call.  It does not perform full C preprocessing or macro
  data-flow analysis.
- Final argument/value conclusions are model-assisted, not compiler-proven.
  They are useful for guided investigation and reporting, but important results
  should be checked against the actual source and build configuration.

## Bottom line

Use this repository for a configured family of makefile-based, multi-file C
programs—especially legacy/event-driven code that invokes known framework
file, queue, and event APIs—and for producing path-by-path operational
metadata.  Do not treat it as a drop-in whole-program analyzer for arbitrary
C/C++ projects, even though its Tree-sitter grammar can parse much of that
syntax.
