# Frontend replacement handoff

## Purpose

Replace the current frontend freely. Its only job is to explore **immutable
static-analysis snapshots**: a process's functions and calls, plus any
daemon-resource evidence inferred during analysis. It is not a live C parser,
does not run the analysis pipeline, and should not scrape the legacy CSV,
Mermaid, or PyVis outputs.

The source of truth for a new UI is `graph.json`, served through the small
read-only API in `frontend/server.py`.

## Where the data comes from

```text
project_aware.py
  ├─ captures the complete static call graph and target-specific traces
  ├─ records each validated analysis result (a `Combined` result)
  └─ VisualizerCollector.write()
       └─ results/csv_results/visualizer/<process>/runs/<run_id>/graph.json
            └─ frontend/server.py
                 └─ /api/runs, /api/graph, /api/source
                      └─ browser UI
```

`visualizer_export.py` owns the snapshot schema. `project_aware.py` creates a
collector for a run, calls `capture_call_graph(...)` while tracing target APIs,
calls `record_combined(...)` for each completed result, then calls `write()` at
the end. The export is additive: each write creates a new run directory and
does not modify an existing snapshot.

Important distinction:

- **Functions and calls** come from static call-graph construction.
- **Traces** are selected `main`-to-target display paths.
- **Resources and interactions** come from the later model-assisted `Combined`
  results. They may be empty even when the call graph is large.

For example, the currently selected `proc_boiler` snapshot has 214 functions
but zero resources and zero interactions. That is valid data, not a frontend
error.

## Snapshot location and results-root resolution

The expected directory layout is:

```text
<results-root>/
  visualizer/
    runs.json                              # optional convenience manifest
    <process_name>/
      runs/
        <run_id>/
          graph.json                       # one complete schema-v1 snapshot
```

For this checkout, the normal location is:

```text
/mnt/common/Code/c-repo/results/csv_results/visualizer/
```

Both the exporter and frontend honor `VISUALIZER_RESULTS_ROOT`. The frontend
also accepts an explicit CLI value, which is the most reliable way to point a
development UI at fixtures or another machine's output:

```bash
python frontend/server.py \
  --results-root /absolute/path/to/results/csv_results \
  --port 8765
```

Without either setting, the frontend prefers the former environment-specific
path `/home/seigyo/c_repo/c_repo/results/csv_results` when it exists; otherwise
it uses this repository's `results/csv_results` directory.

The server scans `visualizer/*/runs/*/graph.json` directly. It does **not**
read `visualizer/runs.json`; treat that file as optional tooling metadata.

## HTTP interface

The server binds to `127.0.0.1` and has no authentication because it is a local
development server. It serves the frontend directory as static files and
provides the following JSON endpoints.

### `GET /api/runs`

Scans every snapshot and returns lightweight metadata. The response is sorted
by process name, then newest `generated_at` first within each process.

```json
{
  "results_root": "/mnt/common/Code/c-repo/results/csv_results",
  "runs": [
    {
      "process_name": "proc_boiler",
      "run_id": "20260730_101700",
      "generated_at": "2026-07-30T10:17:01.321052+00:00",
      "function_count": 214,
      "resource_count": 0,
      "interaction_count": 0
    }
  ]
}
```

An empty `runs` array is a normal "no snapshots yet" state.

### `GET /api/graph?process=<process_name>&run=<run_id>`

Returns the exact parsed contents of that snapshot's `graph.json`. Parameters
are required. A missing or invalid pair returns:

```json
{ "error": "Graph snapshot not found." }
```

with HTTP 404. The server rejects path traversal by resolving the constructed
path under `<results-root>/visualizer`.

Example:

```text
/api/graph?process=proc_boiler&run=20260730_101700
```

### `GET /api/source?process=<process_name>&run=<run_id>&function=<function_id>`

Returns the definition lines for an internal function:

```json
{
  "file": "/absolute/path/to/bo_safety.c",
  "start_line": 475,
  "end_line": 523,
  "text": "  475  static void example(void) {\\n..."
}
```

`text` is a pre-numbered snippet, read as Latin-1 with replacement for invalid
bytes. It is safe to render as plain text, never HTML. Expect a 404 for external
functions, missing source files, and functions without a source path. Expect a
403 if the function's source falls outside `process.root`.

All frontend responses use `Cache-Control: no-store`; fetch current data rather
than relying on browser cache behavior.

## `graph.json` schema (version 1)

Every snapshot has this top-level shape:

```ts
interface GraphSnapshot {
  schema_version: 1;
  generated_at: string; // ISO-8601 UTC timestamp
  run_id: string;       // directory name; may have a _2 suffix on collision
  process: Process;
  functions: FunctionNode[];
  calls: CallEdge[];
  resources: Resource[];
  interactions: Interaction[];
  traces: Trace[];
}
```

