/**
 * Error Ticket Prompt Store — decides when to ask the user whether they want
 * to submit a bug-report ticket after an unexpected error.
 * 错误工单提示 Store：在发生意外错误后，决定是否弹出“是否提交工单”的提示。
 *
 * Only unexpected failures qualify: API responses with status >= 500 and
 * uncaught frontend runtime errors. 4xx responses are usually input
 * validation that the panel already explains, so they never prompt.
 * 仅意外故障会触发：接口 5xx 与前端未捕获异常。4xx 通常是输入校验错误，
 * 面板已有说明，不弹提示。
 *
 * Noise guards: one prompt at a time (a new error after the card is closed
 * prompts again), a per-session opt-out, and an ignore list for feedback/log endpoints so a
 * failing bug-report upload cannot prompt for another bug report.
 * 防打扰：同一时间只显示一个提示（关闭后再出错会再次提示）、可选“本次不再提示”，
 * 并忽略反馈/日志接口自身的失败，避免循环提示。
 */

import { create } from "zustand";

/** Lowest HTTP status that counts as an unexpected server failure. */
export const ERROR_TICKET_PROMPT_MIN_STATUS = 500;

/**
 * API paths whose failures must never prompt (the feedback pipeline itself).
 * 反馈链路自身的接口失败不提示，避免循环。
 */
const IGNORED_PATH_FRAGMENTS = ["/feedback", "/client-log"];

/**
 * Runtime error messages that are benign browser noise rather than bugs.
 * 属于浏览器噪声而非真实缺陷的运行时错误。
 */
const IGNORED_CLIENT_MESSAGE_PATTERNS = [
  /ResizeObserver loop/i,
  /^Script error\.?$/i,
];

/** Where the error came from. / 错误来源。 */
export type ErrorTicketPromptKind = "api" | "client";

/**
 * Error details shown in the prompt and pre-filled into the ticket.
 * 显示在提示中、并预填到工单描述里的错误信息。
 */
export interface ErrorTicketPromptInfo {
  kind: ErrorTicketPromptKind;
  message: string;
  statusCode?: number;
  path?: string;
  requestId?: string;
  occurredAt: number;
}

interface ErrorTicketPromptState {
  /** Error currently waiting for the user's answer, or null. */
  pending: ErrorTicketPromptInfo | null;
  /** True once the user chose "don't ask again this session". */
  suppressed: boolean;

  reportApiError: (input: {
    statusCode: number | null;
    path: string | null;
    requestId?: string | null;
    message: string;
  }) => void;
  reportClientError: (message: string) => void;
  dismiss: () => void;
  suppressForSession: () => void;
  _resetForTests: () => void;
}

/**
 * Return true when an API failure is an unexpected server-side error that is
 * worth a ticket.
 * 判断接口失败是否为值得提交工单的服务端意外错误。
 */
export function isTicketWorthyApiError(
  statusCode: number | null,
  path: string | null,
): boolean {
  if (typeof statusCode !== "number" || statusCode < ERROR_TICKET_PROMPT_MIN_STATUS) {
    return false;
  }
  const normalizedPath = path ?? "";
  return !IGNORED_PATH_FRAGMENTS.some((fragment) => normalizedPath.includes(fragment));
}

/**
 * Return true when an uncaught runtime error message is a real failure
 * rather than known browser noise.
 * 判断未捕获异常是否为真实错误（而非已知浏览器噪声）。
 */
export function isTicketWorthyClientError(message: string): boolean {
  const trimmed = message.trim();
  if (!trimmed) return false;
  return !IGNORED_CLIENT_MESSAGE_PATTERNS.some((pattern) => pattern.test(trimmed));
}

export const useErrorTicketPromptStore = create<ErrorTicketPromptState>((set, get) => {
  /** Show ``info`` unless suppressed or a prompt is already showing. */
  const offer = (info: ErrorTicketPromptInfo): void => {
    const { pending, suppressed } = get();
    if (suppressed || pending != null) return;
    set({ pending: info });
  };

  return {
    pending: null,
    suppressed: false,

    reportApiError: ({ statusCode, path, requestId, message }) => {
      try {
        if (!isTicketWorthyApiError(statusCode, path)) return;
        offer({
          kind: "api",
          message,
          statusCode: statusCode ?? undefined,
          path: path ?? undefined,
          requestId: requestId ?? undefined,
          occurredAt: Date.now(),
        });
      } catch {
        // The prompt is optional UX and must never break the HTTP layer.
        // 提示只是辅助体验，不能影响 HTTP 调用链。
      }
    },

    reportClientError: (message) => {
      try {
        if (!isTicketWorthyClientError(message)) return;
        offer({ kind: "client", message: message.trim(), occurredAt: Date.now() });
      } catch {
        // Never throw from a global error handler.
        // 全局错误处理器中绝不能再抛错。
      }
    },

    dismiss: () => set({ pending: null }),

    suppressForSession: () => set({ pending: null, suppressed: true }),

    _resetForTests: () => set({ pending: null, suppressed: false }),
  };
});
