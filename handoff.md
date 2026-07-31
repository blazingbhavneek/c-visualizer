# Frontend cleanup handoff

## Who this is for

You are being asked to **simplify and harden an existing frontend**, not to
rewrite it. It works and the owner is happy with its behaviour; the complaint is
about the code.

This document is written by the agent that built it, so treat the *opinions*
here with suspicion and the *facts* as checkable. Everything under
"Invariants" was learned by getting it wrong first — those are the parts most
likely to be silently broken by a well-intentioned refactor, and each one names
the symptom you'll see if you break it.

There are **no automated tests**. That is the single biggest weakness. Read
"Verification" before you change anything.

---

## What the app is

A viewer for **immutable static-analysis snapshots** of a C codebase: a
process's functions and calls, plus daemon-resource evidence inferred during
analysis. It does not parse C, does not run the pipeline, and must not scrape
the legacy CSV/Mermaid/PyVis outputs.

The visual model, which the owner cares about and which should survive:

> **Flat 2D drawings arranged in 3D.** Nothing is drawn with depth *inside* its
> own plane. The ground plane holds a process/daemon-resource overview.
> Expanding a process raises a vertical plane, anchored at that process's ground
> node, holding its full call tree. The only true 3D geometry is the edges that
> cross between planes. A plane seen edge-on collapses to a line — that is the
> decluttering mechanism, not an accident.

At most two process planes are open at once (FIFO). With two open they face each
other and the camera stands between them.

---

## Data contract

Unchanged and not yours to modify. `visualizer_export.py` owns it;
`project_aware.py` drives it.

```text
<results-root>/visualizer/<process_name>/runs/<run_id>/graph.json
```

`frontend/server.py` is a stdlib-only static server plus three read endpoints.
Run it with `--results-root <dir containing visualizer/>`, or set
`VISUALIZER_RESULTS_ROOT`. It serves `frontend/dist` when that exists.

| Endpoint | Returns |
| --- | --- |
| `GET /api/runs` | `{ results_root, runs: [{ process_name, run_id, generated_at, function_count, resource_count, interaction_count }] }` |
| `GET /api/graph?process=&run=` | the snapshot verbatim; 404 `{error}` if absent |
| `GET /api/source?process=&run=&function=` | `{ file, start_line, end_line, text }`; 404 external/missing, 403 outside `process.root` |

`graph.json` (schema_version 1). All six collections are always arrays, any may
be empty. Ignore unknown fields.

```ts
interface GraphSnapshot {
  schema_version: 1;
  generated_at: string;
  run_id: string;
  process: { id; name; root; main_file: string | null; entry_function_id: string | null };
  functions: FunctionNode[];
  calls: CallEdge[];
  resources: Resource[];
  interactions: Interaction[];
  traces: Trace[];
}

interface FunctionNode {
  id; kind: "function" | "external_function"; name;
  file: string | null; file_name: string | null;
  start_line: number;      // -1 when unknown
  end_line: number;
  is_external: boolean; is_static: boolean;
  summary_status: "pending" | "library";
  summary: string | null;  // currently null in every snapshot
  call_count: number; resource_interaction_count: number;
  summary_hint?: string;
}

interface CallEdge {
  id; source; target;      // FunctionNode.id
  line: number | null;     // call site, not definition
  kind: "direct" | "indirect" | "external_call" | "macro_call" | "macro_expansion" | "callback";
  via: string | null;      // registrar, for callbacks
}

interface Resource { id; kind: "file"|"queue"|"event"|"semaphore"|"process"|"message"|"daemon_resource"; name; resolved: boolean }

interface Interaction {
  id; function_id: string | null;   // null = unattributed, show it anyway
  resource_id; target_api; operation; launch_via: string | null;
  call_number; argument_binding: { argument_index: number; value };
  path: string | null; source; function_source;
}

interface Trace { id; target_api; labels: string[]; display_path: string }
```

**Facts about the real data that the UI is shaped around.** Re-derive these if
you doubt them; they are all measurable from `results/csv_results/visualizer/`.

- `id`, never `name`, is function identity. Names repeat across files.
- **Only 51–74 of ~144–210 internal functions per process are reachable from
  `main`.** The rest cannot appear in a tree. Two distinct reasons: some have
  recorded calls but no path from `main`; some have no recorded call at all.
  The UI distinguishes these.
