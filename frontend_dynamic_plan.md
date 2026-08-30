# Dynamic frontend loading plan

## Scope

This is an implementation plan only. No application code or result snapshot is
changed by this document.

The target is the React application under `frontend/` and its Python server at
`frontend/server.py`, reading snapshots under
`results/csv_results/visualizer/`.

## Why the current loading model fails

The current request path is:

1. `App.jsx` calls `/api/runs`.
2. It selects one run for every process.
3. It calls `/api/graph` for every selected process with `Promise.all`.
4. Each response is the complete `graph.json`.
5. The browser keeps every snapshot in `indexes`, including embedded source
   files, and derives the overview from all of them.

There is a second copy of the problem on the server: `scan_graph_runs()` reads
and deserializes complete snapshots merely to obtain run counts, and
`/api/source` loads the complete graph again to find one function.

The current data makes this especially expensive:

- The saved group contains 383 processes, 96,703 functions, 1,195 resources,
  and 4,653 interactions.
- The 383 current graph files occupy about 7.48 GiB in total.
- Individual graph files are approximately 20--27 MiB.
- In representative files, `source_files` is about 97.8% of the JSON size,
  with roughly 5,000 embedded files per process.
- The structural data needed for a process plane is much smaller: functions,
  calls, resources, and interaction links. It does not need all source-file
  contents.

The required behavior is therefore:

```text
initial request
    -> compact catalog + process/entity interaction overview

click process
    -> that process's compact call-tree/DAG input

click function
    -> that function's summary, calls, interactions, traces, and source on demand

close process plane
    -> dispose scene objects and delete that process bundle from browser memory
```

The immutable result snapshots on disk must remain intact. “Delete from
storage” means release the temporary browser/server cache for the open view, not
delete the analysis results.

## Design principles

1. Never send `source_files` as part of the initial overview or process-plane
   response.
2. Never put complete raw snapshots in React state after the migration.
3. Keep only compact overview data permanently in the client.
4. Keep at most the currently open process bundles in client memory. A closed
   process is removed immediately; it is not retained in an unbounded cache.
5. Keep source content out of function lists. Fetch one function's source only
   when that function is selected.
6. Preserve the current semantics: resource joins use `(kind, name)`, process
   target resources can alias process nodes, and library views remain available.
7. Treat every response as immutable and keyed by `(process_name, run_id)` plus
   the group/run selection. Do not mix data from two runs.
8. Keep the current `/api/ask/stream` contract independent of graph rendering.
   Chat can continue to use its server-side corpus, while graph citations
   trigger the same lazy process loading as a canvas click.

## Target request lifecycle

### 1. Bootstrap and overview

Replace the startup fan-out of `/api/graph` calls with:

```text
GET /api/runs
GET /api/overview              (or POST with an explicit run selection)
```

`/api/runs` must be a metadata-only catalog. It should return process name, run
ID, timestamp, counts, schema version, and allowed group membership. It must
not call `json.loads()` on every full snapshot just to calculate those values.
Prefer the saved group manifest and a generated visualizer catalog. For legacy
directories where that metadata is absent, build a bounded server-side index
once, then persist only metadata; do not return the raw graphs to the client.

The overview response should contain only what the ground plane needs:

```json
{
  "api_version": 1,
  "selection_key": "stable-hash-of-selected-process-runs",
  "processes": [
    {
      "id": "process:Example",
      "type": "process",
      "name": "Example",
      "run_id": "20260827_000001",
      "generated_at": "...",
      "function_count": 134,
      "resource_count": 2,
      "interaction_count": 3
    }
  ],
  "resources": [
    {
      "id": "resource:file\\u0000QUEUE_A",
      "key": "file\\u0000QUEUE_A",
      "kind": "file",
      "name": "QUEUE_A",
      "resolved": true,
      "processes": ["Example", "Consumer"]
    }
  ],
  "edges": [
    {
      "id": "edge:Example:file\\u0000QUEUE_A",
      "process_name": "Example",
      "resource_key": "file\\u0000QUEUE_A",
      "target_id": "resource:file\\u0000QUEUE_A",
      "direction": "out",
      "count": 2,
      "operations": ["WRITEF"],
      "apis": ["mpf_mfs_write"]
    }
  ],
  "resource_aliases": {}
}
```

