export function Section({ title, count, children, className = "" }) {
  return (
    <section className={`border-b border-rule px-5 py-4 ${className}`}>
      <h2 className="mb-2.5 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
        {title}
        {count != null && (
          <span className="font-normal normal-case text-ink-faint">{count}</span>
        )}
      </h2>
      {children}
    </section>
  );
}

export function Badge({ tone = "slate", children, className = "" }) {
  const tones = {
    slate: "border-rule bg-sunken text-ink-muted",
    amber: "border-amber-400/60 bg-amber-500/10 text-amber-700 dark:text-amber-300",
    green: "border-emerald-400/60 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
    rose: "border-rose-400/60 bg-rose-500/10 text-rose-700 dark:text-rose-300",
    violet: "border-violet-400/60 bg-violet-500/10 text-violet-700 dark:text-violet-300",
    sky: "border-sky-400/60 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${tones[tone] || tones.slate} ${className}`}
    >
      {children}
    </span>
  );
}
