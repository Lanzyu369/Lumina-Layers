import { useEffect, useMemo } from "react";

import { colorcheckerTouch } from "../api/extractor";

const COLORCHECKER_ARTIFACT_LEASE_INTERVAL_MS = 240_000;

function normalizeLeaseResourceUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("/api/files/")) return url;
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.origin === window.location.origin && parsed.pathname.startsWith("/api/files/")) {
      return `${parsed.pathname}${parsed.search}`;
    }
  } catch {
    return null;
  }
  return null;
}

export function useColorcheckerArtifactLease(
  fileIds: Array<string | null | undefined>,
  enabled = true,
  resourceUrls: Array<string | null | undefined> = [],
): void {
  const leaseKey = useMemo(
    () =>
      Array.from(
        new Set(fileIds.filter((fileId): fileId is string => Boolean(fileId))),
      )
        .sort()
        .join("|"),
    [fileIds],
  );
  const resourceKey = useMemo(
    () =>
      Array.from(
        new Set(
          resourceUrls
            .map(normalizeLeaseResourceUrl)
            .filter((url): url is string => Boolean(url)),
        ),
      )
        .sort()
        .join("|"),
    [resourceUrls],
  );

  useEffect(() => {
    if (!enabled || (!leaseKey && !resourceKey)) return;
    const ids = leaseKey ? leaseKey.split("|") : [];
    const urls = resourceKey ? resourceKey.split("|") : [];
    const renew = () => {
      ids.forEach((fileId) => {
        void colorcheckerTouch(fileId).catch(() => {});
      });
      if (typeof fetch !== "function") return;
      urls.forEach((url) => {
        void Promise.resolve()
          .then(() => fetch(url, { cache: "no-store" }))
          .catch(() => undefined);
      });
    };
    renew();
    const timer = window.setInterval(
      renew,
      COLORCHECKER_ARTIFACT_LEASE_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, [enabled, leaseKey, resourceKey]);
}
