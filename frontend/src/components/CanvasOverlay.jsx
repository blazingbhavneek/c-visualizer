import { useMemo, useState } from "react";

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
              className="rounded-md border border-ink-700 bg-ink-900/85 px-3 py-1.5 text-xs font-medium text-slate-200 backdrop-blur transition hover:border-slate-500 hover:text-white"
            >
              Frame overview
            </button>
            <button
              type="button"
              onClick={onCollapseAll}
              disabled={openPlanes.length === 0}
              className="rounded-md border border-ink-700 bg-ink-900/85 px-3 py-1.5 text-xs font-medium text-slate-200 backdrop-blur transition hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
            >
              Collapse all trees
            </button>
            <button
              type="button"
              onClick={onResetTilt}
              className="rounded-md border border-ink-700 bg-ink-900/85 px-3 py-1.5 text-xs font-medium text-slate-200 backdrop-blur transition hover:border-slate-500 hover:text-white"
            >
              Look straight on
            </button>
            <button
              type="button"
              onClick={() => setShowRuns((value) => !value)}
              className="rounded-md border border-ink-700 bg-ink-900/85 px-3 py-1.5 text-xs font-medium text-slate-200 backdrop-blur transition hover:border-slate-500 hover:text-white"
            >
              Runs
            </button>
          </div>

          <p className="rounded-md bg-ink-900/70 px-2 py-1 text-[11px] text-slate-500 backdrop-blur">
            drag to pan · wheel to zoom · right-drag (or shift-drag) to tilt
          </p>

          {openPlanes.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {openPlanes.map((processName, position) => (
                <span
                  key={processName}
                  className="flex items-center gap-2 rounded-md border border-ink-700 bg-ink-900/85 py-1 pl-2.5 pr-1 text-xs backdrop-blur"
                >
                  <span className="text-slate-500">{position === 0 ? "plane A" : "plane B"}</span>
                  <button
                    type="button"
                    onClick={() => onFocusPlane(processName)}
                    className="font-mono text-slate-100 hover:text-white"
                  >
                    {processName}
                  </button>
                  <button
                    type="button"
                    onClick={() => onClosePlane(processName)}
                    aria-label={`Close ${processName}`}
                    className="rounded px-1.5 text-slate-500 hover:bg-ink-700 hover:text-white"
                  >
                    ×
                  </button>
                </span>
              ))}
              {openPlanes.length === 2 && (
                <span className="rounded-md bg-ink-800/70 px-2 py-1 text-[11px] text-slate-500 backdrop-blur">
                  opening a third collapses plane A
                </span>
              )}
            </div>
          )}

          {showRuns && (
            <div className="max-h-[60vh] w-80 overflow-y-auto rounded-lg border border-ink-700 bg-ink-900/95 p-3 backdrop-blur">
              <p className="mb-2 text-[11px] leading-relaxed text-slate-500">
                Default is the newest run that carries interaction evidence — the newest run alone is
                empty for most processes.
              </p>
              {[...runsByProcess.entries()].map(([processName, list]) => (
                <label key={processName} className="mb-2 block">
                  <span className="mb-1 block font-mono text-xs text-slate-300">{processName}</span>
                  <select
                    value={selectedRuns.get(processName) || ""}
                    onChange={(event) => onSelectRun(processName, event.target.value)}
                    className="w-full rounded border border-ink-700 bg-ink-850 px-2 py-1 text-xs text-slate-200"
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
          <div className="max-w-md rounded-lg border border-ink-700 bg-ink-900/95 px-6 py-5 text-center backdrop-blur">
            <p
              className={
                status.phase === "error" ? "text-sm text-rose-300" : "text-sm text-slate-300"
              }
            >
              {status.message}
            </p>
          </div>
        </div>
      )}

      {unsupported.length > 0 && (
        <div className="absolute bottom-4 left-4 max-w-md rounded-md border border-amber-700/60 bg-amber-950/70 px-3 py-2 text-xs text-amber-200 backdrop-blur">
          Unsupported schema version, not rendered: {unsupported.join(", ")}
        </div>
      )}
    </>
  );
}

const LEGEND = [
  ["#ff2d2d", "main / root"],
  ["#f69e05", "internal function"],
  ["#12dd6a", "daemon API port"],
  ["#68758a", "library call"],
  ["#4a5568", "unreached"],
  ["#38d9ff", "function → resource"],
  ["#ff5fa2", "plane → plane"],
];

function Legend() {
  return (
    <div className="pointer-events-none rounded-lg border border-ink-700 bg-ink-900/80 p-3 backdrop-blur">
      <ul className="space-y-1.5">
        {LEGEND.map(([color, label]) => (
          <li key={label} className="flex items-center gap-2 text-[11px] text-slate-400">
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
