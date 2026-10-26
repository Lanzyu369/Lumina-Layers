import CloseButton from "../ui/CloseButton";
import { useEffect, useRef } from "react";
import type { JSX } from "react";
import { createPortal } from "react-dom";
import { useDialogFocusTrap } from "../../hooks/useDialogFocusTrap";
import { useI18n } from "../../i18n/context";
import Button from "../ui/Button";

/** Focus the primary "Start tour" action when the dialog opens. 打开时聚焦「开始引导」。 */
const focusStartAction = (container: HTMLElement) =>
  container.querySelector<HTMLElement>("[data-welcome-actions] button:last-of-type");

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
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocusTrap(dialogRef, open, { initialFocus: focusStartAction });

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
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-welcome-title"
        tabIndex={-1}
        data-testid="tutorial-welcome-dialog"
        className="relative mx-4 flex max-h-[calc(100dvh-32px)] w-full max-w-md flex-col overflow-hidden rounded-2xl border shadow-2xl outline-none"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between gap-3 px-5 pt-5">
          <div className="flex min-w-0 items-center gap-3">
            <img src="/favicon.ico" alt="" className="h-9 w-9 shrink-0 rounded" />
            <h2
              id="tutorial-welcome-title"
              className="text-lg font-semibold text-slate-800 dark:text-slate-100"
            >
              {t("tutorial_welcome_title")}
            </h2>
          </div>
          <CloseButton label={t("tutorial_welcome_close")} onClick={onSkip} />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain px-5 py-4" data-testid="tutorial-welcome-body">
          <p className="whitespace-pre-line text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t("tutorial_welcome_body")}
          </p>
          <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {t("tutorial_welcome_note")}
          </p>
        </div>

        <div
          className="flex shrink-0 items-center justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-700"
          data-welcome-actions
        >
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
