import { useEffect, useMemo, useState } from "react";
import { ANNOUNCEMENTS } from "../data/announcements";
import type { AnnouncementEntry } from "../data/announcements";
import { nowBeijingIso } from "../utils/beijingTime";

export const ANNOUNCEMENT_STORAGE_KEY = "lumina-announcement-dismissed";

/**
 * 启动弹窗内保留的日公告条数。
 *
 * 服务器可能隔几天才更新一次；这里按条数保留最近的历史记录，
 * 避免用户只看到最新一天而漏掉中间几天的变化。
 */
export const ANNOUNCEMENT_HISTORY_LIMIT = 14;

export interface UseAnnouncementResult {
  visible: boolean;
  /** 最近的日公告历史，按 version 降序；用于多条渲染。 */
  entries: AnnouncementEntry[];
  /** 最新一条 entry（即锚点），用于版本徽章和 dismiss。 */
  entry: AnnouncementEntry | null;
  /** 锚点 version；dismiss 时写入 localStorage。 */
  version: string;
  close: () => void;
  dismissThisVersion: () => void;
}

/**
 * 选出最近的日公告历史（按 version 降序）。
 */
export function selectAnnouncementHistory(
  entries: ReadonlyArray<AnnouncementEntry>,
  limit: number = ANNOUNCEMENT_HISTORY_LIMIT,
): AnnouncementEntry[] {
  if (entries.length === 0 || limit <= 0) {
    return [];
  }

  const sorted = [...entries].sort((left, right) =>
    right.version.localeCompare(left.version),
  );
  return sorted.slice(0, Math.floor(limit));
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
  const entries = useMemo(() => selectAnnouncementHistory(ANNOUNCEMENTS), []);
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
