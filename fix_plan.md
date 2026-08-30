# Fix plan: roots, callbacks, and cross-process evidence

## Objective

Make the discovery pipeline distinguish these cases:

1. A real executable entry path was missed because preprocessing or parsing
   damaged the root function.
2. A target is reached through a registered callback.
3. A target site belongs to another process or library scope.
4. A target is genuinely unreachable from every valid root.

The final exact indexes must remain conservative. A record is not promoted to
an exact process index merely because it appears in another source tree.

## Current seams to preserve

The implementation model should inspect and reuse these existing seams:

- `project_aware.py`
  - `ENTRY_FUNCTION_NAMES`
  - Makefile-derived `potential_main_files`
  - `Preprocess(... expected_entry_names=...)`
  - construction of `entry_points`
- `helpers/Preprocess/preprocess.py`
  - `PreprocessorConfig`
  - `_tree_health()`
  - `_function_definition_names()`
  - per-file preprocessing metadata
- `call_graph/call_graph.py`
  - `CallGraphBuilder._resolve_callee()`
  - `CallGraphBuilder._extract_arg_function_name()`
  - callback extraction in `_process_function_body()`
  - `build_call_trees()` macro/callback rendering
- `value_flow/resolver.py`
  - `_build_call_index()`
  - `_build_callback_edges()`
  - `_compute_reachability()`
  - `_launch_metadata()`
- `discovery_index.py`
  - target-site inventory
  - `_unreachable_facts()`
  - `build_discovery_payloads()` and metadata
- `aggregate_index.py`
  - union of per-process evidence
  - whole-repository scope
- `analysis/step0.py` and `analysis/step1.py`
  - status grouping and report wording

Do not replace the value-flow resolver with a new global graph. Fix the inputs
and the reachability metadata at the existing ownership boundaries.

## Required output contract

Do not overload the value-resolution `status` with every possible cause. Keep
`status` compatible with existing consumers (`EXACT`, `UNRESOLVED`,
`EXTERNAL`, `DYNAMIC`, `NO_TARGET`, `CYCLE`, etc.) and add a separate
`reachability` field to evidence rows.

Recommended reachability values:

- `DIRECT_ROOT` — reached through ordinary call edges from a recognized root.
- `CALLBACK` — reached through a callback-registration edge.
- `CROSS_PROCESS_CALLER` — the site is outside the current process and is
  owned by another executable process according to the process manifest.
- `OUT_OF_PROCESS_SCOPE` — outside the current process, but no owner process
  has been proven yet.
- `ROOT_PARSE_FAILURE` — an executable source file contains a likely accepted
  root, but the parsed graph has no usable root.
- `NO_PROCESS_ROOT` — a library/shared source scope has no executable root by
  design.
- `UNREACHABLE_IN_PROCESS` — in the current process scope, with valid roots,
  no path exists.
- `UNKNOWN` — only for legacy rows or incomplete diagnostic data.

The exact JSON indexes must still require both:

```text
status == EXACT
and in_process == true
and reachability in {DIRECT_ROOT, CALLBACK}
```

Cross-process rows remain evidence and must not increase the current process's
exact file/queue/fork counts.

If changing the CSV schema, increment the discovery schema version and make
readers tolerate old files with no `reachability` column. Do not silently
interpret an old `UNREACHABLE` row as a proven dead-code result.

---

## Phase 0 — establish a reproducible baseline

Before editing behavior:

1. Run the focused test suite from `forkproc_checker/c-visualizer`.
2. Save the current results for these processes:
   - `dyn730`
   - `dyn710`
   - `cha702`
   - `tmm200d`
   - `dif901`
   - `libdif`
   - `svm000`
3. Record, for each process:
   - `entry_points` from visualizer `graph.json`;
   - preprocessing metadata for the entry source;
   - number of target sites and evidence rows;
   - status counts;
   - the rows for the target lines listed in the validation section below.
4. Do not use the old aggregate report as proof of correctness. It may contain
   rows from an older run and does not encode all root diagnostics.

Suggested focused command:

```bash
cd forkproc_checker/c-visualizer
pytest -q tests/test_preprocess.py tests/test_value_flow.py tests/test_discovery_index.py tests/test_visualizer_export.py
```

Use the repository's existing batch/pipeline command for the production runs;
do not invent a second runner just for this fix.

Stop Phase 0 only when the baseline artifacts and commands are recorded.

---

## Phase 1 — make root discovery deterministic and robust

### 1.1 Normalize source identity first

The current project mapping is largely keyed by basename. That allows two
different files with the same basename to overwrite each other and makes
`expected_entry_names` ambiguous.

