import { useMemo, useState } from "react";
import { EDGE_CATEGORIES } from "../scene/graphLayer.js";

const EDGE_TOGGLES = [
  [EDGE_CATEGORIES.CALL, "function calls", "#b0864a"],
  [EDGE_CATEGORIES.INTERACTION, "daemon links", "#0e7fa8"],
  [EDGE_CATEGORIES.GROUND, "process ↔ daemon", "#2563d8"],
  [EDGE_CATEGORIES.PLANE_TO_PLANE, "plane ↔ plane", "#c2185b"],
];

/**
 * Floating controls over the canvas. Deliberately an overlay rather than a
 * third panel: the layout is a 3D viewer plus one inspector, and these are the
 * minimum controls the viewer needs to be usable.
 */
export default function CanvasOverlay({
  status,
  runs,
  selectedRuns,
  onSelectRun,
  openPlanes,
  unsupported,
  onCollapseAll,
  onFocusPlane,
  onClosePlane,
  onFrameOverview,
  onResetTilt,
  onResetLayout,
  edgeVisibility,
  onToggleEdge,
  hoverHighlight,
  onToggleHoverHighlight,
}) {
  const [showRuns, setShowRuns] = useState(false);

  const runsByProcess = useMemo(() => {
    const map = new Map();
    for (const run of runs) {
      if (!map.has(run.process_name)) map.set(run.process_name, []);
      map.get(run.process_name).push(run);
    }
    for (const list of map.values()) {
      list.sort((a, b) => String(b.generated_at || "").localeCompare(String(a.generated_at || "")));
    }
    return map;
  }, [runs]);

  return (
    <>
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-3 p-4">
        <div className="pointer-events-auto flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onFrameOverview}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel"
            >
              Frame overview
            </button>
            <button
              type="button"
              onClick={onCollapseAll}
              disabled={openPlanes.length === 0}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel disabled:cursor-not-allowed disabled:opacity-40"
            >
              Collapse all trees
            </button>
            <button
              type="button"
              onClick={onResetTilt}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel"
            >
              Look straight on
            </button>
            <button
              type="button"
              onClick={onResetLayout}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel"
            >
              Reset layout
            </button>
            <button
              type="button"
              onClick={() => setShowRuns((value) => !value)}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel"
            >
              Runs
            </button>
          </div>

          <p className="rounded-md border border-rule/70 bg-panel/80 px-2 py-1 text-[11px] text-ink-faint backdrop-blur">
            drag a node to move it · drag the background to pan · wheel to zoom
            {openPlanes.length > 0 ? " · right-drag to rotate" : ""}
          </p>

          <div className="w-64 rounded-lg border border-rule bg-panel/90 p-2.5 shadow-sm backdrop-blur">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-faint">
              Edges
            </p>
            {EDGE_TOGGLES.map(([category, label, colour]) => (
              <label
                key={category}
                className="flex cursor-pointer items-center gap-2 py-0.5 text-[11px] text-ink-muted"
              >
                <input
                  type="checkbox"
                  checked={edgeVisibility[category] !== false}
                  onChange={(event) => onToggleEdge(category, event.target.checked)}
                  className="size-3 accent-slate-700"
                />
                <span
                  className="inline-block h-0.5 w-3.5 shrink-0 rounded"
                  style={{ backgroundColor: colour }}
                />
                {label}
              </label>
            ))}
            <label className="mt-1.5 flex cursor-pointer items-center gap-2 border-t border-rule pt-1.5 text-[11px] text-ink-muted">
              <input
                type="checkbox"
                checked={hoverHighlight}
                onChange={(event) => onToggleHoverHighlight(event.target.checked)}
                className="size-3 accent-slate-700"
              />
              highlight on hover
            </label>
          </div>

          {openPlanes.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {openPlanes.map((processName, position) => (
                <span
                  key={processName}
                  className="flex items-center gap-2 rounded-md border border-rule bg-panel/90 py-1 pl-2.5 pr-1 text-xs shadow-sm backdrop-blur"
                >
                  <span className="text-ink-faint">{position === 0 ? "plane A" : "plane B"}</span>
                  <button
                    type="button"
                    onClick={() => onFocusPlane(processName)}
                    className="font-mono text-ink hover:underline"
                  >
                    {processName}
                  </button>
                  <button
                    type="button"
                    onClick={() => onClosePlane(processName)}
                    aria-label={`Close ${processName}`}
                    className="rounded px-1.5 text-ink-faint hover:bg-inset hover:text-ink"
                  >
                    ×
                  </button>
                </span>
              ))}
              {openPlanes.length === 2 && (
                <span className="rounded-md bg-inset px-2 py-1 text-[11px] text-ink-faint">
                  facing each other — drag to turn your head · a third collapses plane A
                </span>
              )}
            </div>
          )}

          {showRuns && (
            <div className="max-h-[60vh] w-80 overflow-y-auto rounded-lg border border-rule bg-panel p-3 shadow-lg">
              <p className="mb-2 text-[11px] leading-relaxed text-ink-muted">
                Default is the newest run that carries interaction evidence — the newest run alone is
                empty for most processes.
              </p>
              {[...runsByProcess.entries()].map(([processName, list]) => (
                <label key={processName} className="mb-2 block">
                  <span className="mb-1 block font-mono text-xs text-ink-muted">{processName}</span>
                  <select
                    value={selectedRuns.get(processName) || ""}
                    onChange={(event) => onSelectRun(processName, event.target.value)}
                    className="w-full rounded border border-rule bg-sunken px-2 py-1 text-xs text-ink"
                  >
                    {list.map((run) => (
                      <option key={run.run_id} value={run.run_id}>
                        {run.run_id} · {run.function_count} fn · {run.interaction_count} interactions
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          )}
        </div>

        <Legend />
      </div>

      {status.phase !== "ready" && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="max-w-md rounded-lg border border-rule bg-panel px-6 py-5 text-center shadow-lg">
            <p
              className={
                status.phase === "error" ? "text-sm text-rose-700" : "text-sm text-ink-muted"
              }
            >
              {status.message}
            </p>
          </div>
        </div>
      )}

      {unsupported.length > 0 && (
        <div className="absolute bottom-4 left-4 max-w-md rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow-sm">
          Unsupported schema version, not rendered: {unsupported.join(", ")}
        </div>
      )}
    </>
  );
}

const LEGEND = [
  ["#b31414", "main / root"],
  ["#cf9010", "internal function"],
  ["#0a6e2a", "daemon API port"],
  ["#7b8798", "library call"],
  ["#9aa5b4", "unreached"],
  ["#0e7fa8", "function → resource"],
  ["#c2185b", "plane → plane"],
];

function Legend() {
  return (
    <div className="pointer-events-none rounded-lg border border-rule bg-panel/90 p-3 shadow-sm backdrop-blur">
      <ul className="space-y-1.5">
        {LEGEND.map(([color, label]) => (
          <li key={label} className="flex items-center gap-2 text-[11px] text-ink-muted">
            <span
              className="inline-block size-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: color }}
            />
            {label}
          </li>
        ))}
      </ul>
    </div>
  );
}
