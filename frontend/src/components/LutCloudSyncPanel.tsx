import { LibraryIdentity, LibraryFields } from "./ui/LibraryDetails";
import CloudLibraryPreview, { CloudLibraryVersionTabs } from "./ui/CloudLibraryPreview";
import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";

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
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import Button from "./ui/Button";
import {
  StatusBanner,
  cardPadClass,
  resolvePanelSurfaceClass,
  wellPadClass,
} from "./ui/panelPrimitives";

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

const resolveLocalPath = (entry: CloudLutRegistryCatalogItem): string | null =>
  resolveCatalogInstallState(entry) === "not_installed"
    ? null
    : entry.installed_path || entry.local_match_path || null;

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
  const workspace = useWorkspaceMode();
  const [status, setStatus] = useState<CloudLutRegistryStatusResponse | null>(null);
  const [catalog, setCatalog] = useState<CloudLutRegistryCatalogResponse | null>(null);
  const [modern, setModern] = useState(true);
  const versionTabs = <CloudLibraryVersionTabs modern={modern} onChange={setModern} />;
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
  const catalogLocalCount = catalog
    ? catalog.items.filter((entry) => resolveCatalogInstallState(entry) !== "not_installed").length
    : (status?.installed_count ?? 0);
  const hasMoreCatalogEntries = status?.configured === true && catalogLoadedCount < catalogTotalCount;

  // The new view completes the lightweight catalog before presenting search as complete.
  useEffect(() => {
    if (modern && hasMoreCatalogEntries && !isLoading && !isLoadingMore && !error) void loadMoreCatalog();
  }, [modern, hasMoreCatalogEntries, isLoading, isLoadingMore, error, loadMoreCatalog]);

  if (modern) return <CloudLibraryPreview versions={versionTabs} resetKey={searchQuery} busy={isLoading}
    toolbar={<><input type="search" aria-label={t("lut_sync_search_placeholder")} placeholder={t("lut_sync_search_placeholder")} value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} className="min-w-48 flex-1 rounded-lg bg-slate-100 px-4 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:bg-slate-800" /><span className="text-xs text-slate-500">{t("cloud_library_results")} · {filteredItems.length}</span><Button label={t("lut_sync_refresh_btn")} variant="secondary" loading={isRefreshing} onClick={() => void refreshCatalog()} /></>}
    notices={<>{notice && <StatusBanner tone="warning">{notice}</StatusBanner>}{error && <StatusBanner tone="error">{error}</StatusBanner>}{success && <StatusBanner tone="success">{success}</StatusBanner>}{hasMoreCatalogEntries && <StatusBanner tone="info">{t("cloud_library_loading_index")}<Button label={t("lut_sync_load_more_btn")} variant="secondary" loading={isLoadingMore} onClick={() => void loadMoreCatalog()} /></StatusBanner>}</>}
    items={filteredItems.map((entry) => {
      const display = normalizeRecord(entry.display);
      const name = readDisplayString(display, ["name", "display_name", "lut_name", "title"]) ?? entry.local_path ?? entry.lut_id;
      const maker = readDisplayString(display, ["manufacturer", "brand", "vendor"]) ?? t("lut_sync_unknown");
      const mode = readCompatibilityString(normalizeRecord(entry.compatibility), ["color_mode", "mode", "profile"]) ?? t("lut_sync_unknown");
      const state = resolveCatalogInstallState(entry);
      const key = catalogItemKey(entry);
      const action = state === "not_installed" ? <Button label={t("lut_sync_install_btn")} variant="secondary" loading={pendingInstall === key} disabled={pendingInstall !== null} onClick={() => void handleInstall(entry)} /> : undefined;
      return {key, name, subtitle: maker, metric: mode, state: t(`lut_sync_catalog_state_${state}`), action,
        detail: <div className="grid gap-5">
          <LibraryIdentity name={name} subtitle={[maker, readDisplayString(display, ["material_type", "material"])].filter(Boolean).join(" · ")} />
          <LibraryFields rows={[{ label: t("lut_library_color_mode_label"), value: mode }]} />
          <LibraryFields rows={[
            { label: t("lut_sync_catalog_state_label"), value: t(`lut_sync_catalog_state_${state}`) },
            ...(entry.channel ? [{ label: t("mat_sync_channel_label"), value: ["official", "community", "team"].includes(entry.channel) ? t(`mat_sync_channel_${entry.channel}`) : entry.channel }] : []),
            { label: t("lut_sync_package_size_label"), value: formatBytes(Number(entry.package_bytes)) },
            ...(resolveLocalPath(entry) ? [{ label: t("lut_sync_local_path_label"), value: resolveLocalPath(entry), multiline: true }] : []),
          ]} />
          {action}
        </div>};
    })} />;

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="lut-cloud-sync-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      {versionTabs}
      <section className={`${cardPadClass} grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center`}>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("lut_sync_title")}
          </p>
          <dl className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t("lut_sync_catalog_count_label")}
              </dt>
              <dd
                data-testid="lut-cloud-catalog-count"
                className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50"
              >
                {catalogTotalCount}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t("lut_sync_installed_count_label")}
              </dt>
              <dd
                data-testid="lut-cloud-installed-count"
                className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50"
              >
                {catalogLocalCount}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t("lut_sync_config_label")}
              </dt>
              <dd
                data-testid="lut-cloud-config-state"
                className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-50"
              >
                {status?.configured ? t("lut_sync_configured") : t("lut_sync_not_configured")}
              </dd>
            </div>
          </dl>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {tRuntime("lut_sync_catalog_loaded_inline", {
              loaded: String(catalogLoadedCount),
              total: String(catalogTotalCount),
            })}
          </p>
        </div>
        <Button
          label={t("lut_sync_refresh_btn")}
          variant="secondary"
          onClick={() => void refreshCatalog()}
          loading={isRefreshing}
        />
      </section>

      {notice && (
        <StatusBanner data-testid="lut-cloud-sync-notice" tone="warning">
          {notice}
        </StatusBanner>
      )}
      {success && (
        <StatusBanner data-testid="lut-cloud-sync-success" tone="success">
          {success}
        </StatusBanner>
      )}
      {error && (
        <StatusBanner data-testid="lut-cloud-sync-error" tone="error" title={t("lut_sync_status_failed")}>
          {error}
        </StatusBanner>
      )}

      <section className={`${cardPadClass} flex flex-col gap-4`}>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <label className="min-w-0 flex-1">
            <span className="sr-only">{t("lut_sync_search_placeholder")}</span>
            <input
              data-testid="lut-cloud-search-input"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t("lut_sync_search_placeholder")}
              className="min-h-11 w-full rounded-[10px] border border-slate-200/80 bg-[var(--surface-panel)] px-4 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] transition-all duration-200 hover:border-slate-300 focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:text-slate-100 dark:hover:border-slate-600"
            />
          </label>
          {hasMoreCatalogEntries && (
            <Button
              label={t("lut_sync_load_more_btn")}
              variant="secondary"
              onClick={() => void loadMoreCatalog()}
              loading={isLoadingMore}
            />
          )}
        </div>

        {isLoading ? (
          <div className="flex min-h-48 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
            {t("lut_sync_loading")}
          </div>
        ) : filteredItems.length === 0 ? (
          <div
            data-testid="lut-cloud-empty"
            className={`${wellPadClass} py-8 text-center text-sm text-slate-500 dark:text-slate-400`}
          >
            {t("lut_sync_catalog_empty")}
          </div>
        ) : (
          <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,20rem),1fr))]">
            {filteredItems.map((entry) => {
              const display = normalizeRecord(entry.display);
              const compatibility = normalizeRecord(entry.compatibility);
              const displayName =
                readDisplayString(display, ["name", "display_name", "lut_name", "title"])
                ?? entry.local_path
                ?? entry.lut_id;
              const maker =
                readDisplayString(display, ["manufacturer", "brand", "vendor"])
                ?? t("lut_sync_unknown");
              const colorMode =
                readCompatibilityString(compatibility, ["color_mode", "mode", "profile"])
                ?? t("lut_sync_unknown");
              const installKey = catalogItemKey(entry);
              const isPending = pendingInstall === installKey;
              const installState = resolveCatalogInstallState(entry);
              return (
                <article
                  key={installKey}
                  data-testid="lut-cloud-catalog-card"
                  className={`${wellPadClass} relative flex min-w-0 flex-col gap-4 p-4`}
                >
                  {entry.channel === "official" ? (
                    <span
                      data-testid="lut-cloud-official-badge"
                      className="absolute right-3 top-3 rounded-bl-lg rounded-tr-[10px] bg-amber-100 px-2 py-1 text-[11px] font-bold text-amber-800 dark:bg-amber-400/15 dark:text-amber-100"
                    >
                      {t("mat_sync_official_badge")}
                    </span>
                  ) : null}
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="min-w-0 flex-1 pr-16">
                      <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {displayName}
                      </p>
                      <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">
                        {maker}
                      </p>
                    </div>
                  </div>

                  <dl className="grid gap-3 text-xs text-slate-600 dark:text-slate-300">
                    <div data-testid="lut-cloud-card-meta" className="min-w-0">
                      <dt className="font-medium text-slate-500 dark:text-slate-400">
                        {t("lut_sync_color_mode_label")}
                      </dt>
                      <dd className="mt-1 truncate">{colorMode}</dd>
                    </div>
                    <div data-testid="lut-cloud-card-meta" className="min-w-0">
                      <dt className="font-medium text-slate-500 dark:text-slate-400">
                        {t("lut_sync_catalog_state_label")}
                      </dt>
                      <dd
                        data-testid={`lut-cloud-state-${entry.lut_id}`}
                        className="mt-1 truncate font-semibold text-slate-800 dark:text-slate-100"
                      >
                        {t(`lut_sync_catalog_state_${installState}`)}
                      </dd>
                    </div>
                    {resolveLocalPath(entry) && (
                      <div data-testid="lut-cloud-card-meta" className="min-w-0">
                        <dt className="font-medium text-slate-500 dark:text-slate-400">
                          {t("lut_sync_local_path_label")}
                        </dt>
                        <dd className="mt-1 truncate">{resolveLocalPath(entry)}</dd>
                      </div>
                    )}
                    <div data-testid="lut-cloud-card-meta" className="min-w-0">
                      <div className="min-w-0">
                        <dt className="font-medium text-slate-500 dark:text-slate-400">
                          {t("lut_sync_package_size_label")}
                        </dt>
                        <dd className="mt-1 truncate">{formatBytes(Number(entry.package_bytes))}</dd>
                      </div>
                    </div>
                  </dl>

                  {installState === "installed" ? (
                    <Button
                      label={t("lut_sync_installed_btn")}
                      variant="secondary"
                      disabled
                      className="w-full"
                    />
                  ) : installState === "local_available" ? (
                    <Button
                      label={t("lut_sync_local_available_btn")}
                      variant="secondary"
                      disabled
                      className="w-full"
                    />
                  ) : (
                    <Button
                      label={t("lut_sync_install_btn")}
                      onClick={() => void handleInstall(entry)}
                      loading={isPending}
                      disabled={pendingInstall !== null}
                      className="w-full"
                    />
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </motion.aside>
  );
}
