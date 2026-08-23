import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";

import {
  fetchMaterialRegistryCatalog,
  fetchMaterialSyncStatus,
  installMaterialRegistryCatalogEntry,
  rollbackMaterialSyncRevision,
} from "../api/materialSync";
import { apiErrorToVisibleMessage } from "../api/client";
import type { MaterialRegistryCatalogQuery } from "../api/materialSync";
import type {
  MaterialRegistryCatalogEntry,
  MaterialRegistryCatalogResponse,
  MaterialSyncInstalledEntry,
  MaterialSyncStatusResponse,
} from "../api/types";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import Button from "./ui/Button";
import {
  StatusBanner,
  cx,
  mutedSectionCardClass,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

type CatalogFilter = "all" | "not_installed" | "updates" | "installed";
type CatalogInstallState = "not_installed" | "installed" | "update_available" | "local_missing" | "local_available";

interface CatalogDisplay {
  brand: string;
  name: string;
  rgb: [number, number, number] | null;
}

interface LoadCatalogAndStatusResult {
  statusResponse: MaterialSyncStatusResponse | null;
  catalogResponse: MaterialRegistryCatalogResponse | null;
  hasError: boolean;
  hasNotice: boolean;
  isCurrent: boolean;
}

const catalogFilters: CatalogFilter[] = [
  "all",
  "not_installed",
  "updates",
  "installed",
];
const MATERIAL_CATALOG_PAGE_SIZE = 50;
const MATERIAL_CATALOG_SEARCH_DEBOUNCE_MS = 400;
const MATERIAL_REGISTRY_NOT_CONFIGURED_DETAIL = "Material registry URL is not configured";
const MATERIAL_REGISTRY_STALE_INSTALL_DETAIL =
  "Selected material registry package is not in current material registry catalog";

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
  display: Record<string, unknown>,
  keys: string[],
): string | null => {
  for (const key of keys) {
    const value = display[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
};

const readDisplayRgb = (
  display: Record<string, unknown>,
): [number, number, number] | null => {
  const value = display.estimated_rgb ?? display.rgb;
  if (!Array.isArray(value) || value.length < 3) {
    return null;
  }
  const channels = value.slice(0, 3).map((channel) => Number(channel));
  if (channels.some((channel) => !Number.isInteger(channel) || channel < 0 || channel > 255)) {
    return null;
  }
  return [channels[0], channels[1], channels[2]];
};

const toRgbCss = ([red, green, blue]: [number, number, number]): string =>
  `rgb(${red}, ${green}, ${blue})`;

const toHex = ([red, green, blue]: [number, number, number]): string =>
  `#${[red, green, blue]
    .map((channel) => channel.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;

const resolveCatalogDisplay = (entry: MaterialRegistryCatalogEntry): CatalogDisplay => ({
  brand: readDisplayString(entry.display, ["brand", "manufacturer", "vendor"]) ?? "",
  name: readDisplayString(entry.display, ["material_name", "name", "display_name"])
    ?? entry.local_directory
    ?? entry.material_id,
  rgb: readDisplayRgb(entry.display),
});

const shortContentFingerprint = (entry: MaterialRegistryCatalogEntry): string => {
  const rawValue = (entry.content_hash || entry.revision_id || "").trim();
  const normalized = rawValue
    .replace(/^sha256:/i, "")
    .replace(/^rev_/i, "");
  return normalized ? normalized.slice(0, 12) : "-";
};

const materialLocalSignatureKey = (
  localDirectory: string | null | undefined,
  contentHash: string | null | undefined,
): string | null => {
  const directory = (localDirectory ?? "")
    .trim()
    .replace(/\\/g, "/")
    .replace(/^\/+|\/+$/g, "");
  const hash = (contentHash ?? "").trim().toLowerCase();
  if (!directory || !hash) {
    return null;
  }
  return `${directory}\n${hash}`;
};

const resolveInstallState = (
  entry: MaterialRegistryCatalogEntry,
  installed?: MaterialSyncInstalledEntry,
): CatalogInstallState => {
  if (!installed) {
    return "not_installed";
  }
  if (!installed.local_exists || !installed.material_file_exists) {
    return "local_missing";
  }
  if (
    materialLocalSignatureKey(installed.local_directory, installed.content_hash)
    === materialLocalSignatureKey(entry.local_directory, entry.content_hash)
  ) {
    return "installed";
  }
  if (installed.revision_id === entry.revision_id) {
    return "installed";
  }
  if (installed.available_revisions.includes(entry.revision_id)) {
    return "local_available";
  }
  return "update_available";
};

const resolveRollbackRevisions = (installed: MaterialSyncInstalledEntry): string[] =>
  Array.from(new Set(installed.available_revisions.filter(
    (revisionId) => revisionId && revisionId !== installed.revision_id,
  )));

const readApiErrorDetail = (err: unknown): string | null => {
  if (!err || typeof err !== "object" || !("response" in err)) {
    return null;
  }
  const response = (err as { response?: { data?: unknown } }).response;
  const data = response?.data;
  if (!data || typeof data !== "object" || !("detail" in data)) {
    return null;
  }
  const detail = (data as { detail?: unknown }).detail;
  return typeof detail === "string" && detail.trim() ? detail.trim() : null;
};

const isMaterialRegistryNotConfiguredError = (err: unknown): boolean =>
  readApiErrorDetail(err) === MATERIAL_REGISTRY_NOT_CONFIGURED_DETAIL;

const resolveErrorMessage = (err: unknown, fallback: string): string =>
  apiErrorToVisibleMessage(err, readApiErrorDetail(err) ?? fallback);

const readApiErrorStatus = (err: unknown): number | null => {
  if (!err || typeof err !== "object" || !("response" in err)) {
    return null;
  }
  const response = (err as { response?: { status?: unknown } }).response;
  return typeof response?.status === "number" ? response.status : null;
};

const resolveInstallErrorMessage = (err: unknown, fallback: string): string => {
  const detail = readApiErrorDetail(err);
  if (
    readApiErrorStatus(err) === 422
    && detail === MATERIAL_REGISTRY_STALE_INSTALL_DETAIL
  ) {
    return fallback;
  }
  return apiErrorToVisibleMessage(err, fallback);
};

const emptyMaterialRegistryCatalog = (): MaterialRegistryCatalogResponse => ({
  schema_version: "1.0",
  channels: [],
  count: 0,
  total_count: 0,
  offset: 0,
  limit: MATERIAL_CATALOG_PAGE_SIZE,
  materials: [],
});

const mergeCatalogPage = (
  current: MaterialRegistryCatalogResponse | null,
  nextPage: MaterialRegistryCatalogResponse,
): MaterialRegistryCatalogResponse => {
  if (!current || (nextPage.offset ?? 0) <= 0) {
    return {
      ...nextPage,
      count: nextPage.materials.length,
      total_count: nextPage.total_count ?? nextPage.materials.length,
      offset: nextPage.offset ?? 0,
      limit: nextPage.limit ?? MATERIAL_CATALOG_PAGE_SIZE,
    };
  }
  const existingKeys = new Set(
    current.materials.map((entry) => `${entry.material_id}:${entry.revision_id}`),
  );
  const appended = nextPage.materials.filter(
    (entry) => !existingKeys.has(`${entry.material_id}:${entry.revision_id}`),
  );
  const materials = [...current.materials, ...appended];
  return {
    ...nextPage,
    channels: nextPage.channels.length > 0 ? nextPage.channels : current.channels,
    materials,
    count: materials.length,
    total_count: nextPage.total_count ?? current.total_count ?? materials.length,
    offset: current.offset ?? 0,
    limit: nextPage.limit ?? current.limit ?? MATERIAL_CATALOG_PAGE_SIZE,
  };
};

export default function MaterialCloudSyncPanel() {
  const { t, lang } = useI18n();
  const workspace = useWorkspaceMode();
  const [status, setStatus] = useState<MaterialSyncStatusResponse | null>(null);
  const [catalog, setCatalog] = useState<MaterialRegistryCatalogResponse | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<CatalogFilter>("all");
  const [isLoading, setIsLoading] = useState(true);
  const [isSearchPending, setIsSearchPending] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isLoadingAll, setIsLoadingAll] = useState(false);
  const [pendingInstall, setPendingInstall] = useState<string | null>(null);
  const [pendingRollback, setPendingRollback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const catalogRequestIdRef = useRef(0);
  const searchScheduleIdRef = useRef(0);
  const latestSearchQueryRef = useRef("");

  const fetchCatalogPage = useCallback((query: MaterialRegistryCatalogQuery) => {
    return fetchMaterialRegistryCatalog(query);
  }, []);

  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    }),
    [lang],
  );

  const formatDate = useCallback((value: string | null | undefined) => {
    if (!value) {
      return "-";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return dateFormatter.format(parsed);
  }, [dateFormatter]);

  const installedByMaterialId = useMemo(() => {
    const result = new Map<string, MaterialSyncInstalledEntry>();
    for (const entry of status?.installed ?? []) {
      result.set(entry.material_id, entry);
    }
    return result;
  }, [status]);

  const installedByLocalSignature = useMemo(() => {
    const result = new Map<string, MaterialSyncInstalledEntry>();
    for (const entry of status?.installed ?? []) {
      if (!entry.local_exists || !entry.material_file_exists) {
        continue;
      }
      const signatureKey = materialLocalSignatureKey(entry.local_directory, entry.content_hash);
      if (signatureKey) {
        result.set(signatureKey, entry);
      }
    }
    return result;
  }, [status]);

  const resolveCatalogInstalledEntry = useCallback((entry: MaterialRegistryCatalogEntry) => {
    const signatureKey = materialLocalSignatureKey(entry.local_directory, entry.content_hash);
    if (signatureKey) {
      const localMatch = installedByLocalSignature.get(signatureKey);
      if (localMatch) {
        return localMatch;
      }
    }
    return installedByMaterialId.get(entry.material_id);
  }, [installedByLocalSignature, installedByMaterialId]);

  const updateCount = useMemo(() => {
    return (catalog?.materials ?? []).filter((entry) => {
      const installed = resolveCatalogInstalledEntry(entry);
      return resolveInstallState(entry, installed) === "update_available";
    }).length;
  }, [catalog, resolveCatalogInstalledEntry]);

  const loadCatalogAndStatus = useCallback(async (
    query: string,
  ): Promise<LoadCatalogAndStatusResult> => {
    const requestId = ++catalogRequestIdRef.current;
    setCatalogQuery(query);
    setIsLoading(true);
    setError(null);
    setNotice(null);
    try {
      const [statusResult, catalogResult] = await Promise.allSettled([
        fetchMaterialSyncStatus(),
        fetchCatalogPage({
          limit: MATERIAL_CATALOG_PAGE_SIZE,
          offset: 0,
          ...(query ? { q: query } : {}),
        }),
      ] as const);

      if (requestId !== catalogRequestIdRef.current) {
        return {
          statusResponse: null,
          catalogResponse: null,
          hasError: false,
          hasNotice: false,
          isCurrent: false,
        };
      }

      const statusResponse = statusResult.status === "fulfilled" ? statusResult.value : null;
      let catalogResponse = catalogResult.status === "fulfilled" ? catalogResult.value : null;
      const failures: string[] = [];
      let nextNotice: string | null = null;

      if (statusResult.status === "rejected") {
        failures.push(resolveErrorMessage(statusResult.reason, t("mat_sync_status_failed")));
      }
      if (catalogResult.status === "rejected") {
        if (isMaterialRegistryNotConfiguredError(catalogResult.reason)) {
          catalogResponse = emptyMaterialRegistryCatalog();
          nextNotice = t("mat_sync_catalog_not_configured");
        } else {
          failures.push(resolveErrorMessage(catalogResult.reason, t("mat_sync_status_failed")));
        }
      }

      setStatus(statusResponse);
      setCatalog(catalogResponse ? mergeCatalogPage(null, catalogResponse) : null);
      setNotice(nextNotice);
      if (failures.length > 0) {
        setError(failures.join(" / "));
      }
      return {
        statusResponse,
        catalogResponse,
        hasError: failures.length > 0,
        hasNotice: nextNotice !== null,
        isCurrent: true,
      };
    } finally {
      if (requestId === catalogRequestIdRef.current) {
        setIsLoading(false);
      }
    }
  }, [fetchCatalogPage, t]);

  useEffect(() => {
    const scheduledQuery = searchQuery.trim();
    const scheduleId = ++searchScheduleIdRef.current;
    catalogRequestIdRef.current += 1;

    const runScheduledSearch = () => {
      if (scheduleId === searchScheduleIdRef.current) {
        setIsSearchPending(false);
        void loadCatalogAndStatus(scheduledQuery);
      }
    };
    const timer = scheduledQuery
      ? window.setTimeout(runScheduledSearch, MATERIAL_CATALOG_SEARCH_DEBOUNCE_MS)
      : null;
    if (timer === null) {
      runScheduledSearch();
    }

    return () => {
      if (timer !== null) {
        window.clearTimeout(timer);
      }
      catalogRequestIdRef.current += 1;
    };
  }, [loadCatalogAndStatus, searchQuery]);

  const loadCurrentQueryImmediately = useCallback(() => {
    searchScheduleIdRef.current += 1;
    setIsSearchPending(false);
    return loadCatalogAndStatus(latestSearchQueryRef.current.trim());
  }, [loadCatalogAndStatus]);

  const handleSearchQueryChange = useCallback((value: string) => {
    latestSearchQueryRef.current = value;
    catalogRequestIdRef.current += 1;
    searchScheduleIdRef.current += 1;
    setIsLoading(false);
    setIsSearchPending(Boolean(value.trim()));
    setSearchQuery(value);
  }, []);

  const refreshCatalog = useCallback(async () => {
    setIsRefreshing(true);
    setSuccess(null);
    try {
      const result = await loadCurrentQueryImmediately();
      if (result.isCurrent && !result.hasError && !result.hasNotice) {
        setSuccess(t("mat_sync_catalog_refresh_success"));
      }
    } finally {
      setIsRefreshing(false);
    }
  }, [loadCurrentQueryImmediately, t]);

  const loadMoreCatalog = useCallback(async () => {
    const loadedCount = catalog?.materials.length ?? 0;
    const totalCount = catalog?.total_count ?? catalog?.count ?? loadedCount;
    if (!catalog || loadedCount >= totalCount || isLoading || isSearchPending || isLoadingMore || isLoadingAll) {
      return;
    }
    const requestId = ++catalogRequestIdRef.current;
    setIsLoadingMore(true);
    setError(null);
    try {
      const nextPage = await fetchCatalogPage({
        limit: MATERIAL_CATALOG_PAGE_SIZE,
        offset: loadedCount,
        ...(catalogQuery ? { q: catalogQuery } : {}),
      });
      if (requestId === catalogRequestIdRef.current) {
        setCatalog((current) => mergeCatalogPage(current, nextPage));
      }
    } catch (err) {
      if (requestId === catalogRequestIdRef.current) {
        setError(resolveErrorMessage(err, t("mat_sync_status_failed")));
      }
    } finally {
      setIsLoadingMore(false);
    }
  }, [catalog, catalogQuery, fetchCatalogPage, isLoading, isLoadingAll, isLoadingMore, isSearchPending, t]);

  const loadAllCatalog = useCallback(async () => {
    const loadedCount = catalog?.materials.length ?? 0;
    let totalCount = catalog?.total_count ?? catalog?.count ?? loadedCount;
    if (!catalog || loadedCount >= totalCount || isLoading || isSearchPending || isLoadingMore || isLoadingAll) {
      return;
    }
    const requestId = ++catalogRequestIdRef.current;
    setIsLoadingAll(true);
    setError(null);
    try {
      let mergedCatalog = catalog;
      let nextOffset = loadedCount;
      while (nextOffset < totalCount) {
        const nextPage = await fetchCatalogPage({
          limit: MATERIAL_CATALOG_PAGE_SIZE,
          offset: nextOffset,
          ...(catalogQuery ? { q: catalogQuery } : {}),
        });
        if (requestId !== catalogRequestIdRef.current) {
          return;
        }
        mergedCatalog = mergeCatalogPage(mergedCatalog, nextPage);
        totalCount = nextPage.total_count ?? totalCount;
        const pageCount = nextPage.count ?? nextPage.materials.length;
        if (pageCount <= 0) {
          break;
        }
        nextOffset += pageCount;
      }
      if (requestId === catalogRequestIdRef.current) {
        setCatalog(mergedCatalog);
      }
    } catch (err) {
      if (requestId === catalogRequestIdRef.current) {
        setError(resolveErrorMessage(err, t("mat_sync_status_failed")));
      }
    } finally {
      setIsLoadingAll(false);
    }
  }, [catalog, catalogQuery, fetchCatalogPage, isLoading, isLoadingAll, isLoadingMore, isSearchPending, t]);

  const handleInstall = useCallback(async (entry: MaterialRegistryCatalogEntry) => {
    const installKey = `${entry.material_id}:${entry.revision_id}`;
    setPendingInstall(installKey);
    setError(null);
    setSuccess(null);
    try {
      const response = await installMaterialRegistryCatalogEntry(
        {
          material_id: entry.material_id,
          revision_id: entry.revision_id,
          package_url: entry.package_url,
          package_sha256: entry.package_sha256,
        }
      );
      await loadCurrentQueryImmediately();
      setSuccess(response.message || t("mat_sync_install_success"));
    } catch (err) {
      setError(resolveInstallErrorMessage(err, t("mat_sync_install_failed")));
    } finally {
      setPendingInstall(null);
    }
  }, [loadCurrentQueryImmediately, t]);

  const handleRollback = useCallback(async (entry: MaterialSyncInstalledEntry, revisionId: string) => {
    const rollbackKey = `${entry.material_id}:${revisionId}`;
    setPendingRollback(rollbackKey);
    setError(null);
    setSuccess(null);
    try {
      const response = await rollbackMaterialSyncRevision(
        entry.material_id,
        revisionId,
      );
      await loadCurrentQueryImmediately();
      setSuccess(response.message || t("mat_sync_rollback_success"));
    } catch (err) {
      setError(resolveErrorMessage(err, t("mat_sync_rollback_failed")));
    } finally {
      setPendingRollback(null);
    }
  }, [loadCurrentQueryImmediately, t]);

  const syncIndexStateLabel = status
    ? t(`mat_sync_state_${status.index_state}`)
    : t("mat_sync_state_unknown");
  const installedEntries = useMemo(
    () => (status?.installed ?? []).filter(
      (entry) => (
        entry.local_exists
        && entry.material_file_exists
        && resolveRollbackRevisions(entry).length > 0
      ),
    ),
    [status],
  );
  const catalogLoadedCount = catalog?.materials.length ?? 0;
  const catalogTotalCount = catalog?.total_count ?? catalog?.count ?? catalogLoadedCount;
  const hasMoreCatalogEntries = catalogLoadedCount < catalogTotalCount;

  const filteredCatalogEntries = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    return (catalog?.materials ?? []).filter((entry) => {
      const installed = resolveCatalogInstalledEntry(entry);
      const installState = resolveInstallState(entry, installed);
      if (activeFilter === "not_installed" && installState !== "not_installed" && installState !== "local_missing") {
        return false;
      }
      if (activeFilter === "updates" && installState !== "update_available") {
        return false;
      }
      if (activeFilter === "installed" && installState !== "installed") {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      const display = resolveCatalogDisplay(entry);
      const haystack = [
        display.brand,
        display.name,
        entry.material_id,
        entry.revision_id,
        entry.local_directory,
        entry.channel,
        entry.visibility,
      ].join(" ").toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [activeFilter, catalog, resolveCatalogInstalledEntry, searchQuery]);

  const renderCatalogAction = (
    entry: MaterialRegistryCatalogEntry,
    installState: CatalogInstallState,
  ) => {
    const installKey = `${entry.material_id}:${entry.revision_id}`;
    const isPending = pendingInstall === installKey;
    if (installState === "installed") {
      return (
        <Button
          label={t("mat_sync_installed_btn")}
          variant="secondary"
          disabled
          className="w-full"
        />
      );
    }
    if (installState === "local_available") {
      return (
        <Button
          label={t("mat_sync_local_available_btn")}
          variant="secondary"
          disabled
          className="w-full"
        />
      );
    }
    const label = installState === "update_available"
      ? tRuntime("mat_sync_update_btn", { revisionId: shortContentFingerprint(entry) })
      : t("mat_sync_install_btn");
    return (
      <Button
        label={label}
        onClick={() => void handleInstall(entry)}
        disabled={pendingInstall !== null}
        loading={isPending}
        className="w-full"
      />
    );
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="material-cloud-sync-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <section className={`${mutedSectionCardClass} grid gap-4 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center`}>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_sync_title")}
          </p>
          <dl className="mt-3 grid gap-3 sm:grid-cols-4">
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t("mat_sync_catalog_count_label")}
              </dt>
              <dd
                data-testid="material-cloud-catalog-count"
                className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50"
              >
                {catalogTotalCount}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t("mat_sync_installed_count_label")}
              </dt>
              <dd
                data-testid="material-cloud-sync-installed-count"
                className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50"
              >
                {status?.installed_count ?? 0}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t("mat_sync_update_count_label")}
              </dt>
              <dd
                data-testid="material-cloud-update-count"
                className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50"
              >
                {updateCount}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t("mat_sync_index_state_label")}
              </dt>
              <dd className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                {syncIndexStateLabel}
              </dd>
            </div>
          </dl>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {tRuntime("mat_sync_last_sync_inline", { time: formatDate(status?.last_sync_at) })}
          </p>
        </div>
        <Button
          label={t("mat_sync_refresh_btn")}
          variant="secondary"
          onClick={() => void refreshCatalog()}
          disabled={isLoading || isRefreshing}
          loading={isRefreshing}
          className="w-full lg:w-auto"
        />
      </section>

      <section className={`${resolveSectionCardClass(workspace.mode)} grid gap-3`}>
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <input
            data-testid="material-cloud-search-input"
            type="search"
            value={searchQuery}
            onChange={(event) => handleSearchQueryChange(event.target.value)}
            placeholder={t("mat_sync_search_placeholder")}
            className="min-h-11 rounded-2xl border border-slate-200/80 bg-[var(--surface-panel)] px-3 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:text-slate-100"
          />
          <div className="flex min-w-0 flex-wrap gap-2" role="group" aria-label={t("mat_sync_filter_group_label")}>
            {catalogFilters.map((filter) => (
              <button
                key={filter}
                type="button"
                data-testid={`material-cloud-filter-${filter}`}
                aria-pressed={activeFilter === filter}
                onClick={() => setActiveFilter(filter)}
                className={cx(
                  "min-h-9 rounded-xl border px-3 py-1.5 text-xs font-semibold transition",
                  activeFilter === filter
                    ? "border-blue-400 bg-blue-50 text-blue-700 dark:border-blue-400/70 dark:bg-blue-500/15 dark:text-blue-200"
                    : "border-slate-200/80 bg-[var(--surface-panel)] text-slate-600 hover:border-slate-300 dark:border-slate-700/80 dark:text-slate-300",
                )}
              >
                {t(`mat_sync_filter_${filter}`)}
              </button>
            ))}
          </div>
        </div>
      </section>

      {error ? (
        <StatusBanner data-testid="material-cloud-sync-error" tone="error">
          {error}
        </StatusBanner>
      ) : null}
      {notice ? (
        <StatusBanner data-testid="material-cloud-sync-notice" tone="info">
          {notice}
        </StatusBanner>
      ) : null}
      {success ? (
        <StatusBanner data-testid="material-cloud-sync-success" tone="success">
          {success}
        </StatusBanner>
      ) : null}

      {installedEntries.length > 0 ? (
        <section
          data-testid="material-cloud-local-installed-section"
          className={`${resolveSectionCardClass(workspace.mode)} grid gap-4`}
        >
          <h2 className="text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_sync_local_section_title")}
          </h2>
          <div className="grid divide-y divide-slate-200/70 dark:divide-slate-700/70">
            {installedEntries.map((installed) => {
              const rollbackRevisions = resolveRollbackRevisions(installed);
              const displayName = installed.display_name || installed.local_directory || installed.material_id;
              return (
                <div
                  key={installed.material_id}
                  data-testid="material-cloud-local-installed-card"
                  className="grid gap-3 py-3 first:pt-0 last:pb-0 lg:grid-cols-[minmax(0,1fr)_minmax(12rem,auto)] lg:items-center"
                >
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {displayName}
                    </h3>
                    {installed.display_brand ? (
                      <p className="mt-1 text-xs font-medium text-slate-600 dark:text-slate-300">
                        {installed.display_brand}
                      </p>
                    ) : null}
                    <dl className="mt-3 grid gap-3 sm:grid-cols-3">
                      <div className="min-w-0">
                        <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                          {t("mat_sync_material_id_label")}
                        </dt>
                        <dd className="mt-1 break-all font-mono text-xs text-slate-700 dark:text-slate-200">
                          {installed.material_id}
                        </dd>
                      </div>
                      <div className="min-w-0">
                        <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                          {t("mat_sync_revision_label")}
                        </dt>
                        <dd className="mt-1 break-all font-mono text-xs text-slate-700 dark:text-slate-200">
                          {installed.revision_id}
                        </dd>
                      </div>
                      <div className="min-w-0">
                        <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
                          {t("mat_gradient_library_directory_label")}
                        </dt>
                        <dd className="mt-1 break-all text-xs font-semibold text-slate-700 dark:text-slate-200">
                          {installed.local_directory}
                        </dd>
                      </div>
                    </dl>
                  </div>
                  <div className="grid gap-2">
                    {rollbackRevisions.length > 0 ? rollbackRevisions.map((revisionId) => (
                      <Button
                        key={revisionId}
                        label={tRuntime("mat_sync_rollback_btn", { revisionId })}
                        variant="secondary"
                        onClick={() => void handleRollback(installed, revisionId)}
                        disabled={pendingRollback !== null}
                        loading={pendingRollback === `${installed.material_id}:${revisionId}`}
                        className="w-full"
                      />
                    )) : (
                      <p className="text-sm text-slate-500 dark:text-slate-400">
                        {t("mat_sync_no_rollback")}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {isLoading ? (
        <section className={`${mutedSectionCardClass} flex min-h-40 items-center justify-center`}>
          <p className="text-sm text-slate-500 dark:text-slate-400">{t("mat_gradient_library_loading")}</p>
        </section>
      ) : filteredCatalogEntries.length > 0 ? (
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,19rem),1fr))]">
          {filteredCatalogEntries.map((entry) => {
            const installed = resolveCatalogInstalledEntry(entry);
            const installState = resolveInstallState(entry, installed);
            const display = resolveCatalogDisplay(entry);
            return (
              <section
                key={`${entry.material_id}:${entry.revision_id}`}
                data-testid="material-cloud-catalog-card"
                className={`${resolveSectionCardClass(workspace.mode)} relative flex flex-col gap-4`}
              >
                {entry.channel === "official" ? (
                  <span
                    data-testid="material-cloud-official-badge"
                    className="absolute right-3 top-3 rounded-bl-xl rounded-tr-2xl border border-amber-300/80 bg-amber-100 px-2 py-1 text-[11px] font-bold text-amber-800 shadow-sm dark:border-amber-400/40 dark:bg-amber-400/15 dark:text-amber-100"
                  >
                    {t("mat_sync_official_badge")}
                  </span>
                ) : null}
                <div className="flex min-w-0 items-start gap-4">
                  <div
                    data-testid="material-cloud-catalog-swatch"
                    className={cx(
                      "flex h-20 w-20 shrink-0 items-center justify-center rounded-3xl border border-slate-200/80 text-lg font-semibold text-slate-500 dark:border-slate-700/80 dark:text-slate-300",
                      display.rgb ? "" : "bg-slate-100 dark:bg-slate-800",
                    )}
                    style={display.rgb ? { backgroundColor: toRgbCss(display.rgb) } : undefined}
                  >
                    {display.rgb ? null : display.name.trim().slice(0, 1).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1 pr-16">
                    <h3 className="flex min-w-0 flex-wrap items-center gap-2 text-base font-semibold text-slate-900 dark:text-slate-50">
                      <span
                        data-testid="material-cloud-brand-tag"
                        className="max-w-full truncate rounded-full border border-slate-200/80 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:border-slate-700/80 dark:text-slate-300"
                      >
                        {display.brand || t("mat_gradient_library_brand_unassigned")}
                      </span>
                      <span className="min-w-0 truncate">{display.name}</span>
                    </h3>
                    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                      {display.rgb ? toHex(display.rgb) : entry.channel}
                    </p>
                  </div>
                </div>

                <dl className="grid gap-3 sm:grid-cols-2">
                  <div data-testid="material-cloud-card-meta" className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_directory_label")}
                    </dt>
                    <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {entry.local_directory}
                    </dd>
                  </div>
                  <div data-testid="material-cloud-card-meta" className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_sync_package_size_label")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {formatBytes(entry.package_bytes)}
                    </dd>
                  </div>
                  <div data-testid="material-cloud-card-meta" className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_sync_catalog_state_label")}
                    </dt>
                    <dd
                      data-testid={`material-cloud-state-${entry.material_id}`}
                      className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50"
                    >
                      {t(`mat_sync_catalog_state_${installState}`)}
                    </dd>
                  </div>
                  <div data-testid="material-cloud-card-meta" className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_sync_content_fingerprint_label")}
                    </dt>
                    <dd className="mt-1 break-all font-mono text-xs font-semibold text-slate-900 dark:text-slate-50">
                      {shortContentFingerprint(entry)}
                    </dd>
                  </div>
                </dl>

                <div className="grid gap-3">
                  {renderCatalogAction(entry, installState)}
                </div>
              </section>
            );
          })}
          {hasMoreCatalogEntries ? (
            <div className={`${mutedSectionCardClass} grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center`}>
              <p
                data-testid="material-cloud-loaded-count"
                className="text-sm font-medium text-slate-600 dark:text-slate-300"
              >
                {tRuntime("mat_sync_catalog_loaded_inline", {
                  loaded: catalogLoadedCount,
                  total: catalogTotalCount,
                })}
              </p>
              <Button
                label={t("mat_sync_load_more_btn")}
                variant="secondary"
                onClick={() => void loadMoreCatalog()}
                disabled={isLoading || isSearchPending || isLoadingMore || isLoadingAll}
                loading={isLoadingMore}
                className="w-full sm:w-auto"
              />
              <Button
                label={t("mat_sync_load_all_btn")}
                variant="secondary"
                onClick={() => void loadAllCatalog()}
                disabled={isLoading || isSearchPending || isLoadingMore || isLoadingAll}
                loading={isLoadingAll}
                className="w-full sm:w-auto"
              />
            </div>
          ) : null}
        </div>
      ) : (
        <section className={`${mutedSectionCardClass} flex min-h-32 items-center justify-center`}>
          <p className="text-sm text-slate-500 dark:text-slate-400">{t("mat_sync_catalog_empty")}</p>
        </section>
      )}

    </motion.aside>
  );
}
