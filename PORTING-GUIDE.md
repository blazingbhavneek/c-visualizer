# Porting from codegraph's frontend into this one

A guide for an agent bringing UI work from `/mnt/common/Code/codegraph/frontend`
back into `/mnt/common/Code/c-repo/frontend`.

**Read this whole file before touching anything.** The two frontends share a
common ancestor — this one — so most of what looks new over there is additive,
but a few things are subtly incompatible and will silently break if ported
verbatim.

---

## 1. The single most important fact

**The 3D scene is already identical in both repos.** 12 of the 13 files under
`frontend/src/scene/` and `frontend/src/graph/` in codegraph are *byte-for-byte*
copies of this repo's (verified with `diff -q`):

```
scene/  buildOverview.js  buildProcessPlane.js  CanvasControls.js  graphLayer.js
        labels.js  palette.js  primitives.js  relaxation.js
graph/  layout.js  model.js  prepare.js  textMetrics.js

scene/  SceneManager.js   <- the ONLY divergence: +40 lines, see below
```

Verify before assuming otherwise:

```bash
for f in scene/*.js graph/*.js; do
  diff -q "/mnt/common/Code/c-repo/frontend/src/$f" \
          "/mnt/common/Code/codegraph/frontend/src/$f" >/dev/null \
    && echo "SAME     $f" || echo "DIVERGED $f"
done
```

That one divergence is **+40 lines**, all additive and all marked with
`CODEGRAPH ADDITION` comments (4 of them — `grep -c` to confirm before porting,
in case it has drifted since this was written):

- `setHighlights({ answerIds, openIds })` — sets two Sets, flags `stylingDirty`.
- One block in `_applyStyling()` multiplying node opacity by `CITATION_DIM`
  (0.35) for nodes *not* in `answerIds`.
- The `CITATION_DIM` constant.

Nothing else in the camera, physics, layout or input path differs. **Do not
"port the 3D scene".** If you want citation highlighting here, port only those
three marked additions.

> History worth knowing: codegraph's scene was originally rewritten rather than
> copied, and the result had visibly wrong camera behaviour. It was then
> replaced wholesale with this repo's files. Treat this repo as the source of
> truth for anything spatial.

---

## 2. What actually differs, and what it costs to port

| Feature | codegraph file(s) | Portable? |
|---|---|---|
| Chat UI (activity log, markdown answers, citations) | `components/ChatPanel.jsx` (413) | Needs a backend — see §5 |
| App shell (left sidebar / top bar / right rail) | `App.jsx` (401), `LeftSidebar.jsx`, `TopBar.jsx`, `AppFooter.jsx` | Yes, but it *replaces* this repo's layout |
| Tabbed right rail + inspectors | `components/RightRail.jsx` (926) | Yes — largest single win |
| Sources panel ("files/functions behind the answer") | `RightRail.jsx` → `SourcesList` | Only meaningful with chat |
| Reveal-in-graph | `App.jsx` `revealFunction`, `GraphView.jsx` reveal effect | **Yes — cheapest high-value port** |
| Settings page | `components/SettingsView.jsx` (501), `hooks/useConfig.js`, `hooks/useCookies.js` | Yes, needs a config API |
| i18n (en/ja) | `i18n.jsx` (116) | Yes, self-contained |
| Dark theme | `i18n.jsx` `useResolvedTheme` + `index.css` | Yes, self-contained |
| Search | `hooks/useSearch.js` (49) | Yes |
| Data loading | `hooks/useGraphData.js` (203) | **No** — see §4, runs vs no runs |
| Offline single-file build | `vite.config.js` + `vite-plugin-singlefile` | Yes |

### Dependency delta

This repo:

```json
{ "d3-force", "d3-hierarchy", "react": "^19.2.0", "react-dom", "three": "^0.181.0" }
```

codegraph adds: `lucide-react` (icons — used *everywhere* in its components),
`react-markdown` + `remark-gfm` (chat answers), `mermaid` (declared, lazily
imported, currently unused). Dev: `vite-plugin-singlefile`.

Note **three 0.181 here vs 0.170 there**. The scene files are identical and work
on both, but if you port anything touching three.js internals, test on 0.181.

---

## 3. Recommended porting order

Ordered by value-per-risk. Each step is independently shippable.

1. **`lucide-react` + icons.** Prerequisite for nearly every component below.
2. **Reveal-in-graph** (§6). Small, self-contained, works with this repo's
   existing data. Highest value for the effort.
3. **Tabbed right rail.** Replaces `Inspector.jsx` (371 lines) with
   `RightRail.jsx` (926) — navigator + one closable tab per opened
   function/resource. Strictly more capable; the panels inside are close
   relatives of this repo's `FunctionPanel`/`ResourcePanel`/`ProcessPanel`.
