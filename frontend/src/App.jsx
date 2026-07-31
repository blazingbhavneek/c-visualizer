import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import SceneManager from "./scene/SceneManager.js";
import Inspector from "./components/Inspector.jsx";
import CanvasOverlay from "./components/CanvasOverlay.jsx";
import { fetchGraph, fetchRuns } from "./api.js";
import { SCHEMA_VERSION, deriveOverview, indexSnapshot } from "./graph/model.js";
import { layoutOverview } from "./graph/layout.js";
import { prepareProcess } from "./graph/prepare.js";

/**
 * Interim run-selection policy (task #2): prefer the newest run that actually
 * carries interaction evidence, because the newest run for five of six
 * processes has none and would render an overview with no daemon edges at all.
 */
function chooseRuns(runs) {
  const byProcess = new Map();
  for (const run of runs) {
    if (!byProcess.has(run.process_name)) byProcess.set(run.process_name, []);
    byProcess.get(run.process_name).push(run);
  }
  const chosen = new Map();
  for (const [processName, entries] of byProcess) {
    const sorted = [...entries].sort((a, b) =>
      String(b.generated_at || "").localeCompare(String(a.generated_at || "")),
    );
    const withEvidence = sorted.find((run) => run.interaction_count > 0);
    chosen.set(processName, (withEvidence || sorted[0]).run_id);
  }
  return chosen;
}

export default function App() {
  const containerRef = useRef(null);
  const sceneRef = useRef(null);
  const preparedCache = useRef(new Map());

  const [status, setStatus] = useState({ phase: "loading", message: "Scanning snapshots…" });
  const [runs, setRuns] = useState([]);
  const [selectedRuns, setSelectedRuns] = useState(new Map());
  const [indexes, setIndexes] = useState([]);
  const [openPlanes, setOpenPlanes] = useState([]);
  const [selection, setSelection] = useState(null);
  const [edgeVisibility, setEdgeVisibility] = useState({});
  const [hoverHighlight, setHoverHighlight] = useState(true);
  const [unsupported, setUnsupported] = useState([]);

  // ---------------------------------------------------------------- data load

  useEffect(() => {
    let cancelled = false;
    fetchRuns()
      .then((payload) => {
        if (cancelled) return;
        const list = payload.runs || [];
        setRuns(list);
        if (list.length === 0) {
          setStatus({
            phase: "empty",
            message: "No snapshots found. Run the analysis pipeline, then reload.",
          });
          return;
        }
        setSelectedRuns(chooseRuns(list));
      })
      .catch((error) => {
        if (cancelled) return;
        setStatus({ phase: "error", message: `Could not reach the API: ${error.message}` });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (selectedRuns.size === 0) return;
    let cancelled = false;
    setStatus({ phase: "loading", message: "Loading graph snapshots…" });
    preparedCache.current.clear();

    Promise.all(
      [...selectedRuns.entries()].map(([processName, runId]) =>
        fetchGraph(processName, runId)
          .then((snapshot) => ({ processName, snapshot }))
          .catch((error) => ({ processName, error })),
      ),
    ).then((results) => {
      if (cancelled) return;
      const loaded = [];
      const badVersion = [];
      const failed = [];
      for (const result of results) {
        if (result.error) {
          failed.push(`${result.processName}: ${result.error.message}`);
          continue;
        }
        if (result.snapshot.schema_version !== SCHEMA_VERSION) {
          badVersion.push(`${result.processName} (schema_version ${result.snapshot.schema_version})`);
          continue;
        }
        loaded.push(indexSnapshot(result.snapshot));
      }
      setUnsupported(badVersion);
      if (loaded.length === 0) {
        setStatus({
          phase: "error",
          message: failed.length
            ? `No snapshot could be loaded. ${failed.join("; ")}`
            : "Every snapshot uses an unsupported schema version.",
        });
        return;
      }
      loaded.sort((a, b) => a.process.name.localeCompare(b.process.name));
      setIndexes(loaded);
      setStatus({ phase: "ready", message: "" });
    });

    return () => {
      cancelled = true;
    };
  }, [selectedRuns]);

  // ------------------------------------------------------------------- scene

  const overview = useMemo(() => (indexes.length ? deriveOverview(indexes) : null), [indexes]);
  const overviewLayout = useMemo(() => (overview ? layoutOverview(overview) : null), [overview]);
  const processIndexById = useMemo(() => {
    const map = new Map();
    indexes.forEach((index, position) => map.set(index.process.name, position));
    return map;
  }, [indexes]);

  const handleSelect = useCallback(
    (pick) => {
      if (!pick) {
        setSelection(null);
        return;
      }
      if (pick.type === "process") {
        const index = indexes.find((entry) => entry.process.name === pick.process.name);
        if (index) {
          if (!preparedCache.current.has(pick.process.name)) {
            preparedCache.current.set(pick.process.name, prepareProcess(index));
          }
          sceneRef.current?.openProcess(preparedCache.current.get(pick.process.name), processIndexById);
        }
      }
      setSelection(pick);
    },
    [indexes, processIndexById],
  );

  // Keep the scene's callback pointing at the latest closure without tearing
  // down and rebuilding the WebGL context on every render.
  const handleSelectRef = useRef(handleSelect);
  useEffect(() => {
    handleSelectRef.current = handleSelect;
  }, [handleSelect]);

  useEffect(() => {
    if (!containerRef.current || sceneRef.current) return;
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
    if (!sceneRef.current || !overview || !overviewLayout) return;
    sceneRef.current.setOverview(overview, overviewLayout);
    setOpenPlanes([]);
    setSelection(null);
  }, [overview, overviewLayout]);

  const selectedIndex = useMemo(() => {
    if (!selection) return null;
    const name = selection.processName || selection.process?.name;
    return indexes.find((entry) => entry.process.name === name) || null;
  }, [selection, indexes]);

  return (
    <div className="flex h-full w-full bg-paper">
      <div className="relative min-w-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" />

        <CanvasOverlay
          status={status}
          runs={runs}
          selectedRuns={selectedRuns}
          onSelectRun={(processName, runId) =>
            setSelectedRuns((previous) => new Map(previous).set(processName, runId))
          }
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
        />
      </div>

      <Inspector
        selection={selection}
        index={selectedIndex}
        runId={selectedIndex ? selectedRuns.get(selectedIndex.process.name) : null}
      />
    </div>
  );
}
