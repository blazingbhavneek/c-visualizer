# Plan: Replace path-enumeration tracing with value-flow resolution

Status: proposal, not yet implemented.
Written after the design conversation. Every decision below cites the message it
came from, so nothing here is my invention unless it says so.

---

## 0. How to read this document

Section 1 explains the problem and the idea in plain language.
Section 2 lists what I verified by reading the code (ground truth).
Section 3 lists mistakes I made during the conversation and the corrections, so
nobody re-introduces them.
Section 4 is the design.
Section 5 is the implementation phases, in order, with a safety gate on each.
Section 6 is risk and fallback.
Section 7 is the message-by-message provenance index.

If you only read one thing, read **Section 3 (mistakes)** and **Section 6
(risks)**. Those are where this can go wrong.

---

## 1. The problem and the idea, in plain language

### 1.1 What happens today

The tracer wants to know: *what concrete values reach a specific argument of a
specific framework function?* For example, which file number is passed to
`mpf_mfs_open`.

Today it answers that by:

1. Building a call graph (`CallGraphBuilder.build`).
2. Turning that graph into a giant materialised tree (`build_call_trees`).
3. Walking the tree to list **every route from `main` to the target**
   (`dfs_for_finding_path`).
4. Sending **one LLM request per route**.

You reported the real number: *"60 unique target point instances can turn into
100,000 paths"* and *"that much llm calls will take like multiple days, thats for
one process one target function. This is unacceptable."* [MSG 1 — you]

### 1.2 Why the number is so big

Path counting **multiplies**. Every branch above a function multiplies the number
of routes through it.

```
main
 ├─ P ─┐
 ├─ Q ─┼──→ M ──→ A ──→ target
 └─ R ─┘
```

That is 3 routes. Add 100 branches above `M` and it is 100 routes. Add another
fan-out higher up and you multiply again. That is where 100,000 comes from.

But the **answer** does not depend on any of that. If `M` passes a constant to
`A`, the value is decided at `M`. Everything above `M` is irrelevant to the
question being asked.

### 1.3 The idea

Start at the target and walk **backward**, and stop as soon as the value is
concrete. You proposed exactly this [MSG 1 — you]:

> "either our target's target parameter is constant/resolved from a macro, in
> that case the 'path is done' ... whats the other case? the target parameter of
> target depends on the input of A, right? so how will we resolve? find all the
> invocations of A right?"

Walking backward **adds** instead of multiplying. In the picture above, if `M`
passes a constant, we ask 2 questions and never look at `P`, `Q`, `R` at all.
Even in the worst case where we *do* need `P`, `Q` and `R`, we ask about each
**once** — 3 questions — while path enumeration would produce 3 × (however many
ways each of them is reachable from `main`) routes.

**This — not caching — is the main saving.** I initially led with caching and had
to correct myself [MSG 8 — me].

### 1.4 The second idea: `UNRESOLVED` is a bug, not an answer

You pointed out [MSG 3 — you]:

> "if there is something which is not hardcoded like that, for example the
> process recieves data from an event listener/comes from main as user input and
> that becomes the value of target parameter, then it will say UNRESOLVED ... we
> can leave it to the last parameter that affects the parameter of parent, right?
> we can use that as answer, from reader's perspective he can atleast knows that
> this comes from externally, doesnt exists inside a hardcoded value"

So when the chain does not end in a constant, we do **not** print `UNRESOLVED`.
We print the last program point that still affects the value — the variable name,
its file and line, and which parameter it was.

### 1.5 The third idea: deduplicate by *source*, not by *value*

Also yours [MSG 3 — you]:

> "the value itself might be same/repeated, but still the source of those values
> would be unique right?"

Today the CSV has the same value repeated thousands of times because the same
value is re-derived once per route. The new output has **one row per (source,
target invocation)**. Two rows may both say `100`, but only if that `100` really
came from two different places — and then they are two genuine facts, not
duplicates.

---

## 2. Ground truth — what I verified by reading the code

Everything in this section I confirmed by reading the files. Line numbers are
from the current `main` branch.

### 2.1 The path explosion is where I said it is

- `build_call_trees._build_recursive` uses `visited.copy()` per branch
  (`call_graph/call_graph.py:517-589`). Shared subtrees are materialised once per
  route, not shared.
- `dfs_for_finding_path` (`call_graph/call_graph.py:596-627`) appends a full
  label list per occurrence.
- `orchestrate` only ever starts from `main_key = f"[{main_file_name}]main"`
  (`call_graph/call_graph.py:711-713`).

### 2.2 The dedup information already exists and is thrown away

`project_aware.py:837-885` already builds `unique_paths` and `invocation_paths`
(grouped by `(function, target_src_path, target_src_line)`) and writes them to an
Excel report — then the LLM loop at `project_aware.py:1198+` iterates over the
original per-path contexts anyway.

