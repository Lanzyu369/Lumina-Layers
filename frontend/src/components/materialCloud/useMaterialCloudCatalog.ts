import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiErrorToVisibleMessage } from "../../api/client";
import {
  fetchMaterialRegistryCatalog,
  fetchMaterialSyncStatus,
  installMaterialRegistryCatalogEntry,
  rollbackMaterialSyncRevision,
} from "../../api/materialSync";
import type {
  MaterialRegistryCatalogEntry,
  MaterialRegistryCatalogResponse,
  MaterialSyncInstalledEntry,
  MaterialSyncStatusResponse,
} from "../../api/types";
import { useI18n } from "../../i18n/context";
import { clampPage, resolvePageCount } from "../ui/paginationModel";
import {
  CATALOG_FILTERS,
  hasLocalMaterialFiles,
  matchesCatalogFilter,
  materialLocalSignatureKey,
  resolveInstallState,
  resolveRollbackRevisions,
} from "./catalogModel";
import type { CatalogFilter } from "./catalogModel";

export const MATERIAL_CATALOG_PAGE_SIZE = 24;
export const MATERIAL_CATALOG_SEARCH_DEBOUNCE_MS = 400;
const MATERIAL_REGISTRY_NOT_CONFIGURED_DETAIL = "Material registry URL is not configured";
const MATERIAL_REGISTRY_STALE_INSTALL_DETAIL =
  "Selected material registry package is not in current material registry catalog";

type CatalogAvailability = "loading" | "ready" | "not_configured" | "error";

interface ServerCatalogPage {
  query: string;
  page: number;
  response: MaterialRegistryCatalogResponse;
}

interface FullCatalog {
  query: string;
  materials: MaterialRegistryCatalogEntry[];
}

interface LoadResult {
  isCurrent: boolean;
  hasError: boolean;
  hasNotice: boolean;
}

/** What the catalog list area should render. 目录列表区域的渲染状态。 */
export type MaterialCatalogView =
  | { kind: "loading" }
  | { kind: "full_catalog_failed" }
  | {
    kind: "entries";
    entries: MaterialRegistryCatalogEntry[];
    total: number;
    page: number;
    pageCount: number;
  };

export type CatalogFilterCounts = Partial<Record<CatalogFilter, number>>;

const readApiErrorDetail = (err: unknown): string | null => {
  if (!err || typeof err !== "object" || !("response" in err)) {
    return null;
  }
  const data = (err as { response?: { data?: unknown } }).response?.data;
  if (!data || typeof data !== "object" || !("detail" in data)) {
    return null;
  }
  const detail = (data as { detail?: unknown }).detail;
  return typeof detail === "string" && detail.trim() ? detail.trim() : null;
};

const readApiErrorStatus = (err: unknown): number | null => {
  if (!err || typeof err !== "object" || !("response" in err)) {
    return null;
  }
  const status = (err as { response?: { status?: unknown } }).response?.status;
  return typeof status === "number" ? status : null;
};

const isNotConfiguredError = (err: unknown): boolean =>
  readApiErrorDetail(err) === MATERIAL_REGISTRY_NOT_CONFIGURED_DETAIL;

const resolveErrorMessage = (err: unknown, fallback: string): string =>
  apiErrorToVisibleMessage(err, readApiErrorDetail(err) ?? fallback);

const resolveInstallErrorMessage = (err: unknown, fallback: string): string => {
  if (
    readApiErrorStatus(err) === 422
    && readApiErrorDetail(err) === MATERIAL_REGISTRY_STALE_INSTALL_DETAIL
  ) {
    return fallback;
  }
  return apiErrorToVisibleMessage(err, fallback);
};

const emptyCatalogResponse = (): MaterialRegistryCatalogResponse => ({
  schema_version: "1.0",
  channels: [],
  count: 0,
  total_count: 0,
  offset: 0,
  limit: MATERIAL_CATALOG_PAGE_SIZE,
  materials: [],
});

