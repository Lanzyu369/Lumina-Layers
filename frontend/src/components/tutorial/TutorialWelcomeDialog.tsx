import { useEffect } from "react";
import type { JSX } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../../i18n/context";
import Button from "../ui/Button";

export interface TutorialWelcomeDialogProps {
  open: boolean;
  onStart: () => void;
  onSkip: () => void;
}

/**
 * First-run welcome dialog that offers the beginner tutorial.
 * 首次启动欢迎窗，询问用户是否开始新手引导。
 *
 * Closing the dialog in any way (Skip, the close button, Escape, or a backdrop
 * click) counts as skipping so the user never has to dismiss it twice.
 * 以任何方式关闭（跳过、关闭按钮、Esc、点击背景）都视为跳过，用户无需二次关闭。
 */
export default function TutorialWelcomeDialog({
  open,
  onStart,
  onSkip,
}: TutorialWelcomeDialogProps): JSX.Element | null {
  const { t } = useI18n();

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onSkip();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onSkip]);

  if (!open || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[9000] flex items-center justify-center backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onSkip}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-welcome-title"
        data-testid="tutorial-welcome-dialog"
        className="relative mx-4 flex w-full max-w-md flex-col overflow-hidden rounded-2xl border shadow-2xl"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 px-5 pt-5">
          <div className="flex min-w-0 items-center gap-3">
            <img src="/favicon.ico" alt="" className="h-9 w-9 shrink-0 rounded" />
            <h2
              id="tutorial-welcome-title"
              className="text-lg font-semibold text-slate-800 dark:text-slate-100"
            >
              {t("tutorial_welcome_title")}
            </h2>
          </div>
          <button
            type="button"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            onClick={onSkip}
            aria-label={t("tutorial_welcome_close")}
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-4">
          <p className="whitespace-pre-line text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t("tutorial_welcome_body")}
          </p>
          <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {t("tutorial_welcome_note")}
          </p>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-700">
          <Button
            label={t("tutorial_welcome_skip")}
            variant="secondary"
            onClick={onSkip}
            className="px-4"
          />
          <Button
            label={t("tutorial_welcome_start")}
            variant="primary"
            onClick={onStart}
            className="px-4"
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
