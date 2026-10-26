import { useCallback, useEffect, useMemo, useState } from "react";

import { apiErrorToVisibleMessage } from "../api/client";
import {
  fetchCloudLutRegistryCatalog,
  fetchCloudLutRegistryStatus,
  installCloudLut,
} from "../api/lut";
import type {
  CloudLutRegistryCatalogItem,
  CloudLutRegistryCatalogResponse,
  CloudLutRegistryStatusResponse,
} from "../api/types";
import { useI18n } from "../i18n/context";
import Button from "./ui/Button";

const CLOUD_LUT_PAGE_SIZE = 100;

type CloudLutInstallState = "not_installed" | "installed" | "local_available";

const emptyCloudLutCatalog = (
  status: CloudLutRegistryStatusResponse | null,
): CloudLutRegistryCatalogResponse => ({
  configured: status?.configured ?? false,
  channels: status?.channels ?? [],
  items: [],
  total: 0,
});

const formatBytes = (bytes: number): string => {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
};

const readDisplayString = (
  display: Record<string, unknown> | null | undefined,
  keys: string[],
): string | null => {
  if (!display) {
    return null;
  }
  for (const key of keys) {
    const value = display[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
};

const readCompatibilityString = (
  compatibility: Record<string, unknown> | null | undefined,
  keys: string[],
): string | null => {
  if (!compatibility) {
    return null;
  }
  for (const key of keys) {
    const value = compatibility[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
};

const normalizeRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;

const catalogItemKey = (entry: CloudLutRegistryCatalogItem): string =>
  `${entry.lut_id}:${entry.revision_id}`;

const resolveCatalogInstallState = (
  entry: CloudLutRegistryCatalogItem,
): CloudLutInstallState => {
  if (entry.local_state === "installed") {
    return "installed";
  }
  if (entry.local_state === "local_available" || entry.local_exists === true) {
    return "local_available";
  }
  return "not_installed";
};

const mergeCatalogPage = (
  current: CloudLutRegistryCatalogResponse | null,
  nextPage: CloudLutRegistryCatalogResponse,
): CloudLutRegistryCatalogResponse => {
  if (!current) {
    return nextPage;
  }
  const existing = new Set(current.items.map(catalogItemKey));
  const appended = nextPage.items.filter((entry) => !existing.has(catalogItemKey(entry)));
  return {
    ...nextPage,
    channels: nextPage.channels.length > 0 ? nextPage.channels : current.channels,
    items: [...current.items, ...appended],
    total: nextPage.total ?? current.total,
  };
};

export default function LutCloudSyncPanel() {
  const { t } = useI18n();
  const [status, setStatus] = useState<CloudLutRegistryStatusResponse | null>(null);
  const [catalog, setCatalog] = useState<CloudLutRegistryCatalogResponse | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [pendingInstall, setPendingInstall] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadCatalogAndStatus = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setNotice(null);
    try {
      const statusResponse = await fetchCloudLutRegistryStatus();
      setStatus(statusResponse);
      if (!statusResponse.configured) {
        setCatalog(emptyCloudLutCatalog(statusResponse));
        setNotice(t("lut_sync_catalog_not_configured"));
        return;
      }
      const catalogResponse = await fetchCloudLutRegistryCatalog({
        channels: statusResponse.channels,
        limit: CLOUD_LUT_PAGE_SIZE,
        offset: 0,
      });
      setCatalog(catalogResponse);
    } catch (err) {
      setCatalog(null);
      setError(apiErrorToVisibleMessage(err, t("lut_sync_status_failed")));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadCatalogAndStatus();
  }, [loadCatalogAndStatus]);

  const refreshCatalog = useCallback(async () => {
    setIsRefreshing(true);
    setSuccess(null);
    try {
      await loadCatalogAndStatus();
      setSuccess(t("lut_sync_catalog_refresh_success"));
    } finally {
      setIsRefreshing(false);
    }
  }, [loadCatalogAndStatus, t]);

  const loadMoreCatalog = useCallback(async () => {
    if (!status?.configured || !catalog || isLoadingMore) {
      return;
    }
    const loadedCount = catalog.items.length;
    if (loadedCount >= catalog.total) {
      return;
    }
    setIsLoadingMore(true);
    setError(null);
    try {
      const nextPage = await fetchCloudLutRegistryCatalog({
        channels: status.channels,
        limit: CLOUD_LUT_PAGE_SIZE,
        offset: loadedCount,
      });
      setCatalog((current) => mergeCatalogPage(current, nextPage));
    } catch (err) {
      setError(apiErrorToVisibleMessage(err, t("lut_sync_status_failed")));
    } finally {
      setIsLoadingMore(false);
    }
  }, [catalog, isLoadingMore, status, t]);

  const handleInstall = useCallback(async (entry: CloudLutRegistryCatalogItem) => {
    const installKey = catalogItemKey(entry);
    setPendingInstall(installKey);
    setError(null);
    setSuccess(null);
    try {
      await installCloudLut(entry);
      await loadCatalogAndStatus();
      setSuccess(t("lut_sync_install_success"));
    } catch (err) {
      setError(apiErrorToVisibleMessage(err, t("lut_sync_install_failed")));
    } finally {
      setPendingInstall(null);
    }
  }, [loadCatalogAndStatus, t]);

  const filteredItems = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    return (catalog?.items ?? []).filter((entry) => {
      if (!normalizedQuery) {
        return true;
      }
      const display = normalizeRecord(entry.display);
      const compatibility = normalizeRecord(entry.compatibility);
      const haystack = [
        entry.lut_id,
        entry.revision_id,
        entry.content_hash,
        entry.local_path,
        entry.channel,
        entry.visibility,
        readDisplayString(display, ["name", "display_name", "lut_name", "title"]),
        readDisplayString(display, ["manufacturer", "brand", "vendor"]),
        readCompatibilityString(compatibility, ["color_mode", "mode", "profile"]),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [catalog, searchQuery]);

  const catalogLoadedCount = catalog?.items.length ?? 0;
  const catalogTotalCount = catalog?.total ?? catalogLoadedCount;
  const hasMoreCatalogEntries = status?.configured === true && catalogLoadedCount < catalogTotalCount;

}
