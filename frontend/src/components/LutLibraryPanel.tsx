import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { motion } from "framer-motion";

import { apiErrorToVisibleMessage } from "../api/client";
import { fetchLutDetailsCatalog, uploadLocalLut } from "../api/lut";
import type { LutDetailsCatalogGroup, LutDetailsCatalogItem } from "../api/types";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import { useLutDetailsStore } from "../stores/lutDetailsStore";
import { useWidgetStore } from "../stores/widgetStore";
import Button from "./ui/Button";
import {
  StatusBanner,
  mutedSectionCardClass,
  resolvePanelSurfaceClass,
} from "./ui/panelPrimitives";

type LutOrigin = "cloud" | "custom" | "preset";

const flattenCatalog = (groups: LutDetailsCatalogGroup[]): LutDetailsCatalogItem[] =>
  groups.flatMap((group) => group.items ?? []);

const normalizedText = (value: string): string =>
  value.toLowerCase().replace(/[\s\-_&/\\]+/g, "");

const itemMatchesQuery = (item: LutDetailsCatalogItem, query: string): boolean => {
  const terms = query.trim().split(/\s+/).map(normalizedText).filter(Boolean);
  if (terms.length === 0) {
    return true;
  }
  const tokens = [
    item.name,
    item.manufacturer,
    item.material_type,
    item.color_mode,
    item.source_kind,
    item.path,
    ...item.search_tokens,
  ].map(normalizedText);
  return terms.every((term) => tokens.some((token) => token.includes(term)));
};

const resolveLutOrigin = (item: LutDetailsCatalogItem): LutOrigin => {
  const normalizedPath = item.path.replace(/\\/g, "/").toLowerCase();
  const normalizedName = item.name.toLowerCase();
  if (normalizedPath.includes("/lut-preset/cloud/") || normalizedPath.startsWith("lut-preset/cloud/") || normalizedName.startsWith("cloud -")) {
    return "cloud";
  }
  if (normalizedPath.includes("/lut-preset/custom/") || normalizedPath.startsWith("lut-preset/custom/") || normalizedName.startsWith("custom -")) {
    return "custom";
  }
  return "preset";
};

const groupItems = (
  items: LutDetailsCatalogItem[],
  unknownLabel: string,
): LutDetailsCatalogGroup[] => {
  const groups = new Map<string, LutDetailsCatalogItem[]>();
  for (const item of items) {
    const key = item.manufacturer || unknownLabel;
    const existing = groups.get(key);
    if (existing) {
      existing.push(item);
    } else {
      groups.set(key, [item]);
    }
  }
  return Array.from(groups, ([manufacturer, groupItemsValue]) => ({
    manufacturer,
    items: groupItemsValue,
  })).sort((left, right) => left.manufacturer.localeCompare(right.manufacturer));
};