All six collection fields are always arrays but any of them may be empty.
Unknown fields should be ignored so a newer exporter can add metadata without
breaking the UI.

### `process`

```ts
interface Process {
  id: string;                 // e.g. "process:5e5184ea48497dc1"
  name: string;               // e.g. "proc_boiler"
  root: string;               // absolute process directory
  main_file: string | null;
  entry_function_id: string | null;
}
```

`entry_function_id` is the first non-external function named `main`, when one
was found. Do not assume it is non-null; a UI should choose a sensible fallback
such as graph roots.

### `functions`

```ts
interface FunctionNode {
  id: string;                 // opaque ID, e.g. "function:ee4626d46fc400ac"
  kind: "function" | "external_function";
  name: string;
  file: string | null;        // absolute definition path when known
  file_name: string | null;
  start_line: number;         // -1 if not known
  end_line: number;           // -1 if not known
  is_external: boolean;
  is_static: boolean;
  summary_status: "pending" | "library";
  summary: string | null;     // currently normally null
  call_count: number;
  resource_interaction_count: number;
  summary_hint?: string;      // present for non-external functions
}
```

`id`, not `name`, is the identity. The same function name may occur in more
than one source file. `is_static` means file-local C linkage. `is_external`
includes unresolved/library/macro-style targets and normally has no usable
source evidence.

### `calls`

```ts
interface CallEdge {
  id: string;
  source: string;             // FunctionNode.id
  target: string;             // FunctionNode.id
  line: number | null;        // call-site line, not definition line
  kind:
    | "direct"
    | "indirect"
    | "external_call"
    | "macro_call"
    | "macro_expansion"
    | "callback";
  via: string | null;         // FunctionNode.id for a callback registrar
}
```

`calls` is the complete captured graph, not only the paths that successfully
reached a target. Multiple calls between the same pair are distinct when their
line/kind/via differs. Preserve rather than silently deduplicate them.

`indirect` represents a call the static analyzer could not resolve (often a
function pointer). `callback` is an inferred registrar-to-handler connection;
its `via` identifies the registration target. Macro edges are also deliberate
analysis artifacts and should remain visible.

### `resources`

```ts
interface Resource {
  id: string;
  kind: "file" | "queue" | "event" | "semaphore" | "process"
      | "message" | "daemon_resource";
  name: string;               // an inferred value, not necessarily a file path
  resolved: boolean;
}
```

Resources are keyed by `kind + name` within a snapshot. They are derived from
the values in `Combined.target_number.ans`; they are analysis evidence, not a
live daemon inventory. `resolved: false` commonly corresponds to `UNRESOLVED`
or `NO TARGET`.

### `interactions`

```ts
interface Interaction {
  id: string;
  function_id: string | null; // FunctionNode.id when attribution succeeded
  resource_id: string;        // Resource.id
  target_api: string;
  operation: string;          // e.g. READF, ENQ, EVENT, SEMAPHORE
  launch_via: string | null;
  call_number: number | string | null;
  argument_binding: {
    argument_index: number;   // one-based index in the target API
    value: string | number | boolean | null;
  };
  path: string | null;        // display path supplied by the tracer
  source: Record<string, unknown>;
  function_source: Record<string, unknown>;
}
```

One `Combined` result with several resolved argument values produces one
interaction per value. An interaction can have `function_id: null` when the
exporter cannot match the model evidence back to a static call site; show it as
unattributed instead of dropping it. In current snapshots, `source` and
`function_source` normally contain `{ "path": string, "line_number": string }`.

### `traces`

```ts
interface Trace {
  id: string;
  target_api: string;
  labels: string[];
  display_path: string;       // labels joined with " -> "
}
```

Traces are target-API paths, not a replacement for `calls`. Use `labels` for an
ordered path view; use `display_path` for a readable compact representation.
Labels are display strings rather than stable IDs, so do not use them for graph
joins.

## Representative snapshot fragment

This is abbreviated from an existing `proc_boiler` snapshot. IDs are opaque;
the cross-references are the important part.

