# Changes

## Later addition: library-first indexing (item 8)

**Problem.** The path count explodes in the *prefix*, not in the answer. Every
process multiplies out its own routes into the same shared library
(`libdio`, `libapl`, …) and pays for one LLM call per route, even though the
resolved value at the library call site is identical for all of them.

**Change** — new `library_facts.py`, plus small hooks in
`call_graph/call_graph.py`, `makefile_resolver/makefile_resolver.py` and
`project_aware.py`.

- `discover_libraries(root, prefix="lib")` finds library folders (name starts
  with the prefix, contains C sources, is not itself inside one).
- `orchestrate(..., root_keys=[...])` — a library has no `main`, so it is
  rooted at its own functions. One small addition; without `root_keys` the
  behaviour is exactly as before.
- `library_project_mapping()` builds a structure for a library folder with no
  Makefile of its own (every C source is a seed; discovery supplies headers).
- `LibraryFactStore` harvests the library run's CSV and stores each resolved
  answer under **the path suffix that produced it**. In a later process run,
  `make_llm_calls_for_function` looks up each path's suffixes shortest-first;
  on a hit it writes the row from the cached answer and makes **no LLM call**.
- The cached answer supplies only the resolved value, the call number and the
  operation type. Where the call sits in *this* process — launch, calling
  function, source lines — still comes from that process's own call graph.

**Why a cached answer is safe for any caller.** Only answers the library could
resolve *without a caller* are stored. A value that comes from the library
function's own parameter comes back `UNRESOLVED` in the library run, is not
cached, and the process run traces it in full exactly as before.

**Shortest suffix wins** on lookup: a shorter suffix means the library needed
less context, so it holds for more callers.

**CLI:** `--index-libraries ROOT`, `--library-prefix`, `--library-facts PATH`,
`--no-library-facts`. Libraries are indexed before any process run in the same
command, and the facts file is picked up automatically by later runs sharing an
`--output-root`.

**Also fixed:** `orchestrate` did `console.print(paths)` — rich-printing the
entire path list, which is unusable past a few dozen paths and ruinous at the
scale this runs at. It now prints a count.

**Verified.** New `tests/test_library_facts.py` (6 tests: suffix reuse across
different routes, unresolved answers never cached, shortest-suffix and
right-API matching, labels containing `->` surviving the round trip, save/load,
library discovery). End to end with the LLM mocked: 10 paths where 8 share a
library tail → **2 LLM calls instead of 10**, 8 cache hits, all 10 CSV rows
correct, process-side fields preserved. Library-rooted enumeration checked
against a synthetic graph with no `main`: the old call returns nothing, the
rooted call finds both the short and the long path.

### The same split in the frontend

Libraries are separate code, so the visualizer stops mixing them into the
processes that use them.

- **Snapshots say what they are.** `visualizer_export.py` writes
  `process.kind = "library" | "process"`, and tags every function with the
  `library` it came from (matched against the library roots recorded in
  `library_facts.json`). A process pulls the library's sources into its own
  structure, so without this tag the two are indistinguishable.
- **A process plane stops at the library.** The first library function a
  process calls is drawn as a **boundary node** — its own colour, a ring, a
  permanent `name → libdio` label — and nothing below it is expanded. Library
  functions are also kept off that process's unreached shelf, and counted
  separately in the coverage line.
- **Daemon links survive the cut.** A daemon call made *inside* the library is
  attributed to a library function that is no longer drawn, so
  `attachInteractions` walks back through the library to the boundary the
  process actually calls. The link still lands on the plane: "this process
  touches file 1007, through `DioGetPtr`".
- **The overview gives libraries their own place.** Library nodes sit on an
  outer ring (book-stack icon, angled toward the processes that use them), with
  a quiet `uses` edge from each process built on them. They are **not** in the
  process ring, and their own daemon calls are not drawn there — the processes
  that inherit those calls already draw them. A library nobody has indexed yet
  still appears, dimmed and marked "not indexed".
- **Opening the library reconnects the halves.** Click a library node and its
  plane opens like a process's. With both open, a seam is drawn from each
  boundary node to the same function inside the library plane
  (`PLANE_TO_PLANE`, so the existing edge toggle controls it).

**Verified** on a real snapshot relabelled so one file counts as a library:
process plane 120 → 71 nodes (tree) and 74 → 55 (DAG), 3 boundary nodes, zero
library functions expanded or shelved, **all 105 interactions still attached**,
library plane still showing its full 74-node inside, overview showing a separate
library node with its `uses` edge, and 3/3 boundary nodes finding their
counterpart in the library plane. A separate synthetic check covers the
re-attribution specifically: a daemon call two hops inside the library attaches
to the boundary node in both tree and DAG mode. Two new Python tests cover the
snapshot marking (`library` per function, `kind` per snapshot).

