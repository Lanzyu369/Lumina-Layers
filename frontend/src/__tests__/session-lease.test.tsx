// @vitest-environment jsdom

import { StrictMode } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  heartbeatSessionMock,
  closeSessionMock,
  beaconCloseSessionMock,
  isSessionCloseRequestedMock,
} = vi.hoisted(() => ({
  heartbeatSessionMock: vi.fn(),
  closeSessionMock: vi.fn(),
  beaconCloseSessionMock: vi.fn(),
  isSessionCloseRequestedMock: vi.fn(),
}));

vi.mock("../api/session", () => ({
  heartbeatSession: heartbeatSessionMock,
  closeSession: closeSessionMock,
  beaconCloseSession: beaconCloseSessionMock,
  isSessionCloseRequested: isSessionCloseRequestedMock,
}));

import { useSessionLease } from "../hooks/useSessionLease";

function StrictModeWrapper({ children }: { children: React.ReactNode }) {
  return <StrictMode>{children}</StrictMode>;
}

describe("useSessionLease", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    isSessionCloseRequestedMock.mockReturnValue(false);
  });

  afterEach(async () => {
    cleanup();
    await act(async () => {
      vi.runOnlyPendingTimers();
      await Promise.resolve();
    });
    vi.useRealTimers();
  });

  it("sends heartbeat every two minutes while a session is active", async () => {
    heartbeatSessionMock.mockResolvedValue(undefined);

    renderHook(({ sessionId }) => useSessionLease(sessionId), {
      initialProps: { sessionId: "session-a" },
      wrapper: StrictModeWrapper,
    });

    await act(async () => {
      vi.advanceTimersByTime(240_000);
      await Promise.resolve();
    });

    expect(heartbeatSessionMock).toHaveBeenCalledTimes(2);
    expect(heartbeatSessionMock).toHaveBeenNthCalledWith(1, "session-a");
    expect(heartbeatSessionMock).toHaveBeenNthCalledWith(2, "session-a");
  });

  it("does not close the current session during StrictMode initial mount", async () => {
    renderHook(({ sessionId }) => useSessionLease(sessionId), {
      initialProps: { sessionId: "session-a" },
      wrapper: StrictModeWrapper,
    });

    await act(async () => {
      vi.runOnlyPendingTimers();
      await Promise.resolve();
    });

    expect(closeSessionMock).not.toHaveBeenCalled();
  });

  it("closes the previous session when the session id changes after the delay", async () => {
    const { rerender } = renderHook(
      ({ sessionId }) => useSessionLease(sessionId),
      {
        initialProps: { sessionId: "session-a" },
        wrapper: StrictModeWrapper,
      },
    );

    rerender({ sessionId: "session-b" });

    expect(closeSessionMock).not.toHaveBeenCalled();

    await act(async () => {
      vi.runOnlyPendingTimers();
      await Promise.resolve();
    });

    expect(closeSessionMock).toHaveBeenCalledTimes(1);
    expect(closeSessionMock).toHaveBeenCalledWith("session-a", []);
  });

  it("closes the active session on real unmount after the delay", async () => {
    const { unmount } = renderHook(
      ({ sessionId }) => useSessionLease(sessionId),
      {
        initialProps: { sessionId: "session-a" },
        wrapper: StrictModeWrapper,
      },
    );

    await act(async () => {
      vi.runOnlyPendingTimers();
      await Promise.resolve();
    });
    closeSessionMock.mockClear();

    unmount();

    expect(closeSessionMock).not.toHaveBeenCalled();

    await act(async () => {
      vi.runOnlyPendingTimers();
      await Promise.resolve();
    });

    expect(closeSessionMock).toHaveBeenCalledTimes(1);
    expect(closeSessionMock).toHaveBeenCalledWith("session-a", []);
  });

  it("passes kept file IDs to scheduled close when the session ends", async () => {
    const { unmount } = renderHook(
      ({ sessionId, keepFileIds }) =>
        useSessionLease(sessionId, "converter", keepFileIds),
      {
        initialProps: {
          sessionId: "session-a",
          keepFileIds: ["download-1", "preview-1"],
        },
        wrapper: StrictModeWrapper,
      },
    );

    await act(async () => {
      vi.runOnlyPendingTimers();
      await Promise.resolve();
    });
    closeSessionMock.mockClear();

    unmount();

    await act(async () => {
      vi.runOnlyPendingTimers();
      await Promise.resolve();
    });

    expect(closeSessionMock).toHaveBeenCalledTimes(1);
    expect(closeSessionMock).toHaveBeenCalledWith("session-a", [
      "download-1",
      "preview-1",
    ]);
  });

  it("skips scheduled close when another caller already requested it", async () => {
    isSessionCloseRequestedMock.mockReturnValue(true);
    const { unmount } = renderHook(({ sessionId }) => useSessionLease(sessionId), {
      initialProps: { sessionId: "session-a" },
      wrapper: StrictModeWrapper,
    });

    unmount();

    await act(async () => {
      vi.runOnlyPendingTimers();
      await Promise.resolve();
    });

    expect(closeSessionMock).not.toHaveBeenCalled();
  });

  it("uses beacon close with kept file IDs when the page unloads", () => {
    renderHook(
      ({ sessionId, keepFileIds }) =>
        useSessionLease(sessionId, "converter", keepFileIds),
      {
        initialProps: {
          sessionId: "session-a",
          keepFileIds: ["download-1", "preview-1"],
        },
        wrapper: StrictModeWrapper,
      },
    );

    act(() => {
      window.dispatchEvent(new Event("beforeunload"));
    });

    expect(beaconCloseSessionMock).toHaveBeenCalledTimes(1);
    expect(beaconCloseSessionMock).toHaveBeenCalledWith("session-a", [
      "download-1",
      "preview-1",
    ]);
  });

  it("does not heartbeat without a session id", async () => {
    renderHook(({ sessionId }) => useSessionLease(sessionId), {
      initialProps: { sessionId: null as string | null },
      wrapper: StrictModeWrapper,
    });

    await act(async () => {
      vi.advanceTimersByTime(240_000);
      await Promise.resolve();
    });

    expect(heartbeatSessionMock).not.toHaveBeenCalled();
    expect(closeSessionMock).not.toHaveBeenCalled();
  });
});