Change the root-discovery inputs so every candidate carries:

```text
absolute_path
canonical_source_key
relative_source_path
is_makefile_source
process_root_membership
```

Do not use only `Path.name` to identify an entry file. If changing the whole
project-structure key is too broad for this patch, add an explicit path-keyed
map for root detection and preserve the old map only at compatibility seams.

Add a regression fixture with `main.c` in both an executable directory and a
library directory. Only the executable file may become a root.

### 1.2 Candidate discovery must use the accepted name list

Keep the accepted names centralized and ordered:

```text
main
pmf_main_H
pmf_start_H
pmf_end_H
pmf_term_H
pmf_abort_H
```

For each Makefile `SRCS` source file, inspect every accepted name. Preserve all
valid definitions in `entry_points`; choose the first only for legacy
`main_file_name`/`entry_function_name` display fields.

Never infer a root from an arbitrary function name, a prototype, a call to a
function with an accepted name, or a library definition outside the process's
Makefile source set.

### 1.3 Make preprocessing selection root-aware

The current fallback is triggered mainly by Tree-sitter parse errors. That is
insufficient: a file may have a parse tree without errors while the expected
root definition or its body was lost.

For every potential entry source, evaluate the initial preprocessing result
using all of these checks:

- tree health (`has_error`, error-node count);
- accepted function definitions found in the tree;
- definition has a body, not only a declaration/prototype;
- root body contains a valid block and has stable source offsets;
- raw-source candidate scan finds an accepted function definition that the
  tree did not recover.

If the file is a potential entry source and any expected root is missing or
malformed, try the guarded compatibility variants even when the initial tree
does not report an error.

The candidate selection order should be deterministic:

1. Actual Makefile defines/undefines, normal preprocessing.
2. Compatibility undefines only for symbols not explicitly controlled by the
   Makefile, currently `_NO_PROTO` and `NOP`.
3. A narrowly targeted compatibility normalization only if a known source
   pattern still cannot parse. It must preserve line count and byte offsets.

Select a variant only when it improves the root validation score and does not
introduce a worse parse. Record all attempted variants and the reason for the
selected variant.

If `_NO_PROTO` is explicitly defined, do not blindly apply `-U_NO_PROTO`; the
Makefile configuration wins. If that configured branch is itself malformed,
report a root diagnostic instead of silently changing build semantics.

### 1.4 Make encoding handling byte-safe

Source preprocessing must:

- read source as bytes;
- pass bytes to `unifdef` and Tree-sitter;
- preserve newlines and byte length where possible;
- decode diagnostic text with a lossless single-byte strategy such as
  `latin-1`, or with replacement only for display;
- never use UTF-8 decoding with `errors="ignore"` for source analysis;
- keep source line numbers and Tree-sitter byte offsets stable.

Add a fixture containing non-UTF-8 bytes in comments and strings plus a valid
entry function. It must still produce the same root and call line.

### 1.5 Add a raw candidate scanner for diagnostics, not authority

Implement a small deterministic scanner that reports accepted-name patterns
from source bytes, including:

- ANSI definitions;
- K&R definitions;
- prototypes;
- calls/usages;
- definitions inside inactive preprocessor branches when detectable.

The scanner may trigger another preprocessing attempt and explain a failure,
but it must not make a raw regex match into a reachable graph root. A parsed
function definition with a body remains mandatory for normal reachability.

Optional one-time audit: delegate a read-only investigator/agent to enumerate
all accepted-name candidates in the corpus and classify them as executable
source, library source, prototype, duplicate definition, or parse failure.
Write the result to an audit CSV if useful. Do not invoke an LLM/agent during
normal pipeline execution and do not let agent output decide roots.

### 1.6 Make root diagnostics explicit

Extend preprocessing/project metadata with fields such as:

```json
{
  "root_candidates": [
    {"name": "main", "kind": "definition", "line": 93}
  ],
  "accepted_entry_points": ["main"],
  "root_variant": "fallback_-U_NO_PROTO",
  "root_validation": "accepted",
  "root_failure_reason": ""
}
```

For an executable Makefile source with a raw accepted definition but no parsed
root, emit `ROOT_PARSE_FAILURE`. For a library source with no accepted root,
emit `NO_PROCESS_ROOT`. Do not emit a blank root with no explanation.

The visualizer graph metadata should expose:

- all accepted `entry_points`;
- candidate roots;
- root diagnostics;
- preprocessing variant and parse-health counts.

### 1.7 Remove silent fallback behavior

When `entry_points` is empty for an executable process:

