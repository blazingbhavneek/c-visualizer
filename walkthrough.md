# Value-Flow Analysis: Linear Walkthrough

Setting: you point the tool at a C project. Goal = for every "target" API call
(like `pmf_setsem(NAME, 0)`), find what real value each argument had, and how that
value traveled from `main` down to the call.

---

## ACT 1 — Read the project (`project_aware.py`, function `trace_variable`)

This one function drives everything. Steps in order:

**1. Find all project files.**
`return_project_mapping(...)` -> `PROJECT_STRUCTURE` = dict `{filename: full path}`
of every `.c`/`.h` involved. Cached to a `.pkl` so next run skips this. Also
returns `potential_main_files` (files that might hold `main`).

**2. Parse every file into a syntax tree.**
`Preprocess.preprocess(...)` -> `trees` = dict
`{filename: (tree-sitter tree, cleaned source bytes)}`. Tree-sitter turns C text
into a structured tree the code can walk.

**3. Per-file bookkeeping.**
Loop over files: `extract_all_macros` -> `macros`, `extract_includes` ->
`file_includes`, `get_local_function_definitions` -> `FILE_FUNCTIONS`
(`{file: {funcname: def}}`). Also picks the real entry point(s) -> `entry_points`
list of `(file, funcname)`.

**4. Build the call graph.**
`build_complete_call_graph(...)` -> `graph` (who calls whom, with call-site info)
+ `registry` (every function as a node). This is the map the backward walk uses.

**5. Snapshot for the visualizer.**
`VisualizerCollector` captures source + call graph, writes a checkpoint file.
(Optional `summarize_collector` adds LLM summaries per function.) If
`index_only=True`, stop here.

**6. Find which targets actually appear.**
`identify_funs_to_trace(...)` -> `functions_identified` = subset of the target
config JSON that is actually called in this project, with which argument numbers
to trace.

**7. Inventory the exact target call sites.**
`build_target_site_inventory(...)` (in `discovery_index.py`) -> `target_sites` =
flat list of "here is target X, argument N, at file:line". Used later for
reporting even if resolution fails.

**8. Launch the resolver.**
`resolver == "valueflow"` -> calls `make_value_flow_calls(...)`. (Old path:
`make_llm_calls_for_function` per function — legacy fallback, ignore.)

---

## ACT 2 — Set up the resolver (`project_aware.py`, `make_value_flow_calls`)

**9. Get the AI helpers ready.**

Most of the work in Act 3 is done by plain code reading the parsed C. But now and
then the code gets stuck. Two situations:

- A function passes an argument on to another call, but does a bit of math on
  it first. Example:
  ```c
  void caller(int fno) {
      open(fno + 1);   // caller was given fno, but open() gets fno + 1
  }
  ```
  The tracer can see `open` got `fno + 1`. It wants the clean answer:
  "= caller's `fno`, plus 1". That `+ 1` in the middle is the part it needs
  help pinning down.

- A function hands back a pointer and we need to know if the program then
  *reads* from it or *writes* to it. Example:
  ```c
  buf = get_record(a, b);
  memcpy(dst, buf, n);   // buf is being READ
  ```

For stuck spots like these, the code asks a local AI model (Ollama). Step 9 just
builds the little "ask the AI" functions and hands them to the resolver. The
resolver decides *when* to use them.

**9a. Is the AI even running?** `llm_endpoint_status()` pokes the model server
once.
- If it answers: plug in the real AI helpers below.
- If it's down: plug in dummy helpers that always say "don't know". The analysis
  still finishes; the stuck spots are just left marked unresolved. The startup
  log prints `VALUE-FLOW LLM DISABLED (syntax-only run)`.

**9b. Grab the surrounding code.** Before asking the AI anything, you show it the
relevant C. `context_for` / `run_context` build a text blob for one call site.
It's not just the one function — it also has:

- each function along the path from the caller down to the target, trimmed to
  the part that matters, with the exact call line tagged `/*CONSIDER THIS CALL*/`
  so the AI can't pick the wrong one
- a comment block at the top listing macro expansions and callbacks involved
- a list of every macro name used in that code and its value, like
  `//FNO_HEALTH=0x120`

So the blob looks roughly like:
```c
/*INFO ABOUT MACRO EXPANSIONS AND CALLBACKS.
... */
//FNO_HEALTH=0x120
void DioGetPtr(int filenum) {
    ret = mpf_mfs_open(&fcb, filenum, 0); /*CONSIDER THIS CALL*/
}
```
That blob gets pasted into the AI prompt. (Runs on a side thread so it doesn't
freeze everything else.)

