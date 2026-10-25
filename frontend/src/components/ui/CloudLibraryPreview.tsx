import { useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n } from "../../i18n/context";
import CloseButton from "./CloseButton";

export function CloudLibraryVersionTabs({ modern, onChange }: { modern: boolean; onChange: (value: boolean) => void }) {
  const { t } = useI18n();
  return <div role="tablist" aria-label={t("cloud_library_version")} className="flex shrink-0 gap-1 bg-slate-200 px-5 py-2 dark:bg-slate-800">
    {[true, false].map((value) => <button key={String(value)} type="button" role="tab" aria-selected={modern === value} tabIndex={modern === value ? 0 : -1} onKeyDown={(event) => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); onChange(event.key === "Home" ? true : event.key === "End" ? false : !modern); const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]'); buttons?.[event.key === "Home" ? 0 : event.key === "End" ? 1 : modern ? 1 : 0]?.focus(); } }} onClick={() => onChange(value)} className={`rounded-lg px-4 py-1.5 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${modern === value ? "bg-slate-50 text-slate-900 dark:bg-slate-600 dark:text-slate-50" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700"}`}>{t(value ? "cloud_library_new" : "cloud_library_old")}</button>)}
  </div>;
}
export interface CloudPreviewItem {
  key: string; name: string; subtitle: string; metric?: string; color?: string;
  state: string; action?: ReactNode; detail: ReactNode;
}
export default function CloudLibraryPreview({ items, toolbar, notices, footer, busy, resetKey, versions }: {
  items: CloudPreviewItem[]; toolbar: ReactNode; notices?: ReactNode; footer?: ReactNode;
  busy?: boolean; resetKey: string; versions: ReactNode;
}) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const detail = items.find((item) => item.key === selected);
  const close = () => { setSelected(null); triggerRef.current?.focus(); };
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = 0; setScrolled(false); setSelected(null); }, [resetKey]);
  useEffect(() => { if (selected) closeRef.current?.focus({ preventScroll: window.innerWidth >= 1024 }); }, [selected]);
  return <section className="flex h-full min-h-0 flex-col overflow-hidden bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
    {versions}
    <div className={`flex shrink-0 flex-wrap items-center gap-3 border-b p-4 transition-colors duration-200 motion-reduce:transition-none ${scrolled ? "border-slate-200 dark:border-slate-700" : "border-transparent"}`}>{toolbar}</div>
    <div ref={scrollRef} onScroll={(event) => setScrolled(event.currentTarget.scrollTop > 0)} className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain p-4">
      {notices && <div className="mb-4 grid gap-3" role="status">{notices}</div>}
      <div className={`grid items-start gap-5 ${detail ? "lg:grid-cols-[minmax(0,1fr)_22rem]" : ""}`}>
        <div className="min-w-0" aria-busy={busy}>
          <div className="grid items-stretch gap-4 [grid-template-columns:repeat(auto-fill,min(100%,15rem))]">
            {items.map((item) => <article key={item.key} className={`flex min-w-0 flex-col rounded-[10px] border p-5 ${selected === item.key ? "border-slate-300 bg-slate-200 dark:border-slate-500 dark:bg-slate-700" : "border-slate-200 bg-slate-100 hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700"}`}>
              <button type="button" aria-expanded={selected === item.key} onClick={(event) => { triggerRef.current = event.currentTarget; setSelected(item.key); }} className="flex flex-1 items-start gap-3 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
                {item.color && <span aria-hidden="true" className="h-14 w-14 shrink-0 rounded-lg ring-1 ring-inset ring-black/10" style={{backgroundColor:item.color}} />}
                <span className="min-w-0"><span className="block break-words text-sm font-semibold">{item.name}</span><span className="mt-2 block text-xs text-slate-600 dark:text-slate-300">{item.subtitle}</span>{item.metric && <span className="mt-1 block text-xs text-slate-600 dark:text-slate-300">{item.metric}</span>}</span>
              </button>
              <div className="mt-4 grid gap-2"><span className="text-xs text-slate-600 dark:text-slate-300">{item.state}</span>{item.action}</div>
            </article>)}
          </div>
          {!items.length && <p className="py-12 text-center text-sm text-slate-500">{t(busy ? "lut_sync_loading" : "lut_sync_catalog_empty")}</p>}
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">{footer}</div>
        </div>
        {detail && <aside onKeyDown={(event) => { if(event.key === "Escape") { event.stopPropagation(); close(); } }} className="relative order-first min-w-0 rounded-[10px] border border-slate-200 bg-slate-100 p-5 lg:sticky lg:top-0 lg:order-last lg:max-h-[calc(100vh-16rem)] lg:overflow-y-auto lg:overscroll-y-contain dark:border-slate-700 dark:bg-slate-800">
          <div className="absolute right-5 top-5"><CloseButton ref={closeRef} label={t("announcement_close")} onClick={close} /></div>
          {detail.detail}
        </aside>}
      </div>
    </div>
  </section>;
}
