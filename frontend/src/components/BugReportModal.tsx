import { useCallback, useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent, JSX } from "react";
import { createPortal } from "react-dom";
import { apiStatusCodeToVisibleMessage } from "../api/client";
import { relayBugReport, submitBugReport } from "../api/feedback";
import type { BugReportRequestPayload, BugReportResponse } from "../api/feedback";
import { trackLuminaEvent } from "../analytics/umami";
import { useI18n } from "../i18n/context";
import { collectBugReportContext } from "../utils/bugReportContext";
import { loadPersistedLogs } from "../utils/clientLog";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import Button from "./ui/Button";
import { StatusBanner, workstationInputClass } from "./ui/panelPrimitives";

const MAX_DESCRIPTION_LENGTH = 10_000;
const MAX_SCREENSHOT_BYTES = 5_000_000;

/**
 * Schedule ``callback`` on the idle-callback queue, falling back to
 * ``setTimeout(..., 0)`` when the browser does not support it (Safari as
 * of 2026 still lacks ``requestIdleCallback``). Used so the expensive
 * ``JSON.stringify(context, null, 2)`` only runs when the user opts in
 * and yields to layout/input in between.
 * 空闲调度：不支持 ``requestIdleCallback`` 时退回到 ``setTimeout(fn, 0)``。
 */
function scheduleIdle(callback: () => void): void {
  const maybeIdle = (
    globalThis as { requestIdleCallback?: (cb: () => void) => number }
  ).requestIdleCallback;
  if (typeof maybeIdle === "function") {
    try {
      maybeIdle(callback);
      return;
    } catch {
      // fall through
    }
  }
  setTimeout(callback, 0);
}

function isGenericStatusCodeMessage(message: string): boolean {
  return /^Request failed with status code \d{3}(?::.*)?$/i.test(message.trim());
}

/**
 * Minimal 3-line snapshot header + 3 recent action entries + up to 2 recent
 * API errors. Designed to stay under ~10 DOM nodes so the modal renders in
 * the SLO 8 budget (< 50 ms at 500 client logs + 100 action entries).
 * 紧凑摘要：只显示当前工作流关键字段、最近 3 次操作、最近 2 次接口错误，
 * 避免 modal 一打开就序列化完整 context。
 */
type CompactContextSummaryProps = {
  context: ReturnType<typeof collectBugReportContext>;
  labelActiveTab: string;
  labelColorMode: string;
  labelLutName: string;
  labelRecentActions: string;
  labelRecentErrors: string;
  labelNoData: string;
};