**9c. Helper #1 — "where did this argument come from?"** (`resolve_transfer`)
The resolver calls this about **one specific call**. It sends the AI: the
function's code, its parameters (renamed `$1`, `$2`, `$3`... so the AI can't leak
local variable names), and the exact call line in question. The AI must reply in
one of three shapes:

| Reply | Means | Example |
|---|---|---|
| a formula | "it's this parameter with some math on it" | call is `open(fno + 1)` and `fno` is param 1 → answer `"$1 + 1"` |
| EXTERNAL | "it comes from outside / from a table, I can't reduce it to a number" | `"Tbl[nIdx].Schfno"` |
| UNKNOWN | "it comes from another function I can't follow here" | `"DynREGetSchfno(nFnoidx)"` |

After the AI answers, the code does **not** just trust it — it checks the formula
actually matches the real source line (Act 4). If the AI times out (120s) or the
server is down, the answer is just "don't know".

**9d. Helper #2 — "is the return value read or written?"** (`resolve_return_use`)
Used when a target's config says to follow the *return value* instead of an
argument. It shows the AI the code after the call and asks: does the program read
from what came back, or write into it? The AI replies READ / WRITE / NOTHING, and
that becomes the operation recorded for that call.

> Side note on `read`/`close` targets (different mechanism, `dependent_`
> `functions` in the config): these calls carry a handle, not a value, so the
> resolver doesn't look at their own arguments. It walks back to the matching
> `open(&fcb, FILE_NO)`, then resolves *that open's* value argument the normal
> way, and uses it as the answer. So the open is always resolved before the
> read/close gets its value — it just happens lazily, as a sub-step of
> resolving the read/close. If the same open is also its own target, the query
> cache means it's only computed once.
>
> **How it makes sure the right open goes with the right read/close**
> (`_binding_opens`, `_handle_candidates`, `normalise_handle`):
>
> 1. **Same handle name.** The handle text is cleaned up first — `&fcb`,
>    `(fcb)`, `fcb[2]` all become `fcb`. But a struct field keeps its owner:
>    `ctx->fcb` and `ctx->other` stay different. The open and the read/close
>    must have the *same* cleaned name.
>    ```c
>    open(&fileA, 10);
>    open(&fileB, 20);
>    read(&fileB);        // matches the fileB open (value 20), not fileA
>    ```
> 2. **Open must come first.** Only opens that appear *before* the read/close
>    (in the same function) are candidates.
> 3. **A close in between cancels the open.** If the handle was already closed
>    before this call, that earlier open doesn't count — the resolver looks for
>    an open *after* the last close.
>    ```c
>    open(&f, 10);
>    read(&f);           // -> 10
>    close(&f);
>    open(&f, 99);
>    read(&f);           // -> 99, not 10
>    ```
>    (A close that only runs in an early-`return` error branch is ignored,
>    since the normal path never hit it.)
> 4. **Where it looks.** Same function first. If the handle came in as a
>    parameter, it follows the callers up and matches there. If it's a global
>    or a struct field, it searches the other reachable functions for the open.
> 5. **If two opens both match and it can't tell which — it refuses to guess.**
>    The result is marked `HANDLE_AMBIGUOUS` rather than a made-up value.
> 6. The config can also set `handle_index` to say exactly which argument is
>    the handle, and there's an LLM fallback as a last resort.

**9e. Two worker pools.** One pool does the "grab the surrounding code" work
(9b), the other does the actual waiting-on-the-AI. They're kept apart so a pile
of code-grabbing jobs can't block the AI calls, and vice versa.

**10. Build `ValueFlowResolver`** (`value_flow/resolver.py`, `__init__`). Runs its
indexing in this order (see the "read these in this order" comment at line ~527):

| Method | Builds | Result |
|---|---|---|
| `_build_function_index` | every function def + its parameter names | `self.functions` |
| `_build_file_static_index` | file-scope `static` variables | |
| `_build_call_index` | turns each call site into an `IndexedSite` (call + AST args + stable byte-ID) | `self.sites` |
| `_build_callback_edges` | fake edges for framework callbacks | |
| `_compute_reachability` | which functions are reachable from an entry point, directly vs only via callback | `self.reachable` |
| `_enumerate_seeds` | one `Seed` per concrete target call site (2 calls to `mdm_open` = 2 seeds) | `self.seeds` |
| `_load_cache` | load previously-answered sub-questions from `query_cache.json` | `self.results` |

