import type { ReactNode } from "react";

export function LibraryIdentity({ name, subtitle, color, children }: {
  name: string; subtitle: string; color?: string; children?: ReactNode;
}) {
  return <header className="flex min-w-0 items-start gap-3 pr-9">
    {color && <span aria-hidden="true" className="h-12 w-12 shrink-0 rounded-lg ring-1 ring-inset ring-black/10 dark:ring-white/15" style={{ backgroundColor: color }} />}
    <div className="min-w-0"><h3 className="break-words text-lg font-semibold leading-snug">{name}</h3>
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>{children}</div>
  </header>;
}

export function LibraryFields({ rows }: { rows: { label: string; value: ReactNode; multiline?: boolean }[] }) {
  return <dl className="grid gap-3 text-sm">{rows.map(({label, value, multiline}) =>
    <div key={label} className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1.5">
      <dt className="shrink-0 text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className={`ml-auto min-w-0 max-w-full text-right tabular-nums ${multiline ? "break-all" : "break-words"}`}>{value}</dd>
    </div>)}</dl>;
}
