import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Network,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n.jsx";
import { Badge } from "./ui.jsx";

const STR = {
  ja: {
    evidence: "根拠",
    sources: "出典",
    paths: "呼び出し経路",
    resources: "デーモン資源",
    empty: "回答が完了すると、出典・呼び出し経路・デーモン資源がここに表示される。",
    copy: "コピー",
    copied: "コピー済み",
    graph: "グラフで表示",
    noSource: "この外部／ライブラリ関数にはソース根拠がない。",
    resolved: "解決済み",
    unresolved: "未解決",
    functions: "関連関数",
    processes: "プロセス",
    trace: "tracer 経路",
    bfs: "BFS 経路",
    via: "経由",
    pathNote: "複数プロセスにまたがる経路では、最初の関数のプロセス平面を表示する。",
    collapse: "根拠パネルを閉じる",
    expand: "根拠パネルを開く",
  },
  en: {
    evidence: "Evidence",
    sources: "Sources",
    paths: "Invocation paths",
    resources: "Daemon resources",
    empty: "Sources, invocation paths, and daemon resources appear here when an answer completes.",
    copy: "Copy",
    copied: "Copied",
    graph: "View in graph",
    noSource: "No source evidence is available for this external or library function.",
    resolved: "resolved",
    unresolved: "unresolved",
    functions: "Functions",
    processes: "Processes",
    trace: "tracer path",
    bfs: "BFS path",
    via: "via",
    pathNote: "For a path spanning processes, the graph opens the first function's process plane.",
    collapse: "Collapse evidence rail",
    expand: "Expand evidence rail",
  },
};

function functionIdsForPath(path) {
  return (path.steps || []).map((step) => step.function_id).filter(Boolean);
}

function edgeKeysForPath(path) {
  const ids = functionIdsForPath(path);
  return ids.slice(1).map((id, index) => `${ids[index]}->${id}`);
}

