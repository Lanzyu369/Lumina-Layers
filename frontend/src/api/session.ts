import apiClient from "./client";

const SESSION_API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";

/**
 * Renew an active frontend session lease.
 */
export async function heartbeatSession(sessionId: string): Promise<void> {
  await apiClient.post(
    "/session/heartbeat",
    { session_id: sessionId },
    { timeout: 30_000 },
  );
}

/**
 * Best-effort close for an active frontend session lease.
 */
export async function closeSession(sessionId: string): Promise<void> {
  await apiClient
    .post(
      "/session/close",
      { session_id: sessionId },
      { timeout: 5_000 },
    )
    .catch(() => {
      /* fire-and-forget: ignore close failures */
    });
}

/**
 * Use sendBeacon to close the active session during page unload.
 */
export function beaconCloseSession(sessionId: string): void {
  const body = JSON.stringify({ session_id: sessionId });
  const beaconUrl = `${SESSION_API_BASE}/session/close`;

  if (
    typeof navigator !== "undefined" &&
    typeof navigator.sendBeacon === "function"
  ) {
    navigator.sendBeacon(
      beaconUrl,
      new Blob([body], { type: "application/json" }),
    );
    return;
  }

  void closeSession(sessionId);
}
