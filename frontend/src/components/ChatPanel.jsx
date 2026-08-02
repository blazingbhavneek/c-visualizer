import { AlertTriangle, LoaderCircle, MessageSquareText } from "lucide-react";
import { useState } from "react";
import { useT } from "../i18n.jsx";
import ActivityLog from "./ActivityLog.jsx";
import AnswerMarkdown from "./AnswerMarkdown.jsx";
import Composer from "./Composer.jsx";
import EvidenceRail from "./EvidenceRail.jsx";

const STR = {
  ja: {
    answer: "回答",
    researching: "調査中…",
    cancelled: "この質問は停止された。",
    error: "回答を取得できなかった",
    cold: "検索インデックスは準備中または未構築です。構造情報だけで回答を試みます。",
    unavailable: "チャット API に接続できません。グラフ表示は引き続き利用できます。",
    emptyTitle: "コードについて質問する",
    emptyBody: "関数の役割、main からの呼び出し経路、デーモン資源との相互作用を調べられる。",
    suggestions: [
      "main から履歴保存 API までの経路は？",
      "イベントを送信する関数と資源を一覧にして",
      "到達不能な関数にはどのようなものがある？",
    ],
  },
  en: {
    answer: "Answer",
    researching: "Researching…",
    cancelled: "This question was stopped.",
    error: "Could not get an answer",
    cold: "The retrieval index is building or unavailable. Structural questions can still be answered.",
    unavailable: "The chat API is unavailable. Graph browsing remains available.",
    emptyTitle: "Ask about this codebase",
    emptyBody: "Explore function roles, invocation paths from main, and interactions with daemon resources.",
    suggestions: [
      "What path leads from main to the history API?",
      "List the functions and resources that post events",
      "What kinds of functions are unreachable?",
    ],
  },
};

export default function ChatPanel({
  turns,
  latestCompleted,
  draft,
  onDraftChange,
  onAsk,
  onStop,
  isStreaming,
  wiki,
  wikiError,
  onReveal,
  onShowGraph,
}) {
  const t = useT(STR);
  const [focusTarget, setFocusTarget] = useState(null);

  const navigateEvidence = (target) =>
    setFocusTarget({ ...target, nonce: Date.now() + Math.random() });

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-paper lg:flex-row">
      <main className="relative min-h-0 min-w-0 flex-1 lg:w-[40%]">
        <div className="h-full overflow-y-auto px-4 pb-40 pt-6 sm:px-7 lg:px-8">
          {wiki?.ready === false && <Notice>{t.cold}</Notice>}
          {wikiError && <Notice tone="error">{t.unavailable}</Notice>}

          {turns.length === 0 ? (
            <EmptyChat t={t} onChoose={onDraftChange} />
          ) : (
            <div className="mx-auto max-w-3xl space-y-10">
              {turns.map((turn) => (
                <article key={turn.id}>
                  <h1 className="text-xl font-semibold leading-snug tracking-tight text-ink sm:text-2xl">
                    {turn.question}
                  </h1>

                  {turn.status === "streaming" && (
                    <div className="mt-5 rounded-xl border border-rule bg-panel p-5 shadow-sm">
                      <div className="flex items-center gap-2 text-sm text-ink-muted">
                        <LoaderCircle size={16} className="animate-spin text-sky-600" />
                        {t.researching}
                      </div>
                    </div>
                  )}

                  {turn.answer && (
                    <section className="mt-5 rounded-xl border border-rule bg-panel shadow-sm">
                      <header className="border-b border-rule px-5 py-3.5">
                        <h2 className="text-sm font-semibold text-ink">{t.answer}</h2>
                      </header>
                      <div className="px-5 py-5">
                        <AnswerMarkdown
                          text={turn.answer}
                          evidence={turn}
                          onNavigate={navigateEvidence}
                          onReveal={onReveal}
                          onShowGraph={onShowGraph}
                        />
                      </div>
                    </section>
                  )}

                  {turn.status === "error" && (
                    <div className="mt-5 flex gap-2 rounded-lg border border-rose-400/60 bg-rose-500/10 p-3 text-sm text-rose-700 dark:text-rose-300">
                      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                      <span><strong>{t.error}:</strong> {turn.error}</span>
                    </div>
                  )}
                  {turn.status === "cancelled" && (
                    <p className="mt-4 text-sm text-ink-faint">{t.cancelled}</p>
                  )}
                  <ActivityLog activity={turn.activity} status={turn.status} />
                </article>
              ))}
            </div>
          )}
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-paper via-paper/95 to-transparent px-4 pb-4 pt-10 sm:px-7 lg:px-8">
          <div className="pointer-events-auto mx-auto max-w-3xl">
            <Composer
              value={draft}
              onChange={onDraftChange}
              onSubmit={(question, mode) => {
                onAsk(question, mode);
                onDraftChange("");
              }}
              onStop={onStop}
              isStreaming={isStreaming}
              hasConversation={turns.length > 0}
            />
          </div>
        </div>
      </main>

      <EvidenceRail turn={latestCompleted} focusTarget={focusTarget} onReveal={onReveal} />
    </div>
  );
}

function Notice({ children, tone = "warning" }) {
  return (
    <div
      className={`mx-auto mb-5 max-w-3xl rounded-lg border px-3 py-2 text-xs leading-relaxed ${
        tone === "error"
          ? "border-rose-400/60 bg-rose-500/10 text-rose-700 dark:text-rose-300"
          : "border-amber-400/60 bg-amber-500/10 text-amber-700 dark:text-amber-300"
      }`}
    >
      {children}
    </div>
  );
}

function EmptyChat({ t, onChoose }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center py-12 text-center lg:py-24">
      <div className="mb-5 rounded-2xl border border-rule bg-panel p-4 text-sky-700 shadow-sm dark:text-sky-300">
        <MessageSquareText size={28} />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight text-ink">{t.emptyTitle}</h1>
      <p className="mt-3 max-w-md text-sm leading-relaxed text-ink-muted">{t.emptyBody}</p>
      <div className="mt-7 flex flex-wrap justify-center gap-2">
        {t.suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onChoose(suggestion)}
            className="rounded-full border border-rule bg-panel px-3 py-2 text-xs text-ink-muted shadow-sm transition hover:border-rule-strong hover:text-ink"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
