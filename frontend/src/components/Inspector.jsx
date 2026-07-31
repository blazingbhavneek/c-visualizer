import { useEffect, useMemo, useState } from "react";
import { fetchSource } from "../api.js";
import { interactionDirection } from "../graph/model.js";

export default function Inspector({ selection, index, runId }) {
  return (
    <aside className="flex w-[26rem] shrink-0 flex-col border-l border-ink-700 bg-ink-900">
      <header className="border-b border-ink-700 px-5 py-4">
        <h1 className="text-sm font-semibold tracking-wide text-slate-200">Inspector</h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Static-analysis evidence for the selected element
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!selection && <EmptyState />}
        {selection?.type === "function" && (
          <FunctionPanel selection={selection} index={index} runId={runId} />
        )}
        {selection?.type === "resource" && <ResourcePanel resource={selection.resource} />}
        {selection?.type === "process" && <ProcessPanel process={selection.process} index={index} />}
      </div>
    </aside>
  );
}

function EmptyState() {
  return (
    <div className="px-5 py-6 text-sm leading-relaxed text-slate-500">
      <p>Nothing selected.</p>
      <ul className="mt-3 space-y-1.5 text-xs">
        <li>Click a process on the ground plane to raise its call tree.</li>
        <li>Click a function in a tree to see its evidence here.</li>
        <li>Click a daemon resource to see which processes touch it.</li>
      </ul>
    </div>
  );
}

function Section({ title, count, children }) {
  return (
    <section className="border-b border-ink-700/70 px-5 py-4">
      <h2 className="mb-2.5 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        {title}
        {count != null && <span className="font-normal normal-case text-slate-600">{count}</span>}
      </h2>
      {children}
    </section>
  );
}