const catalogResponseTotal = (response: MaterialRegistryCatalogResponse): number =>
  response.total_count ?? response.count ?? response.materials.length;

const fetchCatalogPage = (query: string, page: number) =>
  fetchMaterialRegistryCatalog({
    limit: MATERIAL_CATALOG_PAGE_SIZE,
    offset: (page - 1) * MATERIAL_CATALOG_PAGE_SIZE,
    ...(query ? { q: query } : {}),
  });

/** Fetch a page; if it is past the end (catalog shrank), fetch the last page once. */
const fetchCatalogPageClamped = async (
  query: string,
  page: number,
): Promise<{ page: number; response: MaterialRegistryCatalogResponse }> => {
  const response = await fetchCatalogPage(query, page);
  const total = catalogResponseTotal(response);
  const lastPage = resolvePageCount(total, MATERIAL_CATALOG_PAGE_SIZE);
  if (page > lastPage && response.materials.length === 0) {
    return { page: lastPage, response: await fetchCatalogPage(query, lastPage) };
  }
  return { page, response };
};

/**
 * State and actions for the paginated cloud material catalog.
 *
 * The first screen is always one server page. When the user has cloud
 * materials installed locally, the full catalog for the current query is
 * fetched in the background so update counts and install-state filters are
 * exact; paging then happens locally.
 *
 * 云端耗材目录的分页状态与操作。首屏只取一页；若本地已安装云端耗材，
 * 会在后台拉取当前搜索的完整目录，使“可更新”计数和状态筛选准确，之后本地翻页。
 */