- **`summary` is `null` for all 4355 functions in every snapshot.** The AI panel
  is therefore an empty state in practice. Keep it honest — do not fake content.
- **No snapshot contains inter-process data.** The overview is derived by joining
  snapshots on `(resource.kind, resource.name)`; resource `id`s are per-snapshot
  hashes and cannot be used. 24 of 36 distinct resources are shared by 2+
  processes.
- **The newest run for 5 of 6 processes has zero resources and zero
  interactions.** Picking "latest per process" naively renders an overview with
  no daemon edges. See open TODO #2.
- Multiple calls between the same pair are distinct records; do not silently
  deduplicate them.

---

## Current architecture

4485 lines across `frontend/src`. Stack: React 19 + Vite + Tailwind v4 +
three.js, plus `d3-hierarchy` and `d3-force` used only as layout maths.

```
src/
  api.js                     31   three fetch wrappers
  App.jsx                   228   data loading, run selection, scene lifecycle
  components/
    CanvasOverlay.jsx       240   run picker, plane chips, edge toggles, legend
    Inspector.jsx           371   right sidebar; all evidence for a selection
  graph/                          PURE — no three.js, runs headless
    model.js                367   snapshot indexing, tree building, overview derivation
    layout.js               263   tidy tree, unreached shelf, overview affinity layout
    prepare.js               94   everything one plane needs, computed once
    textMetrics.js           67   label geometry; single source of truth
  scene/                          three.js
    SceneManager.js         972   << the problem
    CanvasControls.js       532   << the other problem
    graphLayer.js           221   node/edge registry shared by both builders
    relaxation.js           315   elastic drag physics
    buildProcessPlane.js    274   one process plane's geometry
    buildOverview.js        155   ground plane geometry
    primitives.js           169   discs, rings, edge curves, arrowheads
    labels.js                90   canvas-texture text meshes
    palette.js               86   colours
```

**The `graph/` boundary is good and worth keeping.** It is pure, has no three.js
import, and runs under plain `node`. That is what makes layout testable.

**`scene/` is where the mess is.**

### Key concepts

- **Layer** — one flat drawing: `{ group, pickables, registry, labels }`. Both
  the ground and each process plane are layers.
- **Registry** (`graphLayer.js`) — `nodes: Map(id -> {mesh, parts[], local, radius,
  clearance, home})` and `edges[]` with `edgesByNode`. This is what makes
  dragging, toggling, fading and hover possible; a bare `THREE.Group` cannot
  answer "which edges touch this node".
- **Canvas** — the plane the camera is currently locked to. `CanvasControls` has
  two modes: `canvas` (locked to one plane) and `pivot` (standing between two).

---

## Invariants

Break these and the app regresses in ways that are hard to spot. Each was a real
bug.

1. **Edge geometry must be a constant vertex count.**
   `BufferGeometry.setFromPoints` only overwrites `min(points, capacity)`
   vertices and *never shrinks*. Variable-length point arrays leave stale
   vertices behind and the line draws a segment back to where the node used to
   be. `edgePoints()` always returns `segments + 1` points and trims by the
   curve's *parameter range*, not by dropping points. **Symptom if broken:**
   torn, jumpy edges while dragging.

2. **Spacing must account for label width, not node radius.** A dot is 22 units
   across; `compute_3element_feedwater_setpoint` renders over 300. Tree
   separation and overview collision both measure through
   `graph/textMetrics.js`, which is deliberately shared with the renderer so the
   two cannot drift. **Symptom:** every tier collides into an unreadable smear.

3. **Gesture directions are measured, not derived.** They were repeatedly got
   wrong by reasoning. The rules that hold:
   - *Panning* — content follows the pointer exactly. Must use the **camera's**
     screen axes projected onto the plane, not the plane's fixed `right`, or it
     inverts once the view passes 90°.
   - *Rotating* — judged by **which face comes into view**, which is the opposite
     sign: drag right reveals the tree's left, drag down reveals its top.
   - The two modes legitimately use different signs, because one orbits the
     camera and the other turns it in place.

