import { useEffect } from "react";

import {
  beaconCloseSession,
  closeSession,
  heartbeatSession,
} from "../api/session";

const HEARTBEAT_INTERVAL_MS = 2 * 60 * 1000;
const SESSION_CLOSE_DELAY_MS = 0;
const pendingSessionCloseTimers = new Map<string, number>();

function cancelPendingSessionClose(sessionId: string): void {
  const pendingTimer = pendingSessionCloseTimers.get(sessionId);
  if (pendingTimer === undefined) {
    return;
  }

  window.clearTimeout(pendingTimer);
  pendingSessionCloseTimers.delete(sessionId);
}

function scheduleSessionClose(sessionId: string): void {
  cancelPendingSessionClose(sessionId);
  const timerId = window.setTimeout(() => {
    pendingSessionCloseTimers.delete(sessionId);
    void closeSession(sessionId);
  }, SESSION_CLOSE_DELAY_MS);
  pendingSessionCloseTimers.set(sessionId, timerId);
}

export function useSessionLease(sessionId: string | null | undefined): void {
  useEffect(() => {
    if (!sessionId) {
      return;
    }

    cancelPendingSessionClose(sessionId);

    const intervalId = window.setInterval(() => {
      void heartbeatSession(sessionId).catch(() => {
        /* best-effort keepalive */
      });
    }, HEARTBEAT_INTERVAL_MS);

    const handleBeforeUnload = () => {
      beaconCloseSession(sessionId);
    };

    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("beforeunload", handleBeforeUnload);
      scheduleSessionClose(sessionId);
    };
  }, [sessionId]);
}
