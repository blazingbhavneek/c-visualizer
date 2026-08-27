import { Network } from "lucide-react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { useT } from "../i18n.jsx";

const STR = {
  ja: { graph: "グラフで表示" },
  en: { graph: "View in graph" },
};

function parseCitation(href) {
  if (!href?.startsWith("cg://")) return null;
  const value = href.slice(5);
  const slash = value.indexOf("/");
  if (slash < 0) return null;
  try {
    return { kind: value.slice(0, slash), id: decodeURIComponent(value.slice(slash + 1)) };
  } catch {
    return null;
  }
}

function pathTarget(path) {
  const functionIds = (path?.steps || []).map((step) => step.function_id).filter(Boolean);
  const edgeKeys = functionIds.slice(1).map((id, index) => `${functionIds[index]}->${id}`);
  return { functionIds, edgeKeys };
}

function citedProcess(evidence, functionId) {
  const item = evidence?.cited?.find((entry) => entry.id === functionId);
  return item?.process || item?.processes?.[0] || null;
}

export default function AnswerMarkdown({ text, evidence, onNavigate, onReveal, onShowGraph }) {
  const t = useT(STR);

  const revealCitation = (citation) => {
    if (citation.kind === "function") {
      onReveal?.([citation.id], [], citedProcess(evidence, citation.id));
      return;
    }
    if (citation.kind === "path") {
      const path = evidence?.paths?.find((item) => item.id === citation.id);
      const target = pathTarget(path);
      if (target.functionIds.length) {
        onReveal?.(target.functionIds, target.edgeKeys, path?.process || null);
      }
      else onShowGraph?.();
      return;
    }
    if (citation.kind === "resource") {
      const resource = evidence?.resources?.find((item) => item.key === citation.id);
      const ids = (resource?.functions || []).map((fn) => fn.id).filter(Boolean);
      const process = resource?.functions?.[0]?.process || resource?.processes?.[0] || null;
      if (ids.length) onReveal?.(ids, [], process);
      else onShowGraph?.();
    }
  };

  return (
    <div className="answer text-sm leading-7 text-ink">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (url.startsWith("cg://") ? url : defaultUrlTransform(url))}
        components={{
          a({ href, children }) {
            const citation = parseCitation(href);
            if (!citation) {
              return (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              );
            }
            return (
              <span className="citation-chip" data-citation-kind={citation.kind}>
                <button type="button" onClick={() => onNavigate?.(citation)}>
                  {children}
                </button>
                <button
                  type="button"
                  onClick={() => revealCitation(citation)}
                  className="citation-graph"
                  title={t.graph}
                  aria-label={t.graph}
                >
                  <Network size={11} />
                  <span>{t.graph}</span>
                </button>
              </span>
            );
          },
          code({ className, children, ...props }) {
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="answer-table-wrap">
                <table>{children}</table>
              </div>
            );
          },
          h2({ children }) {
            return <h2>{children}</h2>;
          },
          h3({ children }) {
            return <h3>{children}</h3>;
          },
        }}
      >
        {text || ""}
      </ReactMarkdown>
    </div>
  );
}