### 2.3 `parseFiles` works on a 2-element chain — the key reuse hook

`parse_for_path` (`parser/parser_files.py:195-315`) loops over the path. For each
node that has both a `[file:line]` first block and a `[start:end]` second block,
it reads that function from `start_line` up to `path[index+1]`'s line, appends
`/*CONSIDER THIS CALL*/` and a closing brace. The **last** node in the path
contributes no code — it is only used to supply the call line number.

**Therefore `parseFiles` accepts `[caller_label, callee_label]` and produces
exactly the one-hop context we need.** No change to `parseFiles` at all. This was
verified, not assumed [MSG 6 — me].

### 2.4 How `dependent_functions` (the fcb link) actually works today

You asked me to read this and include it [MSG 9 — you]:

> "there are functions which dont have a target parameter, they have a list of
> dependant functions ... they dont take input file number, they take input a
> fcb, i think its something like a context, so for those functions, you have to
> correctly link it with the open function which makes the context for it"

What the code does:

1. `project_aware.py:691-714` — if `mpf_mfs_getrec` lists `mpf_mfs_open` in
   `dependent_functions`, and `mpf_mfs_open` is also present in the project,
   `check_other_functions` becomes true.
2. That makes `orchestrate` return `return_whole_tree=True`, so real
   `CallTreeNode` objects come back, not just labels
   (`call_graph/call_graph.py:733-741`).
3. `make_tree` (`project_aware.py:233-260`) then does something subtle: for each
   node on the `main→getrec` route it grafts in **that node's entire subtree** via
   `make_tree_custom`, chains them, and runs `dfs_on_path_trees` to find
   `mpf_mfs_open` **anywhere inside that combined tree**.
4. `dfs_on_path_trees` (`project_aware.py:198-221`) clears and rewrites
   `str_path` every time it finds a match and keeps searching, so you get the
   **last** `open` in DFS order.

**So the current rule is: "find an `mpf_mfs_open` somewhere near this route and
use its file number."** It is a tree-proximity guess, not dataflow on the fcb.
You called it *"v fragile"* [MSG 11 — you] and asked for variable tracing
instead. Section 4.6 does that.

### 2.5 How READF/WRITEF is decided today

- When a function's config `type` is `"WRITEF/READF"` (`project_aware.py:1020-1023`),
  its config `get_upper` is `false`, which selects `messages_with_path_with_return`
  (`project_aware.py:502-558`) and `outputModelForReturn`.
- `outputModelForReturn.output` is `Literal["READF", "WRITEF", "UNRESOLVED"]`
  (`models.py:18-27`).
- That prompt traces **forward**: the target returns a pointer, and the classifier
  decides whether the caller reads through it or writes through it.

So such a path costs **two** LLM calls: one forward (classify) and one backward
(get the file number from the linked `open`).

### 2.6 `call_number` is path-scoped in the documented ground truth

`test_scada/CONTRACT.md` item 7:

> "**call_number**: if you place a `scf_evt_post(EVT_xxx, ...)` or
> `scf_var_evt(EVT_xxx, ...)` **on a path**, its 1st argument (an `EVT_*` macro)
> is reported as **the path's** call_number."

This matters and is handled in Section 4.7. It is also one of my corrected
mistakes — see Section 3.2.

### 2.7 Callbacks are NOT ordinary graph edges

- `_process_function_body` stores callbacks on `call_site.callbacks`
  (`call_graph/call_graph.py:412-452`). They are **metadata on the registrar's
  call-site**, not edges in `self.graph`.
- They only become tree edges later, in `build_call_trees`
  (`call_graph/call_graph.py:559-581`).
- `orchestrate` detects a callback node by its label shape
  (`len(re.findall(BLOCK_REGEX, node)) != 2`) and from it sets `launch_via` and
  `call_function` (`call_graph/call_graph.py:760-794`).

So if we build a reverse index over `self.graph` alone, **callbacks disappear**.
They must be synthesised explicitly. This was the reviewer's correction in
[MSG 3 — you], and I had it wrong — see Section 3.1.

`CONTRACT.md` also documents the exact argument forms:
`(Cast)Handler` and `(Handler)` are followed; **bare `Handler` is followed but
appended twice, producing a duplicate**; `&Handler` is **not followed at all**.

### 2.8 Two real defects found while reading (NEW — not discussed before)

These are mine, found while preparing this plan. They change the plan, so they
are here rather than hidden.

**(a) The visualizer reads the legacy CSV. Option (b) breaks it.**

`VisualizerCollector.rehydrate_interactions` (`visualizer_export.py:440-500`)
opens `results_root()/f"{PROJECT_NAME}.csv"` and reads these exact columns:

```
process_name, function_name, target_number->ans, call_number,
target_number->path_str, launch_via, call_function, type,
function_name_src->path, function_name_src->line_number,
target_name_src->path, target_name_src->line_number
```

You chose option (b) — replace the CSV [MSG 11 — you]. If we simply replace it,
`rehydrate_interactions` silently returns 0 and **the visualizer loses all
resource interactions**. Section 4.8 handles this: the legacy CSV is still
emitted, derived from the facts at zero LLM cost, purely as a machine-readable
feed for the visualizer. The two new CSVs are the human deliverable.

**(b) A pre-existing bug in multi-index values.**

`save_dict_csv` joins `target_number->ans` with `"_"`
(`helpers/dict_to_csv.py:56-59`), but `rehydrate_interactions` splits it on
`", "` (`visualizer_export.py:468-471`). For any function with two or more traced
indices (e.g. `scf_tag_write` has `indices: [2, 3]`), rehydration recovers one
merged string instead of two values.

This is **not caused by this change** and I am **not fixing it as part of this
work** — it deserves its own commit and its own verification. Recorded here so it
is not mistaken for a regression later.

**(c) Two smaller portability/performance notes.**

- `save_dict_csv` hardcodes `/home/seigyo/c_repo/c_repo/results/csv_results`
  (`helpers/dict_to_csv.py:24`) while `trace_variable` reads via `results_root()`
  (`project_aware.py:1553`). These coincide on the original machine only.
- `save_dict_csv` re-reads and rewrites the **entire** CSV on every single row
  (`helpers/dict_to_csv.py:69-84`). That is O(n²). With 100k rows it is brutal.
  The new design must write the legacy CSV in **one batch at the end**, never
  row-by-row.

### 2.9 The test fixture does not cover the risky parts

`test_scada/json_data/mpf_data.json`: every entry has `"dependent_functions": []`
and **no** entry has `"type": "WRITEF/READF"`. It does exercise `get_upper: false`
(via `scf_hist_load`).

**So the fcb-linking path and the READF/WRITEF path have no local test.** Those
are exactly the two parts you flagged as important [MSG 9 — you] and fragile
[MSG 11 — you]. Section 5, Phase 5 extends the fixture. This is not optional.

---

## 3. Mistakes I made, and the corrections

You asked for these explicitly [MSG 11 — you]:

> "dont hesistate to add negatives, the things i told you are wrong and corrected
> me so you dont do the opposite of right"

### 3.1 I said callbacks come along "for free" as reverse edges — WRONG

I wrote that "callbacks already in the graph, reverse index picks them up."
Corrected in [MSG 3 — you] (reviewer point 5) and confirmed by reading
`call_graph.py:412-452` and `:559-581`.

**Do the opposite of what I first said:** synthesise callback edges explicitly.
See Section 4.4.

### 3.2 I said `call_number` can be memoised once per enclosing function — WRONG

Corrected in [MSG 3 — you] (reviewer point 6) and independently confirmed by
`CONTRACT.md` item 7, which says it is scoped to *the path*.

**Do not** cache one `call_number` per function and call it done. See Section 4.7
for the actual rule and its honest limitation.

### 3.3 I said `(function, param index)` is a sufficient cache key — WRONG

Corrected in [MSG 3 — you] (reviewer point 3). `A(100)` at one call-site and
`A(200)` at another must not be merged into a value set that both callers
inherit. Every cached value carries its origin, and rows are filtered by origin.
See Section 4.3.

### 3.4 I said "local variable assigned a literal → done" — WRONG

Corrected in [MSG 3 — you] (reviewer point 4):

```c
if (cond) x = 100;
else      x = 200;
target(x);
```

Two reaching definitions, not one. Never take "the last textual assignment".
Either collect all reaching definitions or hand the case to the LLM. Section 4.2
uses a conservative guard.

### 3.5 I claimed "100k paths share about 60 suffixes" and "tens to low hundreds of queries" — OVERREACH

Corrected in [MSG 3 — you] (reviewer point 2). Sixty target locations are sixty
**starting points**, not sixty problems. Do not build a budget or a success
criterion on a predicted number. Measure it.

### 3.6 I led with caching as the main win — WRONG EMPHASIS

Self-corrected in [MSG 8 — me]. The main win is that backward walking is additive
where path enumeration is multiplicative. Caching is a bonus on top. If someone
implements only the cache and keeps enumerating paths, they get almost nothing.

### 3.7 Your seed-ordering idea — we are NOT doing it, and here is why

You proposed [MSG 5 — you]:

> "order your seeds in such way which are most commonly called endpoints, and
> longest paths first, this way we will have most chance of caching"

