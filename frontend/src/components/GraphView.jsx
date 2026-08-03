import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { deriveOverview } from "../graph/model.js";
import { layoutOverview } from "../graph/layout.js";
import { prepareProcess } from "../graph/prepare.js";
import SceneManager from "../scene/SceneManager.js";
import CanvasOverlay from "./CanvasOverlay.jsx";
import Inspector from "./Inspector.jsx";

export default function GraphView({
  active,
  status,
  runs,
  selectedRuns,
  onSelectRun,
  indexes,
  unsupported,
  revealTarget,
  onAskFunction,
}) {
  const containerRef = useRef(null);
  const sceneRef = useRef(null);
  const preparedCache = useRef(new Map());
  const [openPlanes, setOpenPlanes] = useState([]);
  const [selection, setSelection] = useState(null);
  const [edgeVisibility, setEdgeVisibility] = useState({});
  const [hoverHighlight, setHoverHighlight] = useState(true);
  const [layoutMode, setLayoutMode] = useState("tree");
  const [showIsolated, setShowIsolated] = useState(false);

  const overview = useMemo(() => (indexes.length ? deriveOverview(indexes) : null), [indexes]);
  const overviewLayout = useMemo(() => (overview ? layoutOverview(overview) : null), [overview]);
  const processIndexById = useMemo(() => {
    const map = new Map();
    indexes.forEach((index, position) => map.set(index.process.name, position));
    return map;
  }, [indexes]);
  const processByFunctionId = useMemo(() => {
    const map = new Map();
    for (const index of indexes) {
      for (const id of index.functions.keys()) map.set(id, index.process.name);
    }
    return map;
  }, [indexes]);

  /**
   * Function names that some loaded process actually calls. A never-called
   * function is hidden on its own plane, but reappears once another open
   * process turns out to use that name.
   */
  const sharedNames = useMemo(() => {
    const names = new Set();
    for (const index of indexes) {
      for (const call of index.calls) {
        const source = index.functions.get(call.source);
        const target = index.functions.get(call.target);
        if (source) names.add(source.name);
        if (target) names.add(target.name);
      }
    }
    return names;
  }, [indexes]);

  const preparedFor = useCallback(
    (processName) => {
      if (!processName) return null;
      const key = `${processName}|${layoutMode}|${showIsolated ? 1 : 0}`;
      if (!preparedCache.current.has(key)) {
        const index = indexes.find((entry) => entry.process.name === processName);
        if (!index) return null;
        preparedCache.current.set(
          key,
          prepareProcess(index, { mode: layoutMode, showIsolated, sharedNames }),
        );
      }
      return preparedCache.current.get(key);
    },
    [indexes, layoutMode, showIsolated, sharedNames],
  );

  const handleSelect = useCallback(
    (pick) => {
      if (!pick) {
        setSelection(null);
        return;
      }
      if (pick.type === "process") {
        const prepared = preparedFor(pick.process.name);
        if (prepared) sceneRef.current?.openProcess(prepared, processIndexById);
      }
      setSelection(pick);
    },
    [preparedFor, processIndexById],
  );

  const handleSelectRef = useRef(handleSelect);
  useEffect(() => {
    handleSelectRef.current = handleSelect;
  }, [handleSelect]);

  useEffect(() => {
    if (!containerRef.current || sceneRef.current) return undefined;
    sceneRef.current = new SceneManager(containerRef.current, {
      onSelect: (pick) => handleSelectRef.current(pick),
      onPlanesChanged: setOpenPlanes,
    });
    setEdgeVisibility({ ...sceneRef.current.edgeVisibility });
    return () => {
      sceneRef.current?.dispose();
      sceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    preparedCache.current.clear();
  }, [indexes]);

  // Switching the plane shape (or revealing never-called functions) rebuilds
  // whatever is already raised, so the toggle acts on what the user is looking
  // at instead of only on the next process they open.
  const rebuiltOnce = useRef(false);
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    if (!rebuiltOnce.current) {
      rebuiltOnce.current = true;
      return;
    }
    const open = [...scene.planes.keys()];
    for (const processName of open) scene.closeProcess(processName);
    for (const processName of open) {
      const prepared = preparedFor(processName);
      if (prepared) scene.openProcess(prepared, processIndexById);
    }
    // Only the two toggles: reacting to `preparedFor` identity would reopen
    // planes on every unrelated re-render.
  }, [layoutMode, showIsolated]);

  useEffect(() => {
    if (!sceneRef.current || !overview || !overviewLayout) return;
    sceneRef.current.setOverview(overview, overviewLayout);
    sceneRef.current.setHighlights({});
    setOpenPlanes([]);
    setSelection(null);
  }, [overview, overviewLayout]);

  useEffect(() => {
    const scene = sceneRef.current;
    const target = revealTarget;
    if (!scene || !target?.functionIds?.length) return;

    const primary = target.functionIds[0];
    const processName = processByFunctionId.get(primary);
    const prepared = processName && preparedFor(processName);
    if (!prepared) return;

    // Reset first. Revealing a citation is a jump to one place, not an
    // addition to whatever the user was already looking at — without this a
    // second reveal leaves the previous process open and the two planes drop
    // into the facing layout, which is not what "show me this function" means.
    if (!scene.planes.has(processName) || scene.planes.size > 1) {
      scene.collapseAll();
    }
    if (!scene.planes.has(processName)) scene.openProcess(prepared, processIndexById);
    scene.focusPlane(processName);
    scene.setHighlights({
      answerIds: new Set(target.functionIds),
      answerEdgeKeys: new Set(target.edgeKeys || []),
    });
  }, [revealTarget, processByFunctionId, processIndexById, preparedFor]);

  const selectedIndex = useMemo(() => {
    if (!selection) return null;
    const name = selection.processName || selection.process?.name;
    return indexes.find((entry) => entry.process.name === name) || null;
  }, [selection, indexes]);

  return (
    <div
      aria-hidden={!active}
      className={`absolute inset-0 flex bg-paper transition-opacity duration-150 ${
        active ? "z-10 opacity-100" : "pointer-events-none z-0 opacity-0"
      }`}
    >
      <div className="relative min-w-0 flex-1">
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

      <Inspector
        selection={selection}
        index={selectedIndex}
        runId={selectedIndex ? selectedRuns.get(selectedIndex.process.name) : null}
        onAskFunction={onAskFunction}
      />
    </div>
  );
}