```json
{
  "schema_version": 1,
  "generated_at": "2026-07-30T10:17:01.321052+00:00",
  "run_id": "20260730_101700",
  "process": {
    "id": "process:5e5184ea48497dc1",
    "name": "proc_boiler",
    "root": "/mnt/common/Code/c-repo/test_scada/processes/proc_boiler",
    "main_file": "main.c",
    "entry_function_id": "function:ee4626d46fc400ac"
  },
  "functions": [{
    "id": "function:2d7208cd7bd9845d",
    "kind": "function",
    "name": "bo_first_out_annunciate",
    "file": "/mnt/common/Code/c-repo/test_scada/processes/proc_boiler/bo_safety.c",
    "file_name": "bo_safety.c",
    "start_line": 240,
    "end_line": 260,
    "is_external": false,
    "is_static": true,
    "summary_status": "pending",
    "summary": null,
    "call_count": 1,
    "resource_interaction_count": 2,
    "summary_hint": "Static analysis: 1 outgoing call(s), 2 daemon-resource interaction(s)."
  }],
  "calls": [{
    "id": "call:6814bbd13bf51b78",
    "source": "function:2d7208cd7bd9845d",
    "target": "external:8c2f1873d4296f69",
    "line": 257,
    "kind": "external_call",
    "via": null
  }],
  "resources": [{
    "id": "resource:582117e481be3b08",
    "kind": "queue",
    "name": "10",
    "resolved": true
  }],
  "interactions": [{
    "id": "interaction:01ba8ac102b83404",
    "function_id": "function:2d7208cd7bd9845d",
    "resource_id": "resource:582117e481be3b08",
    "target_api": "scf_alarmq_enq",
    "operation": "ENQ",
    "launch_via": "EVENT",
    "call_number": -1,
    "argument_binding": { "argument_index": 1, "value": 10 }
  }],
  "traces": [{
    "id": "trace:104ca1d5f24e2ff3",
    "target_api": "scf_evt_post",
    "labels": [
      "[main.c]main[312:373]",
      "[358]scf_task_fork (accepts callback)-> bo_combust_task",
      "[bo_combust.c:358]bo_combust_task[420:438]",
      "[437]scf_evt_post"
    ],
    "display_path": "[main.c]main[312:373] -> [358]scf_task_fork (accepts callback)-> bo_combust_task -> [bo_combust.c:358]bo_combust_task[420:438] -> [437]scf_evt_post"
  }]
}
```

## Required joins and useful derived data

```text
process.entry_function_id ──────────────► functions[].id
calls[].source / calls[].target ────────► functions[].id
interactions[].function_id (if present) ─► functions[].id
interactions[].resource_id ─────────────► resources[].id
```

Build maps keyed by ID once per snapshot. Good derived values are:

- incoming/outgoing call lists per function;
- interaction lists per function and per resource;
- all resources grouped by `kind` and `resolved` status;
- latest snapshot per `process.name`, based on `generated_at`;
- graph roots: functions with no incoming internal call, if there is no entry
  function.

Do not infer an interaction from an external call merely because the names look
related. Only the `interactions` collection is evidence for a resource link.

## Product requirements for the replacement UI

1. Fetch `/api/runs`; give the user a clear empty state and a process/run
   selector. Keep historical runs selectable.
2. Fetch exactly one `/api/graph` snapshot for the selected run. Show loading,
   404, malformed-data, and network-error states.
3. Provide a usable call-graph view with pan/zoom, search, and filters for
   internal/static/external functions and call kind. Large graphs are expected.
4. Make node and edge selection reveal evidence: definition location, outgoing
   calls, resource interactions, traces containing the function name, and the
   raw ID/source fields when useful for debugging.
5. When a selected internal function has a usable `file` and line range, offer
   the `/api/source` snippet. Handle its 403/404 response without breaking the
   inspector.
6. Make resource evidence a separate, honest layer: distinguish resolved from
   unresolved and attributed from unattributed interactions. A zero-resource
   snapshot must still be a useful call-graph view.
7. Treat `schema_version !== 1` as an explicit unsupported-version state until
   a compatibility adapter is implemented.

The frontend may use a framework and graph library of its choice. Keep the
data-fetching boundary above intact unless the server is deliberately replaced
at the same time.

## Development and debugging

Start the local server:

```bash
python frontend/server.py --port 8765
```

Inspect actual data without a UI:

```bash
curl -s http://127.0.0.1:8765/api/runs | jq
curl -s 'http://127.0.0.1:8765/api/graph?process=proc_boiler&run=20260730_101700' | jq
curl -s 'http://127.0.0.1:8765/api/source?process=proc_boiler&run=20260730_101700&function=<function-id>' | jq
```

Useful source files:

| File | Responsibility |
| --- | --- |
| `visualizer_export.py` | Schema-v1 collector and JSON writer; change this only when intentionally evolving the contract. |
| `project_aware.py` | Connects the analysis pipeline to the collector. |
| `output_paths.py` | Shared `VISUALIZER_RESULTS_ROOT` resolution used by the exporter. |
| `frontend/server.py` | Static-file server and the complete read API. |
| `results/csv_results/visualizer/` | Real fixture data already in the repository. |
| `models.py` | Definition of the richer `Combined` analysis data that becomes resource interactions. |

When changing the exported shape, increment `schema_version`, document the
migration, and keep a representative fixture for each important edge case:
empty interactions, unresolved resources, callback/macro/indirect calls,
external functions, and an unattributed interaction.
