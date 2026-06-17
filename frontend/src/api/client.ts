import axios from "axios";
import { postClientLog, summarizeErrorForLog } from "../utils/clientLog";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import { tRuntime } from "../i18n/runtime";

/**
 * Axios 实例，统一管理 API 请求基础配置。
 *
 * 注意：不设置默认 Content-Type header。
 * - 发送 JSON 时 axios 自动设置 application/json
 * - 发送 FormData 时 axios 自动设置 multipart/form-data 并附加 boundary
 * - 手动设置默认 Content-Type 会阻止 FormData 的 boundary 自动生成，导致后端 422
 */
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api",
  timeout: 3_600_000,
});

function summarizeApiErrorData(data: unknown): unknown {
  if (data == null || typeof data !== "object") {
    return data ?? null;
  }
  if (Array.isArray(data)) {
    return { item_count: data.length };
  }

  const record = data as Record<string, unknown>;
  if ("detail" in record) {
    return { detail: record.detail };
  }
  if ("message" in record) {
    return { message: record.message };
  }
  return { keys: Object.keys(record).slice(0, 12) };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function formatValidationLocation(value: unknown): string | null {
  if (!Array.isArray(value) || value.length === 0) {
    return null;
  }
  return value.map((part) => String(part)).join(".");
}

function formatValidationDetails(details: unknown[]): string | null {
  const messages = details
    .map((item) => {
      if (!isRecord(item)) {
        return typeof item === "string" ? item : null;
      }
      const message = typeof item.msg === "string" ? item.msg : null;
      if (!message) {
        return null;
      }
      const location = formatValidationLocation(item.loc);
      return location ? `${location}: ${message}` : message;
    })
    .filter((message): message is string => Boolean(message));
  return messages.length > 0 ? messages.join("; ") : null;
}

function extractReadableDetail(data: unknown): string | null {
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
  if (Array.isArray(detail)) {
    const validationMessage = formatValidationDetails(detail);
    if (validationMessage) {
      return validationMessage;
    }
  }

  const message = data.message;
  if (typeof message === "string" && message.trim()) {
    return message.trim();
  }
  return null;
}

function isGenericHttpDetail(detail: string, statusCode: number | null): boolean {
  const normalized = detail.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  if (
    typeof statusCode === "number" &&
    new RegExp(`\\b(http|status code|status)\\s*${statusCode}\\b`).test(normalized)
  ) {
    return true;
  }
  return [
    "bad request",
    "unauthorized",
    "payment required",
    "forbidden",
    "not found",
    "method not allowed",
    "request timeout",
    "conflict",
    "payload too large",
    "unsupported media type",
    "unprocessable entity",
    "too many requests",
    "internal server error",
    "internal error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
  ].includes(normalized);
}

function fallbackHttpStatusMessage(statusCode: number | null): string {
  switch (statusCode) {
    case 400:
      return tRuntime("api_error_http_400");
    case 401:
      return tRuntime("api_error_http_401");
    case 402:
      return tRuntime("api_error_http_402");
    case 403:
      return tRuntime("api_error_http_403");
    case 404:
      return tRuntime("api_error_http_404");
    case 405:
      return tRuntime("api_error_http_405");
    case 408:
      return tRuntime("api_error_http_408");
    case 409:
      return tRuntime("api_error_http_409");
    case 413:
      return tRuntime("api_error_http_413");
    case 415:
      return tRuntime("api_error_http_415");
    case 422:
      return tRuntime("api_error_http_422");
    case 429:
      return tRuntime("api_error_http_429");
    case 500:
      return tRuntime("api_error_http_500");
    case 502:
      return tRuntime("api_error_http_502");
    case 503:
      return tRuntime("api_error_http_503");
    case 504:
      return tRuntime("api_error_http_504");
    default:
      if (typeof statusCode !== "number") {
        return tRuntime("api_error_no_response");
      }
      if (statusCode >= 400 && statusCode < 500) {
        return tRuntime("api_error_http_client_default");
      }
      if (statusCode >= 500 && statusCode < 600) {
        return tRuntime("api_error_http_server_default");
      }
      return tRuntime("api_error_http_default");
  }
}

function readableApiErrorMessage(
  data: unknown,
  statusCode: number | null,
  error: unknown,
): string {
  const detail = extractReadableDetail(data);
  if (detail && !isGenericHttpDetail(detail, statusCode)) {
    return detail;
  }
  const fallback = fallbackHttpStatusMessage(statusCode);
  if (fallback) {
    return fallback;
  }
  return error instanceof Error ? error.message : String(error ?? "API request failed");
}

function getResponseHeaderValue(
  headers: unknown,
  name: string,
): string | null {
  if (!headers) {
    return null;
  }
  const lowerName = name.toLowerCase();
  if (
    typeof (headers as { get?: unknown }).get === "function"
  ) {
    const value = (headers as { get: (headerName: string) => unknown }).get(name);
    return typeof value === "string" && value.trim() ? value.trim() : null;
  }
  if (isRecord(headers)) {
    for (const [key, value] of Object.entries(headers)) {
      if (key.toLowerCase() !== lowerName) {
        continue;
      }
      return typeof value === "string" && value.trim() ? value.trim() : null;
    }
  }
  return null;
}

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const response = error?.response;
    const config = error?.config;
    const method =
      typeof config?.method === "string" ? config.method.toUpperCase() : null;
    const url = config?.url ?? null;
    const statusCode: number | null = response?.status ?? null;
    const requestId = getResponseHeaderValue(response?.headers, "x-request-id");
    const readableMessage = readableApiErrorMessage(
      response?.data,
      statusCode,
      error,
    );
    if (error && typeof error === "object") {
      try {
        (error as { message?: string }).message = readableMessage;
      } catch {
        // Preserve the original error object if a runtime marks message read-only.
      }
    }
    postClientLog("api: request failed", {
      scope: "api",
      phase: "request-failed",
      method: "error",
      dedupeMs: 500,
      details: {
        method,
        url,
        status_code: statusCode,
        request_id: requestId,
        response_detail: summarizeApiErrorData(response?.data),
        ...summarizeErrorForLog(error),
        error_message: readableMessage,
      },
    });
    // Mirror the failure into the action history bundle so a bug report
    // submitted minutes later still sees the recent 4xx/5xx context.
    // 同步写入操作历史，便于后续提交 Bug 报告时仍能带上最近的 API 错误。
    if (typeof statusCode === "number" && statusCode >= 400) {
      try {
        useActionHistoryStore.getState().pushAction({
          action_type: "api_error",
          error: {
            status_code: statusCode,
            path: typeof url === "string" ? url : String(url ?? ""),
            ...(requestId ? { request_id: requestId } : {}),
            error_message: readableMessage,
          },
        });
      } catch {
        // Action history must never propagate failure into the HTTP layer.
        // 即便历史记录失败，也不得影响 HTTP 调用链。
      }
    }
    return Promise.reject(error);
  },
);

export default apiClient;