function Badge({ tone = "slate", children }) {
  const tones = {
    slate: "border-ink-700 bg-ink-800 text-slate-300",
    amber: "border-amber-700/50 bg-amber-950/50 text-amber-300",
    green: "border-emerald-700/50 bg-emerald-950/50 text-emerald-300",
    rose: "border-rose-700/50 bg-rose-950/50 text-rose-300",
    violet: "border-violet-700/50 bg-violet-950/50 text-violet-300",
  };
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

function FunctionPanel({ selection, index, runId }) {
  const fn = selection.node.fn;
  const [source, setSource] = useState({ phase: "idle" });
  const [showRaw, setShowRaw] = useState(false);

  const canFetchSource =
    !!index && !fn.is_external && !fn.synthetic && !!fn.file && fn.start_line > 0;

  useEffect(() => {
    if (!canFetchSource || !runId) {
      setSource({ phase: "unavailable" });
      return;
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
    return index.traces.filter((trace) =>
      trace.labels.some((label) => label.includes(fn.name)),
    );
  }, [index, fn.name]);

  return (
    <div>
      <Section title="Function">
        <p className="font-mono text-sm break-all text-slate-100">{fn.name}</p>
        <p className="mt-1 font-mono text-xs break-all text-slate-500">
          {fn.file_name || "—"}
          {fn.start_line > 0 ? ` [${fn.start_line}:${fn.end_line}]` : ""}
        </p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {fn.is_external && <Badge tone="slate">external</Badge>}
          {fn.is_static && <Badge tone="amber">static</Badge>}
          {selection.node.recursive && <Badge tone="violet">recursion back-edge</Badge>}
          {selection.node.unreached && (
            <Badge tone="rose">
              {selection.node.isolated ? "no recorded call at all" : "no path from main"}
            </Badge>
          )}
          {fn.synthetic && <Badge tone="slate">synthetic root</Badge>}
          <Badge tone="slate">{fn.call_count} calls</Badge>
          {fn.resource_interaction_count > 0 && (
            <Badge tone="green">{fn.resource_interaction_count} interactions</Badge>
          )}
        </div>
      </Section>

      <Section title="AI explanation">
        {fn.summary ? (
          <p className="text-sm leading-relaxed text-slate-200">{fn.summary}</p>
        ) : (
          <div className="rounded-md border border-dashed border-ink-700 bg-ink-850/60 p-3">
            <p className="text-xs leading-relaxed text-slate-500">
              No model-written summary in this snapshot.{" "}
              <span className="font-mono text-slate-400">summary_status: {fn.summary_status || "—"}</span>
              {" — "}
              every function in every current snapshot has <span className="font-mono">summary: null</span>,
              so this panel fills in once the pipeline writes summaries.
            </p>
            {fn.summary_hint && (
              <p className="mt-2 border-t border-ink-700 pt-2 text-xs text-slate-400">
                {fn.summary_hint}
              </p>
            )}
          </div>
        )}
      </Section>

      {selection.node.viaCalls?.length > 0 && (
        <Section title="Reached via" count={selection.node.viaCalls.length}>
          <p className="mb-2 text-[11px] leading-relaxed text-slate-600">
            Call sites on this tree edge. Parallel calls to the same target share one node, so all
            of them are listed here.
          </p>
          <ul className="space-y-1">
            {selection.node.viaCalls.map((call) => (
              <li key={call.id} className="flex items-baseline justify-between gap-2 text-xs">
                <span className="font-mono text-slate-300">
                  {index?.functions.get(call.source)?.name || call.source}
                </span>
                <span className="shrink-0 font-mono text-[10px] text-slate-600">
                  {call.kind}
                  {call.line != null && ` :${call.line}`}
                  {call.via && ` via ${index?.functions.get(call.via)?.name || call.via}`}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Daemon interactions" count={interactions.length || null}>
        {interactions.length === 0 ? (
          <p className="text-xs text-slate-600">No resource interaction attributed to this function.</p>
        ) : (
          <ul className="space-y-2">
            {interactions.map((interaction) => {
              const resource = index.resources.get(interaction.resource_id);
              const direction = interactionDirection(interaction);
              return (
                <li key={interaction.id} className="rounded-md bg-ink-850 p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-emerald-300">{interaction.target_api}</span>
                    <Badge tone="slate">{interaction.operation}</Badge>
                  </div>
                  <p className="mt-1.5 font-mono text-[11px] text-slate-400">
                    {direction === "in" ? "←" : direction === "out" ? "→" : "↔"}{" "}
                    {resource ? `${resource.kind} ${resource.name}` : interaction.resource_id}
                    {resource && !resource.resolved && (
                      <span className="ml-1.5 text-rose-400">unresolved</span>
                    )}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-600">
                    arg #{interaction.argument_binding?.argument_index} ={" "}
                    <span className="font-mono">{String(interaction.argument_binding?.value)}</span>
                    {interaction.launch_via && ` · via ${interaction.launch_via}`}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section title="Outgoing calls" count={outgoing.length || null}>
        <CallList calls={outgoing} index={index} field="target" />
      </Section>

      <Section title="Called by" count={incoming.length || null}>
        <CallList calls={incoming} index={index} field="source" />
      </Section>

      <Section title="Traces mentioning this name" count={traces.length || null}>
        {traces.length === 0 ? (
          <p className="text-xs text-slate-600">No trace path contains this function name.</p>
        ) : (
          <ul className="space-y-2">
            {traces.slice(0, 12).map((trace) => (
              <li key={trace.id} className="rounded-md bg-ink-850 p-2.5">
                <p className="font-mono text-[11px] text-sky-300">{trace.target_api}</p>
                <p className="mt-1 font-mono text-[10px] leading-relaxed break-all text-slate-500">
                  {trace.display_path}
                </p>
              </li>
            ))}
            {traces.length > 12 && (
              <li className="text-[11px] text-slate-600">+{traces.length - 12} more</li>
            )}
          </ul>
        )}
      </Section>

      <Section title="Source">
        <SourceBlock state={source} canFetch={canFetchSource} />
      </Section>

      <Section title="Raw">
        <button
          type="button"
          onClick={() => setShowRaw((value) => !value)}
          className="text-[11px] text-slate-500 underline underline-offset-2 hover:text-slate-300"
        >
          {showRaw ? "Hide" : "Show"} raw snapshot fields
        </button>
        {showRaw && (
          <pre className="mt-2 overflow-x-auto rounded-md bg-ink-950 p-3 font-mono text-[10px] leading-relaxed text-slate-400">
            {JSON.stringify(fn, null, 2)}
          </pre>
        )}
      </Section>
    </div>
  );
}

function CallList({ calls, index, field }) {
  if (calls.length === 0) {
    return <p className="text-xs text-slate-600">None recorded.</p>;
  }
  return (
    <ul className="space-y-1">
      {calls.map((call) => {
        const other = index?.functions.get(call[field]);
        return (
          <li key={call.id} className="flex items-baseline justify-between gap-2 text-xs">
            <span className="truncate font-mono text-slate-300">{other?.name || call[field]}</span>
            <span className="shrink-0 font-mono text-[10px] text-slate-600">
              {call.kind}
              {call.line != null && ` :${call.line}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function SourceBlock({ state, canFetch }) {
  if (!canFetch || state.phase === "unavailable") {
    return (
      <p className="text-xs text-slate-600">
        No source evidence — external, synthetic, or no recorded definition range.
      </p>
    );
  }
  if (state.phase === "loading") return <p className="text-xs text-slate-600">Loading source…</p>;
  if (state.phase === "error") {
    const status = state.error.status;
    return (
      <p className="text-xs text-amber-400">
        {status === 403
          ? "Source lies outside this process root (403)."
          : status === 404
            ? "Source file not available (404)."
            : state.error.message}
      </p>
    );
  }
  if (state.phase !== "ready") return null;
  return (
    <div>
      <p className="mb-1.5 font-mono text-[10px] break-all text-slate-600">{state.payload.file}</p>
      <pre className="max-h-96 overflow-auto rounded-md bg-ink-950 p-3 font-mono text-[10px] leading-relaxed text-slate-300">
        {state.payload.text}
      </pre>
    </div>
  );
}

function ResourcePanel({ resource }) {
  return (
    <div>
      <Section title="Daemon resource">
        <p className="font-mono text-sm text-slate-100">
          {resource.kind} {resource.name}
        </p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {resource.resolved ? (
            <Badge tone="green">resolved</Badge>
          ) : (
            <Badge tone="rose">unresolved</Badge>
          )}
          {resource.shared && <Badge tone="amber">shared by {resource.processes.size}</Badge>}
        </div>
      </Section>
      <Section title="Processes touching it" count={resource.processes.size}>
        <ul className="space-y-1">
          {[...resource.processes].sort().map((name) => (
            <li key={name} className="font-mono text-xs text-slate-300">
              {name}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Note">
        <p className="text-xs leading-relaxed text-slate-500">
          Resources are keyed by <span className="font-mono">kind + name</span> across snapshots
          because IDs are per-snapshot hashes. This is analysis evidence from the model-assisted
          results, not a live daemon inventory.
        </p>
      </Section>
    </div>
  );
}

function ProcessPanel({ process, index }) {
  return (
    <div>
      <Section title="Process">
        <p className="font-mono text-sm text-slate-100">{process.name}</p>
        <p className="mt-1 font-mono text-[11px] break-all text-slate-500">
          {index?.process.root || ""}
        </p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <Badge tone="slate">{process.functionCount} functions</Badge>
          <Badge tone="slate">{process.resourceCount} resources</Badge>
          <Badge tone="green">{process.interactionCount} interactions</Badge>
        </div>
      </Section>
      <Section title="Entry">
        <p className="font-mono text-xs text-slate-300">
          {index?.entryId
            ? index.functions.get(index.entryId)?.name || index.entryId
            : "no entry function — plane uses graph roots"}
        </p>
      </Section>
      <Section title="Next">
        <p className="text-xs leading-relaxed text-slate-500">
          Its call tree is now raised on a plane anchored to this node. Click any function in that
          tree to inspect it.
        </p>
      </Section>
    </div>
  );
}
