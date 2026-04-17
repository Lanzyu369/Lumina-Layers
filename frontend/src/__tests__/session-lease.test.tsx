// @vitest-environment jsdom

import { StrictMode } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  heartbeatSessionMock,
  closeSessionMock,
  beaconCloseSessionMock,
} = vi.hoisted(() => ({
  heartbeatSessionMock: vi.fn(),
  closeSessionMock: vi.fn(),
  beaconCloseSessionMock: vi.fn(),
}));

vi.mock("../api/session", () => ({
  heartbeatSession: heartbeatSessionMock,
  closeSession: closeSessionMock,
  beaconCloseSession: beaconCloseSessionMock,
}));

import { useSessionLease } from "../hooks/useSessionLease";

function StrictModeWrapper({ children }: { children: React.ReactNode }) {
  return <StrictMode>{children}</StrictMode>;
}

describe("useSessionLease", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
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
    expect(closeSessionMock).toHaveBeenCalledWith("session-a");
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
    expect(closeSessionMock).toHaveBeenCalledWith("session-a");
  });

  it("uses beacon close when the page unloads", () => {
    renderHook(({ sessionId }) => useSessionLease(sessionId), {
      initialProps: { sessionId: "session-a" },
      wrapper: StrictModeWrapper,
    });

    act(() => {
      window.dispatchEvent(new Event("beforeunload"));
    });

    expect(beaconCloseSessionMock).toHaveBeenCalledTimes(1);
    expect(beaconCloseSessionMock).toHaveBeenCalledWith("session-a");
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
