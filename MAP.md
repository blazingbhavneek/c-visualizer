# Codebase map

Where things live and what to touch when you change something.

The project is four layers that only talk through files on disk:

```
  Makefile / sources
        │  makefile_resolver/ + helpers/Preprocess/     resolve which files are in
        ▼
  call_graph/                                          who calls whom
        │
        ├──► project_aware.py + client/ + parser/       trace target arguments (LLM)
        │         └─► results/csv_results/*.csv         durable per-path answers
        │
        └──► visualizer_export.py                       graph.json snapshot
                  │
                  ├──► frontend/                        3D browser
                  └──► wiki/                            question answering
```

`graph.json` is the contract between the analyzer and everything downstream.
Nothing in `frontend/` or `wiki/` can affect a tracer run, and neither writes
snapshots — `wiki/` only reads, the frontend only reads.

---

## Entry points

| File | What it is |
|---|---|
| `project_aware.py` | **The analyzer.** CLI, per-process orchestration, the target-tracing loop. Start here for anything about *what gets traced*. |
| `summarize_run.py` | Fill in missing function summaries for results that already exist. Needs only a results folder. |
| `frontend/server.py` | Serves the UI and the `/api/*` routes; mounts the chat endpoints when `wiki/` imports. |
| `frontend/dev_mock_ask.py` | Canned chat replay, no model needed. For frontend work. |

Docs: `README.md` (overview), `usage.md` (every flag, copy-paste runs),
`RUNNING.md` (chat/model endpoints, ports), `change.md` (what changed and why),
`walk_plan.md` (the planned backward-walker rewrite), `frontend/ICONS.md`
(adding daemon-entity icons).

---

## 1. Which files are in the project

| File | Handles | Edit when |
|---|---|---|
| `makefile_resolver/makefile_resolver.py` | Parses a process Makefile (`SRCS`, `INCLUDE`, `LIBS`, `$(VAR)`), resolves paths, and **discovers header folders** the Makefile does not name (`discover_include_dirs`). `library_project_mapping` does the same for a library folder with no Makefile. | headers are missing; a new Makefile variable must be understood; library discovery misses a layout |
| `makefile_resolver/extract_includes.py` | Follows `#include` transitively (`IncludeIndex`, `resolve`) to build the final file set | an include is resolved to the wrong file |
| `helpers/Preprocess/preprocess.py` | tree-sitter parse, comment stripping, `unifdef`, macro extraction (`extract_all_macros`) | `#ifdef` handling, macro collection |
| `output_paths.py` | Where a run writes: `results_root()`, `pickle_root()`, `logs_root()`, `set_output_root()` | anything about output locations |

## 2. The call graph

| File | Handles | Edit when |
|---|---|---|
| `call_graph/call_graph.py` | `CallGraphBuilder` (definitions, call sites, macro expansion, callbacks, function pointers) → `graph: caller → [CallSite]`. `build_call_trees` expands that into per-root trees. `dfs_for_finding_path` enumerates root→target paths. `orchestrate` ties it together and produces the per-path metadata. | a call is missed or mis-attributed; path enumeration changes; **this is the file the scaling work in `walk_plan.md` targets** |
| `call_graph/data_classes.py` | `FunctionNode`, `CallSite`, `CallTreeNode` and the **path label grammar** (`[file:line]name[start:end]`, `(macro expansion)->`, `(accepts callback)->`) | the label format changes — many things parse it |
| `call_graph/gen_graph.py` | Per-target mermaid + pyvis output under `results/…/graphs/` | those artifacts |
| `call_graph/ai_fallback.py` | LLM fallback for paths the static builder cannot resolve | fallback behaviour |

## 3. Target tracing (the LLM part)

| File | Handles | Edit when |
|---|---|---|
| `project_aware.py` | `identify_funs_to_trace` (which APIs appear), `make_llm_calls_for_function` (**the per-path loop**, concurrency, resume, CSV/stats writes), `trace_variable` (per-process pipeline), `llm_calls` (the tracer system prompt), `gather_paths`, `record_library_fact` | the prompt, what a row contains, concurrency, resume, library-cache use |
| `library_facts.py` | Library discovery, the suffix-keyed answer cache (`LibraryFactStore`), path-label key normalisation | library caching rules; what counts as a library |
| `parser/parser_files.py` | Builds the C context for one path: the bodies along the chain, trimmed at each call line, `/*CONSIDER THIS CALL*/`, macro comments | what the model is shown |
| `client/llm.py` | `OllamaClient`: OpenAI-compatible chat, tool-call loop, retries, token accounting, response validation | model plumbing, tool-loop behaviour |
| `tools/tools.py` | The tools the tracer model may call: `read_file_content`, `find_definition` | adding or changing a tool |
| `models.py` | Pydantic schemas: `Combined` (one CSV row), `Target`, `Src`, `Stats`, `TokenCount`, the LLM output models | the shape of an answer or a row |
| `helpers/dict_to_csv.py` | Flattens a `Combined` into the per-process CSV (append mode) | CSV columns/format |
| `state/state.py` | `State`, the process-wide singleton (`FUNCTION_TYPES`, `TREES`, `CALL_GRAPH`, `PROJECT_NAME`, …) | anything passed globally between stages |
| `state/load_data.py`, `process_groups.py` | Load `json_data/*.json` (targets, callbacks, function map); discover processes; write/read multi-process **group manifests** | target-config loading, grouping runs |
| `function_summaries.py` | Bottom-up function summaries: SCC layering, concurrency, llm-wiki enrichment, fingerprint cache | summary prompt/scheduling |
| `helpers/extract_functions_from_c.py` | libclang: function definitions and their line ranges | definition extraction |
| `helpers/time_it.py` | `@time_it` timing decorator | — |