4. **The camera never goes below the ground plane.** From beneath, the overview
   reads mirrored and the whole scene looks inverted. Positive pitch *lowers*
   the camera (`camera.y = target.y - sin(pitch) * distance`), so the guard is a
   *ceiling* on pitch, recomputed per frame because it tightens as you zoom in.
   Pivot mode floors the viewer's height instead. Going over the top is
   unrestricted, and so is yaw.

5. **Rotation resists, it never fences.** Turning away is progressively heavier
   with a floor on the resistance so continued dragging always makes progress;
   turning back is assisted. Nothing recentres on its own — where the user lets
   go is where the camera stays. Every hard limit that has ever been added here
   was later reported as a bug.

6. **Drag influence falls off by hop distance.** Immediate neighbours follow;
   rings beyond that are anchored to where they sat when the drag began, via a
   *hard positional clamp*. Stiff anchor springs were tried and are numerically
   unstable under explicit integration — that caused visible flicker. On
   release, every node re-anchors to its current position, or the anchored
   majority springs the dragged cluster back and the drag leaves no trace.

7. **Simulation energy is measured from distance actually travelled**, not from
   velocity. A node held against its clamp keeps velocity forever, so a
   velocity-based test never settles and the sim runs every frame for the rest
   of the session. Settling also waits for zero penetration, so it cannot stop
   while marks overlap.

8. **Edge labels are hidden by default** and appear only for edges highlighted by
   hover. Always-on they are the messiest thing on either plane.

9. **In process view, daemon-link edges start OFF.** The tree is the subject; the
   user opts in to seeing which function touches which resource.

10. **`schema_version !== 1` is an explicit unsupported state.** Do not attempt
    to render it.

---

## Where the complexity actually is

Ranked by how much pain they cause. This is the part you were brought in for.

### 1. `SceneManager.js` is a god object (972 lines, 38 methods)

It owns: scene/renderer lifecycle, the layer registry, camera framing, plane
open/close/FIFO, the two-plane arrangement, cross-plane edge construction,
picking, node dragging, the drag→physics handoff, opacity/visibility resolution,
label LOD, selection rings, and the frame loop.

Natural seams, roughly in order of payoff:

- **`PlaneSet`** — open/close/FIFO, arrangement, anchoring, framing.
- **`CrossPlaneEdges`** — build/update the world-space edges.
- **`Presentation`** — everything that decides an object's opacity/visibility.
- **`Interaction`** — pointer → pick/drag/hover.
- What remains is a thin scene + frame loop.

### 2. Visibility and opacity are decided in three places that fight

`_applyStyling` (hover + category + recede), `_updateLabelVisibility` (distance
LOD), and the initial `visible = false` in `graphLayer.addEdge`. `.visible` is
assigned from 9 sites. There is no single function that answers "should this
object be visible right now", so ordering bugs are easy and have happened.

**Suggested direction:** one pure resolver, `resolve(object, state) -> {visible,
opacity}`, driven by a small explicit state object (activeCanvas, focusedPlane,
hoveredNode, edgeVisibility, cameraDistance). Everything else calls it.

### 3. Positions are represented twice

`registry.nodes[].local` (authoritative, drives meshes) and the relaxation's own
`entry.x/y`. They are hand-synced at the top of `relaxStep` and again when
writing back. `moveNode()` and the inline mesh-moving loop inside `relaxStep`
duplicate the same logic for performance reasons that were never measured.

**Suggested direction:** make the registry the only owner of position, and give
the simulation a narrow read/write interface over it. Measure before assuming
the duplication is needed.

### 4. Cross-plane edges are rebuilt from scratch every frame

While dragging or animating, `_rebuildCrossPlaneEdges()` disposes and recreates
every world-space line. In-plane edges update their buffers in place
(`refreshEdge`); these do not. It is inconsistent and churns GC on exactly the
frames that need to be smooth.

### 5. `_rebuildOverview()` destroys and rebuilds the entire ground layer

...to change a handful of colours when a process expands, then replays saved
positions on top. It is wasteful and a plausible source of subtle state loss
(anything held on the old objects is gone). Expansion state should be a style
input, not a reason to rebuild geometry.

### 6. `CanvasControls.js` (532 lines) has two modes with parallel gesture paths

Four near-duplicate constants (`YAW_SCALE`, `PITCH_SCALE`,
`PIVOT_PITCH_SCALE`, `PIVOT_LOOK_SCALE`) and two resistance helpers
(`resistedRotation`, `_resistedLook`) that differ only in where "rest" is.
The sign conventions live inline in event handlers, which is exactly why they
were wrong so often.

