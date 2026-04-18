import { useEffect, useState } from "react";
import { ANNOUNCEMENTS } from "../data/announcements";
import type { AnnouncementEntry } from "../data/announcements";
import { nowBeijingIso } from "../utils/beijingTime";

export const ANNOUNCEMENT_STORAGE_KEY = "lumina-announcement-dismissed";

export interface UseAnnouncementResult {
  visible: boolean;
  entry: AnnouncementEntry | null;
  version: string;
  close: () => void;
  dismissThisVersion: () => void;
}

function pickLatestEntry(entries: ReadonlyArray<AnnouncementEntry>): AnnouncementEntry | null {
  if (entries.length === 0) {
    return null;
  }

  return [...entries].sort((left, right) => right.version.localeCompare(left.version))[0] ?? null;
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
  const entry = pickLatestEntry(ANNOUNCEMENTS);
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
    entry,
    version,
    close,
    dismissThisVersion,
  };
}