**Config inputs** (`<project>/json_data/`): `mpf_data.json` = the targets
(which function, which argument indices, its type/launch); override per run with
`--targets`. `function_callback_info.json` = which parameters are callbacks.
`combined_data.json` / `pickle_data/function_map.pkl` = the known library API map.

## 4. The snapshot

| File | Handles | Edit when |
|---|---|---|
| `visualizer_export.py` | `VisualizerCollector` — builds `graph.json`: functions (with source, `library` tag, summaries), calls, resources, interactions, traces, embedded source files; `record_combined` / `rehydrate_interactions` turn CSV rows into resource evidence | **any new field the frontend or wiki needs**; bump `schema_version` when the shape changes |

Layout under the results root:

```
results/csv_results/
  <process>.csv                                  per-path answers (durable, resumable)
  stats/<process>_STATS.json                     tokens + which paths are done
  library_facts.json                             cached library answers + library roots
  graphs/<process>/<target>/…                    mermaid + pyvis
  visualizer/
    runs.json                                    index of every run
    groups.json, groups/<name>/runs/<id>/group.json
    <process>/function-summary-cache.json
    <process>/runs/<run_id>/graph.json           ← the snapshot everything reads
```

## 5. Frontend (`frontend/`)

`server.py` serves `dist/` plus `/api/runs`, `/api/graph`, `/api/groups`, and
(via `wiki/serve.py`) `/api/ask/stream`, `/api/wiki/status`.

### Data → view model (pure, no three.js)

| File | Handles | Edit when |
|---|---|---|
| `src/graph/model.js` | The heart of the view model. `indexSnapshot`, `buildProcessTree`, `isBoundary` (library edge), `collectUnreached`, `coverageSummary`, `attachInteractions` (incl. re-attributing library calls to the boundary), `deriveOverview` (processes, resources, **libraries**, one edge per pair, process aliasing), `directPlanePairs`, `ownCodeNodes`, `sharedSourceNodes` | what is drawn at all; how snapshots are joined |
| `src/graph/dag.js` | The DAG view: one node per function, longest-path depth, back-edge detection | DAG structure |
| `src/graph/layout.js` | All 2D maths: `layoutProcessTree` (d3 tidy tree), `layoutProcessDag` (layered + barycentre), `layoutUnreachedShelf`, `layoutOverview` (process ring, resource centroids, library outer ring) | spacing, positions, ring radii |
| `src/graph/prepare.js` | One call per open plane: picks tree/DAG, runs layout, builds `edges`, attachments, coverage | what a plane needs |
| `src/graph/textMetrics.js` | Label measurement shared by layout and rendering — so spacing and pixels cannot drift | font sizes, label padding |

### Scene (three.js)

| File | Handles | Edit when |
|---|---|---|
| `src/scene/SceneManager.js` | The whole 3D app: opening/closing planes, plane scale and arrangement, camera framing, picking, dragging, opacity/dimming, **cross-plane edges** (interaction, plane↔plane, shared source, library seam) | anything about how planes behave together |
| `src/scene/CanvasControls.js` | Camera: pan/zoom/rotate, canvas vs pivot mode, tilt limits, `distanceToFit` | camera feel |
| `src/scene/buildOverview.js` | The ground plane: process, resource and library nodes + their edges | ground-plane visuals |
| `src/scene/buildProcessPlane.js` | One process/library plane: nodes, boundary styling, call edges, unreached shelf, backdrop | plane visuals |
| `src/scene/graphLayer.js` | The addressable node/edge registry every layer shares: `addEdge`, `moveNode`, `refreshEdge`, opacity helpers, `EDGE_CATEGORIES` | edge geometry, per-category toggling |
| `src/scene/primitives.js` | Flat building blocks: discs, rings, edge curves, arrowheads, disposal | shapes and curves |
| `src/scene/icons.js` | Daemon-entity icons (file drum, queue slots, library stack) — see `frontend/ICONS.md` | adding an icon |
| `src/scene/labels.js` | Canvas-texture text meshes, plane-locked (never sprites) | label rendering |
| `src/scene/palette.js` | Every colour, with the contrast reasoning | colours |
| `src/scene/relaxation.js` | Elastic settling while dragging a node | drag feel |