export default function EvidenceRail({ turn, focusTarget, onReveal }) {
  const t = useT(STR);
  const [collapsed, setCollapsed] = useState(false);
  const [expandedSources, setExpandedSources] = useState(new Set());
  const [copied, setCopied] = useState(null);
  const [highlighted, setHighlighted] = useState(null);
  const refs = useRef({ function: new Map(), path: new Map(), resource: new Map() });

  useEffect(() => {
    if (!focusTarget) return undefined;
    setCollapsed(false);
    if (focusTarget.kind === "function") {
      setExpandedSources((current) => new Set(current).add(focusTarget.id));
    }
    setHighlighted(`${focusTarget.kind}:${focusTarget.id}`);
    const scrollTimer = window.setTimeout(() => {
      refs.current[focusTarget.kind]?.get(focusTarget.id)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 80);
    const clearTimer = window.setTimeout(() => setHighlighted(null), 1800);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
    };
  }, [focusTarget]);

  const copySource = async (item) => {
    const text = item.source || `${item.file || item.file_name}:${item.start_line}-${item.end_line}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(item.id);
      window.setTimeout(() => setCopied(null), 1400);
    } catch {
      // Clipboard access can be denied when the app is not on a secure origin.
    }
  };

  if (collapsed) {
    return (
      <aside className="flex shrink-0 justify-center border-t border-rule bg-panel p-2 lg:w-12 lg:border-l lg:border-t-0">
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          title={t.expand}
          aria-label={t.expand}
          className="flex h-9 items-center gap-2 rounded-md border border-rule px-2 text-xs text-ink-muted hover:text-ink lg:w-8 lg:justify-center lg:px-0"
        >
          <ChevronLeft size={15} className="hidden lg:block" />
          <ChevronDown size={15} className="lg:hidden" />
          <span className="lg:hidden">{t.evidence}</span>
        </button>
      </aside>
    );
  }

  const hasEvidence = Boolean(turn?.cited?.length || turn?.paths?.length || turn?.resources?.length);
  return (
    <aside className="flex h-[42%] min-h-0 shrink-0 flex-col border-t border-rule bg-panel lg:h-auto lg:w-[60%] lg:border-l lg:border-t-0">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-rule px-4">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-faint">{t.evidence}</h2>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          title={t.collapse}
          aria-label={t.collapse}
          className="rounded p-1.5 text-ink-faint hover:bg-sunken hover:text-ink"
        >
          <ChevronRight size={15} className="hidden lg:block" />
          <ChevronDown size={15} className="lg:hidden" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!hasEvidence && <p className="px-5 py-8 text-sm leading-relaxed text-ink-faint">{t.empty}</p>}

        {turn?.cited?.length > 0 && (
          <RailSection
            title={t.sources}
            count={turn.cited.length}
            forceOpen={focusTarget?.kind === "function" ? focusTarget.nonce : null}
          >
            <div className="divide-y divide-rule">
              {turn.cited.map((item) => {
                const open = expandedSources.has(item.id);
                const active = highlighted === `function:${item.id}`;
                return (
                  <article
                    key={item.id}
                    ref={(node) => node && refs.current.function.set(item.id, node)}
                    className={`p-3 transition ${active ? "bg-sky-500/10 ring-2 ring-inset ring-sky-400" : ""}`}
                  >
                    <div className="flex items-start gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedSources((current) => {
                            const next = new Set(current);
                            if (next.has(item.id)) next.delete(item.id);
                            else next.add(item.id);
                            return next;
                          })
                        }
                        className="mt-0.5 rounded p-0.5 text-ink-faint hover:text-ink"
                      >
                        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </button>
                      <button
                        type="button"
                        onClick={() => setExpandedSources((current) => new Set(current).add(item.id))}
                        className="min-w-0 flex-1 text-left"
                      >
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge tone="slate">{item.process || "—"}</Badge>
                          <span className="truncate font-mono text-xs text-ink">{item.file_name || item.file || "—"}</span>
                        </div>
                        <p className="mt-1 truncate font-mono text-[11px] text-ink-muted">
                          {item.name || item.id}
                          {item.start_line > 0 ? ` · ${item.start_line}:${item.end_line}` : ""}
                        </p>
                      </button>
                      <button
                        type="button"
                        onClick={() => copySource(item)}
                        title={copied === item.id ? t.copied : t.copy}
                        className="rounded p-1.5 text-ink-faint hover:bg-sunken hover:text-ink"
                      >
                        {copied === item.id ? <Check size={13} /> : <Copy size={13} />}
                      </button>
                      <GraphButton label={t.graph} onClick={() => onReveal?.([item.id])} />
                    </div>
                    {open && (
                      item.source ? (
                        <pre className="mt-3 max-h-96 overflow-auto rounded-md border border-rule bg-inset p-3 font-mono text-[10px] leading-relaxed text-ink">
                          {item.source}
                        </pre>
                      ) : (
                        <p className="mt-3 rounded-md bg-sunken p-3 text-xs text-ink-faint">{t.noSource}</p>
                      )
                    )}
                  </article>
                );
              })}
            </div>
          </RailSection>
        )}

        {turn?.paths?.length > 0 && (
          <RailSection
            title={t.paths}
            count={turn.paths.length}
            forceOpen={focusTarget?.kind === "path" ? focusTarget.nonce : null}
          >
            <p className="border-b border-rule px-4 py-2 text-[11px] leading-relaxed text-ink-faint">{t.pathNote}</p>
            <div className="divide-y divide-rule">
              {turn.paths.map((path) => {
                const active = highlighted === `path:${path.id}`;
                return (
                  <article
                    key={path.id}
                    ref={(node) => node && refs.current.path.set(path.id, node)}
                    className={`p-4 transition ${active ? "bg-sky-500/10 ring-2 ring-inset ring-sky-400" : ""}`}
                  >
                    <div className="mb-3 flex items-start justify-between gap-2">
                      <div>
                        <p className="font-mono text-xs text-ink">{path.label}</p>
                        <div className="mt-1.5 flex gap-1.5">
                          <Badge tone={path.origin === "trace" ? "green" : "amber"}>
                            {path.origin === "trace" ? t.trace : t.bfs}
                          </Badge>
                          {path.process && <Badge>{path.process}</Badge>}
                        </div>
                      </div>
                      <GraphButton
                        label={t.graph}
                        onClick={() => onReveal?.(functionIdsForPath(path), edgeKeysForPath(path))}
                      />
                    </div>
                    <div className="flex flex-wrap items-center gap-y-2">
                      {(path.steps || []).map((step, index) => (
                        <span key={`${step.function_id}:${index}`} className="flex items-center">
                          {index > 0 && (
                            <span className="mx-1.5 flex min-w-8 flex-col items-center text-ink-faint">
                              <span>→</span>
                              {step.kind === "callback" && (
                                <span className="max-w-28 text-center text-[9px] leading-tight text-violet-600 dark:text-violet-300">
                                  {t.via} {step.via || "callback"}
                                </span>
                              )}
                            </span>
                          )}
                          <button
                            type="button"
                            onClick={() => onReveal?.([step.function_id])}
                            className={`rounded-md border px-2 py-1 text-left font-mono text-[10px] transition hover:border-rule-strong ${
                              step.kind === "callback"
                                ? "border-violet-400/60 bg-violet-500/10 text-violet-700 dark:text-violet-300"
                                : "border-rule bg-sunken text-ink-muted hover:text-ink"
                            }`}
                          >
                            {step.name}
                            <span className="block text-[9px] opacity-70">
                              {step.file_name || "—"}{step.line ? `:${step.line}` : ""}
                            </span>
                          </button>
                        </span>
                      ))}
                    </div>
                  </article>
                );
              })}
            </div>
          </RailSection>
        )}

        {turn?.resources?.length > 0 && (
          <RailSection
            title={t.resources}
            count={turn.resources.length}
            forceOpen={focusTarget?.kind === "resource" ? focusTarget.nonce : null}
          >
            <div className="divide-y divide-rule">
              {turn.resources.map((resource) => {
                const active = highlighted === `resource:${resource.key}`;
                const glyph = resource.direction === "in" ? "←" : resource.direction === "out" ? "→" : "↔";
                return (
                  <article
                    key={resource.key}
                    ref={(node) => node && refs.current.resource.set(resource.key, node)}
                    className={`p-4 transition ${active ? "bg-sky-500/10 ring-2 ring-inset ring-sky-400" : ""}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-lg text-emerald-600">{glyph}</span>
                      <span className="font-mono text-xs text-ink">{resource.kind} {resource.name}</span>
                      <Badge tone={resource.resolved ? "green" : "rose"}>
                        {resource.resolved ? t.resolved : t.unresolved}
                      </Badge>
                      {(resource.operations || []).map((operation) => <Badge key={operation}>{operation}</Badge>)}
                    </div>
                    {(resource.processes || []).length > 0 && (
                      <p className="mt-2 text-[11px] text-ink-faint">
                        {t.processes}: <span className="font-mono text-ink-muted">{resource.processes.join(", ")}</span>
                      </p>
                    )}
                    {(resource.functions || []).length > 0 && (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] text-ink-faint">{t.functions}:</span>
                        {resource.functions.map((fn) => (
                          <button
                            key={fn.id}
                            type="button"
                            onClick={() => onReveal?.([fn.id])}
                            className="rounded border border-rule bg-sunken px-1.5 py-0.5 font-mono text-[10px] text-ink-muted hover:text-ink"
                          >
                            {fn.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </RailSection>
        )}
      </div>
    </aside>
  );
}

function GraphButton({ label, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="flex shrink-0 items-center gap-1 rounded-md border border-rule bg-panel px-2 py-1.5 text-[10px] text-ink-faint hover:border-rule-strong hover:text-ink"
    >
      <Network size={12} /> {label}
    </button>
  );
}

function RailSection({ title, count, forceOpen, children }) {
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (forceOpen) setOpen(true);
  }, [forceOpen]);
  return (
    <section className="border-b border-rule">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 bg-sunken/50 px-4 py-3 text-left"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{title}</span>
        <Badge>{count}</Badge>
      </button>
      {open && children}
    </section>
  );
}
