import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ANNOUNCEMENTS } from "../data/announcements";
import type { AnnouncementEntry } from "../data/announcements";
import {
  ANNOUNCEMENT_HISTORY_LIMIT,
  ANNOUNCEMENT_STORAGE_KEY,
  selectAnnouncementHistory,
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
  it("keeps the material-profile 3D preview fix in announcement history", () => {
    const entry = ANNOUNCEMENTS.find((item) => item.version === "2026-07-19");
    const items = entry?.sections.flatMap((section) => section.items) ?? [];

    expect(
      items.some(
        (item) =>
          item.zh.includes("耗材档案") &&
          item.zh.includes("模拟颜色") &&
          item.zh.includes("浮雕") &&
          item.en.includes("Material-profile") &&
          item.en.toLowerCase().includes("simulated recipe colours") &&
          item.en.toLowerCase().includes("relief"),
      ),
    ).toBe(true);
  });

  it("announces Flash Studio Desktop and Flashforge multicolor support", () => {
    expect(ANNOUNCEMENTS[0]?.version).toBe("2026-07-22");
    const items = ANNOUNCEMENTS[0]?.sections.flatMap((section) => section.items) ?? [];

    expect(
      items.some(
        (item) =>
          item.zh.includes("Flash Studio Desktop") &&
          item.zh.includes("AD5X") &&
          item.zh.includes("Creator 5") &&
          item.zh.includes("Guider 3 Ultra") &&
          item.zh.includes("Guider4") &&
          item.en.includes("Flash Studio Desktop") &&
          item.en.includes("0.25") &&
          item.en.includes("0.4") &&
          item.en.includes("2.3.2") &&
          item.en.includes("Lumina process settings"),
      ),
    ).toBe(true);
  });

  it("keeps scoped large-format recolouring in announcement history", () => {
    const entry = ANNOUNCEMENTS.find((item) => item.version === "2026-07-18");
    const items = entry?.sections.flatMap((section) => section.items) ?? [];

    expect(
      items.some(
        (item) =>
          item.zh.includes("大画幅") &&
          item.zh.includes("选中区域") &&
          item.en.includes("Large-format") &&
          item.en.includes("selected area"),
      ),
    ).toBe(true);
  });

  it("keeps the base-layer alignment fix in announcement history", () => {
    const entry = ANNOUNCEMENTS.find((item) => item.version === "2026-07-18");
    const items = entry?.sections.flatMap((section) => section.items) ?? [];

    expect(
      items.some(
        (item) =>
          item.zh.includes("底板层高") &&
          item.zh.includes("浮雕") &&
          item.zh.includes("双面") &&
          item.en.toLowerCase().includes("base-layer") &&
          item.en.toLowerCase().includes("relief") &&
          item.en.toLowerCase().includes("double-sided"),
      ),
    ).toBe(true);
  });

  it("keeps SVG vector relief support in announcement history", () => {
    const reliefEntry = ANNOUNCEMENTS.find((entry) => entry.version === "2026-07-15");
    const items = reliefEntry?.sections.flatMap((section) => section.items) ?? [];

    expect(
      items.some(
        (item) =>
          item.zh.includes("SVG") &&
          item.zh.includes("浮雕") &&
          item.en.includes("SVG") &&
          item.en.toLowerCase().includes("relief"),
      ),
    ).toBe(true);
  });

  it("keeps the Karvax material rename in announcement history", () => {
    const items = ANNOUNCEMENTS.flatMap((entry) =>
      entry.sections.flatMap((section) => section.items),
    );

    expect(items.some((item) => item.zh.includes("Karvax") && item.en.includes("Karvax")))
      .toBe(true);
  });

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
 * 公告弹窗展示最近的日公告历史，防止服务器隔几天上线时只露出最新一天。
 */
describe("selectAnnouncementHistory", () => {
  it("空数组返回空", () => {
    expect(selectAnnouncementHistory([])).toEqual([]);
  });

  it("多条 entry 按 version 降序返回", () => {
    const entries = [
      makeEntry("2026-05-09"),
      makeEntry("2026-05-10"),
      makeEntry("2026-05-08"),
    ];

    const selected = selectAnnouncementHistory(entries);

    expect(selected.map((e) => e.version)).toEqual([
      "2026-05-10",
      "2026-05-09",
      "2026-05-08",
    ]);
  });

  it("最多返回指定条数的历史记录", () => {
    const entries = Array.from({ length: 5 }, (_, index) =>
      makeEntry(`2026-05-${String(10 - index).padStart(2, "0")}`),
    );

    const selected = selectAnnouncementHistory(entries, 3);

    expect(selected.map((e) => e.version)).toEqual([
      "2026-05-10",
      "2026-05-09",
      "2026-05-08",
    ]);
  });

  it("限制为 0 或负数时返回空", () => {
    const entries = [makeEntry("2026-05-10")];

    expect(selectAnnouncementHistory(entries, 0)).toEqual([]);
    expect(selectAnnouncementHistory(entries, -1)).toEqual([]);
  });

  it("默认历史条数足够覆盖这次 5 月更新回顾", () => {
    expect(ANNOUNCEMENT_HISTORY_LIMIT).toBeGreaterThanOrEqual(18);
    expect(selectAnnouncementHistory(ANNOUNCEMENTS).length).toBeGreaterThanOrEqual(18);
    expect(selectAnnouncementHistory(ANNOUNCEMENTS).map((e) => e.version)).toContain(
      "2026-05-05",
    );
  });

  it("非法日期文本也按普通版本文本排序，不会丢掉其它历史", () => {
    const entries = [
      makeEntry("2026-05-09"),
      { ...makeEntry("2026-05-10"), version: "not-a-date" },
    ];

    const selected = selectAnnouncementHistory(entries);
    expect(selected.map((e) => e.version)).toEqual(["not-a-date", "2026-05-09"]);
  });
});
