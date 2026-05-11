import axios from "axios";
import { postClientLog, summarizeErrorForLog } from "../utils/clientLog";
import { useActionHistoryStore } from "../stores/actionHistoryStore";

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

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const response = error?.response;
    const config = error?.config;
    const method =
      typeof config?.method === "string" ? config.method.toUpperCase() : null;
    const url = config?.url ?? null;
    const statusCode: number | null = response?.status ?? null;
    postClientLog("api: request failed", {
      scope: "api",
      phase: "request-failed",
      method: "error",
      dedupeMs: 500,
      details: {
        method,
        url,
        status_code: statusCode,
        response_detail: summarizeApiErrorData(response?.data),
        ...summarizeErrorForLog(error),
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
            error_message:
              typeof error?.message === "string"
                ? error.message
                : String(error ?? "unknown error"),
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
