import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ANNOUNCEMENTS } from "../data/announcements";
import {
  ANNOUNCEMENT_STORAGE_KEY,
  useAnnouncement,
} from "../hooks/useAnnouncement";

beforeEach(() => {
  localStorage.clear();
});

describe("useAnnouncement", () => {
  it("case-1 首次访问", async () => {
    const { result } = renderHook(() => useAnnouncement());

    await waitFor(() => {
      expect(result.current.visible).toBe(true);
    });

    expect(result.current.entry).not.toBeNull();
    expect(result.current.entry?.version).toBe(ANNOUNCEMENTS[0].version);
  });

  it("case-2 已 dismiss 当前版本", async () => {
    localStorage.setItem(
      ANNOUNCEMENT_STORAGE_KEY,
      JSON.stringify({
        version: ANNOUNCEMENTS[0].version,
        dismissedAt: "2026-01-01T00:00:00+08:00",
      }),
    );

    const { result } = renderHook(() => useAnnouncement());

    await waitFor(() => {
      expect(result.current.entry?.version).toBe(ANNOUNCEMENTS[0].version);
    });

    expect(result.current.visible).toBe(false);
  });

  it("case-3 已 dismiss 旧版本", async () => {
    localStorage.setItem(
      ANNOUNCEMENT_STORAGE_KEY,
      JSON.stringify({
        version: "1900-01-01",
        dismissedAt: "2026-01-01T00:00:00+08:00",
      }),
    );

    const { result } = renderHook(() => useAnnouncement());

    await waitFor(() => {
      expect(result.current.visible).toBe(true);
    });
  });

  it("case-4 dismissThisVersion 会写 localStorage 并关闭", async () => {
    const { result } = renderHook(() => useAnnouncement());

    await waitFor(() => {
      expect(result.current.visible).toBe(true);
    });

    act(() => {
      result.current.dismissThisVersion();
    });

    expect(result.current.visible).toBe(false);

    const stored = localStorage.getItem(ANNOUNCEMENT_STORAGE_KEY);
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored ?? "{}") as {
      version?: string;
      dismissedAt?: string;
    };
    expect(parsed.version).toBe(ANNOUNCEMENTS[0].version);
    expect(parsed.dismissedAt?.endsWith("+08:00")).toBe(true);
  });

  it("case-5 close 不写 localStorage", async () => {
    const { result } = renderHook(() => useAnnouncement());

    await waitFor(() => {
      expect(result.current.visible).toBe(true);
    });

    act(() => {
      result.current.close();
    });

    expect(result.current.visible).toBe(false);
    expect(localStorage.getItem(ANNOUNCEMENT_STORAGE_KEY)).toBeNull();
  });
});
