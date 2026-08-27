import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchOverview, fetchRuns, wikiStatus } from "./api.js";
import ChatPanel from "./components/ChatPanel.jsx";
import GraphView from "./components/GraphView.jsx";
import TopBar from "./components/TopBar.jsx";
import useAsk from "./hooks/useAsk.js";
import { useT } from "./i18n.jsx";

const STR = {
  ja: {
    scanning: "スナップショットを検索中…",
    loading: "プロセス／資源の概要を読込中…",
    empty: "スナップショットがない。解析パイプラインを実行してから再読込してください。",
    apiError: "API に接続できない: {error}",
    loadError: "概要を読み込めなかった。{details}",
    unsupportedAll: "選択されたスナップショットのすべてが未対応のスキーマバージョンを使用している。",
    askFunction: "`{name}` 関数の役割と呼び出し経路を説明して",
  },
  en: {
    scanning: "Scanning snapshots…",
    loading: "Loading the process/resource overview…",
    empty: "No snapshots found. Run the analysis pipeline, then reload.",
    apiError: "Could not reach the API: {error}",
    loadError: "The overview could not be loaded. {details}",
    unsupportedAll: "Every selected snapshot uses an unsupported schema version.",
    askFunction: "Explain the role and invocation paths of `{name}`",
  },
};

function format(template, values) {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replace(`{${key}}`, value),
    template,
  );
}

/** Prefer the newest run carrying daemon-interaction evidence for each process. */
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
  const t = useT(STR);
  const [view, setView] = useState("chat");
  const [draft, setDraft] = useState("");
  const [loadState, setLoadState] = useState({ phase: "loading", code: "scanning" });
  const [runs, setRuns] = useState([]);
  const [selectedRuns, setSelectedRuns] = useState(new Map());
  const [overview, setOverview] = useState(null);
  const [unsupported, setUnsupported] = useState([]);
  const [wiki, setWiki] = useState(null);
  const [wikiError, setWikiError] = useState(null);
  const [revealTarget, setRevealTarget] = useState(null);
  const askState = useAsk(selectedRuns);

  useEffect(() => {
    const controller = new AbortController();
    fetchRuns(controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        const list = payload.runs || [];
        setRuns(list);
        if (list.length === 0) {
          setLoadState({ phase: "empty", code: "empty" });
          return;
        }
        setSelectedRuns(chooseRuns(list));
      })
      .catch((error) => {
        if (error.name !== "AbortError" && !controller.signal.aborted) {
          setLoadState({ phase: "error", code: "api", detail: error.message });
        }
      });
    return () => controller.abort();
  }, []);

  // Startup request path: catalog + overview.  No process graph is loaded
  // here; a ground click fetches one process at a time.
  useEffect(() => {
    if (selectedRuns.size === 0) return undefined;
    const controller = new AbortController();
    setLoadState({ phase: "loading", code: "loading" });
    fetchOverview([...selectedRuns.entries()], controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        const bad = payload.unsupported || [];
        setUnsupported(
          bad.map((item) => `${item.process_name} (schema_version ${item.schema_version})`),
        );
        if (!payload.processes?.length) {
          setLoadState({
            phase: "error",
            code: bad.length ? "unsupported" : "empty",
            detail: bad
              .map((item) => `${item.process_name} (schema_version ${item.schema_version})`)
              .join(", "),
          });
          return;
        }
        setOverview(payload);
        setLoadState({ phase: "ready", code: "ready" });
      })
      .catch((error) => {
        if (error.name !== "AbortError" && !controller.signal.aborted) {
          setLoadState({ phase: "error", code: "load", detail: error.message });
        }
      });
    return () => controller.abort();
  }, [selectedRuns]);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const poll = () => {
      wikiStatus()
        .then((payload) => {
          if (cancelled) return;
          setWiki(payload);
          setWikiError(null);
          if (payload.indexing) timer = window.setTimeout(poll, 2000);
        })
        .catch((error) => {
          if (!cancelled) setWikiError(error.message);
        });
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  const graphStatus = useMemo(() => {
    let message = "";
    if (loadState.code === "scanning") message = t.scanning;
    if (loadState.code === "loading") message = t.loading;
    if (loadState.code === "empty") message = t.empty;
    if (loadState.code === "api") message = format(t.apiError, { error: loadState.detail || "—" });
    if (loadState.code === "load") {
      message = format(t.loadError, { details: loadState.detail || "" });
    }
    if (loadState.code === "unsupported") message = t.unsupportedAll;
    return { phase: loadState.phase, message };
  }, [loadState, t]);

  const revealFunctions = useCallback(
    (functionIds, edgeKeys = [], processName = null) => {
      if (!functionIds?.length) return;
      setView("graph");
      setRevealTarget({ functionIds, edgeKeys, processName, nonce: Date.now() + Math.random() });
    },
    [],
  );

  const askFunction = useCallback(
    (name) => {
      setDraft(format(t.askFunction, { name }));
      setView("chat");
    },
    [t.askFunction],
  );

  return (
    <div className="flex h-full w-full flex-col bg-paper">
      <TopBar view={view} onChangeView={setView} />
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <div
          className={`absolute inset-0 flex transition-opacity duration-150 ${
            view === "chat" ? "z-10 opacity-100" : "pointer-events-none z-0 opacity-0"
          }`}
        >
          <ChatPanel
            turns={askState.turns}
            latestCompleted={askState.latestCompleted}
            draft={draft}
            onDraftChange={setDraft}
            onAsk={askState.ask}
            onStop={askState.stop}
            isStreaming={askState.isStreaming}
            wiki={wiki}
            wikiError={wikiError}
            onReveal={revealFunctions}
            onShowGraph={() => setView("graph")}
          />
        </div>
        <GraphView
          active={view === "graph"}
          status={graphStatus}
          runs={runs}
          selectedRuns={selectedRuns}
          onSelectRun={(processName, runId) =>
            setSelectedRuns((previous) => new Map(previous).set(processName, runId))
          }
          overview={overview}
          unsupported={unsupported}
          revealTarget={revealTarget}
          onAskFunction={askFunction}
        />
      </div>
    </div>
  );
}