A `Seed` = "target function X, at this exact call site, with this config (which
args, dependent open/close funcs), launched via Y."

---

## ACT 3 — Resolve every seed (`resolver.run`)

**11. `run()` sorts the seeds into two piles, then works both piles at the same
time.**

- **fast pile** (`_seed_is_fast`): every value it needs is *right there* at the
  call — a plain number or a `#define`. Example: `pmf_setsem("svm300d", 0)`, or
  `pmf_setsem(NAME, 0)` where `NAME` is `#define NAME "svm300d"`. Nothing to
  chase.
- **slow pile**: at least one value is a variable, a parameter, or comes out of
  another call — needs the backward walk.

The two piles get **separate worker queues** running concurrently: the fast pile
gets up to 10 workers, the slow pile up to `llm_concurrency`. They run together
(`asyncio.gather`), so a fast seed never waits behind a slow LLM-bound one. Each
seed goes to `_resolve_seed(seed)`.

> **TODO / possible optimization:** right now `run()` does one upfront pass over
> *all* seeds to sort them (`_seed_is_fast`) before any resolution starts. Could
> instead resolve each fast seed inline as it's classified and only queue the
> slow ones. Minor — the sort pass is cheap and current speed is fine; noting it
> for later.

**12. `_resolve_seed` picks how to trace this one seed** — three cases:

**Case A — nothing to trace, or provable on the spot** -> `_resolve_seed_from_`
`queries` (plain query engine, no AI).
- *Nothing to trace:* the target's config lists no argument to resolve, e.g.
  `pmf_yield()` — we only care that it's reached.
- *Provable on the spot:* the value is a literal, a macro, or a local variable
  assigned a constant just above the call:
  ```c
  int mode = 5;
  target(mode);        // walk up 2 lines in the same function -> 5
  ```

**Case B — needs a real backward walk and the AI is up** -> `_resolve_seed_with_`
`transfers` (follows the call route backward, asks the AI about any math on the
way, double-checks its answers).
```c
void w(int fno) { open(fno + 1); }
...
w(FILE_NO);            // must walk open <- w's param <- caller, confirm the +1
```