- do not silently default to `main`;
- do not claim normal `UNREACHABLE_IN_PROCESS` for every target;
- continue producing evidence, but mark the run/root state as
  `ROOT_PARSE_FAILURE` or `NO_PROCESS_ROOT`.

The resolver must continue to use the union of all supplied roots. Keep the
legacy first-root fields only for compatibility and display.

### Root-phase tests

Add unit tests for:

1. one `main` root;
2. `pmf_main_H` plus `pmf_end_H` in the same file;
3. all four PMF roots in one process;
4. dual K&R/ANSI `_NO_PROTO` source;
5. split `NOP` conditional;
6. explicit Makefile macro state not overridden;
7. prototype-only accepted name is not a root;
8. duplicate basename executable/library files;
9. non-UTF-8 source bytes;
10. malformed candidate produces diagnostics, not a false root;
11. cached project mappings cannot reintroduce stale root paths.

### Root-phase production acceptance

For `dyn730` and `dyn710`:

- `main` is present in `entry_points`;
- `dyn730Main.c:230` / corresponding initializer call is a call-graph edge;
- the initializer and its target calls become reachable where source confirms
  the active path;
- no accepted root is lost because of duplicate prototype syntax.

For `cha702`:

- `main` is present;
- `cha702Main.c:278 -> cha702AddEV` is present;
- the root metadata explains which preprocessing variant was selected.

For `tmm200d` and `dif901`:

- all configured lifecycle definitions remain roots;
- no first-root-only regression occurs.

Stop the root phase when these checks pass and no executable process in the
test set has an unexplained empty `entry_points` list. Do not start cross-source
changes to compensate for a root failure.

---

## Phase 2 — make callback resolution macro-aware and lossless

### 2.1 Confirm the callback configuration path

The callback registry is loaded from `json_data/function_callback_info.json` and
is passed as `FUNCTION_POINTER_ARGS`. Before changing extraction, add a test
that asserts the production registry contains the relevant APIs, including:

- `pmf_addevent` and related event APIs;
- Xt/Motif registration APIs used by the corpus;
- `SimAddSemCallback`;
- `MmiAddEvent` and other configured registrars.

If a function is absent from the registry, add it only after confirming its
argument position from the checked-in headers/source. Do not guess callback
positions from target rows.

### 2.2 Use AST named arguments, not raw child positions

The current callback extraction walks `args_node.children` and uses `idx / 2`.
This depends on punctuation nodes and can miss or duplicate arguments.

Change it to iterate `args_node.named_children` with one-based argument
positions. For each configured position:

- extract identifiers;
- unwrap casts;
- unwrap parentheses;
- unwrap address-of expressions;
- preserve the raw argument text and source byte range;
- deduplicate callbacks by canonical function identity.

Keep the call-site line and byte range from the real registration call.

### 2.3 Resolve callback aliases without losing the real function

Support these forms:

```c
pmf_addevent(EVT, cha702Event, data);
pmf_addevent(EVT, &cha702Event, data);
#define CHA_HANDLER cha702Event
pmf_addevent(EVT, CHA_HANDLER, data);
#define REGISTER(E, CB, D) pmf_addevent(E, CB, D)
REGISTER(EVT, cha702Event, data);
```

The callback record must retain both:

- the source spelling (`CHA_HANDLER` or `REGISTER`);
- the canonical target (`cha702Event`).

Use the existing macro resolver as the canonicalization seam, but add a
callback-specific function that can resolve:

- object-like aliases;
- function-like wrapper macros;
- chained aliases;
- safe argument substitution.

If a macro uses token pasting, stringification, variadic forwarding, or an
ambiguous argument reorder, do not guess. Record a callback diagnostic and
leave the target unresolved rather than creating a false edge.

### 2.4 Fix macro callback graph edges

At present a callback argument may become a macro `FunctionNode` whose
`macro_expansion` points to the real function. The value-flow synthetic edge
must point to the canonical real function ID, or there must be an explicit
macro-alias edge from the macro node to the real function.

Preferred implementation:

- retain the macro node for visualizer display;
- store `callback.canonical_id` or equivalent on the callback metadata;
- make `_build_callback_edges()` use the canonical ID as `callee_id`;
- preserve the raw macro node in edge metadata for display/provenance;
- use the expanded callback name when looking up launch/config metadata.

Do not create duplicate direct and callback edges for the same registration.
The visualizer may show the registration edge and callback edge, but the
resolver must deduplicate reachability by canonical function ID.

### 2.5 Resolve callback registrar macros too

Apply callback configuration to both the raw callee and any safely expanded
callee. For example, if `REGISTER_EVENT(...)` expands to `pmf_addevent(...)`,
the configured argument positions belong to the expanded API.