4. **i18n + dark theme.** Self-contained; no data dependencies.
5. **App shell.** Only if you want the sidebar layout. This is a rewrite of
   `App.jsx`, so do it after the pieces it hosts already exist.
6. **Chat + Sources.** Requires the backend in §5. Do last.

---

## 4. The incompatibility that will bite you: runs

**This repo has timestamped tracer runs. codegraph does not.**

- Here: `server.py` serves
  `results/csv_results/visualizer/<process>/runs/<timestamp>/graph.json`, and
  `App.jsx` has `chooseRuns()` plus a Runs overlay in `CanvasOverlay.jsx`.
- There: one current index. The run picker was **deleted**, replaced by an
  index-freshness badge (`GraphView.jsx` → `formatFreshness`).

So `hooks/useGraphData.js` is **not portable as-is** — it has no concept of runs
and will drop your run selection entirely. Port its *shape* (load all processes
in parallel with `Promise.allSettled`, build `functionsById` /
`processIdByFunctionId` / `resourceByKindName` / `mergedSnapshot` across every
snapshot) but keep this repo's run-aware fetching underneath.

### Schema deltas (additive, safe to ignore)

codegraph emits the same `graph.json` **schema v1** documented in `handoff.md`,
plus:

- `summary_status` gains a third value **`"ready"`** (summary is populated).
  Here it is only ever `pending`/`library`, since `summary` is `null` for all
  4355 functions. Any ported code must handle all three.
- New optional `FunctionNode` fields: `wiki_key`, `contract {params, returns,
  effects}`, `stale`. Absent here — guard with `?.`.
- `resources`/`interactions` may be **empty** there (daemon pass not run). Here
  they are usually populated. Ported components must not assume non-empty.

### Reachability means something different

Here, the call tree comes from *traced runtime* calls, and the unreached shelf
splits "has recorded calls but no path from `main`" vs "no recorded call at
all". codegraph's comes from a *static* call graph and redefines the split as
"has callers but not from `main`" vs "no callers at all". If you port shelf
code, keep **this** repo's definition — it matches this repo's data.

---

## 5. Chat requires a backend that does not exist here

`ChatPanel.jsx` is only a renderer. Behind it in codegraph:

- `src/wiki/chat.ts` — structural queries answered by **pure graph traversal,
  no LLM** ("what calls X", "what writes to Q_ALARM_LO", "how does X reach Y").
- `src/wiki/agent.ts` — multi-agent research: a **lead** that coordinates and
  never reads code (`search`/`explore`/`finish`), and **subagents** that each
  start at one function and actually read source, follow call chains, and report
  (`read`/`follow_link`/`finish`).
- `src/wiki/serve.ts` — `POST /api/ask/stream`, SSE.

`server.py` here is read-only and has no equivalent. Porting chat means either
running codegraph's `wiki serve` alongside, or reimplementing the endpoint in
Python.

### SSE event contract (if you do implement it)

Split into two groups, which matters when you wire it up:

```
progress  (ChatPanel.jsx activityLine -> one log line each):
  search  candidates  route  read  follow_link
  subagents_spawned  subagent_start  subagent_done  compiling

lifecycle (handled by the stream consumer in App.jsx, NOT activityLine):
  run  answer  error  cancelled
```

`activityLine()` returns `null` for anything it does not recognise, so an
unknown event is ignored rather than rendered blank.

`answer` carries `{ text, cited: string[] }` where `cited` are **function ids**.
That array is what drives both the Sources panel and the graph highlight.

Two hard-won details worth copying if you write your own agent loop:

- **Never hand a model a raw node id.** They come back mangled (prefix stripped,
  hash truncated). codegraph gives out short handles `F1`, `F2`, … and maps them
  back server-side (`agent.ts` `Handles`). It also strips any handle that leaks
  into prose (`stripHandles`).
- **Force the finish tool on the last step.** A lead that keeps searching gets
  cut off and all its reading is discarded. `tool_choice: {type:'function',
  function:{name:'finish'}}` on the final turn.

---

## 6. Reveal-in-graph — the recommended first port

"Click a function name in a list → go to the graph, raise its process plane,
highlight it." Works with this repo's data as-is. Three pieces:

**(a) `SceneManager.setHighlights`** — port the `CODEGRAPH ADDITION` blocks
described in §1.

**(b) A functionId → processName map.** In codegraph this lives in
`GraphView.jsx`:

```js
const processByFunctionId = useMemo(() => {
  const map = new Map();
  for (const index of indexes) {
    for (const id of index.functions.keys()) map.set(id, index.process.name);
  }
  return map;
}, [indexes]);
```

