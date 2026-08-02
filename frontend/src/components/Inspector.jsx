import { MessageSquareText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchSource } from "../api.js";
import { interactionDirection } from "../graph/model.js";
import { useT } from "../i18n.jsx";
import { Badge, Section } from "./ui.jsx";

const STR = {
  ja: {
    inspector: "インスペクター",
    subtitle: "選択要素の静的解析根拠",
    empty: "何も選択されていない。",
    emptyProcess: "地面のプロセスをクリックすると、呼び出しツリーが立ち上がる。",
    emptyFunction: "ツリーの関数をクリックすると、根拠をここに表示する。",
    emptyResource: "デーモン資源をクリックすると、利用するプロセスを表示する。",
    function: "関数",
    askFunction: "この関数について質問",
    external: "外部",
    static: "static",
    recursion: "再帰バックエッジ",
    noCall: "記録された呼び出しなし",
    noMainPath: "main からの経路なし",
    synthetic: "合成ルート",
    calls: "{n} 呼び出し",
    interactions: "{n} 相互作用",
    ai: "AI による説明",
    noSummary: "このスナップショットにはモデルによる概要がない。",
    libraryBoundary: "このノードはアプリケーションコードではなく外部／ライブラリ境界として扱われるため、概要の対象外です。API の文脈は、この関数を呼び出すリポジトリ関数の概要に含まれます。",
    enableSummary: "解析の実行時にボトムアップ概要生成を有効にしてください。",
    reachedVia: "到達経路",
    reachedHelp: "このツリーエッジ上の呼び出し位置。同じ対象への並列呼び出しは 1 ノードを共有するため、すべてここに列挙する。",
    daemonInteractions: "デーモン相互作用",
    noInteraction: "この関数に帰属する資源相互作用はない。",
    argument: "引数",
    outgoing: "呼び出し先",
    calledBy: "呼び出し元",
    traces: "この名前を含むトレース",
    noTrace: "この関数名を含むトレース経路はない。",
    more: "ほか {n} 件",
    source: "ソース",
    raw: "Raw",
    showRaw: "スナップショットの raw フィールドを表示",
    hideRaw: "スナップショットの raw フィールドを隠す",
    none: "記録なし。",
    noSource: "ソース根拠なし — 外部、合成、または定義範囲が記録されていない。",
    loadingSource: "ソースを読込中…",
    source403: "ソースはこのプロセスのルート外にある (403)。",
    source404: "ソースファイルを利用できない (404)。",
    sourceError: "ソースを読み込めなかった。",
    daemonResource: "デーモン資源",
    resolved: "解決済み",
    unresolved: "未解決",
    shared: "{n} プロセスで共有",
    touching: "利用するプロセス",
    note: "注記",
    resourceNote: "スナップショットごとに ID のハッシュが異なるため、資源は kind + name でスナップショット間を対応付けています。これはモデル支援解析の根拠であり、稼働中デーモンの一覧ではありません。",
    process: "プロセス",
    functions: "{n} 関数",
    resources: "{n} 資源",
    entry: "エントリ",
    noEntry: "エントリ関数なし — 平面はグラフのルートを使用",
    next: "次へ",
    nextHelp: "このノードを基点に呼び出しツリーの平面が立ち上がっています。ツリー内の関数をクリックすると詳細を確認できます。",
  },
  en: {
    inspector: "Inspector",
    subtitle: "Static-analysis evidence for the selected element",
    empty: "Nothing selected.",
    emptyProcess: "Click a process on the ground plane to raise its call tree.",
    emptyFunction: "Click a function in a tree to see its evidence here.",
    emptyResource: "Click a daemon resource to see which processes touch it.",
    function: "Function",
    askFunction: "Ask about this function",
    external: "external",
    static: "static",
    recursion: "recursion back-edge",
    noCall: "no recorded call at all",
    noMainPath: "no path from main",
    synthetic: "synthetic root",
    calls: "{n} calls",
    interactions: "{n} interactions",
    ai: "AI explanation",
    noSummary: "No model-written summary in this snapshot.",
    libraryBoundary: "This node is treated as an external/library boundary, not as application code to summarize. Its API context is folded into summaries of repository functions that call it.",
    enableSummary: "Enable the bottom-up summary pass when running the analyzer.",
    reachedVia: "Reached via",
    reachedHelp: "Call sites on this tree edge. Parallel calls to the same target share one node, so all of them are listed here.",
    daemonInteractions: "Daemon interactions",
    noInteraction: "No resource interaction attributed to this function.",
    argument: "arg",
    outgoing: "Outgoing calls",
    calledBy: "Called by",
    traces: "Traces mentioning this name",
    noTrace: "No trace path contains this function name.",
    more: "+{n} more",
    source: "Source",
    raw: "Raw",
    showRaw: "Show raw snapshot fields",
    hideRaw: "Hide raw snapshot fields",
    none: "None recorded.",
    noSource: "No source evidence — external, synthetic, or no recorded definition range.",
    loadingSource: "Loading source…",
    source403: "Source lies outside this process root (403).",
    source404: "Source file not available (404).",
    sourceError: "Could not load source.",
    daemonResource: "Daemon resource",
    resolved: "resolved",
    unresolved: "unresolved",
    shared: "shared by {n}",
    touching: "Processes touching it",
    note: "Note",
    resourceNote: "Resources are keyed by kind + name across snapshots because IDs are per-snapshot hashes. This is analysis evidence from the model-assisted results, not a live daemon inventory.",
    process: "Process",
    functions: "{n} functions",
    resources: "{n} resources",
    entry: "Entry",
    noEntry: "no entry function — plane uses graph roots",
    next: "Next",
    nextHelp: "Its call tree is now raised on a plane anchored to this node. Click any function in that tree to inspect it.",
  },
};

