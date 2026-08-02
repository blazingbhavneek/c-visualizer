import { Send, Square } from "lucide-react";
import { useState } from "react";
import { useT } from "../i18n.jsx";

const STR = {
  ja: {
    initial: "コードについて質問…",
    followup: "追加の質問…",
    fast: "Fast",
    deep: "Deep",
    send: "質問を送信",
    stop: "停止",
    mode: "調査モード",
  },
  en: {
    initial: "Ask about the code…",
    followup: "Ask a follow-up…",
    fast: "Fast",
    deep: "Deep",
    send: "Send question",
    stop: "Stop",
    mode: "Research mode",
  },
};

export default function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  isStreaming,
  hasConversation,
  disabled = false,
}) {
  const t = useT(STR);
  const [mode, setMode] = useState("deep");

  const submit = () => {
    if (!isStreaming && !disabled && value.trim()) onSubmit(value, mode);
  };

  return (
    <div className="rounded-2xl border border-rule-strong bg-panel/95 p-2 shadow-[0_12px_40px_rgba(15,23,42,0.16)] backdrop-blur">
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        rows={2}
        disabled={isStreaming || disabled}
        placeholder={hasConversation ? t.followup : t.initial}
        className="block max-h-40 min-h-14 w-full resize-none bg-transparent px-2 py-1.5 text-sm leading-relaxed text-ink outline-none placeholder:text-ink-faint disabled:opacity-60"
      />
      <div className="flex items-center justify-between gap-2 border-t border-rule px-1 pt-2">
        <label className="sr-only" htmlFor="ask-mode">
          {t.mode}
        </label>
        <select
          id="ask-mode"
          value={mode}
          onChange={(event) => setMode(event.target.value)}
          disabled={isStreaming}
          className="rounded-full border border-rule bg-sunken px-2.5 py-1 text-[11px] font-semibold text-ink-muted outline-none hover:border-rule-strong"
        >
          <option value="fast">{t.fast}</option>
          <option value="deep">{t.deep}</option>
        </select>
        {isStreaming ? (
          <button
            type="button"
            onClick={onStop}
            className="flex items-center gap-1.5 rounded-full bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-rose-700"
          >
            <Square size={11} fill="currentColor" /> {t.stop}
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={disabled || !value.trim()}
            aria-label={t.send}
            className="rounded-full bg-ink p-2 text-paper transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <Send size={15} />
          </button>
        )}
      </div>
    </div>
  );
}
