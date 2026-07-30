import { useEffect } from "react";
import { createPortal } from "react-dom";

import Button from "../../../components/ui/Button";

interface BeadHandoffConfirmDialogProps {
  open: boolean;
  busy: boolean;
  translate(key: string): string;
  onCancel(): void;
  onConfirm(): void;
}

export function BeadHandoffConfirmDialog({
  open,
  busy,
  translate: t,
  onCancel,
  onConfirm,
}: BeadHandoffConfirmDialogProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onCancel, open]);

  if (!open) {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={busy ? undefined : onCancel}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="bead-handoff-confirm-title"
        className="w-full max-w-md overflow-hidden rounded-[24px] border border-slate-200/80 bg-[var(--surface-panel-strong)] shadow-2xl dark:border-slate-700/80"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="px-5 pb-3 pt-5">
          <h2
            id="bead-handoff-confirm-title"
            className="text-lg font-semibold text-slate-900 dark:text-slate-50"
          >
            {t("workshop.bead.replaceTitle")}
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t("workshop.bead.replaceDescription")}
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200/80 px-5 py-4 dark:border-slate-700/80">
          <Button
            label={t("workshop.bead.replaceCancel")}
            variant="secondary"
            onClick={onCancel}
            disabled={busy}
          />
          <Button
            label={t("workshop.bead.replaceConfirm")}
            onClick={onConfirm}
            loading={busy}
          />
        </div>
      </section>
    </div>,
    document.body,
  );
}