Good instinct, but with a correct memo table **order does not change the total
number of questions at all**. The set of questions reachable from the seeds is
fixed by the code; a memo answers each once; order only permutes which seed
triggers which answer. Also "longest path first" has no meaning once we stop
building paths — there is no length to sort by [MSG 8 — me].

**What actually matters instead:** running in parallel can defeat the cache. With
`asyncio.Semaphore(20)`, if two concurrent workers ask the same question, both
miss, because the answer is only written after both have started. The fix is an
**in-flight map** (`dict[QueryKey, Future]`), not ordering. See Section 4.3.

We use **one shared worklist across all seeds and all target functions**, which
makes ordering moot. A deterministic sort is kept only for reproducible resume.

### 3.8 You rejected my CSV recommendation — follow yours, not mine

I recommended keeping the old CSV shape (option a). You chose option (b) with a
second path CSV [MSG 11 — you]. **The plan follows (b).** My preference is not
the design.

### 3.9 You rejected LLM-based fcb linking — follow yours, not mine

I proposed an LLM fallback as a main route for handle linking. You said use
variable tracing because the LLM route is fragile [MSG 11 — you]. **Variable
tracing is primary; the LLM is only a fallback.** See Section 4.6.

### 3.10 You rejected "provenance chain string" as the reader-facing output

I proposed showing the origin as a chain like
`target←A.param1←B.param2←handler`. You said [MSG 11 — you]:

> "its v difficult for a reader to trace, rather than that, give user a path"

**So the reader gets real paths in a second CSV, not a compressed chain
notation.** See Section 4.8, CSV B.

---

## 4. The design

### 4.1 Vocabulary

- **Seed** — one call-site of one configured target function. Example: the
  `mpf_mfs_open(...)` on line 214 of `dio110d.c`. Sixty seeds, not sixty
  functions.
- **Query** — one question with a stable key. Four kinds:
  - `ArgQuery(call_site_id, arg_index)` — what value sits at this argument?
  - `ParamQuery(function_id, param_index)` — what values arrive at this parameter?
  - `HandleQuery(call_site_id, arg_index)` — which `open` bound this fcb?
  - `ReturnUseQuery(call_site_id)` — is the return value read or written through?
- **Fact** — a resolved answer: a value, its kind, and its origin.
- **Provenance DAG** — the graph of "this query got its answer from that query via
  this call-site". Small, because it only holds value-carrying edges and is pruned
  at every constant.

**Call-site IDs must be stable and unique.** The current identity is
`(function, source file, source line)` (`project_aware.py:851-859`), and the
reviewer correctly noted two calls on one line collapse [MSG 3 — you]. Use the
tree-sitter node **byte offset**, which is free and exact:
`f"{file_name}:{start_byte}"`.

### 4.2 Resolution rules — syntax first, LLM only when stuck

Most work needs no LLM at all. Given an argument expression at a call-site:

| What we see | What we do | LLM? |
|---|---|---|
| `open(..., 100, ...)` — number/string/enum literal | answer is `100`, kind `CONST` | no |
| `open(..., FNO_HEALTH, ...)` — identifier present in `builder.macros`, expanding (recursively) to a literal | answer is the literal, kind `MACRO` | no |
| `open(..., fno, ...)` where `fno` is a parameter of the enclosing function **and the guard below passes** | emit `ParamQuery(enclosing, k)` | no |
| anything else — local variable, `a+b`, result of a call, global, pointer write, macro that does not bottom out | emit an LLM query | yes |

**The guard (this is Section 3.4 made concrete).** Row 3 is only safe if the
parameter is not modified before the call. Reject the fast path — and fall through
to the LLM — if, anywhere between the function's opening brace and the call-site,
tree-sitter finds any of:

- an `assignment_expression` whose left side is that identifier;
- `++` / `--` on that identifier;
- `&identifier` (address taken, so anything could write to it);
- the identifier passed to another call in a position we cannot prove is by-value.

When in doubt, fall through to the LLM. **Never guess.**

Expected effect, stated as an expectation and not a promise (Section 3.5): you
said *"i can promise you, most of this shit is hardcoded, either directily in the
code itself at a level, or in a macro which can be resolved"* [MSG 3 — you].
Those are exactly rows 1 and 2, which cost nothing.

### 4.3 The cache, and the parallelism trap

Two structures:

```python
results:   dict[QueryKey, list[Fact]]     # answered
in_flight: dict[QueryKey, asyncio.Future] # being answered right now
```

Rules:

1. Before starting a query, check `results`; then check `in_flight` and **await
   the existing future** instead of launching a duplicate. Without this, the
   existing `Semaphore(20)` concurrency destroys the hit rate (Section 3.7).
2. Every `Fact` carries its origin (Section 3.3). Cached answers are never merged
   blindly across callers; rows are filtered by origin at output time.
