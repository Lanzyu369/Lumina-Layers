import { useEffect } from "react";

export type ClearGltfUrl = (url: string) => void;

export const GLTF_CACHE_RELEASE_DELAY_MS = 250;

interface GltfCacheEntry {
  owners: number;
  releaseTimer: ReturnType<typeof setTimeout> | null;
}

const gltfCacheEntries = new Map<string, GltfCacheEntry>();

function getOrCreateEntry(url: string): GltfCacheEntry {
  const existing = gltfCacheEntries.get(url);
  if (existing) {
    return existing;
  }

  const created: GltfCacheEntry = {
    owners: 0,
    releaseTimer: null,
  };
  gltfCacheEntries.set(url, created);
  return created;
}

function acquireGltfUrl(url: string): void {
  const entry = getOrCreateEntry(url);
  entry.owners += 1;

  if (entry.releaseTimer !== null) {
    clearTimeout(entry.releaseTimer);
    entry.releaseTimer = null;
  }
}

function releaseGltfUrl(url: string, clearUrl: ClearGltfUrl): void {
  const entry = gltfCacheEntries.get(url);
  if (!entry) {
    return;
  }

  entry.owners = Math.max(0, entry.owners - 1);
  if (entry.owners > 0 || entry.releaseTimer !== null) {
    return;
  }

  entry.releaseTimer = setTimeout(() => {
    const currentEntry = gltfCacheEntries.get(url);
    if (!currentEntry) {
      return;
    }

    currentEntry.releaseTimer = null;
    if (currentEntry.owners > 0) {
      return;
    }

    gltfCacheEntries.delete(url);
    clearUrl(url);
  }, GLTF_CACHE_RELEASE_DELAY_MS);
}

/**
 * Keep the current GLTF resource cached across transient unmount/remount cycles
 * while clearing stale URLs once no active viewer still owns them.
 */
export function useGltfCacheLifecycle(url: string, clearUrl: ClearGltfUrl): void {
  useEffect(() => {
    acquireGltfUrl(url);
    return () => {
      releaseGltfUrl(url, clearUrl);
    };
  }, [clearUrl, url]);
}

export function resetGltfCacheLifecycleForTests(): void {
  for (const entry of gltfCacheEntries.values()) {
    if (entry.releaseTimer !== null) {
      clearTimeout(entry.releaseTimer);
    }
  }
  gltfCacheEntries.clear();
}
