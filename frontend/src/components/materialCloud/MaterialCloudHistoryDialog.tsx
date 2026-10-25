import TransientBanner from "../ui/TransientBanner";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { MaterialSyncInstalledEntry } from "../../api/types";
import { useI18n } from "../../i18n/context";
import Button from "../ui/Button";
import CloseButton from "../ui/CloseButton";
import { StatusBanner } from "../ui/panelPrimitives";
import { resolveRollbackRevisions } from "./catalogModel";

interface Props {
  entries: MaterialSyncInstalledEntry[];
  pendingRollback: string | null;
  error: string | null;
  success: string | null;
  onDismissSuccess: () => void;
  onClose: () => void;
  onRollback: (entry: MaterialSyncInstalledEntry, revision: string) => void;
}

/** Dates identify local snapshots; revision IDs are only used for API requests. */
export default function MaterialCloudHistoryDialog({ entries, pendingRollback, error, success, onDismissSuccess, onClose, onRollback }: Props) {
  const { t, lang } = useI18n();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [selection, setSelection] = useState<{ material: string; revision: string } | null>(null);
  const selectedEntry = entries.find(entry => entry.material_id === selection?.material
    && resolveRollbackRevisions(entry).includes(selection.revision));
  const closeCallback = useRef(onClose);
  closeCallback.current = onClose;
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus({ preventScroll: true });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeCallback.current(); }
      if (event.key !== "Tab") return;
      const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled)") ?? []);
      if (!controls.length) return;
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0].focus(); }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, []);
  const date = (value?: string | null) => {
    if (!value || !Number.isFinite(Date.parse(value))) return t("mat_sync_history_unknown_date");
    return new Date(value).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  };
  return createPortal(
    <div className="fixed inset-0 z-[10000] flex items-center justify-center p-4 backdrop-blur-sm" style={{ background: "var(--surface-scrim)" }}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="flex max-h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 shadow-2xl dark:border-slate-700 dark:bg-slate-950">
        <div className="flex items-center justify-between gap-4 px-6 pt-6">
          <h2 id={titleId} className="text-base font-semibold text-slate-900 dark:text-slate-100">{t("mat_sync_local_section_title")}</h2>
          <CloseButton ref={closeRef} label={t("mat_sync_history_close")} onClick={onClose} />
        </div>
        <p className="px-6 pb-4 pt-2 text-sm text-slate-500 dark:text-slate-400">{t("mat_sync_history_hint")}</p>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-6">
          {entries.length === 0 && <p className="py-6 text-sm text-slate-500">{t("mat_sync_history_empty")}</p>}
          {entries.map(entry => {
            const history = new Map((entry.revision_history ?? []).map(item => [item.revision_id, item.installed_at]));
            const currentDate = history.get(entry.revision_id) ?? entry.installed_at;
            const revisions = resolveRollbackRevisions(entry).sort((a, b) =>
              (Date.parse(history.get(b) ?? "") || 0) - (Date.parse(history.get(a) ?? "") || 0));
            return <fieldset key={entry.material_id} className="min-w-0">
              <legend className="mb-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
                {entry.display_name || entry.local_directory}
                {entry.display_brand && <span className="ml-2 font-normal text-slate-500 dark:text-slate-400">{entry.display_brand}</span>}
              </legend>
              <div className="mb-2 flex flex-wrap justify-between gap-2 rounded-lg bg-slate-100 px-3 py-3 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                <span>{date(currentDate)}</span><span>{t("mat_sync_history_current")}</span>
              </div>
              <div className="space-y-1">
                {revisions.map((revision, index) => <label key={revision} className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-3 text-sm text-slate-700 dark:text-slate-200 ${selection?.material === entry.material_id && selection.revision === revision ? "bg-slate-200 dark:bg-slate-700" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>
                  <input type="radio" name={titleId} checked={selection?.material === entry.material_id && selection.revision === revision}
                    disabled={pendingRollback !== null} onChange={() => setSelection({ material: entry.material_id, revision })}
                    className="h-4 w-4 accent-blue-500" />
                  <span className="flex-1">{date(history.get(revision))}</span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">{t("mat_sync_history_previous")} {index + 1}</span>
                </label>)}
              </div>
            </fieldset>;
          })}
        </div>
        <div className="flex flex-col gap-3 p-6">
          {error && <StatusBanner tone="error">{error}</StatusBanner>}
          <TransientBanner message={success} onDismiss={onDismissSuccess} />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" label={t("mat_sync_history_close")} onClick={onClose} />
            <Button label={t("mat_sync_history_restore")} disabled={!selectedEntry || !selection || pendingRollback !== null}
              loading={pendingRollback !== null} onClick={() => { if (selectedEntry && selection) onRollback(selectedEntry, selection.revision); }} />
          </div>
        </div>
      </div>
    </div>, document.body,
  );
}