3. The whole `results` table is persisted to JSON per process. **This replaces the
   old `PATH_TO_START_WITH` resume logic** (`project_aware.py:756-763`) with
   something strictly better: on restart, every previously answered query is free.

Where caching genuinely pays (verified reasoning, [MSG 8 — me]):

- **Sibling targets in one function.** `open`, `getrec`, `close` on the same `fno`
  all resolve to the same `ParamQuery`. One answer, three targets. Common idiom.
- **High fan-in wrappers.** `DioGetPtr(filenum, sbnum)` called from 40 places →
  one `ParamQuery(DioGetPtr, 1)` serves all 40.
- **Diamonds.** Two callers reconverging on a shared ancestor query.
- **Macros.** A dictionary lookup, free forever.

**The cache must be global across all target functions in a process, not per
function.** Today `make_llm_calls_for_function` runs a completely independent job
per target function, so `mpf_mfs_open` / `mpf_mfs_getrec` / `mpf_mfs_close`
re-derive the same `fno` three separate times.

### 4.4 Callback edges must be built by hand

Per Section 2.7 and Section 3.1. Build a reverse index that includes synthetic
edges:

```
enclosing_function --[via registrar R, launch=config[R].launch]--> callback
```

The edge carries the metadata needed to reproduce today's `launch_via` and
`call_function` columns exactly (`call_graph.py:760-794`).

**Deduplicate callbacks per call-site.** `CONTRACT.md` documents that a bare
`Handler` identifier is appended twice (caused by `call_graph.py:426-452`, where
the `identifier` branch appends and then `_extract_arg_function_name` appends the
same name again). Deduplicating is a correctness improvement and directly reduces
duplicate rows — the whole point of this work.

**Flag this as an intentional behaviour change**, because output will differ from
today for any project using bare-identifier callbacks. It must be called out in
the Phase 1 diff review, not discovered later.

`&Handler` remains unfollowed. That is an existing documented limitation and this
change does not address it.

### 4.5 Only follow what this process can actually reach

Today every route starts at `main_key` (`call_graph.py:711-713`), and there is an
extra filter, `starts_in_target_process` (`project_aware.py:787-813`), that drops
library-rooted paths.

Since paths always start at `main`, that filter looks defensive or vestigial. I
am **not** claiming to fully understand its original intent, so we preserve its
effect rather than delete it:

1. Compute forward reachability from `[main_file]main` once, by BFS over the graph
   **plus the synthetic callback edges**. Cheap.
2. Emit a seed only if its enclosing function is in that reachable set.
3. During the backward walk, **only follow a caller edge if the caller is also in
   that reachable set.** A caller unreachable from `main` cannot supply a value at
   runtime for this process.

This preserves "every value flows on some route from this process's `main`",
which is exactly what the old filter enforced.

### 4.6 The fcb / handle link — variable tracing, not the LLM

This replaces the tree-proximity guess described in Section 2.4, per your
instruction [MSG 11 — you]. The good news: it is the **same worklist, same cache,
same shape** as parameter tracing — a variation, exactly as you suspected.

Given a seed like `mpf_mfs_getrec(&fcb, rec, ...)`:

**Step 1 — find which argument is the handle.**
Prefer an explicit `handle_index` in the function's config entry if present
(a small additive config field, defaults absent). Otherwise infer: the argument
whose root object also appears as an argument to an open-family call in the same
function. If inference is ambiguous (zero or more than one candidate), do not
guess — record `HANDLE_AMBIGUOUS` and fall back (Section 6).

The open-family is exactly what `dependent_functions` already names. **Keep using
that config field** — it is the lookup key for "what counts as an open here".

**Step 2 — normalise the handle to a root object.**

```
&fcb      -> fcb
fcb       -> fcb
p->fcb    -> p->fcb          (kept whole)
fcbs[i]   -> fcbs            (array base; note that the index is unresolved)
```

**Step 3 — find the binding open(s) in the same function.**
Collect **every** open-family call in the enclosing function whose handle
argument normalises to the same root object **and appears before the target
call**.

Note this is Section 3.4 again in a new costume. Do **not** take only the last
one:

```c
if (mode) mpf_mfs_open(&fcb, NULL, FNO_A, ...);
else      mpf_mfs_open(&fcb, NULL, FNO_B, ...);
mpf_mfs_getrec(&fcb, ...);          /* both A and B are possible */
```

Two reaching opens means **two facts**, which is correct and is what you asked
for: *"each unique invocation of target function can still have multiple possible
values"* [MSG 3 — you].

The reopen pattern works correctly with textual ordering:

```c
open(&fcb, A); read(&fcb);   /* links to A */
close(&fcb);
open(&fcb, B); read(&fcb);   /* links to B */
```