**Case C — needs a backward walk but the AI is down** -> falls back to
`_resolve_seed_from_queries` anyway. It still follows parameters up to callers
(that's plain syntax), it just can't handle the "value changed by some math"
spots — those come back `UNRESOLVED`.

> **Important — there are TWO separate backwalk engines, not layers.**
> `_resolve_seed` forks to one or the other *per seed*; a seed goes down one
> road, never both.
>
> | | **Query engine** (`_resolve_seed_from_queries`) | **Transfer engine** (`_resolve_seed_with_transfers`) |
> |---|---|---|
> | core method | `_resolve_expression` (the ladder in step 14) | routes + per-hop LLM formulas (Act 4) |
> | uses the AI? | no | yes, one small question per call-hop |
> | handles | literals, macros, enums, constant tables, plain rename chains, parameter -> caller fan-out | "value went through math across functions" |
> | picked when | seed is "fast" / fully locally provable, **or** the AI is down (fallback) | value is not locally provable **and** the AI is up |
>
> The query engine is the cheap workhorse — most seeds in a normal project go
> here. The transfer engine is the expensive path for the messy tail. Steps
> 13–14 below describe the **query engine**; Act 4 describes the transfer
> engine. They also share small pieces: resolving an `open`'s value for a
> handle, return-use, and `call_number` all run through the query engine even
> during a transfer-engine seed.
>
> **TODO — a richer LLM backwalk.** Both engines are limited: the query engine
> can't do math at all, and the transfer engine's formula grammar is
> arithmetic-only (no local names, no function calls) with a ~2-hop local
> limit. Neither can follow a value through a helper call or a pointer write
> in the middle (`x = 5; modify(&x); target(x);`). A stronger design: let the
> LLM read the whole parameter->target span (across several functions at once,
> not one hop at a time), describe every transformation including
> `x = helper(y)` and in-place mutations, and only *then* hand back to the
> code for the ParamQuery/ArgQuery caller substitution. Current code is ~75%
> of this — the per-hop formula loop exists, but the "what counts as a
> transformation" vocabulary is too narrow.

**13. Both strategies ask "questions" via `resolve(query)`** (`resolver.py:1189`).
Question types (`value_flow/queries.py`):

| Query | Means | Answered by |
|---|---|---|
| `ArgQuery` | "at this one specific call, what got passed in slot N?" | `_resolve_argument` |
| `ParamQuery` | "this function has a parameter N — what values can ever arrive in it?" | `_resolve_parameter` |
| `HandleQuery` | "which `open` created the handle used here?" | `_resolve_handle` |
| `ReturnUseQuery` | "is this returned resource read or written after?" | LLM `resolve_return_use` |

**`ArgQuery` vs `ParamQuery` — the difference:**

```c
void wrapper(int fno) {      // <- fno is a PARAMETER
    open(fno);
}

void a() { wrapper(10); }    // <- 10 is an ARGUMENT at this call
void b() { wrapper(20); }    // <- 20 is an ARGUMENT at this call
```

- `ArgQuery(call in a(), slot 1)` -> looks at *that one line* -> answer: `10`.
- `ParamQuery(wrapper, param 1)` -> "what can `fno` be?" -> `_resolve_parameter`
  finds every place `wrapper` is called (here: `a` and `b`), fires an `ArgQuery`
  at each one, and collects **all** answers -> `{10, 20}`.

So `ArgQuery` is one exact spot; `ParamQuery` is "spread out to every caller and
gather what they pass." The backward walk bounces between the two: tracing
`open(fno)` finds `fno` is a parameter -> `ParamQuery` -> which turns into an
`ArgQuery` per caller -> if a caller passes another variable, that may be a
parameter too -> another `ParamQuery`, and so on up to `main`.

Every query has a stable `token()` string -> cached in `self.results`, so if two
paths hit the same "what can `wrapper`'s param 1 be?" it's only computed once.

**14. The core walk — `_resolve_argument` -> `_resolve_expression`**
(`resolver.py:1341`). Takes the argument expression and tries sources
cheapest->least-certain:

1. literal (`0`, `"svm300d"`) -> `Fact(origin_kind="CONST")` — done.
2. macro / enum name -> `_resolve_macro` -> a `#define` gives `Fact("MACRO")`, an
   enum constant gives `Fact("CONST")` (tagged `termination_reason="ENUM"`).

   > **Next level — how enums are handled.** At startup `_build_enum_index`
   > walks every file's syntax tree looking for `enum { ... }` blocks and works
   > out each name's integer value — following `= 5`, auto-increment, and simple
   > expressions like `A | B` via `_evaluate_enum_expression`. Example source:
   > ```c
   > enum FileNo {
   >     FNO_HEALTH = 0x120,   // -> 288
   >     FNO_NEXT              // -> 289 (auto +1)
   > };
   > ...
   > open(&fcb, FNO_HEALTH);
   > ```
   > It stores, per file, `{ "FNO_HEALTH": ("288", "table.h", 12), ... }` — only
   > for enums actually visible through that file's `#include` graph.
   >
   > During the walk, the expression `FNO_HEALTH` goes to `_resolve_macro`,
   > which checks the enum index *first*, then `#define`s. Match -> terminal
   > `Fact(value="288", origin_kind="CONST", source_expr="FNO_HEALTH")`. No
   > further walking — an enum value is fixed at compile time.
   >
   > If the same name has two different values in two visible headers, it's
   > marked **ambiguous** and dropped — the walk treats it as unresolved rather
   > than pick one.
3. runtime input name (came from external data) ->
   `Fact("RUNTIME_DATA"/"EXTERNAL_DATA")`.

   > **TODO — resolve file-scope globals before calling them EXTERNAL.** Right
   > now a read of a global / file-scope variable isn't chased: the backwalk
   > only looks in the same function and up through parameters, so it lands on
   > the LLM or `UNRESOLVED`. Better: do a small extra search for an
   > initializer or a constant assignment to that global in the same file or a
   > visible header (like the handle code already does for opens). If a
   > constant is found -> resolve it. Only if nothing is found should it be
   > `EXTERNAL` — meaning "the middleware/daemon fills this in at runtime",
   > which is the real intent of that status.
4. it's a function parameter -> emit `ParamQuery`, walk up to all callers.

   > This shortcut is only taken if the argument is the **bare** parameter
   > name (`target(fno)`, not `target(fno + 1)`) **and**
   > `_parameter_fast_path_safe` has explicitly checked that `fno` is never
   > reassigned (`fno = ...`) and its address is never taken (`&fno`)
   > anywhere in the function. If either check fails, the shortcut is skipped
   > and step 5 (reaching-definitions) traces the real last assignment
   > instead. (Regex-based, so it can still miss aliased-pointer mutation or
   > a write hidden behind a macro.)
5. it's a local variable -> `_local_reaching_definitions` /
   `_collect_switch_values` / `_collect_branch_values` find what was assigned to
   it.

   > The value is a variable set earlier in *this same function*. Look upward
   > from the call for the last line that assigned it. If it was set inside an
   > `if` / `switch`, take the value from **every branch** that could run.
   > ```c
   > int m;
   > if (cond) m = 1; else m = 2;
   > target(m);          // -> { 1, 2 }
   > ```
   > Only follows plain assignments (`m = OTHER_CONST`, `m = n`). If the
   > assignment has math in it, that part is handed off (see 8).

6. it comes from a table lookup -> `_resolve_table_expression`,
   `_constant_table_values`, `_indexed_table_facts`, `_bounded_table_indices`.

   > The value is `arr[i]` or `tbl[i].field`. Read the array's initializer
   > straight from the source.
   > - `i` is a constant -> pick that one row.
   > - `i` is a variable / loop counter -> work out the range `i` can take,
   >   keep **all** rows it could land on, tag `BOUNDED_SET` (capped at 32).
   > ```c
   > static int FNO[] = { 10, 20, 30 };
   > target(FNO[k]);     // k unknown but 0..2 -> { 10, 20, 30 }
   > ```

7. it comes from a wrapper's output arg -> `_wrapper_output_facts` (guided by
   `value_flow/value_rules.py`).

   > Some functions don't *return* the value — they write it into a pointer
   > argument. `value_rules.py` is a hardcoded list saying e.g. "for
   > `Dxi_UpTbnFileOpen`, the file number lands in argument 3." So when the
   > traced value came out of such a call, read it from that argument's source
   > instead of chasing a return value.
   > ```c
   > Dxi_UpTbnFileOpen(a, b, &fno, ...);   // rule: arg 3 gets written
   > target(fno);                          // -> what the wrapper's table put there
   > ```

