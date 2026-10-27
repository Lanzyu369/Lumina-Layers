/**
 * Narrow ownership for converter preview cancellation and stale-response guards.
 * 转换器预览取消与旧响应防护的窄职责协调器。
 *
 * A configuration change can happen after a request has already reached the
 * backend. Aborting is best effort, so a monotonically increasing token is
 * also required before a completed old response may write Zustand state.
 * 配置变更可能发生在请求已经到达后端之后。取消只是尽力而为，因此还需要单调
 * 递增的 token，确保已经完成的旧响应不能写入 Zustand 状态。
 */

export interface PreviewRequestLease {
  signal: AbortSignal;
  token: number;
}

let activeController: AbortController | null = null;
let currentToken = 0;

/** Start a preview request, invalidating any previous request. */
export function beginPreviewRequest(): PreviewRequestLease {
  activeController?.abort();
  activeController = new AbortController();
  currentToken += 1;
  return {
    signal: activeController.signal,
    token: currentToken,
  };
}

/** Abort and invalidate the active preview after analysis-affecting changes. */
export function invalidatePreviewRequest(): void {
  currentToken += 1;
  activeController?.abort();
  activeController = null;
}

/** Whether a request is still allowed to publish its result. */
export function isCurrentPreviewRequest(lease: PreviewRequestLease): boolean {
  return (
    currentToken === lease.token &&
    activeController?.signal === lease.signal &&
    !lease.signal.aborted
  );
}
