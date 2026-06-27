import { apiErrorToVisibleMessage } from "../api/client";
import { tRuntime } from "../i18n/runtime";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readResponse(error: unknown): { status: number | null; data: unknown } | null {
  if (!isRecord(error) || !isRecord(error.response)) {
    return null;
  }
  const status = typeof error.response.status === "number" ? error.response.status : null;
  return { status, data: error.response.data };
}

function readDetail(data: unknown): string | null {
  if (typeof data === "string" && data.trim()) {
    return data.trim();
  }
  if (!isRecord(data)) {
    return null;
  }
  const detail = data.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (isRecord(detail) && typeof detail.message === "string" && detail.message.trim()) {
    return detail.message.trim();
  }
  const message = data.message;
  return typeof message === "string" && message.trim() ? message.trim() : null;
}

const MISSING_LUT_PUBLIC_DETAIL = "Selected LUT was not found or is unavailable.";

function isMissingLutDetail(error: unknown): boolean {
  const response = readResponse(error);
  if (!response || response.status !== 404) {
    return false;
  }
  const detail = readDetail(response.data);
  return (
    typeof detail === "string" &&
    (/^LUT not found:/i.test(detail) || detail === MISSING_LUT_PUBLIC_DETAIL)
  );
}

export function lutErrorToVisibleMessage(
  error: unknown,
  fallback?: string,
): string {
  if (isMissingLutDetail(error)) {
    return tRuntime("lut_error_missing_refresh");
  }
  return fallback === undefined
    ? apiErrorToVisibleMessage(error)
    : apiErrorToVisibleMessage(error, fallback);
}