function CompactContextSummary({
  context,
  labelActiveTab,
  labelColorMode,
  labelLutName,
  labelRecentActions,
  labelRecentErrors,
  labelNoData,
}: CompactContextSummaryProps): JSX.Element {
  const recentActions = (context.action_history ?? []).slice(-3).reverse();
  const recentLogs = context.recent_client_logs ?? [];
  const recentApiErrors = recentLogs
    .filter(
      (log) =>
        log.method === "error" &&
        (log.scope === "api" || log.scope === "http"),
    )
    .slice(-2)
    .reverse();

  const hasAnyContent =
    context.active_tab != null ||
    context.color_mode != null ||
    context.lut_name != null ||
    recentActions.length > 0 ||
    recentApiErrors.length > 0;

  if (!hasAnyContent) {
    return (
      <p className="text-xs text-slate-500 dark:text-slate-400">{labelNoData}</p>
    );
  }

  return (
    <div
      data-testid="bug-report-context-summary"
      className="space-y-2 text-xs leading-5 text-slate-600 dark:text-slate-300"
    >
      <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono">
        {context.active_tab && <span>{labelActiveTab}={context.active_tab}</span>}
        {context.color_mode && <span>{labelColorMode}={context.color_mode}</span>}
        {context.lut_name && <span>{labelLutName}={context.lut_name}</span>}
      </div>
      {recentActions.length > 0 && (
        <div>
          <div className="font-medium">{labelRecentActions}</div>
          <ul className="ml-4 list-disc font-mono">
            {recentActions.map((entry, idx) => (
              <li key={`${entry.timestamp}-${idx}`}>
                {new Date(entry.timestamp).toISOString()} · {entry.action_type}
              </li>
            ))}
          </ul>
        </div>
      )}
      {recentApiErrors.length > 0 && (
        <div>
          <div className="font-medium">{labelRecentErrors}</div>
          <ul className="ml-4 list-disc font-mono">
            {recentApiErrors.map((entry, idx) => {
              const details = entry.details as
                | {
                    status_code?: unknown;
                    path?: unknown;
                    url?: unknown;
                    error_message?: unknown;
                  }
                | null
                | undefined;
              const status =
                typeof details?.status_code === "number"
                  ? details.status_code
                  : "?";
              const path =
                typeof details?.path === "string"
                  ? details.path
                  : typeof details?.url === "string"
                    ? details.url
                    : "";
              const message =
                typeof details?.error_message === "string" &&
                details.error_message.trim()
                  ? details.error_message.trim()
                  : "";
              const fallbackMessage = apiStatusCodeToVisibleMessage(
                typeof status === "number" ? status : null,
              );
              const primaryMessage =
                message && !isGenericStatusCodeMessage(message)
                  ? message
                  : fallbackMessage;
              const primaryText = path
                ? `${primaryMessage} · ${path}`
                : primaryMessage || entry.label;
              return (
                <li key={`${entry.timestamp}-${idx}`}>
                  <span>{primaryText}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

interface BugReportModalProps {
  open: boolean;
  onClose: () => void;
  presetDescription?: string;
}

interface NoticeState {
  tone: "success" | "error" | "warning";
  message: string;
}

interface FailedReportState {
  text: string;
  copied: boolean;
}

type RelayState = "idle" | "sending" | "sent" | "failed" | "skipped";

const LOCAL_PATH_PLACEHOLDER = "<local-path>";
const STACK_TRACE_PLACEHOLDER = "<stack-trace omitted>";
const GENERIC_HTTP_FAILURE_MESSAGE = "Request failed. Please try again.";

const SENSITIVE_STACK_KEYS = new Set([
  "error_stack",
  "stack",
  "trace",
  "traceback",
  "stacktrace",
  "stack_trace",
]);

const USER_AUTHORED_TEXT_KEYS = new Set(["description"]);

const LOCAL_FILE_URL_PATTERN = /\bfile:\/\/(?:localhost\/|\/)(?:[A-Za-z]:\/|(?:Users|home|private|tmp|var|Volumes|mnt|opt|etc)\/)[^\s"',)]+/gi;
const POSIX_LOCAL_PATH_PATTERN = /(^|[\s("'=:])((?:\/Users|\/home|\/private|\/tmp|\/var|\/Volumes|\/mnt|\/opt|\/etc)\/[^\s"',)]+)/g;
const WINDOWS_LOCAL_PATH_PATTERN = /\b[A-Za-z]:[\\/][^\s"'<>|?*]+/g;
const UNC_LOCAL_PATH_PATTERN = /\\\\[A-Za-z0-9_.-]+\\[^\s"'<>|]+(?:\\[^\s"'<>|]+)*/g;
const GENERIC_HTTP_STATUS_PATTERN = /\b(?:request failed with status code|http(?:\s+error)?|status(?:\s+code)?|error)\s+\d{3}\b/i;
const STACK_FRAME_PATTERN = /^\s*at\s+.+$/gm;
const HTTP_STATUS_KEY_PATTERN = /^(?:status|status_code|http_status|response_status)$/i;

function redactManualFallbackString(value: string, key: string | null = null): string {
  let redacted = value.replace(LOCAL_FILE_URL_PATTERN, LOCAL_PATH_PLACEHOLDER);
  redacted = redacted.replace(UNC_LOCAL_PATH_PATTERN, LOCAL_PATH_PLACEHOLDER);
  redacted = redacted.replace(WINDOWS_LOCAL_PATH_PATTERN, LOCAL_PATH_PLACEHOLDER);
  redacted = redacted.replace(
    POSIX_LOCAL_PATH_PATTERN,
    (_match, prefix: string) => `${prefix}${LOCAL_PATH_PLACEHOLDER}`,
  );
  redacted = redacted.replace(STACK_FRAME_PATTERN, `    at ${STACK_TRACE_PLACEHOLDER}`);
  if (key && USER_AUTHORED_TEXT_KEYS.has(key.toLowerCase())) {
    return redacted;
  }
  if (GENERIC_HTTP_STATUS_PATTERN.test(redacted)) {
    return GENERIC_HTTP_FAILURE_MESSAGE;
  }
  return redacted;
}

function shouldOmitManualFallbackValue(key: string | null, value: unknown): boolean {
  if (key && SENSITIVE_STACK_KEYS.has(key.toLowerCase())) {
    return true;
  }
  if (!key || !HTTP_STATUS_KEY_PATTERN.test(key)) {
    return false;
  }
  if (typeof value === "number") {
    return value >= 100 && value <= 599;
  }
  return typeof value === "string" && /^\d\d\d$/.test(value);
}

function sanitizeManualFallbackValue(
  value: unknown,
  key: string | null = null,
): unknown {
  if (shouldOmitManualFallbackValue(key, value)) {
    return undefined;
  }
  if (typeof value === "string") {
    return redactManualFallbackString(value, key);
  }
  if (value == null || typeof value === "boolean" || typeof value === "number") {
    return value;
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => sanitizeManualFallbackValue(item))
      .filter((item) => item !== undefined);
  }
  if (typeof value !== "object") {
    return String(value);
  }

  const sanitized: Record<string, unknown> = {};
  for (const [entryKey, entryValue] of Object.entries(value)) {
    const sanitizedKey = redactManualFallbackString(entryKey, entryKey);
    const sanitizedValue = sanitizeManualFallbackValue(entryValue, entryKey);
    if (sanitizedValue !== undefined) {
      sanitized[sanitizedKey] = sanitizedValue;
    }
  }
  return sanitized;
}

function stringifyManualFallbackReport(
  payload: BugReportRequestPayload,
): string {
  return JSON.stringify(sanitizeManualFallbackValue(payload), null, 2);
}

function stringifyUserVisibleBugReportContext(
  context: ReturnType<typeof collectBugReportContext>,
): string {
  return JSON.stringify(sanitizeManualFallbackValue(context), null, 2);
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
  const [submittedPayload, setSubmittedPayload] = useState<BugReportRequestPayload | null>(null);
  const [copied, setCopied] = useState(false);
  const [submittedReportCopied, setSubmittedReportCopied] = useState(false);
  const [failedReport, setFailedReport] = useState<FailedReportState | null>(null);
  const [relayState, setRelayState] = useState<RelayState>("idle");
  const [screenshotDataUrl, setScreenshotDataUrl] = useState<string | null>(null);
  const [screenshotName, setScreenshotName] = useState<string | null>(null);
  const [screenshotError, setScreenshotError] = useState<string | null>(null);
  /**
   * Holds the stringified full context once the user has expanded the
   * context disclosure. Stays ``null`` until requested so a Modal open
   * with a 500-entry log buffer doesn't pay the serialization cost.
   * 仅在用户展开「完整上下文」时按需渲染；避免打开 modal 就做昂贵序列化。
   */
  const [fullContextJson, setFullContextJson] = useState<string | null>(null);

  const resetForm = useCallback(() => {
    setDescription(presetDescription);
    setEmail("");
    setSubmitting(false);
    setDescriptionError(null);
    setNotice(null);
    setContextExpanded(false);
    setFullContextJson(null);
    setSubmittedTicket(null);
    setSubmittedPayload(null);
    setCopied(false);
    setSubmittedReportCopied(false);
    setFailedReport(null);
    setRelayState("idle");
    setScreenshotDataUrl(null);
    setScreenshotName(null);
    setScreenshotError(null);
  }, [presetDescription]);

  useEffect(() => {
    if (open) {
      setDescription((current) => (current ? current : presetDescription));
      // Lazy-load persisted buffers when the user actually opens the modal
      // so regular app usage never pays the sessionStorage read cost. Both
      // calls are swallow-safe and idempotent.
      // 打开 modal 时才从 sessionStorage 合并历史缓冲，平时零 I/O。
      try {
        useActionHistoryStore.getState().loadPersistedHistory();
      } catch {
        // ignore
      }
      try {
        loadPersistedLogs();
      } catch {
        // ignore
      }
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

  // Context is expensive to collect (it pulls from four stores + logs).
  // Memoize the rendered-shallow copy across re-renders within the same
  // modal session; we only re-collect when the modal opens or the user
  // attaches/removes a screenshot (both are coarse signals that any cached
  // context is stale). Must run before any early-return so React Hook
  // ordering stays stable across open/closed states.
  // 采集一次上下文：modal 期间通常不会变动剧烈，避免每次输入触发全量重算。
  // 必须放在任何 early-return 之前，保证 Hook 顺序稳定。
  const context = useMemo(
    () => (open ? collectBugReportContext() : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [open, screenshotDataUrl],
  );

  // Kick off the expensive full-context serialization lazily when the
  // user opens the disclosure. Run it off the render path via the idle
  // queue so we never block the modal's frame budget.
  // 用户展开完整上下文时再序列化；走 idle 回调，不阻塞渲染。
  useEffect(() => {
    if (!open || !contextExpanded || context == null) {
      return;
    }
    if (fullContextJson != null) {
      return;
    }
    let cancelled = false;
    scheduleIdle(() => {
      if (cancelled) return;
      try {
        const serialized = stringifyUserVisibleBugReportContext(context);
        if (!cancelled) {
          setFullContextJson(serialized);
        }
      } catch {
        if (!cancelled) {
          setFullContextJson("// failed to serialize context");
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [open, context, contextExpanded, fullContextJson]);

  if (!open || typeof document === "undefined" || context == null) {
    return null;
  }

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
    if (failedReport) {
      setFailedReport(null);
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
    setFailedReport(null);

    const reportPayload: BugReportRequestPayload = {
      description: trimmedDescription,
      user_email: email.trim() ? email.trim() : null,
      context,
      screenshot_data_url: screenshotDataUrl,
    };
    try {
      const response = await submitBugReport(reportPayload);
      setSubmittedTicket(response);
      setSubmittedPayload(reportPayload);
      setSubmitting(false);
      setCopied(false);
      setSubmittedReportCopied(false);
      setRelayState("idle");
      trackLuminaEvent("lumina_bug_report_done", {
        active_tab: context.active_tab,
        has_screenshot: Boolean(screenshotDataUrl),
        relay: false,
        delivery_status: response.email_status,
      });
    } catch (err) {
      setNotice({
        tone: "error",
        message: t("bug_report_toast_error"),
      });
      setFailedReport({
        text: stringifyManualFallbackReport(reportPayload),
        copied: false,
      });
      setSubmitting(false);
      trackLuminaEvent("lumina_bug_report_failed", {
        active_tab: context.active_tab,
        has_screenshot: Boolean(screenshotDataUrl),
        relay: false,
        error_type: err instanceof Error ? err.name : typeof err,
      });
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

  const submittedReportText = submittedPayload
    ? stringifyManualFallbackReport(submittedPayload)
    : "";

  const handleRelayReport = async () => {
    if (!submittedTicket || !submittedPayload) {
      return;
    }
    setRelayState("sending");
    setNotice(null);
    try {
      await relayBugReport(submittedTicket.ticket_id, submittedPayload);
      setRelayState("sent");
      setNotice({
        tone: "success",
        message: t("bug_report_relay_success"),
      });
      trackLuminaEvent("lumina_bug_report_done", {
        active_tab: submittedPayload.context.active_tab,
        has_screenshot: Boolean(submittedPayload.screenshot_data_url),
        relay: true,
        delivery_status: "relayed",
      });
    } catch (err) {
      setRelayState("failed");
      setNotice({
        tone: "error",
        message: t("bug_report_relay_failed"),
      });
      trackLuminaEvent("lumina_bug_report_failed", {
        active_tab: submittedPayload.context.active_tab,
        has_screenshot: Boolean(submittedPayload.screenshot_data_url),
        relay: true,
        error_type: err instanceof Error ? err.name : typeof err,
      });
    }
  };

  const handleCopySubmittedReport = async () => {
    if (!submittedReportText) {
      return;
    }
    const copiedToClipboard = await copyTextToClipboard(submittedReportText);
    if (!copiedToClipboard) {
      setSubmittedReportCopied(false);
      setNotice({
        tone: "warning",
        message: t("bug_report_fallback_copy_failed"),
      });
      return;
    }
    setNotice(null);
    setSubmittedReportCopied(true);
    window.setTimeout(() => setSubmittedReportCopied(false), 2000);
  };

  const handleCopyFailedReport = async () => {
    if (!failedReport) {
      return;
    }
    const copiedToClipboard = await copyTextToClipboard(failedReport.text);
    if (!copiedToClipboard) {
      setFailedReport({ ...failedReport, copied: false });
      setNotice({
        tone: "warning",
        message: t("bug_report_fallback_copy_failed"),
      });
      return;
    }
    setNotice(null);
    setFailedReport({ ...failedReport, copied: true });
    window.setTimeout(() => {
      setFailedReport((current) => current ? { ...current, copied: false } : current);
    }, 2000);
  };

  const buildFallbackMailto = (reportText: string, ticketId?: string): string => {
    const subject = ticketId
      ? `Lumina Studio bug report ${ticketId}`
      : "Lumina Studio bug report";
    return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(reportText)}`;
  };

  const renderManualFallbackActions = (
    reportText: string,
    copyButton: JSX.Element,
    ticketId?: string,
  ): JSX.Element => (
    <div className="flex flex-wrap items-center gap-2">
      {copyButton}
      <a
        href={buildFallbackMailto(reportText, ticketId)}
        className="rounded-lg px-3 py-1 text-xs font-medium transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
        style={{ color: "var(--surface-text-muted)" }}
      >
        {t("bug_report_fallback_mailto")}
      </a>
      <a
        href="https://mail.qq.com/"
        target="_blank"
        rel="noreferrer"
        className="rounded-lg px-3 py-1 text-xs font-medium transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
        style={{ color: "var(--surface-text-muted)" }}
      >
        {t("bug_report_fallback_qq_mail")}
      </a>
    </div>
  );

  return createPortal(
    <div
      data-testid="bug-report-backdrop"
      className="fixed inset-0 z-[10000] flex items-center justify-center px-4 py-6 backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
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

              <p
                data-testid="bug-report-email-status"
                data-status={submittedTicket.email_status}
                className="text-sm leading-6 text-slate-700 dark:text-slate-200"
              >
                {submittedTicket.email_status === "sent"
                  ? t("bug_report_success_emailed_yes")
                  : submittedTicket.email_status === "pending"
                    ? t("bug_report_success_email_pending")
                    : submittedTicket.email_status === "failed"
                      ? t("bug_report_success_email_failed")
                      : t("bug_report_success_email_unconfigured")}
              </p>

              {(submittedTicket.email_status === "failed" ||
                submittedTicket.email_status === "unconfigured") &&
                submittedTicket.relay_available &&
                relayState !== "sent" && (
                <div
                  className="space-y-3 rounded-[18px] border px-4 py-3"
                  style={{
                    borderColor: "var(--surface-outline)",
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                  }}
                >
                  <p className="text-sm leading-6 text-slate-700 dark:text-slate-200">
                    {t("bug_report_relay_prompt")}
                  </p>
                  <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {t("bug_report_relay_privacy")}
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      data-testid="bug-report-relay-send"
                      onClick={handleRelayReport}
                      disabled={relayState === "sending"}
                      className="rounded-lg px-3 py-1 text-xs font-medium transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
                      style={{ color: "var(--surface-text-muted)" }}
                    >
                      {t("bug_report_relay_send")}
                    </button>
                    <button
                      type="button"
                      data-testid="bug-report-relay-skip"
                      onClick={() => {
                        setRelayState("skipped");
                        setNotice({
                          tone: "warning",
                          message: t("bug_report_relay_skipped"),
                        });
                      }}
                      className="rounded-lg px-3 py-1 text-xs font-medium transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
                      style={{ color: "var(--surface-text-muted)" }}
                    >
                      {t("bug_report_relay_skip")}
                    </button>
                  </div>
                </div>
              )}
              {(submittedTicket.email_status === "failed" ||
                submittedTicket.email_status === "unconfigured") &&
                submittedReportText &&
                relayState !== "sent" && (
                <div
                  className="space-y-3 rounded-[18px] border px-4 py-3"
                  style={{
                    borderColor: "var(--surface-outline)",
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                  }}
                >
                  <p className="text-sm leading-6 text-slate-700 dark:text-slate-200">
                    {t("bug_report_fallback_intro")}
                  </p>
                  {renderManualFallbackActions(
                    submittedReportText,
                    <button
                      type="button"
                      data-testid="bug-report-copy-submitted-report"
                      onClick={handleCopySubmittedReport}
                      className="rounded-lg px-3 py-1 text-xs font-medium transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
                      style={{ color: "var(--surface-text-muted)" }}
                    >
                      {submittedReportCopied
                        ? t("bug_report_fallback_copied")
                        : t("bug_report_fallback_copy")}
                    </button>,
                    submittedTicket.ticket_id,
                  )}
                  <pre
                    data-testid="bug-report-submitted-fallback-text"
                    className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-2xl px-3 py-3 text-xs leading-5 text-slate-100"
                    style={{
                      background:
                        "color-mix(in srgb, var(--surface-panel-strong) 18%, black)",
                    }}
                  >
                    {submittedReportText}
                  </pre>
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
              {failedReport && (
                <div
                  className="space-y-3 rounded-[18px] border px-4 py-3"
                  style={{
                    borderColor: "var(--surface-outline)",
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                  }}
                >
                  <p className="text-sm leading-6 text-slate-700 dark:text-slate-200">
                    {t("bug_report_fallback_intro")}
                  </p>
                  {renderManualFallbackActions(
                    failedReport.text,
                    <button
                      type="button"
                      data-testid="bug-report-copy-failed-report"
                      onClick={handleCopyFailedReport}
                      className="rounded-lg px-3 py-1 text-xs font-medium transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
                      style={{ color: "var(--surface-text-muted)" }}
                    >
                      {failedReport.copied
                        ? t("bug_report_fallback_copied")
                        : t("bug_report_fallback_copy")}
                    </button>,
                  )}
                  <pre
                    data-testid="bug-report-fallback-text"
                    className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-2xl px-3 py-3 text-xs leading-5 text-slate-100"
                    style={{
                      background:
                        "color-mix(in srgb, var(--surface-panel-strong) 18%, black)",
                    }}
                  >
                    {failedReport.text}
                  </pre>
                </div>
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

              <CompactContextSummary
                context={context}
                labelActiveTab={t("bug_report_modal_context_active_tab")}
                labelColorMode={t("bug_report_modal_context_color_mode")}
                labelLutName={t("bug_report_modal_context_lut")}
                labelRecentActions={t("bug_report_modal_context_recent_actions")}
                labelRecentErrors={t("bug_report_modal_context_recent_errors")}
                labelNoData={t("bug_report_modal_context_summary_none")}
              />

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
                  {fullContextJson ?? ""}
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
