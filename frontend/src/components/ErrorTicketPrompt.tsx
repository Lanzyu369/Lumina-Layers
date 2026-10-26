import type { JSX } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "../i18n/context";
import type { ErrorTicketPromptInfo } from "../stores/errorTicketPromptStore";
import Button from "./ui/Button";

/** Longest error message shown inside the prompt card. */
const MAX_PREVIEW_MESSAGE_LENGTH = 160;

function truncateMessage(message: string): string {
  return message.length > MAX_PREVIEW_MESSAGE_LENGTH
    ? `${message.slice(0, MAX_PREVIEW_MESSAGE_LENGTH)}…`
    : message;
}

interface ErrorTicketPromptProps {
  info: ErrorTicketPromptInfo | null;
  onReport: () => void;
  onDismiss: () => void;
  onSuppress: () => void;
}

/**
 * Non-blocking card in the bottom-right corner asking whether to submit a
 * bug-report ticket for the error that just happened.
 * 右下角的非阻塞提示卡片，询问是否为刚刚发生的错误提交工单。
 */
export function ErrorTicketPrompt({
  info,
  onReport,
  onDismiss,
  onSuppress,
}: ErrorTicketPromptProps): JSX.Element | null {
  const { t } = useI18n();
  if (!info || typeof document === "undefined") return null;

  return createPortal(
    <div
      role="alertdialog"
      aria-live="assertive"
      aria-labelledby="error-ticket-prompt-title"
      aria-describedby="error-ticket-prompt-body"
      data-testid="error-ticket-prompt"
      className="fixed bottom-4 right-4 z-[9998] w-[calc(100vw-2rem)] max-w-sm rounded-2xl border p-4 shadow-2xl"
      style={{
        borderColor: "var(--surface-outline)",
        background: "var(--surface-panel-strong)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <h2
          id="error-ticket-prompt-title"
          className="text-sm font-semibold text-slate-800 dark:text-slate-100"
        >
          {t("error_ticket_prompt_title")}
        </h2>
      </div>
      <p
        data-testid="error-ticket-prompt-message"
        className="mt-2 break-words font-mono text-xs text-[var(--error-fg)]"
      >
        {info.statusCode != null ? `HTTP ${info.statusCode} · ` : ""}
        {truncateMessage(info.message)}
      </p>
      <p
        id="error-ticket-prompt-body"
        className="mt-2 text-xs leading-5 text-slate-600 dark:text-slate-300"
      >
        {t("error_ticket_prompt_body")}
      </p>
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          data-testid="error-ticket-prompt-suppress"
          className="mr-auto text-xs text-slate-500 underline-offset-2 hover:underline dark:text-slate-400"
          onClick={onSuppress}
        >
          {t("error_ticket_prompt_suppress")}
        </button>
        <Button
          label={t("error_ticket_prompt_dismiss")}
          variant="secondary"
          size="sm"
          onClick={onDismiss}
        />
        <Button
          label={t("error_ticket_prompt_submit")}
          size="sm"
          onClick={onReport}
        />
      </div>
    </div>,
    document.body,
  );
}
