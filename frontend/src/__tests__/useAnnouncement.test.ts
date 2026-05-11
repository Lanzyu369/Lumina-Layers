import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ANNOUNCEMENTS } from "../data/announcements";
import type { AnnouncementEntry } from "../data/announcements";
import {
  ANNOUNCEMENT_STORAGE_KEY,
  ANNOUNCEMENT_WINDOW_DAYS,
  selectEntriesWithinWindow,
  useAnnouncement,
} from "../hooks/useAnnouncement";

beforeEach(() => {
  localStorage.clear();
});

function makeEntry(version: string): AnnouncementEntry {
  return {
    version,
    title: { zh: `标题 ${version}`, en: `Title ${version}` },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [{ zh: `条目 ${version}`, en: `Item ${version}` }],
      },
    ],
  };
}

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

  it("case-6 entries 至少包含锚点 entry 并与 entry 一致", async () => {
    const { result } = renderHook(() => useAnnouncement());

    await waitFor(() => {
      expect(result.current.entries.length).toBeGreaterThan(0);
    });

    expect(result.current.entries[0]).toBe(result.current.entry);
    expect(result.current.entries[0]?.version).toBe(ANNOUNCEMENTS[0].version);
  });
});

/**
 * AGENTS.md 公告渲染规则：窗口=锚点那一天向前 WINDOW_DAYS 天（含锚点当天）。
 * 下面的不变式断言直接锁住"窗口内所有 entry 都返回"，防止退化成"只返回最新一条"。
 */
describe("selectEntriesWithinWindow", () => {
  it("空数组返回空", () => {
    expect(selectEntriesWithinWindow([])).toEqual([]);
  });

  it("窗口内多条 entry 按 version 降序全部返回", () => {
    const entries = [
      makeEntry("2026-05-10"),
      makeEntry("2026-05-09"),
      makeEntry("2026-05-08"),
    ];

    const selected = selectEntriesWithinWindow(entries);

    expect(selected.map((e) => e.version)).toEqual([
      "2026-05-10",
      "2026-05-09",
      "2026-05-08",
    ]);
  });

  it("超出窗口的旧 entry 被剔除", () => {
    // anchor=2026-05-10, WINDOW_DAYS=3 → [05-08, 05-09, 05-10]，05-07 必须被剔除
    const entries = [
      makeEntry("2026-05-10"),
      makeEntry("2026-05-09"),
      makeEntry("2026-05-07"),
    ];

    const selected = selectEntriesWithinWindow(entries);

    expect(selected.map((e) => e.version)).toEqual(["2026-05-10", "2026-05-09"]);
  });

  it("窗口宽度由 ANNOUNCEMENT_WINDOW_DAYS 控制", () => {
    // 用一个明显更宽的窗口验证可配置性，避免硬编码 3
    const entries = Array.from({ length: 5 }, (_, index) =>
      makeEntry(`2026-05-${String(10 - index).padStart(2, "0")}`),
    );

    const wide = selectEntriesWithinWindow(entries, 5);
    expect(wide).toHaveLength(5);

    const narrow = selectEntriesWithinWindow(entries, 1);
    expect(narrow.map((e) => e.version)).toEqual(["2026-05-10"]);
  });

  it("常量 ANNOUNCEMENT_WINDOW_DAYS 必须 >= 3", () => {
    // AGENTS.md 规则硬性要求窗口至少覆盖 3 天；这个断言让任何私自缩小窗口的改动立刻红
    expect(ANNOUNCEMENT_WINDOW_DAYS).toBeGreaterThanOrEqual(3);
  });

  it("锚点 version 非法格式时降级为只返回锚点本身", () => {
    const entries = [
      { ...makeEntry("2026-05-10"), version: "not-a-date" },
      makeEntry("2026-05-09"),
    ];

    const selected = selectEntriesWithinWindow(entries);
    expect(selected).toHaveLength(1);
    expect(selected[0]?.version).toBe("not-a-date");
  });
});
