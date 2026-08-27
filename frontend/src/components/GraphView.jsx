import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchLibrary, fetchProcess } from "../api.js";
import { indexSnapshot } from "../graph/model.js";
import { layoutOverview } from "../graph/layout.js";
import { prepareProcess } from "../graph/prepare.js";
import SceneManager from "../scene/SceneManager.js";
import CanvasOverlay from "./CanvasOverlay.jsx";
import Inspector from "./Inspector.jsx";

const PROCESS_SEP = "\u0000";

const runKeyOf = (processName, runId) => `${processName}${PROCESS_SEP}${runId}`;
const libraryKeyOf = (name) => `library${PROCESS_SEP}${name}`;

/**
 * Lazy graph view.
 *
 * The ground plane comes entirely from the server overview (one compact
 * request).  Clicking a process fetches exactly that process's structural
 * bundle; function details and source follow the same on-demand rule.  Bundles
 * live only while their plane is open: when SceneManager closes a plane
 * (explicitly or by FIFO eviction) the bundle, its prepared tree/DAG and any
 * pending request for it are released here.
 */
export default function GraphView({
  active,
  status,
  runs,
  selectedRuns,
  onSelectRun,
  overview,
  unsupported,
  revealTarget,
  onAskFunction,
}) {
  const containerRef = useRef(null);
  const sceneRef = useRef(null);
  const indexesRef = useRef(new Map()); // key -> indexSnapshot(bundle)
  const requestsRef = useRef(new Map()); // key -> {promise, controller}
  const preparedRef = useRef(new Map()); // `${key}|${mode}|${iso}` -> prepared plane
  const planeKeysRef = useRef(new Map()); // processName -> key of its loaded bundle
  const rebuildingRef = useRef(false);
  const [planeStates, setPlaneStates] = useState({}); // key -> {status, process, runId, error}
  const [openPlanes, setOpenPlanes] = useState([]);
  const [selection, setSelection] = useState(null);
  const [edgeVisibility, setEdgeVisibility] = useState({});
  const [hoverHighlight, setHoverHighlight] = useState(true);
  const [layoutMode, setLayoutMode] = useState("tree");
  const [showIsolated, setShowIsolated] = useState(false);

  // Normalize the wire overview for the scene: resourceAlias is a Map there.
  const sceneOverview = useMemo(() => {
    if (!overview) return null;
    return {
      processes: overview.processes,
      resources: overview.resources,
      edges: overview.edges,
      resourceAlias: new Map(Object.entries(overview.resource_aliases || {})),
    };
  }, [overview]);

  const overviewLayout = useMemo(
    () => (sceneOverview ? layoutOverview(sceneOverview) : null),
    [sceneOverview],
  );

  const processIndexById = useMemo(() => {
    const map = new Map();
    (sceneOverview?.processes || []).forEach((node, position) => map.set(node.name, position));
    return map;
  }, [sceneOverview]);

  const selectionKey = overview?.selection_key || null;

  const setPlaneState = useCallback((key, patch) => {
    setPlaneStates((previous) => ({ ...previous, [key]: { ...previous[key], ...patch } }));
  }, []);

  /** Function names that some already-loaded plane actually calls. */
  const sharedNames = useCallback(() => {
    const names = new Set();
    for (const index of indexesRef.current.values()) {
      for (const call of index.calls) {
        const source = index.functions.get(call.source);
        const target = index.functions.get(call.target);
        if (source) names.add(source.name);
        if (target) names.add(target.name);
      }
    }
    return names;
  }, []);

  const prepareForIndex = useCallback(
    (key, index) => {
      const cacheKey = `${key}|${layoutMode}|${showIsolated ? 1 : 0}`;
      const cached = preparedRef.current.get(cacheKey);
      if (cached) return cached;
      const prepared = prepareProcess(index, {
        mode: layoutMode,
        showIsolated,
        sharedNames: sharedNames(),
      });
      if (prepared) preparedRef.current.set(cacheKey, prepared);
      return prepared;
    },
    [layoutMode, showIsolated, sharedNames],
  );

  /** Fetch (or reuse) the structural bundle for one process/library plane. */
  const ensureBundle = useCallback(
    (name, { isLibrary = false, runId = null } = {}) => {
      const key = isLibrary ? libraryKeyOf(name) : runKeyOf(name, runId);
      const existingIndex = indexesRef.current.get(key);
      if (existingIndex) {
        return Promise.resolve({ key, index: existingIndex, controller: null });
      }
      const existing = requestsRef.current.get(key);
      if (existing) {
        return existing.promise.then((index) => ({ key, index, controller: existing.controller }));
      }
      const controller = new AbortController();
      const request = (isLibrary
        ? fetchLibrary(name, selectionKey, controller.signal)
        : fetchProcess(name, runId, controller.signal)
      )
        .then((bundle) => {
          const index = indexSnapshot(bundle);
          indexesRef.current.set(key, index);
          setPlaneState(key, { status: "ready", process: bundle.process, runId: bundle.process.run_id || runId });
          return index;
        })
        .catch((error) => {
          if (error.name !== "AbortError") {
            setPlaneState(key, { status: "error", error: error.message });
          }
          throw error;
        })
        .finally(() => {
          requestsRef.current.delete(key);
        });
      requestsRef.current.set(key, { promise: request, controller });
      return request.then((index) => ({ key, index, controller }));
    },
    [selectionKey, setPlaneState],
  );

  /** Synchronous release of everything belonging to one (process, run) plane. */
  const releaseKey = useCallback(
    (key) => {
      const pending = requestsRef.current.get(key);
      if (pending) {
        pending.controller.abort();
        requestsRef.current.delete(key);
      }
      indexesRef.current.delete(key);
      for (const cacheKey of [...preparedRef.current.keys()]) {
        if (cacheKey.startsWith(`${key}|`)) preparedRef.current.delete(cacheKey);
      }
      // The compact process header is kept (it is tiny) so the Inspector can
      // still describe the process; the bundle itself is gone.
      setPlaneStates((previous) => {
        if (!(key in previous)) return previous;
        const next = { ...previous };
        const kept = next[key];
        next[key] = kept.status === "ready" ? { status: "ready", process: kept.process, runId: kept.runId } : next[key];
        return next;
      });
      setSelection((current) => {
        const name = current?.processName || current?.process?.name;
        if (!name) return current;
        const mapped = planeKeysRef.current.get(name);
        const isSelectionsPlane =
          (mapped && mapped === key) || key === libraryKeyOf(name) || key.startsWith(`${name}${PROCESS_SEP}`);
        return isSelectionsPlane ? null : current;
      });
    },
    [setPlaneStates],
  );

  const releaseRef = useRef(releaseKey);
  useEffect(() => {
    releaseRef.current = releaseKey;
  }, [releaseKey]);

  const handleSelect = useCallback(
    (pick) => {
      if (!pick) {
        setSelection(null);
        return;
      }
      if (pick.type !== "process") {
        setSelection(pick);
        return;
      }
      setSelection(pick);
      const name = pick.process.name;
      const isLibrary = pick.process.type === "library";
      const runId = isLibrary ? null : selectedRuns.get(name);
      if (!isLibrary && !runId) return;
      const scene = sceneRef.current;
      if (scene?.planes.has(name)) return; // already raised
      const key = isLibrary ? libraryKeyOf(name) : runKeyOf(name, runId);
      planeKeysRef.current.set(name, key);
      setPlaneState(key, { status: "loading" });
      ensureBundle(name, { isLibrary, runId })
        .then(({ index, controller }) => {
          // A closed/evicted plane must not be repopulated by a late response.
          if (controller?.signal.aborted || planeKeysRef.current.get(name) !== key) return;
          const prepared = prepareForIndex(key, index);
          if (prepared && sceneRef.current) sceneRef.current.openProcess(prepared, processIndexById);
        })
        .catch(() => {});
    },
    [ensureBundle, prepareForIndex, processIndexById, selectedRuns, setPlaneState],
  );

  const handleSelectRef = useRef(handleSelect);
  useEffect(() => {
    handleSelectRef.current = handleSelect;
  }, [handleSelect]);

  useEffect(() => {
    if (!containerRef.current || sceneRef.current) return undefined;
    sceneRef.current = new SceneManager(containerRef.current, {
      onSelect: (pick) => handleSelectRef.current(pick),
      onPlanesChanged: (openNames) => {
        if (!rebuildingRef.current) {
          for (const [name, key] of [...planeKeysRef.current]) {
            if (!openNames.includes(name)) {
              planeKeysRef.current.delete(name);
              releaseRef.current(key);
            }
          }
        }
        setOpenPlanes(openNames);
      },
    });
    return () => {
      sceneRef.current?.dispose();
      sceneRef.current = null;
    };
  }, []);

  // Switching the plane shape rebuilds whatever is already raised from the
  // still-loaded bundles; the toggle acts on what the user is looking at.
  const rebuiltOnce = useRef(false);
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    if (!rebuiltOnce.current) {
      rebuiltOnce.current = true;
      return;
    }
    preparedRef.current.clear();
    const open = [...scene.planes.keys()];
    if (open.length === 0) return;
    rebuildingRef.current = true;
    try {
      for (const name of open) scene.closeProcess(name);
      for (const name of open) {
        const key = planeKeysRef.current.get(name);
        const index = key && indexesRef.current.get(key);
        if (!index) continue;
        const prepared = prepareForIndex(key, index);
        if (prepared) scene.openProcess(prepared, processIndexById);
      }
    } finally {
      rebuildingRef.current = false;
    }
  }, [layoutMode, showIsolated, prepareForIndex, processIndexById]);

  // A new overview means a new selection: release every plane and its bundle,
  // then raise the ground. Closed processes are refetched only on click.
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !sceneOverview || !overviewLayout) return;
    scene.collapseAll();
    scene.setOverview(sceneOverview, overviewLayout);
    scene.setHighlights({});
    setSelection(null);
    setPlaneStates((previous) => {
      const next = {};
      for (const [key, state] of Object.entries(previous)) {
        if (state.status === "ready") next[key] = { status: "ready", process: state.process, runId: state.runId };
      }
      return next;
    });
  }, [sceneOverview, overviewLayout]);

  // Chat citation reveal: fetch exactly the cited process's plane, then
  // highlight.  It must not force every process graph to load.
  useEffect(() => {
    const scene = sceneRef.current;
    const target = revealTarget;
    if (!scene || !target?.functionIds?.length || !sceneOverview) return undefined;
    const name = target.processName;
    const runId = name && selectedRuns.get(name);
    if (!name || !runId) return undefined;
    let cancelled = false;
    const key = runKeyOf(name, runId);
    ensureBundle(name, { runId })
      .then(({ index, controller }) => {
        if (cancelled || controller?.signal.aborted) return;
        if (!scene.planes.has(name) || scene.planes.size > 1) scene.collapseAll();
        if (!scene.planes.has(name)) {
          const prepared = prepareForIndex(key, index);
          if (!prepared) return;
          planeKeysRef.current.set(name, key);
          scene.openProcess(prepared, processIndexById);
        }
        scene.focusPlane(name);
        scene.setHighlights({
          answerIds: new Set(target.functionIds),
          answerEdgeKeys: new Set(target.edgeKeys || []),
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [revealTarget, sceneOverview, selectedRuns, ensureBundle, prepareForIndex, processIndexById]);

  // Inspector context for the currently selected element.
  const selectionContext = useMemo(() => {
    if (!selection) return null;
    const name = selection.processName || selection.process?.name;
    if (!name || !sceneOverview) return null;
    const isLibrary = sceneOverview.processes.find((node) => node.name === name)?.type === "library";
    const key = isLibrary ? libraryKeyOf(name) : runKeyOf(name, selectedRuns.get(name));
    const state = planeStates[key];
    return {
      name,
      isLibrary,
      node: sceneOverview.processes.find((node) => node.name === name) || null,
      state,
      index: indexesRef.current.get(key) || null,
      runId: state?.runId || (isLibrary ? null : selectedRuns.get(name) || null),
    };
  }, [selection, sceneOverview, selectedRuns, planeStates]);

  return (
    <div
      aria-hidden={!active}
      className={`absolute inset-0 flex bg-paper transition-opacity duration-150 ${
        active ? "z-10 opacity-100" : "pointer-events-none z-0 opacity-0"
      }`}
    >
      <div className="relative z-0 min-w-0 w-0 flex-1 overflow-hidden">
        <div ref={containerRef} className="absolute inset-0" />
        <CanvasOverlay
          status={status}
          runs={runs}
          selectedRuns={selectedRuns}
          onSelectRun={onSelectRun}
          openPlanes={openPlanes}
          unsupported={unsupported}
          onCollapseAll={() => {
            sceneRef.current?.collapseAll();
            setSelection(null);
          }}
          onFocusPlane={(processName) => sceneRef.current?.focusPlane(processName)}
          onClosePlane={(processName) => sceneRef.current?.closeProcess(processName)}
          onFrameOverview={() => sceneRef.current?.frameOverview()}
          onResetView={() => sceneRef.current?.resetView()}
          onResetLayout={() => sceneRef.current?.resetLayout()}
          onClearHighlights={() => sceneRef.current?.setHighlights({})}
          edgeVisibility={edgeVisibility}
          onToggleEdge={(category, visible) => {
            sceneRef.current?.setEdgeVisibility(category, visible);
            setEdgeVisibility((previous) => ({ ...previous, [category]: visible }));
          }}
          hoverHighlight={hoverHighlight}
          onToggleHoverHighlight={(enabled) => {
            sceneRef.current?.setHoverHighlight(enabled);
            setHoverHighlight(enabled);
          }}
          layoutMode={layoutMode}
          onChangeLayoutMode={setLayoutMode}
          showIsolated={showIsolated}
          onToggleIsolated={setShowIsolated}
        />
      </div>

      <Inspector selection={selection} processInfo={selectionContext} onAskFunction={onAskFunction} />
    </div>
  );
}