For function-like wrapper macros, map actual arguments through the macro
signature before selecting callback positions. If mapping is not provably
reliable, emit a diagnostic rather than using the raw position by accident.

### 2.6 Preserve callback provenance in value-flow output

Extend `Seed`/`ResolvedSeed` or equivalent metadata with a reachability kind.
When `_launch_metadata()` crosses a synthetic callback edge, mark the target
as `CALLBACK` and retain:

- registrar function;
- registrar file/line;
- raw callback expression;
- canonical callback function;
- launch type/configuration.

Value resolution remains `EXACT`, `UNRESOLVED`, etc. Callback provenance is a
separate dimension.

### Callback tests

Add unit fixtures for:

1. direct callback argument;
2. `&callback`;
3. casted and parenthesized callback;
4. object-like callback macro alias;
5. callback registrar wrapped by a macro;
6. callback argument reordered by a macro;
7. unsupported token-paste macro remains unresolved;
8. duplicate callback spelling produces one canonical edge;
9. callback registration in a second lifecycle root;
10. callback path reaches a configured target and records registrar metadata.

### Callback production acceptance

For `cha702`:

```text
cha702Main.c:278
  -> cha702AddEV.c:55 pmf_addevent(..., cha702Event, ...)
  -> cha702Event.c:974 target call
```

The target row must have a nonzero path and `reachability=CALLBACK` when the
argument/value is otherwise resolvable. The graph must show the callback
registration and canonical callback function.

Also check one Xt/Motif or `SimAddSemCallback` production case from the 52-row
callback audit. Do not claim callback support is fixed based only on the small
synthetic fixture.

Stop the callback phase when direct, macro-aliased, and wrapped registrations
all pass, and the production `cha702` path is recovered. Do not add an LLM
fallback for callback names until syntax and macro resolution are exhausted.

---

## Phase 3 — classify cross-process callers without counting them twice

### 3.1 Define ownership separately from observation

Being present in process A's `PROJECT_STRUCTURE` does not make a library or
other process source part of A's exact process graph.

Build a process manifest before aggregate merging. Each entry should contain:

```text
process_name
process_root
source_root
Makefile SRCS paths
library/source paths included by the process
is_executable_process
```

Use canonical absolute paths and longest-prefix matching. A source path under a
specific executable process root belongs to that process; a `lib*` directory is
library-owned unless an explicit process manifest says otherwise.

Do not infer ownership from a basename.

### 3.2 Mark per-process out-of-scope evidence

When a target site is outside the current process root:

- keep it in `discovery_facts.csv`;
- never send it to the current process's exact JSON indexes;
- do not label it as ordinary `UNREACHABLE_IN_PROCESS`;
- initially mark it `OUT_OF_PROCESS_SCOPE` if no owner is available;
- after the process manifest is available, mark it
  `CROSS_PROCESS_CALLER` when another process owns the target site.

Add these fields to evidence if practical:

```text
evidence_process
owner_process
owner_kind
reachability
```

If a schema change is made, update `aggregate_index.py` and all readers to
preserve unknown/new columns and default missing fields for old results.

### 3.3 Add an explicit cross-process relation

The aggregate should emit a small evidence-only artifact, for example
`cross_process_callers.csv` or `cross_process_callers.json`, containing:

```text
target_site_file
target_site_line
target_function
observed_from_process
owner_process
owner_resolution_status
owner_reachability
```

`owner_resolution_status` must be obtained from the owner process's result,
not inferred from source presence. This gives three distinct outcomes:

1. Owner process has an exact/direct or callback resolution: globally proven
   live; count the owner's exact result once.
2. Owner process has the site but no path: owner still needs root/callback/dead
   analysis; do not count it as globally resolved.
3. No owner process exists: library/external evidence only; do not count it as
   an executable-process resolution.

This directly addresses the `tmm200d -> libdif` case: the library call may be
visible while analyzing `tmm200d`, but its exact ownership/resolution belongs
to the process or library result that owns the source site.

### 3.4 Keep aggregate counts correct

Update `aggregate_index.py` so:

- cross-process evidence is retained;
- cross-process rows do not enter `mfs_file_access.json`,
  `mfs_queue_access.json`, forkproc JSON, or exact counts for the observing
  process;
- owner-process exact rows are deduplicated by physical site, operation, and
  value;
- the aggregate metadata reports counts for
  `CROSS_PROCESS_CALLER`, `OUT_OF_PROCESS_SCOPE`, and unresolved owner cases;
- existing visualizer graph artifacts are not overwritten by index writes.

Update `analysis/step0.py` and `analysis/step1.py` to report cross-process rows
separately. They must not include them in the generic unreachable bucket.

