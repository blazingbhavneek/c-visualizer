# Handoff — dynamic (lazy) frontend loading

**Status: implemented and verified (Phases 1–3 of `frontend_dynamic_plan.md`).**
Phases 1–3 are done; Phase 4 (export-side optimization) is intentionally not
started. Read `frontend/dynamic_loading.md` for the detailed design notes and
`frontend_dynamic_plan.md` for the original spec.

## What changed, in one paragraph

The React app used to download **every** complete `graph.json` snapshot at
startup (~7.5 GB for the 383-process group, ~98 % of it embedded
`source_files`). It now sends one `GET /api/runs` (metadata-only catalog) and
one `POST /api/overview` (a <1 MB ground plane) at startup, then fetches one
process's structural bundle per canvas click, one function detail per function
click, and one bounded source slice per source view. The immutable snapshots
under `results/csv_results/visualizer/` are never modified; the server derives
small cache files next to them and caches them in bounded, TTL'd LRU memory.

## Files

| File | Change |
| --- | --- |
| `frontend/visualizer_readmodel.py` | **New (~1,300 lines).** The read model: fast single-pass JSON scanner (never `json.loads` the 20 MB snapshots), per-run derived records (`plane.json` / `function-index.json` / `source-index.json`), persisted catalog + per-selection overview caches, group-membership + path-safety enforcement, LRU byte/count/TTL-bounded in-memory caches, and a faithful Python port of `src/graph/model.js` overview/library/direction logic. |
| `frontend/server.py` | Rewired. New endpoints `/api/overview` (POST + GET), `/api/process`, `/api/function`, `/api/library`, `/api/resource`; `/api/source` now resolves via the read model (embedded slice → filesystem fallback, 403/404 preserved); `/api/runs` is catalog-based and metadata-only. `/api/graph` remains but is marked deprecated; the client never calls it. |
| `wiki/serve.py` | One change: unknown POST paths defer to the visualizer handler (`super().do_POST()`) instead of 404-ing, so `POST /api/overview` works with chat enabled. Chat/SSE flow untouched. |
| `frontend/src/api.js` | `fetchOverview`, `fetchProcess`, `fetchFunctionDetail`, `fetchLibrary`; abort-signal support added to `getJson`/`postJson`; `fetchGraph` removed from the client. |
| `frontend/src/App.jsx` | No more `Promise.all(fetchGraph(...))`. Startup = runs → overview. `unsupported` list comes from the overview payload. Citation reveal now carries the cited process name. |
| `frontend/src/components/GraphView.jsx` | The lazy lifecycle owner: ephemeral in-memory bundle/prepared/request stores keyed by `(process, run)`; a process click fetches before `openProcess()`; `onPlanesChanged` diffing releases a bundle on explicit close **and** FIFO eviction (abort pending request, delete bundle + prepared planes, clear matching selection); late responses for released planes are ignored; `collapseAll` releases every bundle; run/overview changes collapse everything and refetch lazily; chat-citation reveal fetches exactly the cited process. |
| `frontend/src/components/Inspector.jsx` | Function panel fetches one `/api/function` per selection with abort + stale-response drop and a visible loading state; call structure renders immediately from the in-memory bundle while the server detail (summaries, argument evidence, bounded traces) arrives; process panel shows loading/error for the plane request; resource panel consumes the server overview shape (`processes` array). |
| `frontend/src/components/EvidenceRail.jsx` | "View in graph" passes `path.process` (process name) to reveal. |
| `frontend/dynamic_loading.md` | Implementation notes + verification results. |
| `tests/test_visualizer_readmodel.py` | **New, 13 tests:** catalog metadata-only, group membership, traversal/unknown-run rejection, source omission from plane/overview, function-detail bounds, embedded/403/404 source, library aggregation, resource detail, direction semantics, derived-file reuse across instances, scanner/parser agreement. |

Untouched by design: `src/graph/model.js` (still normalizes bundles via
`indexSnapshot`), all `src/scene/*` code, chat hook/payloads, the exporter,
and the result snapshots.

## How to run

```bash
cd forkproc_checker/c-visualizer
python3 frontend/server.py                     # :8765, all runs, chat on
python3 frontend/server.py --no-chat --port 8899
python3 frontend/server.py --group batch-20260827_061907
cd frontend && npm run dev                     # dev mode, proxies /api
cd frontend && npm run build                   # production bundle (done; dist/ rebuilt)
```

First `GET /api/runs` builds the catalog (~26 s one-time for 383 snapshots,
persisted to `visualizer/catalog.json`, mtime-keyed). First full-group
overview builds all derived records (~30–60 s one-time, persisted per run);
subsequent overview hits are ~0.01 s. Delete a `visualizer/**/plane.json`
(or the `overview/` dir) to force re-derivation; derived files validate
against `(path, mtime, size)` and the API version and are rewritten
atomically.

## Verified

- `tests/test_visualizer_readmodel.py` (13) + `tests/test_process_groups.py` (9): all pass.
- Live-server contract checks against the real 383-process group: startup =
  catalog + overview only (0.48 MB payload, zero `/api/graph`, zero source
  payloads); process/function/source/library/resource endpoints all verified
  including 404/400/traversal rejections; group filtering (the saved group
  covers all 383 runs, so out-of-group rejection is unit-test-covered only);
  chat-enabled mode (wiki mixin) delegates `POST /api/overview` correctly.
- `npx eslint --config eslint.check.mjs src` clean; `npx vite build` clean
  (dist/ rebuilt).

## Not verified / known caveats

1. **No browser available in this environment** — the 3D scene, plane
   open/close/eviction UX, Inspector states and citation reveal were verified
   at the build/lint/data-contract level, not visually. First real-browser
   pass is the single most important remaining step (see the network-behavior
   checklist in the plan's verification section).
2. `tests/test_wiki_graph.py` failures seen in a full-suite run look
   pre-existing (they test `wiki/present.py` citation formatting, which this
   work did not touch), but the interrupted baseline comparison was not
   completed — re-run `python3 -m pytest tests/test_wiki_graph.py` on a clean
   checkout to confirm. Several other test modules don't collect in this
   environment (`rich`/`clang` modules missing — pre-existing).
3. "Shared names" (never-called shelf functions) are now computed over the
   *loaded* planes instead of all selected processes — a deliberate
   consequence of not holding a global function registry in the browser
   (documented in `frontend/dynamic_loading.md`).
4. Cold full-group overview blocks the request for ~30–60 s on a never-derived
   results tree; the UI shows the loading overlay meanwhile. If that ever
   matters, the next step is a streaming/progress response or pre-warming the
   derived records at server start.

## Suggested next steps (in order)

1. Manual browser pass: open the group, click 3+ processes (FIFO eviction),
   toggle tree/DAG + show-isolated, change one run in the Runs overlay, use a
   chat citation "View in graph", watch the Network tab against the plan's
   verification checklist, and check heap after opening/closing ten planes.
2. If the visual pass finds issues, they will most likely be in
   `GraphView.jsx`'s release diffing or `Inspector.jsx`'s detail loading —
   both are small, self-contained files.
3. Phase 4 (export-side: separate structural metadata from source content,
   SHA-256 content addressing, schema-v2 with a v1 compatibility reader) is
   the remaining plan phase and is a pipeline-side change, not a frontend one.