The exact wire names can follow the existing frontend names, but the response
must not contain `functions`, `calls`, `source_files`, or `traces` for every
process. `resource_aliases` must preserve the current mapping for process/event/
message resources whose name is another loaded process.

The server should derive this data once from compact per-run records. The
direction calculation currently lives in `frontend/src/graph/model.js`; it
must be shared or reproduced on the server so the overview and process planes
agree about producer/consumer arrows.

When the Runs overlay changes one process's run, request a new overview using
the new selection. Do not reload every process plane. Close/release any open
plane whose `(process, run)` changed, then lazily reload it only if selected
again.

### 2. Process-plane load

Clicking a ground process must be the first request for that process's graph
data:

```text
GET /api/process?process=<name>&run=<id>
```

The response is a compact process bundle. It may be called `plane` in the
implementation, but it must include enough structural information to preserve
the existing tree/DAG toggle and unreached shelf behavior:

```json
{
  "api_version": 1,
  "process": {
    "name": "Example",
    "run_id": "20260827_000001",
    "root": "/source/Example",
    "entry_function_id": "function:...",
    "entry_function": "main"
  },
  "functions": [
    {
      "id": "function:...",
      "name": "main",
      "file": "/source/Example/main.c",
      "file_name": "main.c",
      "start_line": 1,
      "end_line": 40,
      "is_external": false,
      "is_library_api": false,
      "is_static": false,
      "call_count": 3,
      "resource_interaction_count": 1,
      "summary_status": "pending"
    }
  ],
  "calls": [],
  "resources": [],
  "interaction_links": []
}
```

`functions` in this response are metadata only. In particular, omit each
function's `source` and omit all `source_files`. The client can continue to use
`prepareProcess()` after normalizing this response to its existing index shape,
or the server can later return a display-ready tree. The first implementation
should keep layout in the client so the existing tree/DAG, `showIsolated`, and
layout reset controls retain their behavior.

`interaction_links` should be a compact form of the existing interactions,
containing only what is needed to attach process-plane ports and cross-plane
edges: function ID, resource key/ID, target API, operation, launch mode,
direction, and enough resource metadata to resolve the ground target. Full
paths, value origins, and argument evidence belong to the function detail
request.

The process-plane response must not include traces or full source content.
Those are not needed to construct `buildProcessPlaneLayer()`.

### 3. Function detail load

Selecting a function node must fetch only the selected function's related data:

```text
GET /api/function?process=<name>&run=<id>&function=<function-id>
```

The response should include:

- the complete function metadata and summary fields;
- outgoing calls and incoming calls for that function;
- compact neighbor function records so the Inspector can display names without
  loading the process's complete function registry again;
- interactions attributed to the function, with resource metadata and argument
  evidence;
- bounded traces relevant to the function, preserving the current maximum of
  12 displayed traces;
- a source availability flag/reference, but not unrelated source files.

The Inspector should show a loading state immediately and discard the response
if the user has selected a different function before it arrives. The request
key must include process and run, not only function ID, because IDs are scoped
by snapshot/run semantics in the current application.

### 4. Source load

Keep `/api/source` as a separate small request, but stop loading the complete
graph to locate the function:

```text
GET /api/source?process=<name>&run=<id>&function=<function-id>
```

The server should resolve a source slice using a compact function/source index:

1. Return the embedded function slice when that function has one.
2. Otherwise locate the source file by its content hash/path in the server's
   source index and read only the requested line range.
3. Fall back to the existing process-root filesystem check for older snapshots.
4. Preserve the current 403 behavior for files outside the process root and 404
   behavior for unavailable source.

The response remains a bounded `{file, start_line, end_line, text}` object.
Never expose a source-file listing or a complete source file unless that is an
explicit future feature.

### 5. Resource detail load

