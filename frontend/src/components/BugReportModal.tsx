import { useCallback, useEffect, useState } from "react";
import type { ChangeEvent, FormEvent, JSX } from "react";
import { createPortal } from "react-dom";
import { submitBugReport } from "../api/feedback";
import type { BugReportResponse } from "../api/feedback";
import { useI18n } from "../i18n/context";
import { collectBugReportContext } from "../utils/bugReportContext";
import Button from "./ui/Button";
import { StatusBanner, workstationInputClass } from "./ui/panelPrimitives";

const MAX_DESCRIPTION_LENGTH = 10_000;
const MAX_SCREENSHOT_BYTES = 5_000_000;

interface BugReportModalProps {
  open: boolean;
  onClose: () => void;
  presetDescription?: string;
}

interface NoticeState {
  tone: "success" | "error" | "warning";
  message: string;
}

function interpolateTicket(template: string, ticket: string): string {
  return template.replace("{{ticket}}", ticket);
}

function copyTextWithSelectionFallback(text: string): boolean {
  if (typeof document === "undefined" || typeof document.execCommand !== "function") {
    return false;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, text.length);

  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(textarea);
  }
}

async function copyTextToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Clipboard API unavailable; the ticket text is still selectable in the UI.
    }
  }

  return copyTextWithSelectionFallback(text);
}

function readScreenshotAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
      } else {
        reject(new Error("Invalid file reader result"));
      }
    };
    reader.onerror = () => reject(reader.error ?? new Error("File reader failed"));
    reader.readAsDataURL(file);
  });
}

