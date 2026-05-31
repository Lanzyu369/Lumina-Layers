import axios from "axios";
import { postClientLog, summarizeErrorForLog } from "../utils/clientLog";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import { getMlsPassword } from "../stores/mlsAuthStore";

/**
 * When set to ``true`` (e.g. by the MLS entry bootstrap), every request
 * issued by ``apiClient`` is decorated with the cached ``X-MLS-Password``
 * header. The main converter app leaves the flag at its default ``false``
 * so its requests stay unchanged.
 *
 * MLS 入口启动时把该标志置为 ``true``，于是 ``apiClient`` 的每次请求都自动
 * 注入 ``X-MLS-Password`` 头；主转换器应用保持 ``false``，请求行为不变。
 */
let MLS_PASSWORD_HEADER_ATTACH_ENABLED = false;

/** Enable automatic ``X-MLS-Password`` header injection for ``apiClient``.
 * 启用 ``apiClient`` 的 ``X-MLS-Password`` 头自动注入。
 */
export function enableApiClientMlsPasswordHeader(): void {
  MLS_PASSWORD_HEADER_ATTACH_ENABLED = true;
}

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

apiClient.interceptors.request.use((config) => {
  if (MLS_PASSWORD_HEADER_ATTACH_ENABLED) {
    const password = getMlsPassword();
    if (password) {
      config.headers = config.headers ?? {};
      (config.headers as Record<string, string>)["X-MLS-Password"] = password;
    }
  }
  return config;
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
