import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { motion } from "framer-motion";

import { apiErrorToVisibleMessage } from "../api/client";
import { fetchLutDetailsCatalog, uploadLocalLut } from "../api/lut";
import type { LutDetailsCatalogGroup, LutDetailsCatalogItem } from "../api/types";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import { useLutDetailsStore } from "../stores/lutDetailsStore";
import { useWidgetStore } from "../stores/widgetStore";
import Button from "./ui/Button";
import {
  StatusBanner,
  cardPadClass,
} from "./ui/panelPrimitives";


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
        </div>
        </div>
              </div>
        )}
    </motion.aside>
  );
}