export default function LutLibraryPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const setActiveTab = useWidgetStore((state) => state.setActiveTab);
  const [catalog, setCatalog] = useState<LutDetailsCatalogGroup[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const refreshCatalog = useCallback(async () => {
    setError(null);
    try {
      const response = await fetchLutDetailsCatalog();
      setCatalog(response.groups ?? []);
      return response.groups ?? [];
    } catch (err) {
      setCatalog([]);
      setError(apiErrorToVisibleMessage(err, t("lut_library_load_failed")));
      return [];
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refreshCatalog();
  }, [refreshCatalog]);

  const allItems = useMemo(() => flattenCatalog(catalog), [catalog]);
  const filteredItems = useMemo(
    () => allItems.filter((item) => itemMatchesQuery(item, query)),
    [allItems, query],
  );
  const groupedItems = useMemo(
    () => groupItems(filteredItems, t("lut_library_unknown")),
    [filteredItems, t],
  );
  const cloudCount = useMemo(
    () => allItems.filter((item) => resolveLutOrigin(item) === "cloud").length,
    [allItems],
  );
  const customCount = useMemo(
    () => allItems.filter((item) => resolveLutOrigin(item) === "custom").length,
    [allItems],
  );
  const modeCount = useMemo(
    () => new Set(allItems.map((item) => item.color_mode).filter(Boolean)).size,
    [allItems],
  );

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    setSuccess(null);
    try {
      await refreshCatalog();
    } finally {
      setIsRefreshing(false);
    }
  }, [refreshCatalog]);

  const handleUpload = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setIsUploading(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await uploadLocalLut(file);
      await refreshCatalog();
      setSuccess(response.message || t("lut_library_upload_success"));
    } catch (err) {
      setError(apiErrorToVisibleMessage(err, t("lut_library_upload_failed")));
    } finally {
      setIsUploading(false);
    }
  }, [refreshCatalog, t]);

  const openDetails = useCallback(async (item: LutDetailsCatalogItem) => {
    const store = useLutDetailsStore.getState();
    await store.fetchCatalog();
    useLutDetailsStore.getState().setQuery("");
    useLutDetailsStore.getState().selectManufacturer(item.manufacturer);
    useLutDetailsStore.getState().selectLut(item.name);
    setActiveTab("lut-details");
    void useLutDetailsStore.getState().loadSelectedLut();
  }, [setActiveTab]);

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="lut-library-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <section className={`${mutedSectionCardClass} grid gap-4 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center`}>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("lut_library_title")}
          </p>
          <dl className="mt-3 grid gap-3 sm:grid-cols-4">
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{t("lut_library_total_label")}</dt>
              <dd data-testid="lut-library-total-count" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">{allItems.length}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{t("lut_library_cloud_label")}</dt>
              <dd data-testid="lut-library-cloud-count" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">{cloudCount}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{t("lut_library_custom_label")}</dt>
              <dd data-testid="lut-library-custom-count" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">{customCount}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{t("lut_library_mode_count_label")}</dt>
              <dd data-testid="lut-library-mode-count" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">{modeCount}</dd>
            </div>
          </dl>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            label={t("lut_library_refresh_btn")}
            variant="secondary"
            onClick={() => void handleRefresh()}
            loading={isRefreshing}
          />
          <Button
            label={t("lut_library_upload_btn")}
            onClick={() => uploadInputRef.current?.click()}
            loading={isUploading}
          />
          <input
            ref={uploadInputRef}
            type="file"
            accept=".npy,.json,.npz,.msgpack"
            className="hidden"
            onChange={(event) => void handleUpload(event)}
          />
        </div>
      </section>

      {success && (
        <StatusBanner data-testid="lut-library-success" tone="success">
          {success}
        </StatusBanner>
      )}
      {error && (
        <StatusBanner data-testid="lut-library-error" tone="error">
          {error}
        </StatusBanner>
      )}

      <section className="flex flex-col gap-4">
        <label className="min-w-0">
          <span className="sr-only">{t("lut_library_search_placeholder")}</span>
          <input
            data-testid="lut-library-search-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("lut_library_search_placeholder")}
            className="min-h-11 w-full rounded-[22px] border border-slate-200/80 bg-[var(--surface-panel)] px-4 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] transition-all duration-200 hover:border-slate-300 focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:text-slate-100 dark:hover:border-slate-600"
          />
        </label>

        {isLoading ? (
          <div className="flex min-h-48 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
            {t("lut_library_loading")}
          </div>
        ) : filteredItems.length === 0 ? (
          <div
            data-testid="lut-library-empty"
            className="rounded-[22px] border border-dashed border-slate-300/80 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700/80 dark:text-slate-400"
          >
            {t("lut_library_empty")}
          </div>
        ) : (
          groupedItems.map((group) => (
            <section key={group.manufacturer} className="flex flex-col gap-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                  {group.manufacturer}
                </h3>
                <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400">
                  {tRuntime("lut_library_group_count", { count: String(group.items.length) })}
                </span>
              </div>
              <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,20rem),1fr))]">
                {group.items.map((item) => {
                  const origin = resolveLutOrigin(item);
                  return (
                    <article
                      key={`${item.name}:${item.fingerprint}`}
                      data-testid="lut-library-card"
                      className="flex min-w-0 flex-col gap-4 rounded-[22px] border border-slate-200/80 bg-[var(--surface-panel)] p-4 shadow-[var(--shadow-control)] dark:border-slate-800/80"
                    >
                      <div className="flex min-w-0 items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                            {item.name}
                          </p>
                          <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">
                            {item.material_type || t("lut_library_unknown")}
                          </p>
                        </div>
                        <span className="shrink-0 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 dark:bg-blue-950/45 dark:text-blue-300">
                          {t(`lut_library_origin_${origin}`)}
                        </span>
                      </div>
                      <dl className="grid gap-3 text-xs text-slate-600 dark:text-slate-300">
                        <div className="min-w-0">
                          <dt className="font-medium text-slate-500 dark:text-slate-400">{t("lut_library_color_mode_label")}</dt>
                          <dd className="mt-1 truncate">{item.color_mode || t("lut_library_unknown")}</dd>
                        </div>
                        <div className="min-w-0">
                          <dt className="font-medium text-slate-500 dark:text-slate-400">{t("lut_library_source_kind_label")}</dt>
                          <dd className="mt-1 truncate">{item.source_kind || t("lut_library_unknown")}</dd>
                        </div>
                        <div className="min-w-0">
                          <dt className="font-medium text-slate-500 dark:text-slate-400">{t("lut_library_path_label")}</dt>
                          <dd className="mt-1 truncate">{item.path}</dd>
                        </div>
                        <div className="min-w-0">
                          <dt className="font-medium text-slate-500 dark:text-slate-400">{t("lut_library_fingerprint_label")}</dt>
                          <dd className="mt-1 truncate">{item.fingerprint}</dd>
                        </div>
                      </dl>
                      <Button
                        label={t("lut_library_details_btn")}
                        variant="secondary"
                        onClick={() => void openDetails(item)}
                        className="w-full"
                      />
                    </article>
                  );
                })}
              </div>
            </section>
          ))
        )}
      </section>
    </motion.aside>
  );
}