### Bug fix: cross-plane links were wiring processes through shared APIs

**Reported:** with two processes open, the plane-to-plane lines connected them
through library/external functions, reading as "these two reuse this function".
A cross-process source link should mean one process compiles code out of the
other's source tree — not that both call the same API.

Three causes, all fixed in `directPlanePairs` / `SceneManager`:

1. **Unresolved resources were treated as shared objects.** Every process has
   `UNRESOLVED` and `NO TARGET` rows and they all carry the same resource key,
   so every plane paired with every other plane on them. Pairs are now limited
   to resources that actually resolved. On the fixtures that alone is 22 of one
   process's 105 interactions.
2. **Lines were anchored on the shared API node.** The endpoints came from
   `portNodes` — the external API leaf — so a line literally joined
   `mpf_mfs_open` in plane A to `mpf_mfs_open` in plane B. Endpoints are now
   each process's **own** code (`ownCodeNodes`: not external, not library, not a
   boundary); an interaction with no own-code anchor draws no direct line at
   all, since the ground resource node already carries that relationship.
3. **Library boundaries could anchor a line too**, after the re-attribution
   above, joining the same library function across two processes. Same filter
   removes it.

**And the link that was missing:** `sharedSourceNodes` joins the *same source
function* (file + name + definition range) drawn in both planes — the real
"process A is built from process B's source" signal — in its own colour, with a
legend entry.

Measured on the fixtures: **87 pairs before, 9 of them drawn between the same
external function in both planes → 28 pairs after**, every one anchored on own
code, none on an unresolved resource. With three functions borrowed from another
process's tree, the new shared-source link finds exactly those three.

