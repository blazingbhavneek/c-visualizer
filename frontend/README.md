# Process visualizer

React + Vite + Tailwind + three.js. Reads immutable `graph.json` snapshots and
optional saved process-group manifests through the read-only API in `server.py`
(see `../handoff.md` for the schema).
The tracer continues to write its normal CSV, Mermaid, PyVis, stats and log
outputs; this UI reads only the snapshots:

```text
results/csv_results/visualizer/<process>/runs/<timestamp>/graph.json
```

## Running

```bash
# API + built bundle on one port
python frontend/server.py --port 8765     # then open http://127.0.0.1:8765

# pin the view to exact snapshots from one saved multi-process analysis
python frontend/server.py --group production-line --port 8765

# or, for development: vite on :5173, proxying /api to :8765
cd frontend && npm install && npm run dev
```

`npm run build` writes `dist/`, which `server.py` serves automatically when it
exists. Without a build, `server.py` falls back to serving this directory and
prints a note.

The default results directory is `results/csv_results/` in this repository when
the former `/home/seigyo/...` directory is unavailable. Override it with
`--results-root <dir containing visualizer/>` or `VISUALIZER_RESULTS_ROOT`.
`--group` accepts a group name (latest group run), `name@run-id`, or an explicit
`group.json` path. `/api/groups` lists the saved manifests.

## The layout model

The screen is a 3D canvas plus one inspector sidebar.

**Every graph in the scene is a flat 2D drawing.** The 3D is only *which plane a
drawing lives on*. Nothing is given depth inside its own plane, so a plane seen
edge-on collapses to a line — that is the decluttering mechanism, not a
rendering artifact. Labels are plane-locked meshes rather than sprites for
exactly this reason: a sprite would billboard toward the camera and defeat it.

- **Ground plane** — processes and daemon resources as one bipartite graph.
  The app's fixed frame of reference; laid out once with d3-force and frozen.
- **Process planes** — clicking a process raises a vertical plane anchored at
  that process's ground node, holding its full call tree with `main` at the
  anchor and leaves growing upward.
- **Cross-plane edges** — the only true 3D geometry. Cyan: a daemon API port on
  a tree down to its resource on the ground. Pink: a producer on one plane and a
  consumer on another that meet on the same resource.

Orientation: a plane opens facing wherever the camera is. Opening a second one
animates **both** to a single orientation taken from the current camera, so they
end up parallel and facing. At most two are open; a third evicts the oldest
(FIFO). The plane that is not focused fades so the other reads through it.

## The camera

`CanvasControls` replaces OrbitControls, because this is a graph, not a model —
free orbit is the wrong verb for it.

Exactly one plane is **the active canvas** at any moment, and the camera is
locked to it: drag pans parallel to that plane, the wheel dollies along its
normal, and screen-up is always the plane's up. Looking dead-on is the resting
state, so the active plane looks identical to the flat drawing it was laid out
as. With nothing open the ground plane is the canvas, which makes the opening
view an ordinary top-down 2D graph canvas.

Rotation is not free. Tilt (right-drag, or shift + drag) is clamped to ±24°
yaw / ±18° pitch — enough to see which edges leave the surface and where they
land, never enough to get lost behind or under the graph. "Look straight on"
resets it, and 75% of any tilt is shed when the active canvas changes so you
always arrive on a new plane essentially flat.

Expanding a process hands the plane to the same controls as the new canvas and
lets the camera glide there, so it reads as the canvas *moving onto* that plane
rather than as a camera flying around a scene. Closing a plane hands the canvas
back to the remaining plane, or down to the ground.

## Data notes that shape the UI

- **Coverage.** Only 51–74 of ~144–210 internal functions per process are
  reachable from `main`. The rest cannot be in a tree, so each plane carries an
  *unreached shelf* to the right, grouped by source file. The shelf separates
  two different facts: functions with recorded calls but no path from `main`
  (brighter), and functions with no recorded call at all (dimmer).
- **Tree, not DAG.** Functions reached by more than one path are duplicated.
  Parallel calls from the same parent to the same target are *not* duplicated —
  that clones whole subtrees for no new information (proc_waterworks: 127 nodes
  becomes 500, and 3.9k units wide becomes 19k). Every call site is preserved on
  the node and shown on the edge label and in the inspector.
- **Cross-process join.** No snapshot contains inter-process data. Resource IDs
  are per-snapshot hashes, so the overview joins on `(kind, name)`. 24 of 36
  distinct resources are touched by more than one process.
- **AI summaries.** New analyzer runs can populate bottom-up model summaries
  (`summary_status: ready`). Runs made without that pass remain `pending` or
  `library`; the inspector states the absence and falls back to `summary_hint`.
  The frontend itself has no LLM dependency.
- **Portable source.** New snapshots embed analyzed source files and exact
  function slices. `/api/source` prefers that evidence, so copied snapshots do
  not depend on absolute paths from the analysis PC. Older snapshots still use
  the filesystem fallback.
- **Run selection.** The newest run for five of six processes has zero
  resources and zero interactions. The interim default is *the newest run that
  has interaction evidence*; the Runs overlay allows overriding per process.

## Source map

| Path | Responsibility |
| --- | --- |
| `src/api.js` | The three read endpoints. |
| `src/graph/model.js` | Snapshot indexing, tree construction, overview derivation, operation polarity. |
| `src/graph/layout.js` | All 2D layout: tidy tree, unreached shelf, frozen force layout. |
| `src/graph/prepare.js` | Everything one plane needs, incl. the graph-roots fallback when `entry_function_id` is null. |
| `src/scene/SceneManager.js` | Camera, planes, orientation, FIFO, fade, picking, cross-plane edges. |
| `src/scene/buildOverview.js` | Ground plane geometry. |
| `src/scene/buildProcessPlane.js` | Process plane geometry. |
| `src/scene/primitives.js` | Flat discs, curves, arrowheads. |
| `src/scene/labels.js` | Plane-locked canvas-texture labels. |
| `src/components/Inspector.jsx` | The sidebar. |
| `src/components/CanvasOverlay.jsx` | Run picker, plane chips, legend. |

`window.__viz` exposes the `SceneManager` for console debugging; scene state is
otherwise unreachable from the DOM.
