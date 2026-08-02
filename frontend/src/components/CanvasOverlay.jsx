import { useMemo, useState } from "react";
import { useT } from "../i18n.jsx";
import { EDGE_CATEGORIES } from "../scene/graphLayer.js";

const EDGE_TOGGLES = [
  [EDGE_CATEGORIES.CALL, "functionCalls", "#b0864a"],
  [EDGE_CATEGORIES.INTERACTION, "daemonLinks", "#0e7fa8"],
  [EDGE_CATEGORIES.GROUND, "processDaemon", "#2563d8"],
  [EDGE_CATEGORIES.PLANE_TO_PLANE, "planePlane", "#c2185b"],
];

const STR = {
  ja: {
    frame: "全体を表示",
    collapse: "すべてのツリーを閉じる",
    resetView: "表示をリセット",
    resetLayout: "配置をリセット",
    clear: "強調をクリア",
    runs: "実行結果",
    hint: "ノードをドラッグして移動 · 背景をドラッグしてパン · ホイールでズーム",
    rotate: " · 右ドラッグで回転",
    edges: "エッジ",
    functionCalls: "関数呼び出し",
    daemonLinks: "デーモンリンク",
    processDaemon: "プロセス ↔ デーモン",
    planePlane: "平面 ↔ 平面",
    hover: "ホバー時に強調",
    planeA: "平面 A",
    planeB: "平面 B",
    close: "{process} を閉じる",
    twoPlanes: "向かい合わせ · ドラッグで視点移動 · 3 枚目を開くと平面 A を閉じる",
    runHelp: "相互作用の根拠を含む最新の実行結果を既定にしている。単純な最新版は多くのプロセスで空になっている。",
    runOption: "{run} · 関数 {functions} · 相互作用 {interactions}",
    unsupported: "未対応のスキーマバージョンのため非表示: ",
    mainRoot: "main / ルート",
    internal: "内部関数",
    daemonPort: "デーモン API ポート",
    library: "ライブラリ呼び出し",
    unreached: "到達不能",
    functionResource: "関数 → 資源",
    planeToPlane: "平面 → 平面",
  },
  en: {
    frame: "Frame overview",
    collapse: "Collapse all trees",
    resetView: "Reset view",
    resetLayout: "Reset layout",
    clear: "Clear highlights",
    runs: "Runs",
    hint: "drag a node to move it · drag the background to pan · wheel to zoom",
    rotate: " · right-drag to rotate",
    edges: "Edges",
    functionCalls: "function calls",
    daemonLinks: "daemon links",
    processDaemon: "process ↔ daemon",
    planePlane: "plane ↔ plane",
    hover: "highlight on hover",
    planeA: "plane A",
    planeB: "plane B",
    close: "Close {process}",
    twoPlanes: "facing each other · drag to turn your head · a third collapses plane A",
    runHelp: "The default is the newest run carrying interaction evidence; the newest run alone is empty for most processes.",
    runOption: "{run} · {functions} fn · {interactions} interactions",
    unsupported: "Unsupported schema version, not rendered: ",
    mainRoot: "main / root",
    internal: "internal function",
    daemonPort: "daemon API port",
    library: "library call",
    unreached: "unreached",
    functionResource: "function → resource",
    planeToPlane: "plane → plane",
  },
};