The current overview object is enough for the basic resource Inspector, but a
future richer resource panel should use:

```text
GET /api/resource?selection=<selection-key>&kind=<kind>&name=<name>
```

This endpoint can return the processes, operation counts, and bounded
function/interaction references for one `(kind, name)` resource. It must not
load or return all interactions from every process.

## Server-side storage and caching

### Canonical data versus derived cache

Do not delete or rewrite the immutable `graph.json` snapshots when a user closes
a plane. They are shared analysis results and may be needed by another browser
or by the chat index.

Use a separate derived representation for the dynamic API. The preferred
layout is:

```text
visualizer/
  catalog.json                         # run metadata and counts
  overview/<selection-key>.json        # compact ground-plane data
  <process>/runs/<run>/
    plane.json                         # functions/calls/resource links only
    function-index.json                # IDs, line ranges, source references
    source-index.json                  # source metadata, no bulk content
```

Source content should be content-addressed by SHA-256 when a durable cache is
introduced, so the same header included by hundreds of process snapshots is
stored once. The raw snapshots remain the compatibility source of truth until
the exporter is migrated.

For the first migration, the server may derive these compact records lazily
from a legacy `graph.json`, but it must:

- build the compact record once per `(path, mtime, size, API version)`;
- discard the raw `source_files` list immediately after extraction;
- atomically write derived files so an interrupted request cannot leave a
  partial record;
- coordinate concurrent requests for the same run so two clicks do not parse
  the same 20 MiB graph twice.

### In-memory limits

The server's derived-record cache should be bounded by both entry count and
bytes, with TTL/LRU eviction. It must cache compact plane/index data, not full
snapshots. A reasonable initial policy is a small number of active plane bundles
plus a bounded overview cache; tune it using measured heap and request metrics.

The browser must not use `localStorage` or `IndexedDB` for raw graph data. The
compact overview can remain in React state. Process bundles and function details
belong in an ephemeral in-memory store with explicit release methods. If a
server session cache is added later, it needs an idle TTL and cleanup on both
normal release and timeout; a missing release request must not leak storage
forever.

## Client state and release contract

The current `indexes` array and `preparedCache` are the main retention points.
Replace them with separate stores:

```text
overviewState                       persistent for the current selection
processBundles: Map<runKey, Bundle>  only open/actively loading planes
preparedPlanes: Map<runKey, View>    only while the plane is open
functionDetail: one selected record  cleared on selection/plane change
sourceDetail: one selected record    cleared on selection/plane change
```

Required lifecycle:

1. On process click, create an `AbortController`, fetch one process bundle, and
   open the plane only after the bundle is valid.
2. If the same process/run is already loaded, reuse that one bundle.
3. When `SceneManager` closes a process, including FIFO eviction when a third
   plane opens, notify React and synchronously:
   - abort a pending request for that run;
   - delete its process bundle;
   - delete its prepared tree/DAG and layout references;
   - clear selected function/detail/source if they belong to that process;
   - let `SceneManager` dispose the Three.js layer as it already does.
4. `collapseAll` must release every process bundle, not only the Three.js
   objects.
5. When a run selection changes, invalidate only the affected `(process, run)`
   entries and rebuild the compact overview.
6. Every asynchronous response must check that its request key is still the
   active key before entering state. A late response from a closed plane must
   be ignored and must not repopulate the cache.

Add a visible loading/error state on the process node or Inspector while the
tree request is pending. The ground overview must remain usable while a process
plane loads.

## Existing feature compatibility requirements

### Library planes

`GraphView` currently calls `buildLibraryIndexes(indexes)` and derives synthetic
library planes from all loaded process snapshots. That cannot remain a client
operation after process snapshots become lazy.

The server must either:

- produce library process nodes in `/api/overview` and a compact library-plane
  endpoint; or
- expose a cached `/api/library?component=<name>&selection=<selection-key>`
  endpoint that returns the aggregated library functions, calls, and interaction
  links when the library node is clicked.

The aggregation must retain the current library boundary rules and must not
recreate a full client-side copy of every process snapshot.

### Chat citation reveal