function fmt(template, n) {
  return template.replace("{n}", n);
}

export default function Inspector({ selection, index, runId, onAskFunction }) {
  const t = useT(STR);
  return (
    <aside className="flex w-[26rem] shrink-0 flex-col border-l border-rule bg-panel">
      <header className="border-b border-rule px-5 py-4">
        <h1 className="text-sm font-semibold tracking-wide text-ink">{t.inspector}</h1>
        <p className="mt-0.5 text-xs text-ink-faint">{t.subtitle}</p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!selection && <EmptyState t={t} />}
        {selection?.type === "function" && (
          <FunctionPanel
            selection={selection}
            index={index}
            runId={runId}
            onAskFunction={onAskFunction}
            t={t}
          />
        )}
        {selection?.type === "resource" && <ResourcePanel resource={selection.resource} t={t} />}
        {selection?.type === "process" && <ProcessPanel process={selection.process} index={index} t={t} />}
      </div>
    </aside>
  );
}

function EmptyState({ t }) {
  return (
    <div className="px-5 py-6 text-sm leading-relaxed text-ink-muted">
      <p>{t.empty}</p>
      <ul className="mt-3 list-disc space-y-1.5 pl-4 text-xs">
        <li>{t.emptyProcess}</li>
        <li>{t.emptyFunction}</li>
        <li>{t.emptyResource}</li>
      </ul>
    </div>
  );
}