function format(template, values) {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replace(`{${key}}`, value),
    template,
  );
}

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
  onResetView,
  onResetLayout,
  onClearHighlights,
  edgeVisibility,
  onToggleEdge,
  hoverHighlight,
  onToggleHoverHighlight,
}) {
  const t = useT(STR);
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
              {t.frame}
            </button>
            <button
              type="button"
              onClick={onCollapseAll}
              disabled={openPlanes.length === 0}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t.collapse}
            </button>
            <button
              type="button"
              onClick={onResetView}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel"
            >
              {t.resetView}
            </button>
            <button
              type="button"
              onClick={onResetLayout}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel"
            >
              {t.resetLayout}
            </button>
            <button
              type="button"
              onClick={() => setShowRuns((value) => !value)}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel"
            >
              {t.runs}
            </button>
            <button
              type="button"
              onClick={onClearHighlights}
              className="rounded-md border border-rule bg-panel/90 px-3 py-1.5 text-xs font-medium text-ink shadow-sm backdrop-blur transition hover:border-rule-strong hover:bg-panel"
            >
              {t.clear}
            </button>
          </div>

          <p className="rounded-md border border-rule/70 bg-panel/80 px-2 py-1 text-[11px] text-ink-faint backdrop-blur">
            {t.hint}
            {openPlanes.length > 0 ? t.rotate : ""}
          </p>

          <div className="w-64 rounded-lg border border-rule bg-panel/90 p-2.5 shadow-sm backdrop-blur">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-faint">
              {t.edges}
            </p>
            {EDGE_TOGGLES.map(([category, labelKey, colour]) => (
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
                {t[labelKey]}
              </label>
            ))}
            <label className="mt-1.5 flex cursor-pointer items-center gap-2 border-t border-rule pt-1.5 text-[11px] text-ink-muted">
              <input
                type="checkbox"
                checked={hoverHighlight}
                onChange={(event) => onToggleHoverHighlight(event.target.checked)}
                className="size-3 accent-slate-700"
              />
              {t.hover}
            </label>
          </div>

          {openPlanes.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {openPlanes.map((processName, position) => (
                <span
                  key={processName}
                  className="flex items-center gap-2 rounded-md border border-rule bg-panel/90 py-1 pl-2.5 pr-1 text-xs shadow-sm backdrop-blur"
                >
                  <span className="text-ink-faint">{position === 0 ? t.planeA : t.planeB}</span>
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
                    aria-label={format(t.close, { process: processName })}
                    className="rounded px-1.5 text-ink-faint hover:bg-inset hover:text-ink"
                  >
                    ×
                  </button>
                </span>
              ))}
              {openPlanes.length === 2 && (
                <span className="rounded-md bg-inset px-2 py-1 text-[11px] text-ink-faint">
                  {t.twoPlanes}
                </span>
              )}
            </div>
          )}

          {showRuns && (
            <div className="max-h-[60vh] w-80 overflow-y-auto rounded-lg border border-rule bg-panel p-3 shadow-lg">
              <p className="mb-2 text-[11px] leading-relaxed text-ink-muted">
                {t.runHelp}
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
                        {format(t.runOption, {
                          run: run.run_id,
                          functions: run.function_count,
                          interactions: run.interaction_count,
                        })}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          )}
        </div>

        <Legend t={t} />
      </div>

      {status.phase !== "ready" && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="max-w-md rounded-lg border border-rule bg-panel px-6 py-5 text-center shadow-lg">
            <p
              className={
                status.phase === "error"
                  ? "text-sm text-rose-700 dark:text-rose-300"
                  : "text-sm text-ink-muted"
              }
            >
              {status.message}
            </p>
          </div>
        </div>
      )}

      {unsupported.length > 0 && (
        <div className="absolute bottom-4 left-4 max-w-md rounded-md border border-amber-400/60 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 shadow-sm dark:text-amber-300">
          {t.unsupported}{unsupported.join(", ")}
        </div>
      )}
    </>
  );
}

const LEGEND = [
  ["#b31414", "mainRoot"],
  ["#cf9010", "internal"],
  ["#0a6e2a", "daemonPort"],
  ["#7b8798", "library"],
  ["#9aa5b4", "unreached"],
  ["#0e7fa8", "functionResource"],
  ["#c2185b", "planeToPlane"],
];

function Legend({ t }) {
  return (
    <div className="pointer-events-none rounded-lg border border-rule bg-panel/90 p-3 shadow-sm backdrop-blur">
      <ul className="space-y-1.5">
        {LEGEND.map(([color, labelKey]) => (
          <li key={labelKey} className="flex items-center gap-2 text-[11px] text-ink-muted">
            <span
              className="inline-block size-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: color }}
            />
            {t[labelKey]}
          </li>
        ))}
      </ul>
    </div>
  );
}
