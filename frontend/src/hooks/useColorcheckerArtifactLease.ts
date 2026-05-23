import { useEffect, useMemo } from "react";

import { colorcheckerTouch } from "../api/extractor";

const COLORCHECKER_ARTIFACT_LEASE_INTERVAL_MS = 240_000;

export function useColorcheckerArtifactLease(
  fileIds: Array<string | null | undefined>,
  enabled = true,
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

  useEffect(() => {
    if (!enabled || !leaseKey) return;
    const ids = leaseKey.split("|");
    const renew = () => {
      ids.forEach((fileId) => {
        void colorcheckerTouch(fileId).catch(() => {});
      });
    };
    renew();
    const timer = window.setInterval(
      renew,
      COLORCHECKER_ARTIFACT_LEASE_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, [enabled, leaseKey]);
}