function FunctionPanel({ selection, index, runId, onAskFunction, t }) {
  const fn = selection.node.fn;
  const [source, setSource] = useState({ phase: "idle" });
  const [showRaw, setShowRaw] = useState(false);
  const canFetchSource =
    !!index && !fn.is_external && !fn.synthetic && !!fn.file && fn.start_line > 0;

  useEffect(() => {
    if (!canFetchSource || !runId) {
      setSource({ phase: "unavailable" });
      return undefined;
    }
    let cancelled = false;
    setSource({ phase: "loading" });
    fetchSource(index.process.name, runId, fn.id)
      .then((payload) => !cancelled && setSource({ phase: "ready", payload }))
      .catch((error) => !cancelled && setSource({ phase: "error", error }));
    return () => {
      cancelled = true;
    };
  }, [fn.id, index, runId, canFetchSource]);

  const outgoing = index?.outgoing.get(fn.id) || [];
  const incoming = index?.incoming.get(fn.id) || [];
  const interactions = index?.interactionsByFunction.get(fn.id) || [];
  const traces = useMemo(() => {
    if (!index) return [];
    return index.traces.filter((trace) => trace.labels.some((label) => label.includes(fn.name)));
  }, [index, fn.name]);

  return (
    <div>
      <Section title={t.function}>
        <p className="break-all font-mono text-sm text-ink">{fn.name}</p>
        <p className="mt-1 break-all font-mono text-xs text-ink-muted">
          {fn.file_name || "—"}{fn.start_line > 0 ? ` [${fn.start_line}:${fn.end_line}]` : ""}
        </p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {fn.is_external && <Badge>{t.external}</Badge>}
          {fn.is_static && <Badge tone="amber">{t.static}</Badge>}
          {selection.node.recursive && <Badge tone="violet">{t.recursion}</Badge>}
          {selection.node.unreached && (
            <Badge tone="rose">{selection.node.isolated ? t.noCall : t.noMainPath}</Badge>
          )}
          {fn.synthetic && <Badge>{t.synthetic}</Badge>}
          <Badge>{fmt(t.calls, fn.call_count)}</Badge>
          {fn.resource_interaction_count > 0 && (
            <Badge tone="green">{fmt(t.interactions, fn.resource_interaction_count)}</Badge>
          )}
        </div>
        <button
          type="button"
          onClick={() => onAskFunction?.(fn.name)}
          className="mt-3 flex items-center gap-1.5 rounded-md border border-rule bg-sunken px-2.5 py-1.5 text-xs font-medium text-ink-muted hover:border-rule-strong hover:text-ink"
        >
          <MessageSquareText size={13} /> {t.askFunction}
        </button>
      </Section>

      <Section title={t.ai}>
        {fn.summary ? (
          <p className="text-sm leading-relaxed text-ink">{fn.summary}</p>
        ) : (
          <div className="rounded-md border border-dashed border-rule-strong bg-sunken p-3">
            <p className="text-xs leading-relaxed text-ink-muted">
              {t.noSummary}{" "}
              <span className="font-mono">summary_status: {fn.summary_status || "—"}</span>
              {fn.summary_error
                ? ` — ${fn.summary_error}`
                : ` — ${fn.summary_status === "library" || fn.is_external ? t.libraryBoundary : t.enableSummary}`}
            </p>
            {fn.summary_hint && <p className="mt-2 border-t border-rule pt-2 text-xs text-ink-muted">{fn.summary_hint}</p>}
          </div>
        )}
      </Section>

      {selection.node.viaCalls?.length > 0 && (
        <Section title={t.reachedVia} count={selection.node.viaCalls.length}>
          <p className="mb-2 text-[11px] leading-relaxed text-ink-faint">{t.reachedHelp}</p>
          <ul className="space-y-1">
            {selection.node.viaCalls.map((call) => (
              <li key={call.id} className="flex items-baseline justify-between gap-2 text-xs">
                <span className="font-mono text-ink-muted">{index?.functions.get(call.source)?.name || call.source}</span>
                <span className="shrink-0 font-mono text-[10px] text-ink-faint">
                  {call.kind}{call.line != null && ` :${call.line}`}{call.via && ` via ${index?.functions.get(call.via)?.name || call.via}`}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title={t.daemonInteractions} count={interactions.length || null}>
        {interactions.length === 0 ? (
          <p className="text-xs text-ink-faint">{t.noInteraction}</p>
        ) : (
          <ul className="space-y-2">
            {interactions.map((interaction) => {
              const resource = index.resources.get(interaction.resource_id);
              const direction = interactionDirection(interaction);
              return (
                <li key={interaction.id} className="rounded-md border border-rule bg-sunken p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-emerald-700 dark:text-emerald-300">{interaction.target_api}</span>
                    <Badge>{interaction.operation}</Badge>
                  </div>
                  <p className="mt-1.5 font-mono text-[11px] text-ink-muted">
                    {direction === "in" ? "←" : direction === "out" ? "→" : "↔"}{" "}
                    {resource ? `${resource.kind} ${resource.name}` : interaction.resource_id}
                    {resource && !resource.resolved && <span className="ml-1.5 text-rose-700 dark:text-rose-300">{t.unresolved}</span>}
                  </p>
                  <p className="mt-1 text-[11px] text-ink-faint">
                    {t.argument} #{interaction.argument_binding?.argument_index} ={" "}
                    <span className="font-mono">{String(interaction.argument_binding?.value)}</span>
                    {interaction.launch_via && ` · via ${interaction.launch_via}`}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section title={t.outgoing} count={outgoing.length || null}>
        <CallList calls={outgoing} index={index} field="target" t={t} />
      </Section>
      <Section title={t.calledBy} count={incoming.length || null}>
        <CallList calls={incoming} index={index} field="source" t={t} />
      </Section>
      <Section title={t.traces} count={traces.length || null}>
        {traces.length === 0 ? (
          <p className="text-xs text-ink-faint">{t.noTrace}</p>
        ) : (
          <ul className="space-y-2">
            {traces.slice(0, 12).map((trace) => (
              <li key={trace.id} className="rounded-md border border-rule bg-sunken p-2.5">
                <p className="font-mono text-[11px] text-sky-700 dark:text-sky-300">{trace.target_api}</p>
                <p className="mt-1 break-all font-mono text-[10px] leading-relaxed text-ink-muted">{trace.display_path}</p>
              </li>
            ))}
            {traces.length > 12 && <li className="text-[11px] text-ink-faint">{fmt(t.more, traces.length - 12)}</li>}
          </ul>
        )}
      </Section>
      <Section title={t.source}><SourceBlock state={source} canFetch={canFetchSource} t={t} /></Section>
      <Section title={t.raw}>
        <button type="button" onClick={() => setShowRaw((value) => !value)} className="text-[11px] text-ink-muted underline underline-offset-2 hover:text-ink">
          {showRaw ? t.hideRaw : t.showRaw}
        </button>
        {showRaw && <pre className="mt-2 overflow-x-auto rounded-md border border-rule bg-inset p-3 font-mono text-[10px] leading-relaxed text-ink-muted">{JSON.stringify(fn, null, 2)}</pre>}
      </Section>
    </div>
  );
}

function CallList({ calls, index, field, t }) {
  if (calls.length === 0) return <p className="text-xs text-ink-faint">{t.none}</p>;
  return (
    <ul className="space-y-1">
      {calls.map((call) => {
        const other = index?.functions.get(call[field]);
        return (
          <li key={call.id} className="flex items-baseline justify-between gap-2 text-xs">
            <span className="truncate font-mono text-ink-muted">{other?.name || call[field]}</span>
            <span className="shrink-0 font-mono text-[10px] text-ink-faint">{call.kind}{call.line != null && ` :${call.line}`}</span>
          </li>
        );
      })}
    </ul>
  );
}

function SourceBlock({ state, canFetch, t }) {
  if (!canFetch || state.phase === "unavailable") return <p className="text-xs text-ink-faint">{t.noSource}</p>;
  if (state.phase === "loading") return <p className="text-xs text-ink-faint">{t.loadingSource}</p>;
  if (state.phase === "error") {
    const status = state.error.status;
    return <p className="text-xs text-amber-700 dark:text-amber-300">{status === 403 ? t.source403 : status === 404 ? t.source404 : `${t.sourceError} ${state.error.message || ""}`}</p>;
  }
  if (state.phase !== "ready") return null;
  return (
    <div>
      <p className="mb-1.5 break-all font-mono text-[10px] text-ink-faint">{state.payload.file}</p>
      <pre className="max-h-96 overflow-auto rounded-md border border-rule bg-inset p-3 font-mono text-[10px] leading-relaxed text-ink">{state.payload.text}</pre>
    </div>
  );
}

function ResourcePanel({ resource, t }) {
  return (
    <div>
      <Section title={t.daemonResource}>
        <p className="font-mono text-sm text-ink">{resource.kind} {resource.name}</p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <Badge tone={resource.resolved ? "green" : "rose"}>{resource.resolved ? t.resolved : t.unresolved}</Badge>
          {resource.shared && <Badge tone="amber">{fmt(t.shared, resource.processes.size)}</Badge>}
        </div>
      </Section>
      <Section title={t.touching} count={resource.processes.size}>
        <ul className="space-y-1">{[...resource.processes].sort().map((name) => <li key={name} className="font-mono text-xs text-ink-muted">{name}</li>)}</ul>
      </Section>
      <Section title={t.note}><p className="text-xs leading-relaxed text-ink-muted">{t.resourceNote}</p></Section>
    </div>
  );
}

function ProcessPanel({ process, index, t }) {
  return (
    <div>
      <Section title={t.process}>
        <p className="font-mono text-sm text-ink">{process.name}</p>
        <p className="mt-1 break-all font-mono text-[11px] text-ink-muted">{index?.process.root || ""}</p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <Badge>{fmt(t.functions, process.functionCount)}</Badge>
          <Badge>{fmt(t.resources, process.resourceCount)}</Badge>
          <Badge tone="green">{fmt(t.interactions, process.interactionCount)}</Badge>
        </div>
      </Section>
      <Section title={t.entry}>
        <p className="font-mono text-xs text-ink-muted">{index?.entryId ? index.functions.get(index.entryId)?.name || index.entryId : t.noEntry}</p>
      </Section>
      <Section title={t.next}><p className="text-xs leading-relaxed text-ink-muted">{t.nextHelp}</p></Section>
    </div>
  );
}
