import { Box, MessageSquare, Moon, Share2, Sun } from "lucide-react";
import { useState } from "react";
import { LangToggle, useResolvedTheme, useT } from "../i18n.jsx";

const STR = {
  ja: {
    product: "DeepWiki",
    chat: "チャット",
    graph: "グラフ",
    share: "共有",
    copied: "コピー済み",
    dark: "ダークモード",
    light: "ライトモード",
    primary: "主要表示",
  },
  en: {
    product: "DeepWiki",
    chat: "Chat",
    graph: "Graph",
    share: "Share",
    copied: "Copied",
    dark: "Dark mode",
    light: "Light mode",
    primary: "Primary view",
  },
};

export default function TopBar({ view, onChangeView }) {
  const t = useT(STR);
  const { resolvedTheme, setTheme } = useResolvedTheme();
  const [copied, setCopied] = useState(false);

  const share = async () => {
    try {
      if (navigator.share) {
        await navigator.share({ title: document.title, url: window.location.href });
      } else {
        await navigator.clipboard.writeText(window.location.href);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      }
    } catch {
      // Cancelling the native share sheet needs no UI error.
    }
  };

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-rule bg-panel px-3 sm:px-5">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold tracking-tight text-ink">{t.product}</p>
      </div>

      <nav className="flex rounded-lg bg-sunken p-1" aria-label={t.primary}>
        <ViewButton
          active={view === "chat"}
          onClick={() => onChangeView("chat")}
          icon={MessageSquare}
        >
          {t.chat}
        </ViewButton>
        <ViewButton active={view === "graph"} onClick={() => onChangeView("graph")} icon={Box}>
          {t.graph}
        </ViewButton>
      </nav>

      <button
        type="button"
        onClick={share}
        title={t.share}
        className="hidden items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-ink-muted hover:bg-sunken hover:text-ink sm:flex"
      >
        <Share2 size={14} /> {copied ? t.copied : t.share}
      </button>
      <LangToggle />
      <button
        type="button"
        onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        title={resolvedTheme === "dark" ? t.light : t.dark}
        aria-label={resolvedTheme === "dark" ? t.light : t.dark}
        className="rounded-md border border-rule bg-panel p-2 text-ink-muted transition hover:border-rule-strong hover:text-ink"
      >
        {resolvedTheme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
      </button>
    </header>
  );
}

function ViewButton({ active, onClick, icon: Icon, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition ${
        active ? "bg-panel text-ink shadow-sm" : "text-ink-muted hover:text-ink"
      }`}
    >
      <Icon size={14} />
      <span className="hidden sm:inline">{children}</span>
    </button>
  );
}