`close` does not rebind, so only `open`-family calls are considered bindings.

**Step 4 — once linked, hand off to the ordinary resolver.**
The link gives us an `open` call-site. The file number is just
`ArgQuery(open_call_site, file_number_index)` where the index comes from the open
function's config `indices`. **Full reuse of Sections 4.2 and 4.3.** No new
resolution machinery.

**Step 5 — handle is a parameter of the enclosing function.**

```c
void A(MPF_FCB *fcb) { mpf_mfs_getrec(fcb, ...); }
```

Emit `HandleQuery(A, param_index)`, walk to callers via the reverse index, and at
each caller call-site restart from Step 2 with the actual argument. **Identical
shape to `ParamQuery`, identical cache, identical in-flight dedup.**

**Step 6 — handle is a global or a struct field.**
Search all functions reachable from `main` for open-family calls binding that same
global. Multiple candidates produce multiple facts. Do not pick one.

**Step 7 — fallbacks, in order.**
If Steps 1–6 cannot resolve it: (a) LLM, using the existing prompt; then (b) the
legacy tree-proximity heuristic, unchanged. Record which route produced the answer
in a `link_method` column so fragile results are visible in the output rather than
indistinguishable from solid ones.

### 4.7 READF/WRITEF, and the `call_number` honesty note

**READF/WRITEF** is straightforward and a big win. Per Section 2.5, the
classification depends only on the enclosing function body plus tool lookups into
consumer functions — the existing prompt already uses `find_definition` for that.
It does **not** depend on how control reached the function from `main`.

So: `ReturnUseQuery(call_site_id)`, cached per call-site. Sixty invocations means
at most sixty of these instead of one per route. Keep
`messages_with_path_with_return` and `outputModelForReturn` **exactly as they
are**; only the context changes, from a whole-path context to the enclosing
function's context.

**`call_number` needs an explicit warning.** Per Section 2.6 and Section 3.2, the
documented ground truth scopes it to *a path*. Our new paths start at the value's
source, not at `main`, so an event post sitting on the `main → source` prefix
would be missed.

Rule we will implement:

1. Look for `scf_evt_post` / `scf_var_evt` (configurable names; `pmf_addevent` /
   `pmf_addvarevt` in the company config) in the target's enclosing function.
2. If absent, walk up the provenance chain's functions.
3. If still absent, walk up call-graph ancestors toward `main` (BFS, first hit).
4. Cache per function.

**Known divergence, stated plainly:** if two different `main → target` prefixes
contain two *different* event posts, today's code reports different
`call_number`s per route, and we would report one. I judge this rare, but it is a
real semantic difference and must be checked during Phase 1 diffing. If the diff
shows it happening in the company code, we add an opt-in mode that resolves
`call_number` per enumerated path (which is cheap, since the enumeration happens
over the small provenance DAG, not over the call graph).

### 4.8 Outputs — three files

You chose option (b) with a second CSV [MSG 11 — you]:

> "make another csv, not just the minimal one where each row points to a unique
> source to a uniquee invokation of target function, instead it gives all possible
> paths from that source to the target, this is different from current, current
> one starts from main always always, this one will start from uniquee source and
> mark all possible paths. So we have two now."

**CSV A — the fact table (one row per unique source → unique target invocation).**

| column | meaning |
|---|---|
| `fact_id` | stable key, used to join to CSV B |
| `process_name` | as today |
| `function_name` | the target function |
| `target_site_file`, `target_site_line`, `target_site_id` | the exact invocation |
| `arg_index` | which argument this fact is about |
| `value` | the literal, or the external variable expression |
| `origin_kind` | `CONST` / `MACRO` / `EXTERNAL_ENTRY` / `EXTERNAL_DATA` / `UNKNOWN_INDIRECT` / `RECURSIVE` / `UNRESOLVED` |
| `source_file`, `source_line`, `source_expr` | where the value is decided |
| `type` | as today (config, or LLM for `WRITEF/READF`) |
| `launch_via`, `call_function` | as today, from the callback edge metadata |
| `call_number` | per Section 4.7 |
| `link_method` | for fcb-linked rows: `VARTRACE` / `LLM` / `LEGACY_PROXIMITY` |
| `path_count` | how many source→target paths carry this fact |
| `resolved_by` | `SYNTAX` / `LLM` — so you can see what cost money |

The `origin_kind` values implement your "not just UNRESOLVED" idea [MSG 3 — you],
split into distinct cases so the reader learns *which* kind of external:

- `EXTERNAL_ENTRY` — the function has no callers; it is an entry point or a
  registered callback. Value arrives from outside at that parameter.
- `EXTERNAL_DATA` — a caller passes something irreducible: `msg->file_no`,
  `argv[1]`, the result of `recv()`. The expression and location are recorded.