`indexSnapshot()` already keys `functions` by id in both repos, so this works
here unchanged. (Measured on codegraph's fixture: 1083 entries across 6
processes.)

**(c) The reveal effect**, keyed on a **nonce** so asking for the same function
twice re-fires — the user may have panned away since:

```js
useEffect(() => {
  const scene = sceneRef.current;
  const id = revealTarget?.functionId;
  if (!scene || !id) return;

  const processName = processByFunctionId.get(id);
  const prepared = processName && preparedByProcess.get(processName);
  if (!prepared) return;                    // unknown id = clean no-op

  scene.resetView();                        // land from a known camera state
  if (!scene.planes.has(processName)) scene.openProcess(prepared, processIndexById);
  scene.focusPlane(processName);
  scene.setHighlights({ answerIds: new Set([id]), openIds });
}, [revealTarget, /* … */]);
```

Caller side (`App.jsx`):

```js
const revealFunction = useCallback((functionId) => {
  if (!functionId) return;
  setCenterView('graph');
  setRevealTarget({ functionId, nonce: Date.now() });
}, []);
```

This repo has no `centerView` (the canvas is always visible), so drop that line
and keep the rest.

---

## 7. Things to avoid repeating

Real bugs hit during codegraph's build. Cheaper to read than rediscover.

- **`esbuild --bundle` does not catch undefined variables.** A bare `snapshot`
  identifier is valid *syntax*; it bundled clean at 218 KB while being fatally
  broken at runtime. Use ESLint `no-undef` on JS/JSX:

  ```bash
  npx eslint --config <flat-config> src   # rules: { "no-undef": "error" }
  ```

- **react-markdown v10 removed the `inline` prop.** The common
  `code: ({inline}) => inline ? … : …` pattern is now *always* truthy, so fenced
  blocks get inline pill styling inside their own `<pre>`. Decide it in CSS
  instead (`.answer code` vs `.answer pre code` — specificity wins).

- **Check the pick payload shape.** `buildOverview.js` emits
  `{ type: "process", process }` and `{ type: "resource", resource }`;
  `buildProcessPlane.js` emits `{ type: "function", node, processName }`. Reading
  `pick.node.name` for a process silently does nothing. Cross-check every
  handler against the emitters:

  ```bash
  grep -n "userData.pick = " src/scene/*.js
  ```

- **Set vs array at component boundaries.** codegraph passes `answerIds` as an
  array from `App.jsx` while `GraphView` documents `Set`. It happens to work
  (only iterated and re-wrapped with `new Set(...)`) — but don't rely on it;
  pick one and state it.

---

## 8. Concrete file map

```
codegraph/frontend/src/
  App.jsx              401  shell, chat transport, reveal, tab state
  api.js               239  /api/{index,graph,source,note,config,ask/stream}
  i18n.jsx             116  useT(dict), LangProvider, LangToggle, useResolvedTheme
  index.css                 Tailwind v4 + .cg-answer markdown styling
  components/
    ChatPanel.jsx      413  activity log, markdown Answer, citation chips
    RightRail.jsx      926  tabs; Navigator(Processes|Resources|Sources),
                            FunctionInspector, ResourceInspector, SourcesList
    GraphView.jsx      474  SceneManager lifecycle, reveal, lit path, overlays
    SettingsView.jsx   501  cookie > project > default, per-field reset
    LeftSidebar.jsx    213  Chat/Graph/Settings + Processes/Resources nav
    TopBar.jsx         156  search + right-rail toggle
    AppFooter.jsx       45
    ErrorBoundary.jsx   55
    Centered.jsx        14
  hooks/
    useGraphData.js    203  ⚠️ no runs — see §4
    useConfig.js       295  config layers
    useCookies.js      153  cookie state
    useSearch.js        49
```

`c-repo/frontend/src/` for comparison: `App.jsx` (228),
`components/CanvasOverlay.jsx` (240), `components/Inspector.jsx` (371).

---

## 9. Verifying a port

```bash
# 1. Undefined identifiers (bundling will NOT catch these)
npx eslint --config <flat-config> src

# 2. Whole module graph resolves
npx esbuild src/main.jsx --bundle --outdir=/tmp/check --format=esm \
  --loader:.js=jsx --external:tailwindcss

# 3. Scene still matches this repo's canonical version
for f in scene/*.js graph/*.js; do diff -q "src/$f" "<other>/src/$f"; done

# 4. In the browser: API up first, then the UI
python frontend/server.py --port 8765     # this repo's API
cd frontend && npm run dev                # proxies /api to 8765
```

A 500 from `/api/*` in the dev server almost always means `server.py` is not
running — Vite's proxy returns 500 on connection refused, which looks like an
app error but is not.
