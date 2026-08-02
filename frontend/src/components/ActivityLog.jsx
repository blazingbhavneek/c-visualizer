import { ChevronDown, ChevronRight, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useT } from "../i18n.jsx";

const STR = {
  ja: { title: "実行ログ", waiting: "エージェントを起動中…", cancelled: "停止しました" },
  en: { title: "Activity", waiting: "Starting agents…", cancelled: "Stopped" },
};

export default function ActivityLog({ activity, status }) {
  const t = useT(STR);
  const [open, setOpen] = useState(status === "streaming");

  useEffect(() => {
    if (status === "streaming") setOpen(true);
    if (status === "complete") setOpen(false);
  }, [status]);

  const newest = activity.at(-1) || (status === "cancelled" ? t.cancelled : t.waiting);
  return (
    <div className="mt-3 overflow-hidden rounded-lg border border-rule bg-panel">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
          {t.title}
        </span>
        {!open && (
          <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-ink-muted">
            {newest}
          </span>
        )}
        {status === "streaming" && <LoaderCircle size={13} className="animate-spin text-sky-600" />}
      </button>
      {open && (
        <ol className="max-h-56 space-y-1 overflow-y-auto border-t border-rule bg-sunken px-3 py-2.5">
          {activity.length === 0 ? (
            <li className="font-mono text-[11px] text-ink-faint">{newest}</li>
          ) : (
            activity.map((line, index) => (
              <li key={`${index}:${line}`} className="font-mono text-[11px] leading-relaxed text-ink-muted">
                {line}
              </li>
            ))
          )}
        </ol>
      )}
    </div>
  );
}
