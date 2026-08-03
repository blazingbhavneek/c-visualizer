# Backward walker — plan (not implemented)

This is the harder variant: instead of caching *whole answers* for library
suffixes, walk backwards from the target call and record, for each function you
pass through, **what it does to the value**. Those per-function records are then
reusable by anything that calls that function, anywhere.

The library cache that is now implemented (`library_facts.py`) is the special
case of this where the record happens to be "the value is a constant". The
walker generalises it to "the value is my parameter 2", "the value is one of
{A, B, C} depending on my parameter 1", and so on.

Read this alongside `change.md`, which describes what exists today.

---

## 1. Why the current design costs what it costs

Today: expand the call tree from `main`, list **every** route to the target, and
send one LLM call per route.

```
main → a → b → util → lib_open(FILE_X, 0)
```

If `FILE_X` is a constant at the call site, all 500 routes have the same answer
and 499 of the calls were wasted. The routes multiply in the **prefix**; the
answer lives in the **suffix**. Cost is O(routes) when it should be O(call
sites + a little).

The library pre-pass removes the biggest single chunk of that (everything
funnelling through `libdio`, `libapl`, …). The walker removes the rest, and
removes it for process-local code too.

## 2. What the walker stores

One record per **(function, target API, argument index)**, describing how the
value reaches the target when control passes through that function. Four kinds:

| kind | meaning | example |
|---|---|---|
| `constant` | fixed, whoever calls me | `lib_open(FNO_HEALTH, 0)` |
| `parameter` | it is my own parameter N, untouched | `void util(int fno) { lib_open(fno, 0); }` |
| `branches` | a small set, chosen by my parameter N | `if (mode) lib_open(A,0); else lib_open(B,0);` |
| `opaque` | I cannot describe it in these terms | value from a struct field, a global mutated elsewhere, a computed expression |

A record also carries: the call site it describes (file, line), the definition
range of the function, a source hash for invalidation, and the evidence the
model used.

The point: a record is **caller-independent**. It says what this function does
with a value, not what the value is. That is what makes it reusable across
100,000 routes and across processes.

## 3. How resolving works with records

To resolve argument `i` of a target call:

1. Look at the enclosing function. Get (or compute) its record.
2. `constant` → done. Every route through here has this answer.
3. `parameter N` → the question becomes "what is argument N at the call sites of
   *this* function". Recurse to its direct callers — **not** to every route from
   `main`, just one hop.
4. `branches` → the answer is the small set. If a caller pins the deciding
   parameter, the set collapses to one value; if not, record the whole set with
   its conditions.
5. `opaque` → fall back to today's behaviour for that one chain: build the full
   path context and ask the model.

Each hop is memoised on `(function, argument index)`. A function called from 40
places is resolved **once**, not 40 times, and never once per route.

Termination: a `visited` set of `(function, argument index)`. On a cycle, mark
`opaque` and stop.

## 4. Cost

Let *F* = functions that appear on some route to a target, *A* = tracked
argument indices, *C* = target call sites.

- Today: **O(routes)** LLM calls — the number that reaches 100,000s.
- With the walker: **O(C + F×A)** LLM calls, and in practice far less, because
  most call sites terminate at `constant` on the first step and never expand.

The context per call also shrinks from "every function body on a 6-hop chain" to
"one function body". Cheaper *and* more accurate — the model stops having to
pick the right call site out of five candidate bodies, which is where the
`/*CONSIDER THIS CALL*/` rules in the prompt are currently doing heavy lifting.

## 5. What has to change in the code

This is the part that makes it a real refactor rather than an add-on.

### 5.1 A record extraction prompt + schema (new)

`models.py` gains something like:

```python
class ArgumentRecord(BaseModel):
    kind: Literal["constant", "parameter", "branches", "opaque"]
    value: str | None            # kind == constant
    parameter_index: int | None  # kind == parameter
    branches: list[Branch]       # kind == branches: {condition, value, parameter_index}
    evidence: str                # the line(s) the model based this on
```

The prompt is much smaller than today's: one function body, one call site, one
question — *"where does argument N of this call come from: a constant, one of
your parameters, or a small set chosen by a condition?"* No call-graph walking
inside the prompt, no `/*CONSIDER THIS CALL*/` disambiguation across five
bodies, no early-termination rule to explain. It is the single most likely
source of an accuracy improvement in this whole plan.

### 5.2 A resolver that walks the graph, not the tree (new module)

`resolve_targets.py`:

- Input: the call graph (`graph`, `registry`) that `CallGraphBuilder` already
  produces, plus the tracked API config.
- Find target call sites directly from graph edges — `who calls lib_open` is one
  lookup, no tree, no path enumeration.
- Run the record/recurse loop from §3 with a memo table.
- Output: one resolved value (or a set) per **call site**, plus the caller chain
  it needed. Routes are never enumerated.

### 5.3 `build_call_trees` stops being on the critical path

`call_graph.py:457` expands a full tree **for every function in the project**,
with `visited.copy()` per branch, so it materialises one node per root→node
*path*. This is the thing that will not survive a million lines, and the walker
does not need it at all. Keep it only for the visualizer's own tree view, built
lazily for one process at a time.

### 5.4 Output shape

Today: one CSV row per route, with `path_str`.
With the walker: one row per **(call site, resolved value)**, plus

- `route_count` — how many routes this stands for,
- `example_path` — one representative route, reconstructed from the graph on
  demand so the CSV and the UI still show something familiar,
- `resolution` — `constant` / `via parameter N of f` / `branch set`, which is
  genuinely new information the current output cannot express.

Touch points: `helpers/dict_to_csv.py` (columns), `visualizer_export.py`
(`record_combined`, `rehydrate_interactions` — note the interaction ID currently
includes `path_str`, so it would key on the call site instead), and the
frontend, which already collapses to `(function, resource)` and therefore comes
out unchanged or better.

### 5.5 Invalidation

Records are keyed by function + a hash of its source (`source_sha256` already
exists in the snapshot). Edit a function → its record dies → its callers'
memoised answers die. A `records.json` next to `library_facts.json`, shared
across processes and across runs.

## 6. Suggested order

1. **Records for library functions only.** Reuses the pre-pass that exists now,
   swaps whole-answer caching for record caching. Immediately handles the
   `parameter` case the current cache has to give up on (it caches nothing when
   the library run says `UNRESOLVED` — which is precisely "it is my parameter").
2. **Resolver from call sites**, with the old path tracer still there as the
   fallback for `opaque`. Both can run and be compared on the same process; the
   CSVs are diffable.
3. **Branch sets.** Needs the widest output changes, because one call site can
   now legitimately produce several values.
4. **Retire path enumeration** for tracing; keep it for display only.

Steps 1 and 2 are where nearly all the saving is. 3 is accuracy. 4 is cleanup.

## 7. Risks

- **A wrong record poisons many answers.** A whole-answer cache is wrong once;
  a record is reused by everything downstream. Mitigation: keep the evidence
  string, and add a verification mode that re-resolves a random sample the old
  way and diffs — cheap, and it is the only honest way to trust the cache.
- **`opaque` may be common in real code** (values through struct fields and
  globals are normal in this codebase). If most call sites land there, the
  saving shrinks toward zero. Measure the mix on one real process *before*
  building steps 3–4: instrument the current run to report, per call site,
  whether the answer came from the last hop or needed the whole chain. That
  number decides whether the rest of this plan is worth building.
- **Loss of per-route rows** changes what the CSV means. Anyone reading it as
  "one row per execution route" needs telling.