export function useMaterialCloudCatalog() {
  const { t } = useI18n();
  const [status, setStatus] = useState<MaterialSyncStatusResponse | null>(null);
  const [serverPage, setServerPage] = useState<ServerCatalogPage | null>(null);
  const [fullCatalog, setFullCatalog] = useState<FullCatalog | null>(null);
  const [fullCatalogFailedQuery, setFullCatalogFailedQuery] = useState<string | null>(null);
  const [availability, setAvailability] = useState<CatalogAvailability>("loading");
  const [searchQuery, setSearchQuery] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<CatalogFilter>("all");
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [isPageLoading, setIsPageLoading] = useState(false);
  const [isFullCatalogLoading, setIsFullCatalogLoading] = useState(false);
  const [isSearchPending, setIsSearchPending] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [pendingInstall, setPendingInstall] = useState<string | null>(null);
  const [pendingRollback, setPendingRollback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const catalogRequestIdRef = useRef(0);
  const fullCatalogRequestIdRef = useRef(0);
  const searchScheduleIdRef = useRef(0);
  const latestSearchQueryRef = useRef("");
  const pageRef = useRef(1);

  const updatePage = useCallback((nextPage: number) => {
    pageRef.current = nextPage;
    setPage(nextPage);
  }, []);

  const loadCatalogAndStatus = useCallback(async (
    query: string,
    requestedPage: number,
    { preserveFullCatalog = false }: { preserveFullCatalog?: boolean } = {},
  ): Promise<LoadResult> => {
    const requestId = ++catalogRequestIdRef.current;
    if (!preserveFullCatalog) {
      fullCatalogRequestIdRef.current += 1;
      setFullCatalog(null);
      setFullCatalogFailedQuery(null);
      setIsFullCatalogLoading(false);
    }
    setCatalogQuery(query);
    setIsLoading(true);
    setIsPageLoading(false);
    setError(null);
    setNotice(null);
    try {
      const [statusResult, catalogResult] = await Promise.allSettled([
        fetchMaterialSyncStatus(),
        fetchCatalogPageClamped(query, requestedPage),
      ] as const);
      if (requestId !== catalogRequestIdRef.current) {
        return { isCurrent: false, hasError: false, hasNotice: false };
      }

      const failures: string[] = [];
      let nextNotice: string | null = null;
      if (statusResult.status === "rejected") {
        failures.push(resolveErrorMessage(statusResult.reason, t("mat_sync_status_failed")));
      }
      if (catalogResult.status === "fulfilled") {
        setServerPage({ query, ...catalogResult.value });
        updatePage(catalogResult.value.page);
        setAvailability("ready");
      } else if (isNotConfiguredError(catalogResult.reason)) {
        nextNotice = t("mat_sync_catalog_not_configured");
        setServerPage({ query, page: 1, response: emptyCatalogResponse() });
        updatePage(1);
        setAvailability("not_configured");
      } else {
        failures.push(resolveErrorMessage(catalogResult.reason, t("mat_sync_status_failed")));
        setServerPage(null);
        setAvailability("error");
      }

      setStatus(statusResult.status === "fulfilled" ? statusResult.value : null);
      setNotice(nextNotice);
      if (failures.length > 0) {
        setError(failures.join(" / "));
      }
      return {
        isCurrent: true,
        hasError: failures.length > 0,
        hasNotice: nextNotice !== null,
      };
    } finally {
      if (requestId === catalogRequestIdRef.current) {
        setIsLoading(false);
      }
    }
  }, [t, updatePage]);

  useEffect(() => {
    const scheduledQuery = searchQuery.trim();
    const scheduleId = ++searchScheduleIdRef.current;
    catalogRequestIdRef.current += 1;

    const runScheduledSearch = () => {
      if (scheduleId === searchScheduleIdRef.current) {
        setIsSearchPending(false);
        void loadCatalogAndStatus(scheduledQuery, 1);
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

  const reloadCurrentQuery = useCallback((options?: { preserveFullCatalog?: boolean }) => {
    searchScheduleIdRef.current += 1;
    setIsSearchPending(false);
    return loadCatalogAndStatus(latestSearchQueryRef.current.trim(), pageRef.current, options);
  }, [loadCatalogAndStatus]);

  const hasLocalInstalled = useMemo(
    () => (status?.installed ?? []).some(hasLocalMaterialFiles),
    [status],
  );

  // Background full-catalog fetch; only needed when local install state matters.
  useEffect(() => {
    if (
      availability !== "ready"
      || isLoading
      || !hasLocalInstalled
      || isFullCatalogLoading
      || fullCatalog?.query === catalogQuery
      || fullCatalogFailedQuery === catalogQuery
    ) {
      return;
    }
    const requestId = ++fullCatalogRequestIdRef.current;
    const query = catalogQuery;
    setIsFullCatalogLoading(true);
    fetchMaterialRegistryCatalog(query ? { q: query } : {})
      .then((response) => {
        if (requestId === fullCatalogRequestIdRef.current) {
          setFullCatalog({ query, materials: response.materials });
        }
      })
      .catch(() => {
        if (requestId === fullCatalogRequestIdRef.current) {
          setFullCatalogFailedQuery(query);
        }
      })
      .finally(() => {
        if (requestId === fullCatalogRequestIdRef.current) {
          setIsFullCatalogLoading(false);
        }
      });
  }, [
    availability,
    catalogQuery,
    fullCatalog,
    fullCatalogFailedQuery,
    hasLocalInstalled,
    isFullCatalogLoading,
    isLoading,
  ]);

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
      const signatureKey = hasLocalMaterialFiles(entry)
        ? materialLocalSignatureKey(entry.local_directory, entry.content_hash)
        : null;
      if (signatureKey) {
        result.set(signatureKey, entry);
      }
    }
    return result;
  }, [status]);

  const resolveCatalogInstalledEntry = useCallback((entry: MaterialRegistryCatalogEntry) => {
    const signatureKey = materialLocalSignatureKey(entry.local_directory, entry.content_hash);
    const localMatch = signatureKey ? installedByLocalSignature.get(signatureKey) : undefined;
    return localMatch ?? installedByMaterialId.get(entry.material_id);
  }, [installedByLocalSignature, installedByMaterialId]);

  const resolveEntryInstallState = useCallback(
    (entry: MaterialRegistryCatalogEntry) =>
      resolveInstallState(entry, resolveCatalogInstalledEntry(entry)),
    [resolveCatalogInstalledEntry],
  );

  const localCatalog = fullCatalog?.query === catalogQuery ? fullCatalog.materials : null;
  const serverTotal = serverPage ? catalogResponseTotal(serverPage.response) : 0;
  const catalogTotalCount = localCatalog?.length ?? serverTotal;

  const filterCounts = useMemo<CatalogFilterCounts>(() => {
    if (localCatalog) {
      const counts: CatalogFilterCounts = {};
      for (const filter of CATALOG_FILTERS) {
        counts[filter] = 0;
      }
      for (const entry of localCatalog) {
        const installState = resolveEntryInstallState(entry);
        for (const filter of CATALOG_FILTERS) {
          if (matchesCatalogFilter(installState, filter)) {
            counts[filter] = (counts[filter] ?? 0) + 1;
          }
        }
      }
      return counts;
    }
    if (!serverPage) {
      return {};
    }
    if (!hasLocalInstalled) {
      return { all: serverTotal, not_installed: serverTotal, updates: 0, installed: 0 };
    }
    return { all: serverTotal };
  }, [hasLocalInstalled, localCatalog, resolveEntryInstallState, serverPage, serverTotal]);

  /** Exact update count, or null while the full catalog is still loading. */
  const updateCount = filterCounts.updates ?? null;

  const view = useMemo<MaterialCatalogView>(() => {
    if (localCatalog) {
      const filtered = localCatalog.filter(
        (entry) => matchesCatalogFilter(resolveEntryInstallState(entry), activeFilter),
      );
      const pageCount = resolvePageCount(filtered.length, MATERIAL_CATALOG_PAGE_SIZE);
      const currentPage = clampPage(page, pageCount);
      const start = (currentPage - 1) * MATERIAL_CATALOG_PAGE_SIZE;
      return {
        kind: "entries",
        entries: filtered.slice(start, start + MATERIAL_CATALOG_PAGE_SIZE),
        total: filtered.length,
        page: currentPage,
        pageCount,
      };
    }
    if (!serverPage) {
      return isLoading
        ? { kind: "loading" }
        : { kind: "entries", entries: [], total: 0, page: 1, pageCount: 1 };
    }
    const serverServesFilter = activeFilter === "all"
      || (activeFilter === "not_installed" && !hasLocalInstalled);
    if (serverServesFilter) {
      return {
        kind: "entries",
        entries: serverPage.response.materials,
        total: serverTotal,
        page: serverPage.page,
        pageCount: resolvePageCount(serverTotal, MATERIAL_CATALOG_PAGE_SIZE),
      };
    }
    if (!hasLocalInstalled || availability !== "ready") {
      return { kind: "entries", entries: [], total: 0, page: 1, pageCount: 1 };
    }
    if (fullCatalogFailedQuery === catalogQuery) {
      return { kind: "full_catalog_failed" };
    }
    return { kind: "loading" };
  }, [
    activeFilter,
    availability,
    catalogQuery,
    fullCatalogFailedQuery,
    hasLocalInstalled,
    isLoading,
    localCatalog,
    page,
    resolveEntryInstallState,
    serverPage,
    serverTotal,
  ]);

  const goToPage = useCallback(async (target: number) => {
    const previousPage = pageRef.current;
    updatePage(target);
    if (localCatalog || !serverPage || serverPage.page === target || availability !== "ready") {
      return;
    }
    const requestId = ++catalogRequestIdRef.current;
    const query = serverPage.query;
    setIsPageLoading(true);
    setError(null);
    try {
      const result = await fetchCatalogPageClamped(query, target);
      if (requestId === catalogRequestIdRef.current) {
        setServerPage({ query, ...result });
        updatePage(result.page);
      }
    } catch (err) {
      if (requestId === catalogRequestIdRef.current) {
        updatePage(previousPage);
        setError(resolveErrorMessage(err, t("mat_sync_status_failed")));
      }
    } finally {
      if (requestId === catalogRequestIdRef.current) {
        setIsPageLoading(false);
      }
    }
  }, [availability, localCatalog, serverPage, t, updatePage]);

  const selectFilter = useCallback((filter: CatalogFilter) => {
    setActiveFilter(filter);
    void goToPage(1);
  }, [goToPage]);

  const handleSearchQueryChange = useCallback((value: string) => {
    latestSearchQueryRef.current = value;
    catalogRequestIdRef.current += 1;
    searchScheduleIdRef.current += 1;
    setIsLoading(false);
    setIsPageLoading(false);
    setIsSearchPending(Boolean(value.trim()));
    setSearchQuery(value);
  }, []);

  const refreshCatalog = useCallback(async () => {
    setIsRefreshing(true);
    setSuccess(null);
    try {
      const result = await reloadCurrentQuery();
      if (result.isCurrent && !result.hasError && !result.hasNotice) {
        setSuccess(t("mat_sync_catalog_refresh_success"));
      }
    } finally {
      setIsRefreshing(false);
    }
  }, [reloadCurrentQuery, t]);

  const retryFullCatalog = useCallback(() => {
    setFullCatalogFailedQuery(null);
  }, []);

  const installEntry = useCallback(async (entry: MaterialRegistryCatalogEntry) => {
    setPendingInstall(`${entry.material_id}:${entry.revision_id}`);
    setError(null);
    setSuccess(null);
    try {
      const response = await installMaterialRegistryCatalogEntry({
        material_id: entry.material_id,
        revision_id: entry.revision_id,
        package_url: entry.package_url,
        package_sha256: entry.package_sha256,
      });
      await reloadCurrentQuery({ preserveFullCatalog: true });
      setSuccess(response.message || t("mat_sync_install_success"));
    } catch (err) {
      setError(resolveInstallErrorMessage(err, t("mat_sync_install_failed")));
    } finally {
      setPendingInstall(null);
    }
  }, [reloadCurrentQuery, t]);

  const rollbackEntry = useCallback(async (
    entry: MaterialSyncInstalledEntry,
    revisionId: string,
  ) => {
    setPendingRollback(`${entry.material_id}:${revisionId}`);
    setError(null);
    setSuccess(null);
    try {
      await rollbackMaterialSyncRevision(entry.material_id, revisionId);
      await reloadCurrentQuery({ preserveFullCatalog: true });
      setSuccess(t("mat_sync_rollback_success"));
    } catch (err) {
      setError(resolveErrorMessage(err, t("mat_sync_rollback_failed")));
    } finally {
      setPendingRollback(null);
    }
  }, [reloadCurrentQuery, t]);

  const rollbackCandidates = useMemo(
    () => (status?.installed ?? []).filter(
      (entry) => hasLocalMaterialFiles(entry) && resolveRollbackRevisions(entry).length > 0,
    ),
    [status],
  );

  return {
    status,
    view,
    activeFilter,
    filterCounts,
    updateCount,
    catalogTotalCount,
    rollbackCandidates,
    searchQuery,
    isLoading,
    isPageLoading,
    isSearchPending,
    isRefreshing,
    isFullCatalogLoading,
    pendingInstall,
    pendingRollback,
    error,
    notice,
    success,
    dismissError: () => setError(null),
    dismissSuccess: () => setSuccess(null),
    resolveEntryInstallState,
    resolveLocalDirectory: (entry: MaterialRegistryCatalogEntry): string | null => {
      const installed = resolveCatalogInstalledEntry(entry);
      return installed && hasLocalMaterialFiles(installed) ? installed.local_directory : null;
    },
    handleSearchQueryChange,
    selectFilter,
    goToPage,
    refreshCatalog,
    retryFullCatalog,
    installEntry,
    rollbackEntry,
  };
}