8. value carried across a call by a formula -> **transfers** (Act 4).

   > The value is a parameter with math on it (`target(fno + 1)`), so it
   > can't be finished here — handed to the transfer engine, which builds the
   > formula and substitutes each caller's value.

9. LLM guess -> `Fact("LLM_CANDIDATE")` (evidence only, never treated as exact).
10. nothing works -> `Fact("UNKNOWN_INDIRECT"/"UNRESOLVED")`.

Each `Fact` (`queries.py`) records: the value, origin kind, source
file/line/expr, and the query token (so the path back can be rebuilt).

> **Which of steps 1–10 use the AI?** Almost none. Steps 1–7 and 10 are pure
> code. Only **step 8** is the transfer engine (per-hop LLM formulas, Act 4).
> Step 9 (`_call_one_hop` → `LLM_CANDIDATE`) and the `EXTERNAL_DATA` half of
> step 3 are a *legacy* one-hop LLM call that is **switched off in normal
> value-flow runs** (`one_hop_resolver` is only wired up for the old legacy
> resolver) — so in practice they never fire. This whole ladder is the cheap
> code-only engine; the AI lives in step 8 / Act 4.

**15. Handle pairing** (`_resolve_handle`, uses `value_flow/handles.py`):
`close(&fcb)` -> `normalise_handle` turns `&fcb`, `(fcb)`, `fcb[i]` all into key
`fcb` -> finds the matching `open(&fcb, FILE_NO)` in the same function /
parameter / global -> then resolves `FILE_NO` normally.

---

## ACT 4 — Transfers: value crossing a call (`value_flow/transfers.py`)

Used when the value isn't sitting right there at the call — it's a parameter
with some math on it, or it keeps changing as it's handed from function to
function.

The trick: keep a small "recipe" for the value and carry it backward one
function at a time. At each function, swap in what that function's caller
actually passed. Stop when the recipe is all numbers.

Use this example the whole way through:
```c
#define FNO_BASE 100

void handler(void) {
    wrapper(FNO_BASE);
}
void wrapper(int base) {
    if (base > 0)
        target(base + 1);      // we want: what number is target's 1st arg?
}
```

**16. Find the paths and write the first recipe.**
`routes_for_seed` lists every call chain that ends at this `target` call. Here
there's one: `handler -> wrapper -> target`.

Starting recipe, taken straight from the call: **"arg 1 = `base + 1`"**.
Also note the `if` around the call as a condition that must be true:
**`base > 0`**.

(`base` is written as `$1` internally — "the 1st thing wrapper was given" — so it
can be replaced later. Ignore that detail if it's noise.)

**17. Step back through the functions.**

*Now in `wrapper`.* `base` is wrapper's own parameter, so wrapper can't finish
the recipe by itself — it needs to know what its callers pass. The recipe stays
**"arg 1 = (what the caller passed) + 1"**, condition **"(what the caller
passed) > 0"**.