- `UNKNOWN_INDIRECT` — an indirect call we cannot follow (a documented limitation,
  `CONTRACT.md`).
- `RECURSIVE` — a cycle.
- `UNRESOLVED` — genuine analysis failure only. Should become rare.

**CSV B — the path table (all paths from source to target).**

One row per (fact, path). Columns: `fact_id`, `path_index`, `path`, `path_length`.

The path starts at the **source**, not at `main` — that is the difference you
asked for. Paths are enumerated over the **provenance DAG**, which is small
because it only contains value-carrying edges and is pruned at every constant.

Multiplicity is real, so "all possible paths" is not always one. Concrete example:

```c
void B(int x) {
    A(x);      /* site 1 */
    A(x);      /* site 2 */
}
```

Both call-sites carry the same value to the same target, so that (source, target)
pair has two paths.

**Safety valve:** cap enumeration per fact (default 100) and, when the cap bites,
**write the true count in `path_count` and log the truncation**. A silent cap
would read as "we covered everything" when we did not. Never do that.

**CSV C — the legacy CSV, machine-only.**

Per Section 2.8(a), the visualizer needs the old column layout or it silently
loses all interactions. So we still emit it — derived from CSV A at **zero LLM
cost** — purely as a feed for `rehydrate_interactions`.

This does not walk back your option (b) decision. CSV A and CSV B are the
deliverable; CSV C exists so the visualizer keeps working, and it can be deleted
the day the visualizer is migrated. It must be written **once, in one batch**, not
row-by-row (Section 2.8(c)).

---

## 5. Implementation phases

Each phase ends in a state where the tool still runs. The resolver is selected by
a flag, default `legacy`, until Phase 5 passes.

```
--resolver legacy      (default, current behaviour, untouched)
--resolver valueflow   (new)
```

### Phase 0 — scaffolding, no behaviour change

- New package `value_flow/` (`queries.py`, `resolver.py`, `handles.py`,
  `outputs.py`).
- Reverse-caller index over `CallGraphBuilder.graph`, **plus synthetic callback
  edges** (Section 4.4).
- Forward reachability set from `main` (Section 4.5).
- Seed enumeration from `graph` call-sites, with stable byte-offset IDs
  (Section 4.1).
- Add the `--resolver` flag. Default `legacy`.

**Gate:** with `--resolver legacy`, output is byte-identical to before.
**Gate:** seed count matches the `unique_target_invocations` sheet already
produced at `project_aware.py:860-885`. This is a free, precise cross-check —
use it.

### Phase 1 — syntactic resolver only, no LLM

- Implement Section 4.2 rows 1–3 and the guard.
- Implement the memo + in-flight map (Section 4.3).
- Build the provenance DAG.
- Anything hitting row 4 is marked `NEEDS_LLM` and **not** resolved yet.
- Emit CSV C (legacy shape) by expanding facts, so it can be **diffed against a
  legacy run**.

**Gate — this is the most important gate in the plan.** Run both resolvers on the
same project. Every row the syntactic resolver produces must match legacy. Expect
and individually justify exactly two classes of difference:

1. Fewer duplicate rows from bare-identifier callbacks (Section 4.4) — an
   intended fix.
2. `NEEDS_LLM` rows, still unresolved at this phase.

**Any other difference is a bug and blocks Phase 2.** Do not proceed on "looks
close".

### Phase 2 — LLM fallback for the ambiguous cases

- One-hop LLM query for `NEEDS_LLM`, reusing `parseFiles` with a 2-element chain
  (Section 2.3), `llm_calls`, `run_with_retry`, `OllamaClient`, and the existing
  tools.
- Add `outputModelOneHop` with `kind` / `value` / `param_index`, so the model can
  say "this comes from parameter k" — which the current `outputModel` cannot
  express.
- **If the one-hop call fails or returns something unparseable, fall back to the
  existing full-path LLM call for that sub-problem.** You explicitly allowed
  this: *"we can fallback to original way anypoint"* [MSG 11 — you].
- Keep the existing token accounting and stats JSON.

**Gate:** on the fixture, resolved values match legacy for every path legacy also
resolved. Token count per project drops sharply. Record the actual number —
do not repeat my earlier guess (Section 3.5).

### Phase 3 — handle linking and READF/WRITEF

- Implement Section 4.6 Steps 1–7 (variable tracing primary, LLM then legacy
  proximity as fallbacks, `link_method` recorded).
- Implement `ReturnUseQuery` cached per call-site (Section 4.7).
- Implement `call_number` per Section 4.7, and **actively look for the divergence
  described there** in the diff.

**Gate:** on the extended fixture (Phase 5), fcb links match ground truth,
including the two-branch-open case and the reopen case.