export function BugReportModal({
  open,
  onClose,
  presetDescription = "",
}: BugReportModalProps): JSX.Element | null {
  const { t } = useI18n();
  const [description, setDescription] = useState(presetDescription);
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [descriptionError, setDescriptionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [contextExpanded, setContextExpanded] = useState(false);
  const [submittedTicket, setSubmittedTicket] = useState<BugReportResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const [screenshotDataUrl, setScreenshotDataUrl] = useState<string | null>(null);
  const [screenshotName, setScreenshotName] = useState<string | null>(null);
  const [screenshotError, setScreenshotError] = useState<string | null>(null);

  const resetForm = useCallback(() => {
    setDescription(presetDescription);
    setEmail("");
    setSubmitting(false);
    setDescriptionError(null);
    setNotice(null);
    setContextExpanded(false);
    setSubmittedTicket(null);
    setCopied(false);
    setScreenshotDataUrl(null);
    setScreenshotName(null);
    setScreenshotError(null);
  }, [presetDescription]);

  useEffect(() => {
    if (open) {
      setDescription((current) => (current ? current : presetDescription));
      return;
    }
    resetForm();
  }, [open, presetDescription, resetForm]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        resetForm();
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose, resetForm]);

  if (!open || typeof document === "undefined") {
    return null;
  }

  const context = collectBugReportContext();
  const trimmedDescription = description.trim();
  const canSubmit = trimmedDescription.length > 0 && !submitting;

  const handleDescriptionChange = (value: string) => {
    if (value.length > MAX_DESCRIPTION_LENGTH) {
      setDescription(value.slice(0, MAX_DESCRIPTION_LENGTH));
      setNotice({
        tone: "warning",
        message: t("bug_report_validation_description_truncated"),
      });
      return;
    }
    setDescription(value);
    if (descriptionError) {
      setDescriptionError(null);
    }
    if (notice?.tone === "warning") {
      setNotice(null);
    }
  };

  const handleScreenshotChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setScreenshotDataUrl(null);
    setScreenshotName(null);
    setScreenshotError(null);

    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      setScreenshotError(t("bug_report_validation_screenshot_type"));
      event.target.value = "";
      return;
    }
    if (file.size > MAX_SCREENSHOT_BYTES) {
      setScreenshotError(t("bug_report_validation_screenshot_size"));
      event.target.value = "";
      return;
    }

    try {
      const dataUrl = await readScreenshotAsDataUrl(file);
      setScreenshotDataUrl(dataUrl);
      setScreenshotName(file.name);
    } catch {
      setScreenshotError(t("bug_report_validation_screenshot_read_failed"));
      event.target.value = "";
    }
  };

  const handleRemoveScreenshot = () => {
    setScreenshotDataUrl(null);
    setScreenshotName(null);
    setScreenshotError(null);
  };

  const handleCancel = () => {
    resetForm();
    onClose();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!trimmedDescription) {
      setDescriptionError(t("bug_report_validation_description_required"));
      return;
    }

    setSubmitting(true);
    setDescriptionError(null);
    setNotice(null);

    try {
      const response = await submitBugReport({
        description: trimmedDescription,
        user_email: email.trim() ? email.trim() : null,
        context,
        screenshot_data_url: screenshotDataUrl,
      });
      setSubmittedTicket(response);
      setSubmitting(false);
      setCopied(false);
    } catch {
      setNotice({
        tone: "error",
        message: t("bug_report_toast_error"),
      });
      setSubmitting(false);
    }
  };

  const handleCopyTicket = async () => {
    if (!submittedTicket) {
      return;
    }
    const copiedToClipboard = await copyTextToClipboard(submittedTicket.ticket_id);
    if (!copiedToClipboard) {
      setCopied(false);
      setNotice({
        tone: "warning",
        message: t("bug_report_success_copy_failed"),
      });
      return;
    }
    setNotice(null);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return createPortal(
    <div
      data-testid="bug-report-backdrop"
      className="fixed inset-0 z-[10000] flex items-center justify-center px-4 py-6 backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={handleCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("bug_report_modal_title")}
        className="relative flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-[28px] border shadow-2xl"
        style={{
          background: "var(--surface-panel-strong)",
          borderColor: "var(--surface-outline)",
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <h2 className="text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("bug_report_modal_title")}
          </h2>
          <button
            type="button"
            aria-label={t("announcement_close")}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800 dark:hover:text-slate-200"
            onClick={handleCancel}
          >
            ×
          </button>
        </div>

        {submittedTicket ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
              <StatusBanner tone="success" role="status">
                {interpolateTicket(
                  t("bug_report_toast_success"),
                  submittedTicket.ticket_id,
                )}
              </StatusBanner>
              {notice && (
                <StatusBanner
                  tone={notice.tone}
                  role={notice.tone === "success" ? "status" : "alert"}
                >
                  {notice.message}
                </StatusBanner>
              )}

              <div
                className="flex flex-wrap items-center gap-2 rounded-[18px] border px-4 py-3"
                style={{
                  borderColor: "var(--surface-outline)",
                  background:
                    "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                }}
              >
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("bug_report_success_ticket_label")}:
                </span>
                <code
                  data-testid="bug-report-ticket-id"
                  className="select-all rounded px-2 py-1 font-mono text-sm"
                  style={{
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 30%, black)",
                    color: "var(--surface-text)",
                  }}
                >
                  {submittedTicket.ticket_id}
                </code>
                <button
                  type="button"
                  data-testid="bug-report-copy-ticket"
                  onClick={handleCopyTicket}
                  className="rounded-lg px-3 py-1 text-xs font-medium transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
                  style={{ color: "var(--surface-text-muted)" }}
                >
                  {copied
                    ? t("bug_report_success_copied")
                    : t("bug_report_success_copy")}
                </button>
              </div>

              <p className="text-sm leading-6 text-slate-700 dark:text-slate-200">
                {submittedTicket.emailed
                  ? t("bug_report_success_emailed_yes")
                  : t("bug_report_success_emailed_no")}
              </p>

              {!submittedTicket.emailed && submittedTicket.dump_path && (
                <div
                  className="rounded-[18px] border px-4 py-3"
                  style={{
                    borderColor: "var(--surface-outline)",
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                  }}
                >
                  <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
                    {t("bug_report_success_dump_path_label")}:
                  </div>
                  <code
                    data-testid="bug-report-dump-path"
                    className="mt-1 block break-all font-mono text-xs"
                    style={{ color: "var(--surface-text)" }}
                  >
                    {submittedTicket.dump_path}
                  </code>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-4 dark:border-slate-700">
              <Button
                label={t("bug_report_success_close")}
                variant="primary"
                onClick={handleCancel}
                className="px-4"
              />
            </div>
          </div>
        ) : (
          <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSubmit}>
            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
              {notice && (
                <StatusBanner
                  tone={notice.tone}
                  role={notice.tone === "success" ? "status" : "alert"}
                >
                  {notice.message}
                </StatusBanner>
              )}

              <div className="space-y-2">
                <label
                  htmlFor="bug-report-description"
                  className="text-sm font-medium text-slate-700 dark:text-slate-200"
                >
                  {t("bug_report_modal_description_label")}
                </label>
                <textarea
                  id="bug-report-description"
                  value={description}
                  onChange={(event) => handleDescriptionChange(event.target.value)}
                  onBlur={() => {
                    if (!description.trim()) {
                      setDescriptionError(t("bug_report_validation_description_required"));
                    }
                  }}
                  placeholder={t("bug_report_modal_description_placeholder")}
                  autoFocus
                  rows={6}
                  className={`${workstationInputClass} min-h-[9rem] resize-y`}
                />
                {descriptionError && (
                  <p className="text-sm text-[var(--error-fg)]">{descriptionError}</p>
                )}
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="bug-report-email"
                  className="text-sm font-medium text-slate-700 dark:text-slate-200"
                >
                  {t("bug_report_modal_email_label")}
                </label>
                <input
                  id="bug-report-email"
                  type="email"
                  maxLength={320}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className={workstationInputClass}
                />
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="bug-report-screenshot"
                  className="text-sm font-medium text-slate-700 dark:text-slate-200"
                >
                  {t("bug_report_modal_screenshot_label")}
                </label>
                <input
                  id="bug-report-screenshot"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  onChange={handleScreenshotChange}
                  className={workstationInputClass}
                />
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t("bug_report_modal_screenshot_hint")}
                </p>
                {screenshotError && (
                  <p className="text-sm text-[var(--error-fg)]">{screenshotError}</p>
                )}
                {screenshotName && (
                  <div
                    className="flex flex-wrap items-center gap-2 rounded-[18px] border px-3 py-2"
                    style={{
                      borderColor: "var(--surface-outline)",
                      background:
                        "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                    }}
                  >
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {t("bug_report_modal_screenshot_attached_label")}:
                    </span>
                    <span className="break-all text-sm text-slate-700 dark:text-slate-200">
                      {screenshotName}
                    </span>
                    <button
                      type="button"
                      className="rounded-lg px-2 py-1 text-xs font-medium transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
                      onClick={handleRemoveScreenshot}
                    >
                      {t("bug_report_modal_screenshot_remove")}
                    </button>
                  </div>
                )}
              </div>

              <details
                open={contextExpanded}
                onToggle={(event) =>
                  setContextExpanded((event.currentTarget as HTMLDetailsElement).open)
                }
                className="rounded-[22px] border px-4 py-3 shadow-[var(--shadow-control)]"
                style={{
                  borderColor: "var(--surface-outline)",
                  background:
                    "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                }}
              >
                <summary className="cursor-pointer list-none text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("bug_report_modal_context_disclosure")}
                </summary>
                <pre
                  data-testid="bug-report-context-json"
                  className="mt-3 overflow-x-auto rounded-2xl px-3 py-3 text-xs leading-5 text-slate-100"
                  style={{
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 18%, black)",
                  }}
                >
                  {JSON.stringify(context, null, 2)}
                </pre>
              </details>

              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {t("bug_report_modal_privacy_note")}
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-4 dark:border-slate-700">
              <Button
                label={t("bug_report_modal_cancel")}
                variant="secondary"
                onClick={handleCancel}
                disabled={submitting}
                className="px-4"
              />
              <Button
                type="submit"
                label={t("bug_report_modal_submit")}
                variant="primary"
                onClick={() => {}}
                disabled={!canSubmit}
                loading={submitting}
                className="px-4"
              />
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body,
  );
}