> This step is where the **AI** gets asked — but only if the recipe is too
> complicated for plain code (a helper call like `x = lookup(base)`, or a value
> built up over many lines). The AI is shown just this one function and asked
> "what's the recipe for this argument?". Its answer is then matched against the
> real code lines; if it doesn't match, it's thrown out. Simple `base + 1` here
> needs no AI.

*Cross into `handler`.* `handler` calls `wrapper(FNO_BASE)`, so "what the caller
passed" = `FNO_BASE`. Fill that in: recipe **"arg 1 = `FNO_BASE + 1`"**,
condition **"`FNO_BASE > 0`"**.

*Still in `handler`.* `FNO_BASE` is a `#define` for `100`. Fill that in: recipe
**"arg 1 = `100 + 1`"**, condition **"`100 > 0`"**. `handler` is the top — done.

**Conditions are checked as they fill in.** `100 > 0` is true, so this path is
real — keep it. If `handler` had instead called `wrapper(-5)`, the condition
would become `-5 > 0`, which is false, so the `if` would have skipped the
`target` call on this path — the whole path is **dropped** and produces no
answer. This is how the engine avoids reporting values that an `if` actually
blocks.

**18. Compute the number and save it.** `100 + 1` = **`101`**.
`_fact_from_transfer_binding` saves a `Fact`: `value = "101"`, plus the
supporting info — the exact code lines that prove it (`target(base + 1)`,
`wrapper(FNO_BASE)`, the `#define`), the conditions, the path
`handler -> wrapper -> target`, and — if this call turned out to have more than
one possible number — a shared id linking them as one set.

---

## ACT 5 — Package results

**19. Provenance / paths** (`resolver.py`): `_add_provenance` linked each child
query to its parent during the walk. Now `paths_for_fact` / `provenance_tokens` /
`legacy_path_labels` walk that chain forward -> the readable path
`main -> foo -> wrapper -> target`.

**20. `resolver.run()` returns `records`** = list of `ResolvedSeed` (one per
value/path): `{seed, fact, route, legacy_labels, paths, call_number,
operation}`.

**21. Classify status** (`value_flow/status.py`, `classify_records`): groups all
records for one (site, arg), collapses to a single verdict:
- `RESOLVED` (one exact literal), `RUNTIME` (several possible literals = a
  value-set, gets a `set_id`), `EXTERNAL`, `UNRESOLVED`, `NO_TARGET`.

**22. Write outputs** (`value_flow/outputs.py`):
- `write_outputs` -> `facts.csv` (each value), `paths.csv` (proof paths),
  top-level `<project>.csv` (the feed the visualizer reads), `run_stats.json`.
- `write_trace_logs` -> per-path debug logs.

**23. Back in `trace_variable`:**
- `valueflow_records_to_facts` (`discovery_index.py`) -> `discovery_facts`, then
  `write_discovery_index` -> `index/` folder (machine-readable inventory +
  evidence).
- `collector.rehydrate_interactions(...)` -> reads the CSV back, adds the
  resolved connections into the visualizer graph, `collector.write()` again.
- patches final timings into `run_stats.json`.
- returns `answers` (legacy-shaped dict
  `{target_function: [(Combined, Stats), ...]}`).

---

## One-line-per-file recap

| File | Job |
|---|---|
| `project_aware.py` `trace_variable` | orchestrator: parse project, build call graph, run resolver, write everything |
| `project_aware.py` `make_value_flow_calls` | wires LLM callbacks + builds `ValueFlowResolver` + calls `.run()` |
| `value_flow/resolver.py` | the engine: index code, enumerate seeds, walk backward, produce `ResolvedSeed` records |
| `value_flow/queries.py` | the question shapes (`ArgQuery`/`ParamQuery`/`HandleQuery`/`ReturnUseQuery`) and the answer shape (`Fact`) |
| `value_flow/handles.py` | normalize handle expressions so `close` finds its `open` |
| `value_flow/transfers.py` | formula parse/eval + route/guard model for values crossing calls |
| `value_flow/value_rules.py` | hardcoded per-wrapper rules (which arg/table a known function writes) |
| `value_flow/status.py` | final verdict per target arg (RESOLVED / RUNTIME / EXTERNAL / UNRESOLVED) |
| `value_flow/outputs.py` | write CSVs and logs |
