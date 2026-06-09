import { useEffect, useRef } from "react";

import {
  beaconCloseSession,
  closeSession,
  heartbeatSession,
  isSessionCloseRequested,
} from "../api/session";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import type { Workstream } from "../types/actionHistory";

const HEARTBEAT_INTERVAL_MS = 2 * 60 * 1000;
const SESSION_CLOSE_DELAY_MS = 0;
const EMPTY_KEEP_FILE_IDS: readonly string[] = [];
const pendingSessionCloseTimers = new Map<string, number>();

function cancelPendingSessionClose(sessionId: string): void {
  const pendingTimer = pendingSessionCloseTimers.get(sessionId);
  if (pendingTimer === undefined) {
    return;
  }

  window.clearTimeout(pendingTimer);
  pendingSessionCloseTimers.delete(sessionId);
}

function normalizeKeepFileIds(keepFileIds: readonly string[]): string[] {
  return Array.from(new Set(keepFileIds));
}

function scheduleSessionClose(
  sessionId: string,
  keepFileIds: readonly string[] = EMPTY_KEEP_FILE_IDS,
): void {
  cancelPendingSessionClose(sessionId);
  if (isSessionCloseRequested(sessionId)) {
    return;
  }
  const keepFileIdsSnapshot = normalizeKeepFileIds(keepFileIds);
  const timerId = window.setTimeout(() => {
    pendingSessionCloseTimers.delete(sessionId);
    if (isSessionCloseRequested(sessionId)) {
      return;
    }
    void closeSession(sessionId, keepFileIdsSnapshot);
  }, SESSION_CLOSE_DELAY_MS);
  pendingSessionCloseTimers.set(sessionId, timerId);
}

export function useSessionLease(
  sessionId: string | null | undefined,
  workstream: Workstream = "converter",
  keepFileIds: readonly string[] = EMPTY_KEEP_FILE_IDS,
): void {
  const keepFileIdsRef = useRef<string[]>([]);
  keepFileIdsRef.current = normalizeKeepFileIds(keepFileIds);

  useEffect(() => {
    if (!sessionId) {
      return;
    }

    cancelPendingSessionClose(sessionId);

    // Record this session id into the action-history session ring so the
    // bug-report bundle can reference recent sessions even after the source
    // session has been cleaned up on the backend.
    // TODO(task 1.4): callers in App.tsx should pass an explicit workstream
    // argument ('converter' vs 'single_stage') so the ring is accurately
    // labelled; this wiring only provides the plumbing.
    // 把会话 id 登记到操作历史的会话环中，便于反馈复现包在后端 session 已清理
    // 后仍能追溯近期会话。工作流分类的精细化由后续任务 1.4 处理。
    useActionHistoryStore.getState().observeSession(workstream, sessionId);

    const intervalId = window.setInterval(() => {
      void heartbeatSession(sessionId).catch(() => {
        /* best-effort keepalive */
      });
    }, HEARTBEAT_INTERVAL_MS);

    const handleBeforeUnload = () => {
      if (isSessionCloseRequested(sessionId)) {
        return;
      }
      beaconCloseSession(sessionId, keepFileIdsRef.current);
    };

    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("beforeunload", handleBeforeUnload);
      scheduleSessionClose(sessionId, keepFileIdsRef.current);
    };
  }, [sessionId, workstream]);
}
