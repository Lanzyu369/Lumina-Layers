import { useEffect, useMemo, useState } from "react";
import { ANNOUNCEMENTS } from "../data/announcements";
import type { AnnouncementEntry } from "../data/announcements";
import { nowBeijingIso } from "../utils/beijingTime";

export const ANNOUNCEMENT_STORAGE_KEY = "lumina-announcement-dismissed";

/**
 * 公告渲染窗口（自然日）。锚点 = `ANNOUNCEMENTS[0].version`（等价于 PR 合入日期），
 * 窗口 = [anchor - (WINDOW_DAYS - 1), anchor]，含锚点当日。
 *
 * Do NOT silently shrink this to "只展示最新一条"；规则写在 AGENTS.md 里，
 * 改动前先同步规则和测试。
 */
export const ANNOUNCEMENT_WINDOW_DAYS = 3;

export interface UseAnnouncementResult {
  visible: boolean;
  /** 窗口内所有 entry，按 version 降序；用于多条渲染。 */
  entries: AnnouncementEntry[];
  /** 窗口内最新一条 entry（即锚点），用于版本徽章和 dismiss。 */
  entry: AnnouncementEntry | null;
  /** 锚点 version；dismiss 时写入 localStorage。 */
  version: string;
  close: () => void;
  dismissThisVersion: () => void;
}

/** 把 `YYYY-MM-DD` 解析成当日 UTC 零点毫秒，用于稳定做日期减法。 */
function parseVersionToUtcMs(version: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(version);
  if (!match) {
    return null;
  }
  const [, yearStr, monthStr, dayStr] = match;
  const utcMs = Date.UTC(Number(yearStr), Number(monthStr) - 1, Number(dayStr));
  return Number.isNaN(utcMs) ? null : utcMs;
}

/**
 * 选出窗口内所有 entry（按 version 降序）。
 *
 * 锚点取输入数组中 version 最大者；窗口包含锚点当日并向前覆盖
 * `ANNOUNCEMENT_WINDOW_DAYS - 1` 天。
 */
export function selectEntriesWithinWindow(
  entries: ReadonlyArray<AnnouncementEntry>,
  windowDays: number = ANNOUNCEMENT_WINDOW_DAYS,
): AnnouncementEntry[] {
  if (entries.length === 0) {
    return [];
  }

  const sorted = [...entries].sort((left, right) =>
    right.version.localeCompare(left.version),
  );

  const anchorVersion = sorted[0]?.version;
  if (!anchorVersion) {
    return [];
  }

  const anchorMs = parseVersionToUtcMs(anchorVersion);
  if (anchorMs === null) {
    // 锚点日期格式异常时降级为仅返回锚点本身，避免把一整批古董公告推给用户。
    return [sorted[0]];
  }

  const earliestMs = anchorMs - (windowDays - 1) * 24 * 60 * 60 * 1000;

  return sorted.filter((candidate) => {
    const candidateMs = parseVersionToUtcMs(candidate.version);
    if (candidateMs === null) {
      return false;
    }
    return candidateMs >= earliestMs && candidateMs <= anchorMs;
  });
}

function readDismissedVersion(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(ANNOUNCEMENT_STORAGE_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as { version?: unknown; dismissedAt?: unknown };
    return typeof parsed.version === "string" ? parsed.version : null;
  } catch {
    return null;
  }
}

export function useAnnouncement(): UseAnnouncementResult {
  const entries = useMemo(() => selectEntriesWithinWindow(ANNOUNCEMENTS), []);
  const entry = entries[0] ?? null;
  const version = entry?.version ?? "";
  const [visible, setVisible] = useState<boolean>(() => false);

  useEffect(() => {
    if (typeof window === "undefined") {
      setVisible(false);
      return;
    }

    if (!entry) {
      setVisible(false);
      return;
    }

    const dismissedVersion = readDismissedVersion();
    setVisible(dismissedVersion !== version);
  }, [entry, version]);

  const close = () => {
    setVisible(false);
  };

  const dismissThisVersion = () => {
    setVisible(false);

    if (typeof window === "undefined") {
      return;
    }

    try {
      window.localStorage.setItem(
        ANNOUNCEMENT_STORAGE_KEY,
        JSON.stringify({
          version,
          dismissedAt: nowBeijingIso(),
        }),
      );
    } catch {
      // Ignore storage write failures such as private mode or quota errors.
    }
  };

  return {
    visible,
    entries,
    entry,
    version,
    close,
    dismissThisVersion,
  };
}