### Cross-process tests

Add a fixture with:

- process A source calling a target site in a library directory;
- process B owning the target site and having a valid root/path;
- a second library target with no owner process;
- an in-process orphan target.

Assert:

- A's evidence contains the target and marks it cross-process;
- A's exact JSON excludes it;
- B's exact result contains it once when B has a valid path;
- the ownerless library target remains evidence-only, not falsely reachable;
- the in-process orphan is `UNREACHABLE_IN_PROCESS` only;
- aggregate counts do not double-count A and B.

### Cross-process production acceptance

Verify these audited examples:

- `t-dif/src/libdif/difGetF1Data.c:55` and `:66` appear in the relevant
  library/owner results and are classified separately from ordinary
  unreachable rows;
- `t-cha/src/libCha/ChaGetJisseki.c` rows are cross-process evidence when
  observed outside their owner scope;
- `t-svm/src/svm000/svm000SendInt.c:288` and `:311` do not inflate the
  observing process's exact counts;
- `dif901InitDllData` remains ordinary dead/unreachable evidence because its
  only source caller is commented out, not cross-process.

Stop this phase when the fixture and all three production families produce
stable owner/cross-process classifications and aggregate exact counts remain
unchanged except for genuinely recovered root/callback paths.

---

## Phase 4 — close the remaining value-flow failure modes

The consolidated report
`subagents/agent_final_report.md` found additional failures beyond root,
callback, and process-scope classification. The report covers agents 1–5:
2,123 claim rows and 1,959 unique sites. Agent 6 (`t-sim`, `t-svm`, `t-rep`)
was not run, so its expected failure modes must be audited before declaring
the corpus complete.

The estimates below are priority guidance, not acceptance counts. They overlap
one another: for example, a missing wrapper write can appear both as an
unresolved value and as a stale initializer value.

| ID | Failure mode | Estimated sites | Main risk |
|---|---|---:|---|
| F1 | Root tracking fails even though a same-function open is visible | 400–450 | Large recall loss; usually no precision loss |
| F2 | Wrapper/table lookup returns a bounded constant set but is not modeled | 125–130 | Large recall loss; set-valued result must not look path-exact |
| F3 | Direct macro/enum values, especially non-UTF-8 headers, are missed | 150–170 | Large recall loss; possible encoding/index bug |
| F4 | A guaranteed wrapper write leaves the initializer `0` as a false value | 8–10 | Precision loss; only confirmed c-viz overapproximation |
| F5 | The middle arm of a three-way `if/else if/else` merge disappears | 4–5 | Recall loss; both pipelines currently show the same gap |
| F6 | Pointer-parameter handles are not traced through in-tree callers | 25–30 | Recall loss |
| F7 | File-static FCB opened in one function is used in another | Few today | Recurring cross-function handle loss |
| F8 | Local string constants do not flow through `strcpy`/`strncpy` to forkproc | Few today | Forkproc names remain unresolved |

Do not fix these by making the resolver accept every nearby open or every
unknown value. Preserve the existing precision invariants: c-viz was correct
on essentially all audited numeric values except F4, it handled reopen identity
correctly, and it already unions several ordinary local branches.

### F1 — add a safe same-function local back-walk

Root repair remains the primary fix. Add a second, explicitly labeled fallback
for a target whose enclosing function is not in the recognized-root reachable
set but whose handle binding is mechanically provable inside that same
function.

Implement it at the handle-binding seam around `_binding_opens()` and
`_resolve_handle()`:

1. Identify the target handle expression.
2. Find prior configured opens in the same function using the same normalized
   handle identity.
3. Remove candidates before the last matching close.
4. Preserve all candidates that can reach the target through the local control
   flow; do not simply choose the nearest textual open.
5. Resolve the open's configured file-number argument using ordinary syntax,
   macro, enum, wrapper, or bounded-table resolution.
6. Emit provenance with `link_method=LOCAL_BACKWALK` and
   `reachability=LOCAL_BACKWALK`.

This fallback must not pretend to prove that the enclosing function is
executed. It proves only that the target's value is source-valid if that
function executes. Keep it separate from `DIRECT_ROOT` and make the exact-index
promotion policy explicit. The initial implementation should retain the value
in evidence and report it separately; only promote it to exact process indexes
after the root diagnostics show the process has no unresolved root failure.

Add a negative test where a nearby open uses a different FCB, and another where
the matching FCB is closed before the target. Neither may produce a value.

Production targets:

- `/home/chukyu/t-dyn/src/dyn730/dyn730Init.c:478,487` and sibling opens;
- `/home/chukyu/t-dif/src/dif901/dif901IntDll.c:200` and later sites;
- `/home/chukyu/t-tmm/tool/opmtool/tmmtool.c:69,76`;
- `/home/chukyu/t-cha/src/cha100d/cha100dMain.c:229`;
- `/home/chukyu/t-dyn/src/dyn710/dyn710Init.c:292`.

Acceptance: every recovered local value is tagged `LOCAL_BACKWALK`, no
unrelated handle gains a value, and root failures remain visible rather than
being hidden by the fallback.

### F2 — model bounded constant-table and wrapper results

Add a small abstract value kind for a finite source-backed set, for example
`BOUNDED_SET`. It represents possible values, not one guaranteed runtime path.

The resolver should recognize a function that returns or writes an element of a
static constant table only when it can prove:

- the table is translation-unit visible and constant;
- the table elements are literal/macro/enum values already resolvable by the
  syntax resolver;
- the index is within a known finite range, or the full table is the declared
  conservative bound;
- no active mutation or out-of-range access changes the result.

Return one fact per possible value, but mark the facts with
`origin_kind=CONST_TABLE`, `link_method=TABLE_LOOKUP`, and set metadata such as
table file, table line, index expression, and bound. Downstream must not treat
16 bounded values as 16 independent exact execution paths.

Start with declarative wrapper rules rather than a general C abstract
interpreter. The first rules must cover:

- `DynREGetSchfno`, `DynREGetSchKKfno`,
  `DynREGetSchKKLCfno`, `DynREGetPfmfno`;
- `ChaGetFileInfo`;
- `Dxi_UpTbnFileOpen` and its `DnTbn` equivalents;
- static-table forkproc names in `tmm000_deamon.c`.

The rule format should describe whether a function returns a table element or
writes a table element to a pointer argument, the table symbol, the index
argument, and the applicable output argument. Keep rules in the target/value
configuration seam so they are testable and auditable, not scattered through
the resolver.

Tests:

- 16-entry `DynReScheFno` table with loop index 0..15;
- `ChaGetFileInfo` TM and SV sets;
- two-entry `Dxi_UpTbn` table;
- two active `tmm000` process names;
- unknown/unbounded index remains `EXTERNAL`/`DYNAMIC`, not an invented exact
  value;
- bounded values are retained in evidence but counted as a set in reports.

Production targets:

- `/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57` and callers such
  as `dyn600MainProc.c:1042`;
- `/home/chukyu/t-cha/src/libCha/ChaGetFileInfo.c`;
- `/home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c:74`;
- `/home/chukyu/t-tmm/src/tmm000/tmm000_deamon.c:56`.

Stop F2 when bounded sets are emitted with explicit provenance and no report
counts them as ordinary exact paths.

### F3 — make macro, enum, and non-UTF-8 header resolution uniform

The current capability works for some macro patterns but not all. Audit the
entire active include chain instead of only the target source file.

Implement:

1. A byte-preserving macro/enum index keyed by canonical absolute header path.
2. Include-aware lookup that prefers the active header in the process source
   and Makefile include configuration.
3. Explicit enum-constant extraction, not only `#define` extraction.
4. Macro-chain resolution with source file/line provenance.
5. Diagnostics when a header could not be decoded, parsed, or selected.
6. A consistency check: a bare identifier used as a target argument that is
   proven to be an active macro/enum must not fall through to `EXTERNAL_DATA`.

Read SJIS/non-UTF-8 headers as bytes and decode only for display with a
lossless strategy. Test the active headers called out by the report:

- `t-dyn/include/Dyn/DynReEneFileDef.h`;
- `t-dif/include/Dif.h` and `DifP.h`;
- `t-dxi/include/dxi_const.h`;
- `t-tmm/include/TmmFileNo.h`;
- `t-cha/include/ChaDef.h`.

Production targets:

- `/home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:151` with
  `PROC_NAME` from line 47;
- `/home/chukyu/t-dif/src/dif400d/dif400Deque.c:65`;
- `/home/chukyu/t-dxi/src/dxi110d/dxi110d_parent.c:2298,2316`;
- `/home/chukyu/t-dxi/src/dxiG150d/dxiG150d_child.c:936`;
- `/home/chukyu/t-dyn/src/dyn710/dyn710Init.c:292`.

Keep the working contrast case as a regression test:
`/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:78` already resolves a similar
local macro. The fix must make the failing case behave like the working case,
not weaken the working case's source ownership rules.

### F4 — model wrapper output writes and kill impossible initializers

The `ChaLrgCom.c` false value `0` is a precision bug. Do not solve it by
removing all zero initializers.

Add declarative write-effect metadata for wrappers such as `ChaGetFileInfo`:

```text
function: ChaGetFileInfo
writes_arguments: [3, 4]
return_error_values: [-1]
output_value_rule: bounded_table(TM/SV)
```

During local data-flow:

1. Track the initializer `iOpenFileNo = 0`.
2. Recognize the call writing `&iOpenFileNo`.
3. Recognize the immediate `if (return == -1) return` failure guard.
4. On the succeeding path, kill `0` and replace it with the wrapper's bounded
   output set.
5. If the return value is not checked, the wrapper rule is incomplete, or the
   call may leave the output unchanged, retain `0` as a possible value and do
   not claim the write was guaranteed.

Regression targets:

- `/home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:458,470,477`;
- `:657,663`;
- `:996,1008,1015`;
- `:1127,1133`.

Expected result: no `0` value at those opens/reads; the result is the
appropriate TM/SV bounded set with wrapper provenance. Add a counterexample
where the error path does not return and verify the initializer remains.

### F5 — fix nested `else if` branch merging

The current `_local_reaching_definitions()` logic treats an outer `if` as two
arms and can miss assignments in a nested `else if` arm. Replace the special
two-arm shortcut with a small recursive arm collector for assignments to the
same variable.

For a chain:

```c
if (a)       x = A;
else if (b)  x = B;
else         x = C;
```

collect all live arms in source order, preserve the value set `{A,B,C}`, and
retain the existing conservative behavior for a missing `else` or an arm that
does not assign the variable. Do not infer mutual exclusivity as a reason to
drop an arm; the output is a possible-value set.

Add a fixture with 3, 4, and nested branch arms, including an arm added after
the original source version. Assert that the merged set size equals the number
of live assignments.

Production targets:

- `/home/chukyu/t-dxi/src/dxi110d/dxi110d_parent.c:1582-1591`, target sites
  `:1687` and `:1695`, expected `{2512,2519,2525}`;
- `/home/chukyu/t-dxi/src/libdxiinside/dxi_initmng.c:72,80`, same set;
- `/home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:898,904`, expected
  `{2502,2517,2523}`.

### F6 — trace pointer-parameter handles through in-tree callers

When a target uses a pointer parameter such as `set_fcb`, the resolver must
enumerate all in-tree callers and map the actual argument back to its open.

Update the parameter path around `_resolve_parameter()` and `_resolve_handle()`:

- use reverse call-graph edges for the formal parameter;
- accept `&local_fcb`, direct pointer variables, and compatible casts;
- resolve the caller's open and file-number argument;
- preserve one result per caller/value;
- distinguish an address-passed mutable pointer from a by-value scalar;
- do not use nearby-open proximity when handle identity is not proven.

Initially enumerate all syntactically valid in-tree callers, then annotate
whether each caller is root-reachable. This prevents a missing root from
silently looking like an external parameter while keeping provenance honest.

Production targets:

- `/home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:636`, callers around
  `tmm910_gnqset.c:284,314`, open at `tmm910_gnqmnt.c:84` with FNO 2716;
- `ChaReadRecm`, `ChaReadTm`, `ChaReadSv`, and `ChaWriteRecn` in
  `/home/chukyu/t-cha/src/libChaCom/ChaCase.c`;
- `DxiEnqEvent`, `DxiEnqEvent2`, `Dxi_DnTbnFileCtrl`, and `Dxi_FcbG` users.

Add tests for multiple callers with distinct values and for a caller passing a
different FCB. The latter must not inherit the first caller's value.

### F7 — track file-static FCBs across functions

Add a translation-unit-level index for file-scope `static` FCB variables. For
each static FCB, record:

- declaration file and identity;
- opens in each function;
- closes and writes;
- uses in sibling functions;
- any function parameter or global alias that can change the binding.

Only connect an open in function A to a use in function B when the variable
identity is the same and no proven close/rebind invalidates the relationship.
Keep this separate from global symbol lookup so same-named statics in different
files cannot collide.

Production target:

- `/home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c:131,143`, where
  `SFcbRE` is opened in `DynReEneOutStaGet` with `DynReOutStaFNO=3937` and
  used by the sibling function.

Add a fixture with two translation units containing same-named statics; only
the correct file's open may bind.

### F8 — propagate bounded local strings into forkproc names

Add a conservative string-constant transfer for local character buffers:

- direct string assignment where represented by the AST;
- `strcpy(destination, "literal")`;
- `strncpy(destination, "literal", constant_bound)`;
- branch-union of multiple literal writes;
- safe `memset` only as initialization, not as a process name.

Do not infer arbitrary `sprintf`, input/config data, or dynamically assembled
strings as exact names. Emit `BOUNDED_SET`/`EXTERNAL` as appropriate.

