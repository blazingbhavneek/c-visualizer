# Dynamic frontend loading — implementation notes

This is the implemented counterpart to `frontend_dynamic_plan.md`. The React
app no longer downloads complete `graph.json` snapshots; it loads one compact
overview at startup and fetches each process, function and source on demand.
The immutable snapshots under `results/csv_results/visualizer/` are untouched.

## Request lifecycle

```text
startup        GET  /api/runs                (metadata-only catalog)
               POST /api/overview            (compact ground plane for the selection)
click process  GET  /api/process             (one process's structural bundle)
click function GET  /api/function            (detail: calls, interactions, traces, summary)
source view    GET  /api/source              (one bounded slice, embedded or filesystem)
library node   GET  /api/library             (synthetic plane for one component)
resource click (overview data is already in memory; /api/resource is available)
plane close    no request — the bundle is released from browser memory
```

The deprecated `GET /api/graph` (raw snapshot) is still served for debugging;
the client never calls it.

## Server (`frontend/server.py`, `frontend/visualizer_readmodel.py`)

* `ReadModel` derives, per `(process, run)`, small derived files next to the
  snapshot:

  ```text
  visualizer/
    catalog.json                        # run metadata + counts, mtime-keyed
    overview/<selection-key>.json       # compact overview per selection
    <process>/runs/<run>/
      plane.json                        # functions (no source), calls, resources, interactions, traces
      function-index.json               # per-function line ranges + embedded slices
      source-index.json                 # source-file metadata (built lazily)
  ```

  A derived file is only served when its `built_from`
  `(path, mtime, size)` matches the current snapshot and the API version is
  current; otherwise it is rebuilt atomically (temp file + `os.replace`).
  Concurrent requests for the same run are serialized by a per-path lock, and
  in-memory caches are LRU-bounded by both entry count and bytes with a TTL.

* Snapshots are ~98 % embedded `source_files`, so the read model never runs a
  full `json.loads` on them. A single-pass, string-aware scanner
  (`scan_graph_sections`) walks the file skipping string content with
  `str.find`, records the structural array spans and counts, and only the
  small arrays are parsed. `source_files` content is never retained; its
  metadata is walked out lazily on first `/api/source` use.

* The overview, library and direction logic is a faithful port of
  `src/graph/model.js` (producer/consumer operations, API overrides,
  `(kind, name)` resource joins, process-target aliases, library boundary and
  library-ownership rules), so the server-derived ground plane and the
  client-rendered process planes agree on every arrow.

* When `--group` is set, every process/run endpoint (overview, process,
  function, source, library, resource, and the deprecated graph) rejects
  out-of-group runs. All lookups go through the catalog, so path traversal and
  symlink escapes cannot reach the filesystem; `/api/source` additionally
  keeps the 403-outside-root / 404-unavailable behavior.

* First full-group overview (383 processes) builds all derived records once
  (~30–60 s, one-time) and is then served from cache in milliseconds. The
  overview payload for the whole group is under 1 MB; the old path transferred
  ~7.5 GB per browser startup.

## Client (`src/App.jsx`, `src/components/GraphView.jsx`, `Inspector.jsx`)

* `App` fetches runs, then one overview for the selected runs. There is no
  `Promise.all` over process graphs anymore, and no snapshot data in React
  state beyond the compact overview.

* `GraphView` keeps ephemeral, in-memory stores:
  `indexesRef` (open/loaded bundles), `preparedRef` (prepared tree/DAG per
  mode), `requestsRef` (in-flight fetch with its `AbortController`).
  `SceneManager`'s `onPlanesChanged` is diffed: a plane that disappears
  (explicit close *or* FIFO eviction) aborts any pending request for it,
  deletes its bundle and prepared planes, and clears a selection that belongs
  to it. `collapseAll` releases every bundle the same way. A late response for
  a released plane is ignored and cannot repopulate the stores.

* Selecting a function fires one `/api/function` request; the Inspector shows
  a loading state and aborts/drops the response if the selection moves first.
  The call structure of the already-open plane is rendered immediately from
  the in-memory bundle while the server detail (summaries, argument evidence,
  bounded traces) arrives.

* Library planes come from the server (`/api/library`), not from a
  client-side aggregation of all snapshots.

* Chat citation reveal now carries the cited process name (the wiki payload
  already provides it); revealing a citation fetches exactly that process's
  bundle, opens its plane and highlights the cited functions.

## Behavior notes

* "Shared names" (never-called functions that reappear because another
  process uses the name) are now computed over the *loaded* planes instead of
  every selected process — the cross-process call registry no longer exists
  in the browser by design. The `show never-called` toggle is unchanged.
* No browser persistence (`localStorage`/`IndexedDB`) is used for graph data.

## Verification

* `tests/test_visualizer_readmodel.py`: catalog metadata-only, group
  membership, traversal/unknown-run rejection, source omission from plane and
  overview, function-detail bounds, embedded/403/404 source behavior,
  library aggregation, resource detail, direction semantics, derived-file
  reuse across instances, scanner/parser agreement.
* Measured against the 383-process group: startup performs one catalog and
  one overview request (0.48 MB), zero `/api/graph` and zero source payloads;
  a process click performs one `/api/process`; a function click performs one
  `/api/function` plus one bounded `/api/source`.
* `npx eslint --config eslint.check.mjs src` and `npx vite build` are clean.
* The 3D scene itself was not exercised in a browser in this environment;
  the client changes were verified at the build, lint and data-contract level.