### React

| File | Handles |
|---|---|
| `src/App.jsx` | Top-level state: run selection, snapshot loading, chat ↔ graph view switch |
| `src/components/GraphView.jsx` | Owns `SceneManager`; prepared-plane cache (keyed by process + mode + toggles), tree/DAG + never-called toggles, reveal-from-chat |
| `src/components/CanvasOverlay.jsx` | The floating controls: view-mode slider, edge toggles, run picker, legend |
| `src/components/Inspector.jsx` | Right rail: function / resource / process / library detail |
| `src/components/ChatPanel.jsx`, `Composer.jsx`, `ActivityLog.jsx`, `AnswerMarkdown.jsx`, `EvidenceRail.jsx` | The chat side: input, streaming activity, rendered answer, citations |
| `src/components/TopBar.jsx`, `ui.jsx` | Chrome and shared bits |
| `src/hooks/useAsk.js` | SSE lifecycle for a question: progress events, cancel, completion |
| `src/api.js` | Every `/api/*` call |
| `src/i18n.jsx` | JA/EN strings (JA is the default) — **every user-visible string is defined next to its component** |
| `src/index.css` | Tailwind v4 theme tokens (`bg-paper`, `text-ink`, `border-rule`, …) |

## 6. Wiki / chat (`wiki/`)

Reads snapshots, never writes them. Degrades to structural, no-LLM answers when
no model is configured.

| File | Handles |
|---|---|
| `corpus.py` | Loads a run selection into one cross-process corpus |
| `index.py` | Hybrid retrieval: BM25 + dense, fused, then reranked |
| `embed.py` | Embedding/rerank clients + endpoint discovery |
| `graphops.py` | Pure traversal over the corpus (callers, paths, resources) |
| `structural.py` | Answers structural questions with no model in the loop |
| `agent.py` | Lead + subagent research loop over the call graph |
| `present.py` | Builds the answer payload (citations, paths, resources) |
| `serve.py` | Routes a question and streams SSE; mixed into `frontend/server.py` |
| `labels.py` | Parses the tracer's path-label grammar |
| `config.py`, `http.py`, `llm.py` | Env/JSON config, JSON-over-HTTP, model client |

## 7. Tests (`tests/`)

`python -m unittest discover -s tests -q`

| File | Covers |
|---|---|
| `test_library_facts.py` | Library discovery, suffix cache, snapshot library tagging |
| `test_visualizer_export.py` | Collector: graph capture, CSV rehydration |
| `test_process_groups.py` | Run scanning, group manifests |
| `test_function_summaries.py` | SCC layering and scheduling |
| `test_wiki_graph.py` | The chat layer |
| `test_parser_paths.py` | Path context building — **has one known pre-existing failure** |
| `test_no_target_pipeline.py` | Full index-only run on a synthetic project |

`test_scada/` is the offline fixture: `processes/proc_*` (six processes),
`headers/`, `lib/`, and `json_data/` with the target config.

---

## Common edits, and where they start

| I want to… | Start in |
|---|---|
| trace a new API / change tracked argument indices | `json_data/mpf_data.json` (or `--targets`) |
| change what the tracer model is told | `project_aware.py` → `llm_calls` prompt; `parser/parser_files.py` for the context |
| add a column to the CSV | `models.py` (`Combined`) → `helpers/dict_to_csv.py` → `visualizer_export.py` |
| add a field the UI needs | `visualizer_export.py` → `src/graph/model.js` |
| change what a process plane draws | `src/graph/model.js` / `dag.js` → `src/graph/layout.js` → `src/scene/buildProcessPlane.js` |
| change the ground plane | `src/graph/model.js` (`deriveOverview`) → `layout.js` (`layoutOverview`) → `scene/buildOverview.js` |
| add an icon | `src/scene/icons.js` + `frontend/ICONS.md` |
| change camera behaviour | `src/scene/CanvasControls.js` |
| add a UI control | `src/components/CanvasOverlay.jsx` (+ strings in the same file's `STR`) → wire through `GraphView.jsx` |
| fix header resolution | `makefile_resolver/` |
| fix a missed call edge | `call_graph/call_graph.py` |
| make tracing cheaper | `library_facts.py` today, `walk_plan.md` next |