For a forkproc target, preserve the raw expression, the buffer name, each write
site, and the resulting string set.

Production targets:

- `/home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1262`, expected
  `{ECS-A,ECS-B}` from writes at `:1227` and `:1233`;
- `/home/chukyu/t-dxi/src/libdxiinside/dxi_dblcirreq.c:100`, expected
  `{dxi500d,dxi501d,dxi502d}`;
- the working/failing macro contrast in `libDynDspCom.c:151` and
  `libDynRe/DynReEneLib.c:78`.

Add a negative test for a string read from configuration and a positive test
for two branch-selected literals.

### Phase 4 regression invariants

Before accepting these changes, rerun the existing correct-case tests and add
explicit assertions for:

- reopen identity: `dxi150d/dxiG150d_main.c:1042` must not include the earlier
  FNO after the handle is reopened;
- branch union: `libDynRe/DynRePfmCSVOut.c:188` keeps both values;
- local branch union: `dyn432dAdvCtrl.c:108,116,269` keeps both values;
- cross-module header constant: `libDynRe/DynReITCLock.c:83` remains 2022;
- type-branch values: `dxiG_cirmng.c:146` keeps both 2552 and 2554;
- disabled source does not become active merely because a macro is found in a
  disabled branch;
- runtime/config-loaded values remain `EXTERNAL`/`DYNAMIC` rather than being
  guessed.

Stop Phase 4 only when each F1–F8 has a focused fixture, at least one listed
production target, provenance in the output, and a negative test preventing
the obvious unsound shortcut.

## Phase 5 — rerun the full audit and update the checklist

After Phases 1–3:

1. Rerun the full process pipeline.
2. Rebuild per-process indexes and the aggregate index from the new results.
3. Re-run `analysis/step0.py` and `analysis/step1.py`.
4. Reclassify the prior 225 apparent gaps:
   - parser/root failures should become recovered or `ROOT_PARSE_FAILURE`;
   - callback cases should become recovered or explicit callback diagnostics;
   - cross-project cases should become cross-process evidence;
   - genuinely dead cases should remain ordinary in-process unreachable.
5. Add the F1–F8 audit classifications to the report. Do not collapse
   `BOUNDED_SET`, `LOCAL_BACKWALK`, callback, root-failure, or cross-process
   evidence into generic `UNREACHABLE`.
6. Run the previously omitted agent-6 scope (`t-sim`, `t-svm`, `t-rep`) or
   explicitly record it as an unfinished audit. Any new failure pattern must
   receive a fixture before the plan is considered complete.
7. Compare physical site identity, not only total resolution counts.
8. Save a before/after summary with:
   - root count and root failures;
   - callback edges and callback-reached targets;
   - cross-process rows and owner resolutions;
   - local-backwalk values;
   - bounded-table values;
   - wrapper write effects;
   - pointer-parameter and file-static bindings;
   - string-flow forkproc values;
   - exact rows by process;
   - remaining `UNREACHABLE_IN_PROCESS` rows.

## Global stop conditions

The implementation is complete only when all are true:

- multiple configured roots are preserved and traversed;
- no executable test process has an unexplained empty root list;
- encoding and duplicate prototype cases do not lose valid root bodies;
- callback functions survive direct, alias, and wrapper-macro forms;
- callback paths carry registrar provenance;
- cross-process evidence is visible and separately classified;
- cross-process rows do not inflate exact process or aggregate counts;
- library-only scopes are not falsely treated as executable roots;
- same-function visible opens are either root-recovered or explicitly marked
  `LOCAL_BACKWALK`;
- bounded table/wrapper outputs are represented as bounded sets, not dropped or
  falsely flattened into one value;
- active macro/enum values resolve through non-UTF-8 headers;
- guaranteed wrapper writes eliminate impossible initializer-only values;
- all live `else if` arms survive value merging;
- pointer-parameter and file-static FCB bindings carry source provenance;
- statically provable forkproc string sets are resolved without guessing
  runtime/configuration strings;
- `dyn730`, `dyn710`, `cha702`, `tmm200d`, `dif901`, `libdif`, and `svm000`
  satisfy the targeted checks;
- the agent-6 corpus scope is either audited or explicitly listed as pending;
- all focused and full tests pass;
- no LLM/agent is required for normal pipeline execution;
- no unrelated resolver, frontend, or schema behavior is changed.

If a production target still fails after these conditions, stop and record the
remaining source pattern and evidence. Do not broaden accepted root names,
apply global macro undefines, count library evidence as process resolution, or
add speculative callback edges without a new source-backed test.