**Known limits (v1).** The library run itself still traces overlapping routes
(root `DioRead → DioGetPtr → target` as well as `DioGetPtr → target`) — the
shortest-first pruning is listed as follow-up work. Branch variations ("this
function passes one of 3 constants depending on its parameter") are **not**
handled: they need a prompt/schema change and are covered in `walk_plan.md`,
which plans the backward walker that generalises this cache.

---

Seven requested items, kept to the smallest diff that actually implements each.
Nothing in `call_graph/`, `parser/`, `client/llm.py`, the tool-chain prompts or
`wiki/` was touched beyond replacing hardcoded output paths.

---

## 1. Header discovery beside and above a process

**Problem.** Headers only came from the `-I` tokens of the process's own
Makefile. A delivered package (`pkg/include`, `pkg/common`, next to
`pkg/g-svm/src`) resolves to nothing, because those folders are either not
mentioned or named through a build-machine variable.

**Change** — `makefile_resolver/makefile_resolver.py`

- New `discover_include_dirs(project_path, levels)`: walks up `levels` folders
  and collects every sibling directory that is either named like a header pool
  (`include`, `inc`, `includes`, `header`, `headers`, `common`, `public`, `api`)
  or holds loose `.h` files **and** has no `Makefile` of its own — the second
  condition is what stops it swallowing a sibling process. `.git`, `build`,
  `node_modules`, `results`, dotfolders and unreadable directories are skipped.
- `return_project_mapping(...)` takes `include_levels` (default 2) and
  `extra_include_dirs`, and passes Makefile dirs first, then discovered ones,
  to `resolve(...)`.

Discovered folders join the **`#include` search path only**, never the file
list, so a header still enters the project exactly when something includes it —
a shared `include/` with 2,000 headers does not become 2,000 parsed files.

**CLI:** `--include-levels N` (0 disables), `--include-dir PATH` (repeatable).

Verified against a synthetic package: from `pkg/g-svm` it finds `include` and
`common`, ignores the sibling processes `g-xyz`/`g-svm`'s own dir and `build`;
from `pkg/g-svm/src` it additionally finds `modern/`.

## 2. Concurrent path tracing

**Problem.** `make_llm_calls_for_function` traced one path at a time, blocking
on a forked subprocess per LLM call.

**Change** — `project_aware.py`, `helpers/dict_to_csv.py`

- `make_llm_calls_for_function` is now `async`. Each of its two path loops
  became a coroutine (`trace_one_path`) with the body unchanged apart from
  `continue` → `return`; the blocking call became
  `await asyncio.to_thread(run_with_retry, ...)`.
- New `gather_paths(runner, contexts, completed_paths)` builds one coroutine
  per outstanding path and runs them under `asyncio.Semaphore(N)`.
- `trace_variable` drives each function with `asyncio.run(...)`. **Functions
  stay sequential**: their call-graph and parsing work is CPU-bound and would
  block the loop; the paths inside a function are where the 100k-scale win is.
- Concurrency from `--trace-concurrency` / `TRACER_CONCURRENCY` (default 4).

**Write safety.** No lock was added, and none is needed: a coroutine only
yields at `await`, the single `await` is the LLM call, and every write that
follows it — stats JSON, CSV row, `answers` list, token counters — runs to
completion before another path can resume. Two projects in parallel no longer
share a CSV either (item 5).

**Resume.** `PATH_TO_START_WITH` (a high-water mark) was replaced by a set of
completed path numbers, because paths now finish out of order. Old stats files,
written in order, resume identically.

**Also:** `save_dict_csv` appends instead of read-concat-rewriting the whole
file when the columns match, which removes a quadratic cost that only got worse
under concurrency (a mismatched older column set still takes the slow path).

**Fixed on the way:** `dependent_functions[0]` on an empty list — every entry in
`test_scada/json_data/mpf_data.json` has `dependent_functions: []`, so any real
(non `--index-only`) run raised `IndexError` on its first function.

## 3. Process plane: bigger, quieter, tree *or* DAG

**Bigger** — `scene/SceneManager.js`. Every plane was squeezed to
`PLANE_TARGET_WIDTH = 2400`, so a 20k-wide tree came back at 12%. The target now
grows with `sqrt(nodes / 130)` up to 12,000, and the fog (9,000–42,000) and
`maxDistance` (60,000) were opened up to match.

**Quieter** — `graph/model.js`, `graph/prepare.js`, `components/*`. Functions
with no recorded call in either direction — the kept backup copies — are left
off the unreached shelf by default, which is what was pushing it far off the
plane. They come back if **another loaded process calls a function of the same
name** (`sharedNames`, computed in `GraphView` across all open snapshots), or
via the toggle. The shelf caption reports how many are being held back.
On the fixtures this removes 44–84 dots per process.

**DAG** — new `graph/dag.js`, new `layoutProcessDag` in `graph/layout.js`.
The tree duplicates a function once per path from `main`; the DAG draws it once
and gives it an edge per caller. Depth is the longest path from the root, so
every edge still points up the plane; back edges are kept, drawn once, and
excluded from that calculation. Placement is a barycentre sweep (down, then up,
3 rounds) using the same measured label footprints as the tree, so labels cannot
collide and the layout is deterministic.

Measured on the existing snapshots — `proc_waterworks` 120 nodes / 5,535 wide
(tree) → 74 nodes / 2,119 wide (DAG); `proc_railyard` 5,144 → 2,659. Every
non-back edge verified upward, no dangling endpoints.

**The toggle** is in the top-left overlay panel, above the edge toggles: a
two-position tree ⇄ DAG slider plus a "show never-called functions" switch.
Flipping either rebuilds the planes that are already open.

**Enabling change:** `buildProcessPlaneLayer` now draws from an explicit
`edges` list instead of `node.parent`, which is what lets one builder serve both
shapes. `prepareProcess(index, {mode, showIsolated, sharedNames})` produces it
for either; the tree's node/parent structure is otherwise untouched.

## 4. Summaries as a separate pass

**New `summarize_run.py`** plus 5 lines in `function_summaries.py`.

A `graph.json` already carries every function's source and all call edges, so
summarizing after the fact needs neither the project-structure pickle nor the
source tree. `SnapshotCollector` exposes exactly what `summarize_collector`
uses (`functions`, `calls`, `results_root`, `process_name`, `write()`), and its
`write()` rewrites **that same** snapshot, so the run keeps its id and stays
selectable in the frontend.

`SummaryConfig.only_missing` (default `False`, so normal runs are unchanged)
makes `_summarize_one` skip any function that already has a summary — that is
what "only fill the empty ones" means even when the fingerprint cache is gone.

Verified on a copy of the real results: blanking 5 summaries and re-running
regenerated exactly those 5, left the other 191 untouched, kept the run id, and
preserved calls/source_files.

## 5. Per-project output root

**Problem.** Results went to a repo-global folder, and three writers ignored it
entirely — `helpers/dict_to_csv.py:24`, the stats JSON, and the mermaid/pyvis
graphs all wrote to a hardcoded `/home/seigyo/...`. On any other machine the
tracer CSV therefore landed somewhere `rehydrate_interactions` never read, so
resumed runs silently lost their interactions.

**Change** — `output_paths.py` gains `set_output_root()`, `pickle_root()` and
`logs_root()`. With `--output-root DIR` a run writes only under it:

```
DIR/results/csv_results/…      snapshots, CSV, stats, graphs
DIR/pickle_data/…              resolved project structures
DIR/logs/…
```

Without the flag everything falls back to today's behaviour. `pickle_root()`
also honours `PROJECT_STRUCTURE_CACHE_ROOT`, an env var the test suite already
assumed but nothing implemented. All four hardcoded paths now go through these
helpers.

The project-structure pickle name now carries a short hash of the include
options, since a structure resolved under a different search path must not be
reused. Existing pickles are ignored and re-resolved once.

**Serving:** `frontend/server.py --results-root DIR/results/csv_results`
(already supported, no change).

## 6. Overview graph

- **Icons** — new `scene/icons.js`: a database drum for `file`, three stacked
  slots for `queue`, disc for everything else. Each is one mesh with one
  material built from flat XY shapes, because picking raycasts
  non-recursively, dimming multiplies a single `material.opacity`, and a plane
  seen edge-on must collapse to a line. `frontend/ICONS.md` documents where a
  kind comes from, how to add a shape, and the rules an icon has to follow.
- **One arrow per pair** — `deriveOverview` aggregated on
  `(resource, direction)`, so a process that reads and writes the same file drew
  two or three parallel arrows. It now aggregates on the resource alone and
  merges directions (read + write ⇒ one bidirectional edge). Verified: at most
  one edge per (process, target) pair, where there used to be up to three.
- **Events aimed at real processes** — an interaction of kind
  `event`/`message`/`process` whose resolved name matches a loaded process (a
  `pmf_sendevent` target) now points at that process's node instead of minting a
  duplicate dot; a process addressing itself is dropped. The mapping is
  returned as `overview.resourceAlias` and reused for the plane→ground links, so
  the raised plane points at the same node. Names that match no loaded process
  still get their own resource, as before.

## 7. Adding targets to an existing run

`--targets PATH` overrides `<json_data>/mpf_data.json`
(`load_project_state(json_dir, targets_path)`). Nothing else was needed: paths
already traced are skipped by the per-function resume state, new ones are
appended to the same CSV, and `rehydrate_interactions` replays the whole CSV
into the new snapshot — so the snapshot that comes out holds the old *and* the
new targets. The run is additive rather than in-place, which keeps the earlier
snapshot intact and is what the frontend's run picker already expects.

Caveat: argument indices are rehydrated only for APIs present in the current
targets file; an API dropped from the JSON falls back to positional indices.

---

## Verification

- **Concurrent tracing, driven end to end with the LLM call mocked** (12 paths
  × 50 ms of blocking work): finished in 0.20 s with a peak of 4 in flight —
  0.60 s sequentially — and produced exactly 12 CSV rows, 12 stats entries and
  12 answers with correct token totals, i.e. no write was lost or interleaved.
  Re-running made zero LLM calls and added zero rows; deleting 3 stats entries
  made it redo exactly those 3, out of order, and end up complete again.
- `python -m unittest discover -s tests -q` → 38/39. The one failure,
  `test_parser_paths`, is the pre-existing one documented in `RUNNING.md` and is
  unrelated. `test_no_target_pipeline` **now passes**: it was failing because a
  stale repo-global pickle from an earlier temp directory was being reused
  (fixed by item 5) and because `trace_variable` returned `None` instead of `{}`
  when a project has no tracked APIs — a one-line change to match the
  `--index-only` return shape.
- Graph logic exercised in node against the six real snapshots in `results/`:
  DAG sizes and edge directions, shelf hiding, per-pair edge counts, direction
  merging, and the process-alias path (with a synthesised `pmf_sendevent`
  interaction).
- `npx eslint --config eslint.check.mjs src` clean; `npx vite build` succeeds.
- CSV append verified for column alignment, `NA` handling and list joining.
- Python paths, discovery, `gather_paths` (concurrency ceiling, skip list),
  `--targets` loading and the new CLI flags exercised directly.

**Not verified:** the 3D scene was not opened in a browser — no browser tooling
is available in this session — so the icons, the plane scale and the toggle were
checked at the data/layout level and by a clean production build, not visually.
A full `project_aware.py` run also could not be completed here: the call-graph
builder segfaults in "PHASE 2: RESOLVING CALL SITES" on the `test_scada`
fixtures. That crash reproduces identically on the unmodified baseline
(`git stash`), so it predates these changes and is unrelated to them, but it
does mean the concurrent tracing path has not been run end to end against a
live model.