**Suggested direction:** extract the sign/resistance maths into a pure module
with unit tests, and express the two modes as data (a frame + a set of enabled
gestures) rather than branches.

### 7. Small things

- Dead exports: `getLabelTexture`, `disposeLabelCache`, `RESOURCE_COLORS`,
  `PROCESS_COLORS`, `FONT_STACK`.
- `graphLayer.addEdge` takes a 14-key options object.
- `localPosition()` is a trivial `new Vector3` wrapper.
- `window.__viz` is a debug global; it is genuinely useful for driving the scene
  from a test harness, so keep it but make it deliberate.
- `layout.js` mixes three unrelated layouts (tree, shelf, overview affinity).
- `relaxation.js` collision is O(n²) per frame over up to ~300 nodes. Fine today,
  measured at well under a millisecond, but it is the first thing to bite if
  planes get bigger.

---

## Verification

**There are no tests.** Everything so far was checked with throwaway Playwright
scripts that were not kept. Do not trust "it builds" — every regression in this
project's history built cleanly.

The highest-value thing you can do alongside the cleanup is leave tests behind.

**Cheap and worth it (pure, no browser):** `graph/` runs under plain `node`.
Assert on real snapshots from `results/csv_results/visualizer/`:

- tree node counts and depth per process (63–120 nodes, depth 5–8)
- coverage: tree ∪ shelf = every internal function, exactly once, no overlap
- **zero overlapping bounding boxes** among node dots and label boxes, in both
  the tree and the overview layouts
- overview join produces the expected shared-resource count (24 of 36)

**Worth the setup (browser):** `window.__viz` exposes the `SceneManager`, so a
Playwright script can drive gestures and assert on scene state rather than
pixels. The checks that caught real bugs:

- every edge line has an identical vertex count, and no vertex sits far off the
  curve (catches invariant 1)
- drag a node, measure displacement bucketed by hop distance (catches 6)
- assert simulation energy reaches zero and stays (catches 7)
- for each gesture, measure whether on-screen content moves with the pointer, at
  several camera angles including past 90° (catches 3)
- camera `y` never drops below the floor during aggressive rotation (catches 4)

**Manual:** the owner tests by hand and gives direct feedback. Behaviour changes
they have not asked for will be noticed.

---

## Deliberately not done

Not bugs. Do not "fix" them without asking.

- **Node duplication in the tree.** Functions reached by multiple paths are
  duplicated so the tree is a real tree. Parallel calls from the same parent to
  the same target are *not* duplicated (that clones whole subtrees: 127 nodes →
  500, 3.9k units wide → 19k). Every call site is preserved on the node.
- **The unreached shelf.** Deliberate honesty about the ~60% of functions that
  cannot be in the tree.
- **Free camera movement.** The only limit is the ground plane. You can walk
  behind a tree and see it mirrored; "Reset view" is the escape hatch. This was
  requested explicitly after several rounds of the opposite.
- **No layout persistence.** Dragged positions live in memory only; "Reset
  layout" restores the computed layout.

### Open TODOs

1. **Alternate cross-plane edge origin.** Interaction edges currently leave the
   green external-API leaf. The alternate is to leave the internal calling
   function (`interactions[].function_id`) and skip the leaf. Wanted as a toggle.
2. **Run-selection policy.** Interim rule is "newest run that has interaction
   evidence", because the newest run alone is empty for most processes. Needs a
   real decision.
3. **Light-theme completeness.** The scene and UI were re-themed for white; the
   palette reasoning and its validator output are recorded in
   `scene/palette.js`. Two residual notes: an aggressive drag can leave ~1
   overlapping label pair (the relaxation models clearance as a circle centred
   on the node, but labels are wide rectangles offset below it), and cross-plane
   edges dim uniformly on hover instead of participating in the highlight.

---

## Running it

```bash
python frontend/server.py --port 8765     # API + built bundle
cd frontend && npm install && npm run dev # vite on :5173, proxies /api to :8765
npm run build                             # writes dist/, which server.py serves
```

`results/` is gitignored, so a fresh clone has no snapshots until the pipeline
runs. `frontend/README.md` describes the layout model and the camera in more
detail and should be updated if you change either.