### Phase 4 — the new outputs

- CSV A, CSV B (Section 4.8), with the truncation log.
- CSV C written once in a batch, not row-by-row.

**Gate:** `rehydrate_interactions` recovers the same interaction count from CSV C
as from a legacy run.

### Phase 5 — fixture extension and validation

Required, per Section 2.9. Add to `test_scada`:

- an open/read/write/close trio sharing one fcb, with `dependent_functions` wired
  in `mpf_data.json`;
- a `WRITEF/READF` ambiguous-pointer function;
- a two-branch open (`if/else` with different file numbers) — the Section 3.4 trap;
- a reopen sequence;
- a handle passed as a parameter (Section 4.6 Step 5);
- an external-input path that should land as `EXTERNAL_ENTRY`, so the
  no-more-`UNRESOLVED` behaviour is actually tested.

**Gate:** full run on the fixture with `--resolver valueflow`, all ground truth
matched. Only then flip the default.

---

## 6. Risk and fallback

You accepted the risk knowingly [MSG 11 — you]:

> "we can fallback to original way anypoint, so lets take a risk, be v carefully
> when implementing this, because its crucial productio grade code."

Fallbacks, from cheapest to heaviest:

1. **Per-query:** one-hop LLM fails → full-path LLM call for that sub-problem.
2. **Per-link:** handle variable tracing fails → LLM → legacy tree-proximity.
   `link_method` records which fired.
3. **Per-run:** `--resolver legacy` restores today's behaviour exactly. The legacy
   code paths are **not deleted** by this work.

Highest risks, ranked:

| Risk | Why it hurts | Mitigation |
|---|---|---|
| Silently breaking the visualizer via option (b) | `rehydrate_interactions` returns 0 with no error | CSV C (Section 4.8) + a Phase 4 gate on interaction count |
| fcb linking regresses on real code | It is the fragile part and has **no local test** | Phase 5 fixture; `link_method` column; legacy fallback retained |
| `call_number` divergence | Path-scoped in the ground truth; our paths are shorter | Documented in Section 4.7; hunted for in the Phase 1 diff; opt-in per-path mode if it appears |
| Fast-path guard too loose | Wrong values, reported confidently | Guard defaults to rejecting; when in doubt use the LLM |
| Parallelism defeats the cache | Silently no speedup | In-flight map (Section 4.3), not seed ordering |
| Callback dedup changes output | Looks like a regression during diffing | Called out **before** Phase 1 diff review, not after |

**One thing I will not do without asking:** delete or rewrite the legacy path
enumeration. `orchestrate`, `build_call_trees` and `dfs_for_finding_path` stay as
they are. They are still used by `make_graph` and the visualizer's
`capture_call_graph(trace_paths=...)`, and they are the run-level fallback.

---

## 7. Provenance index — where each decision came from

| # | Message | What it established |
|---|---|---|
| 1 | you | Problem statement; 60 invocations → 100,000 paths; multi-day runtime unacceptable. The two-case backward algorithm (constant/macro, or trace the caller's argument). |
| 2 | me | Read the code; described the four current phases; named the algorithm family. |
| 3 | you | `UNRESOLVED` should become an external-origin answer. Deduplicate by source, not value. Plus a 9-point critique that corrected me on callbacks, `call_number`, cache-key granularity, reaching definitions, forward tracing, cycles, and my "60 suffixes" overreach. |
| 4 | me | Accepted the critique point by point. |
| 5 | you | Implement it; reuse as much existing code as possible; keep the diff minimal. Asked whether caching is real, and proposed seed ordering. |
| 6 | me | Verified `parseFiles` accepts 2-element chains — the key reuse hook. |
| 7 | you | Asked me to re-think properly and explain simply. |
| 8 | me | Corrected my own emphasis: additive vs multiplicative is the real win, not caching. Listed the genuine cache cases. Showed seed ordering does not reduce total work; the in-flight map does. Identified the syntax-first free win. |
| 9 | you | Asked me to restate the CSV question; confirmed the external-variable answer; required `dependent_functions` / fcb linking and READF/WRITEF to be read and included. |
| 10 | me | Restated the CSV choice; split external into four kinds; traced the fcb-linking and READF/WRITEF code and reported how they actually work. |
| 11 | you | **Chose option (b)** plus a second CSV of paths from source (not from `main`). **Rejected LLM-based fcb linking**, asked for variable tracing. Accepted the risk with a fallback. Asked for this plan.md with provenance and with my mistakes recorded. |

Findings marked **NEW** in Section 2.8 were discovered while writing this plan,
not during the conversation: the visualizer's dependence on the legacy CSV, the
`"_"` vs `", "` mismatch, the hardcoded results path, and the O(n²) CSV write.
