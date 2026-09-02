import type { BatchResponse } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { normalizeResourceUrl } from "../../utils/resourceUrl";
import { isUnsafeVisibleErrorText } from "../../utils/visibleErrorText";

interface BatchResultSummaryProps {
  result: BatchResponse;
}

const API_BATCH_ITEM_FAILED_DETAIL =
  "This file could not be converted. Re-upload it or check the server log for details.";
const API_BATCH_ITEM_TIMEOUT_DETAIL = "Batch item conversion timed out";

function shouldHideRawBatchItemError(error: string): boolean {
  const trimmed = error.trim();
  return (
    trimmed === API_BATCH_ITEM_FAILED_DETAIL ||
    isUnsafeVisibleErrorText(trimmed)
  );
}

function visibleBatchItemError(
  error: string | undefined,
  fallback: string,
  timeoutFallback: string,
): string | null {
  if (!error?.trim()) {
    return null;
  }
  const trimmed = error.trim();
  if (trimmed === API_BATCH_ITEM_TIMEOUT_DETAIL) {
    return timeoutFallback;
  }
  return shouldHideRawBatchItemError(trimmed) ? fallback : trimmed;
}

export default function BatchResultSummary({ result }: BatchResultSummaryProps) {
  const { t } = useI18n();
  const downloadUrl =
    normalizeResourceUrl(result.download_url) ?? result.download_url ?? "";
  const hasDownload =
    typeof downloadUrl === "string" && downloadUrl.length > 0;
  const successCount = result.results.filter(
    (r) => r.status === "success",
  ).length;
  const failedCount = result.results.filter(
    (r) => r.status === "failed",
  ).length;
  const total = result.results.length;
  const failedItems = result.results.filter((r) => r.status === "failed");

  return (
    <div className="flex flex-col gap-3 rounded-md bg-slate-800 p-3 text-sm">
      {/* Summary stats */}
      <p className="text-slate-300">
        {t("batch_success")}{" "}
        <span className="font-medium text-green-400">{successCount}</span>
        {" / "}{t("batch_total")}{" "}
        <span className="font-medium text-slate-200">{total}</span>
        {failedCount > 0 && (
          <>
            {"，"}{t("batch_failed")}{" "}
            <span className="font-medium text-red-400">{failedCount}</span>
          </>
        )}
      </p>

      {/* Download button — rendered unconditionally when download_url is non-empty */}
      {hasDownload && (
        <a
          href={downloadUrl}
          download
          className="inline-flex items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          aria-label={t("batch.download.mergedThreemf")}
        >
          <svg
            className="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          {t("batch.download.mergedThreemf")}
        </a>
      )}

      {/* Plate-overflow warnings — keyed by WarningEntry.code, never by message text */}
      {result.warnings?.map((w) => {
        if (w.code === "plate-overflow") {
          return (
            <p key={w.code} role="status" className="text-xs text-amber-400">
              {t("batch.warnings.plateOverflow.body")}
            </p>
          );
        }
        if (w.code === "preview-limited") {
          return (
            <p key={w.code} role="status" className="text-xs text-amber-400">
              {t("batch.warnings.previewLimited.body")}
            </p>
          );
        }
        if (w.code === "wipe_tower_manual_adjustment_required") {
          return (
            <div
              key={w.code}
              role="alert"
              className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
            >
              <p className="font-medium">
                {t("batch.warnings.wipeTowerManual.title")}
              </p>
              <p>{t("batch.warnings.wipeTowerManual.body")}</p>
            </div>
          );
        }
        return null;
      })}

      {/* Failed items list */}
      {failedItems.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-red-400">{t("batch_failed_files")}</p>
          <ul className="flex flex-col gap-1" aria-label={t("batch_failed_list_label")}>
            {failedItems.map((item, index) => {
              const visibleError = visibleBatchItemError(
                item.error,
                t("batch.itemError.conversionFailed"),
                t("batch.itemError.timeout"),
              );
              return (
                <li
                  key={`${item.filename}-${index}`}
                  className="rounded bg-red-900/20 px-2 py-1 text-xs text-slate-300"
                >
                  <span className="font-medium">{item.filename}</span>
                  {visibleError && (
                    <span className="text-red-300"> — {visibleError}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