`GraphView` currently finds a citation's process by scanning all loaded function
IDs. With lazy data, chat citations must carry `process_name` and `run_id`, or
the client must call a small function-resolution endpoint. A citation reveal
then fetches exactly that process bundle, opens its plane, and highlights the
returned function IDs. It must not force all process graphs to load.

### Run picker and group filtering

All process/run endpoints must validate against the active `--group` selection.
The existing `/api/runs` filter is not sufficient because `/api/graph` currently
accepts a direct process/run query independently of that filter. Reject
out-of-group runs consistently for overview, process, function, resource, and
source requests.

Keep path validation rooted at `results_root/visualizer` and continue rejecting
path traversal or symlink escapes. Do not expose absolute filesystem paths in
new catalog fields unless the existing Inspector explicitly needs them.

## Suggested implementation phases

### Phase 1: server read model, no UI behavior change

- Add a compact catalog/overview builder.
- Add server-side extraction/cache for legacy snapshots.
- Add `/api/process`, `/api/function`, and direct source lookup.
- Keep `/api/graph` temporarily for debugging and backward compatibility, but
  mark it as a raw/deprecated endpoint and do not call it from the new client.
- Add tests for group membership, schema versions, path safety, and omission of
  `source_files`.

### Phase 2: switch the client to lazy loading

- Change `src/api.js` to request catalog, overview, process bundles, function
  details, and source separately.
- Remove startup `Promise.all([...fetchGraph(...)])` from `App.jsx`.
- Change `GraphView` so a process click fetches before `openProcess()`.
- Replace global `indexes`/`preparedCache` retention with the bounded lifecycle
  described above.
- Add a close callback from `SceneManager` for both explicit close and FIFO
  eviction.
- Update Inspector loading/error handling and response race cancellation.

### Phase 3: move aggregate work out of the browser

- Add server-generated library overview/plane data.
- Add explicit process/run fields to chat citation payloads or add a resolver
  endpoint.
- Make run selection refresh only the overview and affected open plane.
- Add a feature flag so the old and new data paths can be compared on the same
  snapshot selection.

### Phase 4: durable export optimization

- Change future exports to write compact structural metadata separately from
  source content.
- Deduplicate source content by SHA-256.
- Keep a compatibility reader for existing schema-v1 `graph.json` files.
- Once all readers use the dynamic API, remove only the obsolete duplicate
  derived caches; do not remove canonical result snapshots without an explicit
  retention policy.

## Verification plan

### Network behavior

For the current 383-process group, browser startup must show only catalog and
overview requests. It must show zero `/api/graph` requests and zero source-file
payloads.

Then verify:

- one process click produces one `/api/process` request;
- opening a second process produces at most one additional process request;
- a function click produces one function-detail request and, if source exists,
  one bounded source request;
- closing/collapsing a plane produces no new graph request and releases its
  client bundle;
- reopening a closed process fetches it again or uses only a deliberately small,
  bounded cache;
- changing one run does not reload unrelated process planes;
- chat citation reveal loads only the cited process.

### Payload and memory checks

- `/api/overview` contains process/resource/edge data only.
- `/api/process` contains no `source_files` and no function source bodies.
- `/api/function` contains only the selected function's related records.
- `/api/source` never serializes the entire snapshot.
- Browser heap after opening and closing ten different processes is close to the
  heap after opening one process, apart from the compact overview and Three.js
  baseline.
- Server cache size remains below its configured byte limit after repeated
  process clicks and run changes.

### Functional regression checks

- The overview still joins resources by `(kind, name)` and aliases process
  targets correctly.
- Producer/consumer arrows and plane-to-plane edges remain correct.
- Tree and DAG modes produce the same structure as the current client for a
  selected snapshot.
- The virtual-root fallback still works when `entry_function_id` is absent.
- Unreached and never-called shelf behavior remains available.
- Function source keeps the existing embedded-source, filesystem fallback, 403,
  and 404 behavior.
- Library planes, run picker, Inspector, and chat citation highlighting still
  work with no global function registry in the browser.

