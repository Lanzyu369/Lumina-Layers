import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { motion } from "framer-motion";

import { tRuntime } from "../i18n/runtime";
import {
  deleteGradientCardMaterial,
  exportGradientCardMaterials,
  importGradientCardMaterials,
  listGradientCardMaterials,
  updateGradientCardMaterial,
} from "../api/extractor";
import type { SavedMaterialLibraryItem } from "../api/types";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useWidgetStore } from "../stores/widgetStore";

import { normalizeResourceUrl } from "../utils/resourceUrl";
import Button from "./ui/Button";
import {
  StatusBanner,
  mutedSectionCardClass,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

const isRgbTriplet = (value: number[] | null | undefined): value is [number, number, number] =>
  Array.isArray(value) && value.length === 3;

const toRgbCss = (rgb: [number, number, number]) => `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;

const clampChannel = (channel: number): number =>
  Math.max(0, Math.min(255, Math.round(Number.isFinite(channel) ? channel : 0)));

const toHex = (rgb: [number, number, number]) =>
  `#${rgb
    .map((channel) => clampChannel(channel).toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;

const HEX_COLOR_PATTERN = /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

const parseHexColor = (hex: string): [number, number, number] | null => {
  const match = HEX_COLOR_PATTERN.exec(hex.trim());
  if (!match) {
    return null;
  }
  const digits = match[1];
  const expanded = digits.length === 3
    ? digits.split("").map((char) => char + char).join("")
    : digits;
  const r = Number.parseInt(expanded.slice(0, 2), 16);
  const g = Number.parseInt(expanded.slice(2, 4), 16);
  const b = Number.parseInt(expanded.slice(4, 6), 16);
  return [r, g, b];
};

const DEFAULT_EDIT_COLOR: [number, number, number] = [128, 128, 128];

const formatNumericValue = (value: number | null | undefined, digits = 3) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";

const formatNumericVector = (values: number[] | null | undefined, digits = 3) =>
  Array.isArray(values) && values.length > 0
    ? values.map((value) => formatNumericValue(value, digits)).join(", ")
    : "-";

const triggerDownload = (url: string, filename?: string) => {
  const link = document.createElement("a");
  link.href = url;
  if (filename) {
    link.download = filename;
  }
  document.body.appendChild(link);
  link.click();
  link.remove();
};

const textInputClass =
  "min-h-10 w-full rounded-2xl border border-slate-200/80 bg-white/90 px-3 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-100";

const colorPickerInputClass =
  "h-10 w-14 shrink-0 cursor-pointer rounded-2xl border border-slate-200/80 bg-white/90 p-1 shadow-[var(--shadow-control)] dark:border-slate-700/80 dark:bg-slate-900";

const normalizeLibraryItem = (item: SavedMaterialLibraryItem): SavedMaterialLibraryItem => ({
  ...item,
  material_file_url: normalizeResourceUrl(item.material_file_url) ?? item.material_file_url,
  stage_a_params_url: normalizeResourceUrl(item.stage_a_params_url) ?? item.stage_a_params_url,
});

const getMaterialBrand = (item: SavedMaterialLibraryItem): string | null => {
  const brand = item.brand?.trim();
  return brand ? brand : null;
};

const UNASSIGNED_BRAND_GROUP_KEY = "__unassigned__";

const getMaterialBrandGroupKey = (brand: string | null): string =>
  brand ?? UNASSIGNED_BRAND_GROUP_KEY;

type MaterialLibraryBrandGroup = {
  brand: string | null;
  items: SavedMaterialLibraryItem[];
};

export default function MaterialLibraryPanel() {
  const { t, lang } = useI18n();
  const workspace = useWorkspaceMode();
  const setActiveTab = useWidgetStore((state) => state.setActiveTab);
  const startMaterialVerification = useSingleStageStore((state) => state.startMaterialVerification);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const [materials, setMaterials] = useState<SavedMaterialLibraryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pendingDeleteDirectoryName, setPendingDeleteDirectoryName] = useState<string | null>(null);
  const [pendingUpdateDirectoryName, setPendingUpdateDirectoryName] = useState<string | null>(null);
  const [historyMaterial, setHistoryMaterial] = useState<SavedMaterialLibraryItem | null>(null);
  const [selectedDirectoryNames, setSelectedDirectoryNames] = useState<string[]>([]);
  const [editingMaterial, setEditingMaterial] = useState<SavedMaterialLibraryItem | null>(null);
  const [expandedBrandGroupKeys, setExpandedBrandGroupKeys] = useState<string[]>([]);

  const refreshMaterials = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listGradientCardMaterials();
      const nextMaterials = (response.materials ?? []).map(normalizeLibraryItem);
      setMaterials(nextMaterials);
      setHistoryMaterial((previous) =>
        previous
          ? nextMaterials.find((item) => item.directory_name === previous.directory_name) ?? null
          : null,
      );
      setSelectedDirectoryNames((previous) =>
        previous.filter((directoryName) =>
          nextMaterials.some((item) => item.directory_name === directoryName),
        ),
      );
      return nextMaterials;
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_gradient_library_load_failed"));
      setMaterials([]);
      setSelectedDirectoryNames([]);
      return [];
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refreshMaterials();
  }, [refreshMaterials]);

  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    }),
    [lang],
  );

  const formatCreatedAt = useCallback((value: string | null | undefined) => {
    if (!value) {
      return "-";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return dateFormatter.format(parsed);
  }, [dateFormatter]);

  const selectedCount = selectedDirectoryNames.length;
  const allSelected = materials.length > 0 && selectedCount === materials.length;
  const groupedMaterials = useMemo<MaterialLibraryBrandGroup[]>(() => {
    const groups = new Map<string, SavedMaterialLibraryItem[]>();
    const unassigned: SavedMaterialLibraryItem[] = [];
    for (const item of materials) {
      const brand = getMaterialBrand(item);
      if (!brand) {
        unassigned.push(item);
        continue;
      }
      const existing = groups.get(brand);
      if (existing) {
        existing.push(item);
      } else {
        groups.set(brand, [item]);
      }
    }
    const result: MaterialLibraryBrandGroup[] = Array.from(groups, ([brand, items]) => ({
      brand,
      items,
    }));
    if (unassigned.length > 0) {
      result.push({ brand: null, items: unassigned });
    }
    return result;
  }, [materials]);

  const expandedBrandGroupKeySet = useMemo(() => new Set(expandedBrandGroupKeys), [expandedBrandGroupKeys]);

  const handleStartVerification = useCallback((item: SavedMaterialLibraryItem) => {
    startMaterialVerification({
      materialName: item.material_name,
      directoryName: item.directory_name,
      verificationCount: item.verification_count ?? 1,
    });
    setActiveTab("gradient-card-extract");
  }, [setActiveTab, startMaterialVerification]);

  const handleOpenEditDialog = useCallback((item: SavedMaterialLibraryItem) => {
    setEditingMaterial(item);
    setError(null);
    setSuccess(null);
  }, []);

  const handleCloseEditDialog = useCallback(() => {
    setEditingMaterial(null);
  }, []);

  const handleOpenHistoryDialog = useCallback((item: SavedMaterialLibraryItem) => {
    setHistoryMaterial(item);
  }, []);

  const handleCloseHistoryDialog = useCallback(() => {
    setHistoryMaterial(null);
  }, []);

  const handleSaveEditDialog = useCallback(
    async (values: {
      materialName: string;
      brand: string | null;
      estimatedRgb: [number, number, number];
    }) => {
      if (!editingMaterial) {
        return;
      }
      const directoryName = editingMaterial.directory_name;
      setPendingUpdateDirectoryName(directoryName);
      setError(null);
      setSuccess(null);
      try {
        const response = await updateGradientCardMaterial(directoryName, {
          materialName: values.materialName,
          brand: values.brand,
          estimatedRgb: values.estimatedRgb,
        });
        const nextItem = normalizeLibraryItem(response.material);
        setMaterials((previous) =>
          previous.map((item) =>
            item.directory_name === directoryName ? nextItem : item,
          ),
        );
        setSuccess(response.message || t("mat_gradient_library_edit_success"));
        setEditingMaterial(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : t("mat_gradient_library_edit_failed"));
      } finally {
        setPendingUpdateDirectoryName(null);
      }
    },
    [editingMaterial, t],
  );

  const handleDeleteMaterial = useCallback(async (item: SavedMaterialLibraryItem) => {
    const confirmed = window.confirm(
      tRuntime("mat_gradient_library_delete_confirm", {
        materialName: item.material_name,
      }),
    );
    if (!confirmed) {
      return;
    }
    setPendingDeleteDirectoryName(item.directory_name);
    setError(null);
    try {
      await deleteGradientCardMaterial(item.directory_name);
      setMaterials((previous) =>
        previous.filter((entry) => entry.directory_name !== item.directory_name),
      );
      setHistoryMaterial((previous) =>
        previous?.directory_name === item.directory_name ? null : previous,
      );
      setSelectedDirectoryNames((previous) =>
        previous.filter((directoryName) => directoryName !== item.directory_name),
      );
      setSuccess(t("mat_gradient_library_delete_success"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_gradient_library_load_failed"));
    } finally {
      setPendingDeleteDirectoryName(null);
    }
  }, [t]);

  const toggleMaterialSelection = useCallback((directoryName: string) => {
    setSelectedDirectoryNames((previous) =>
      previous.includes(directoryName)
        ? previous.filter((item) => item !== directoryName)
        : [...previous, directoryName],
    );
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedDirectoryNames(
      allSelected ? [] : materials.map((item) => item.directory_name),
    );
  }, [allSelected, materials]);

  const toggleBrandGroupCollapsed = useCallback((groupKey: string) => {
    setExpandedBrandGroupKeys((previous) =>
      previous.includes(groupKey)
        ? previous.filter((item) => item !== groupKey)
        : [...previous, groupKey],
    );
  }, []);

  const handleExportSelected = useCallback(async () => {
    if (selectedDirectoryNames.length === 0) {
      setError(t("mat_gradient_library_export_requires_selection"));
      return;
    }
    setIsExporting(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await exportGradientCardMaterials(selectedDirectoryNames);
      const downloadUrl = normalizeResourceUrl(response.download_url) ?? response.download_url;
      triggerDownload(downloadUrl, response.filename);
      setSuccess(response.message || t("mat_gradient_library_export_success"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_gradient_library_export_failed"));
    } finally {
      setIsExporting(false);
    }
  }, [selectedDirectoryNames, t]);

  const handleImportClick = useCallback(() => {
    setError(null);
    setSuccess(null);
    importInputRef.current?.click();
  }, []);

  const handleImportArchives = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0) {
      return;
    }
    setIsImporting(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await importGradientCardMaterials(files);
      const refreshedMaterials = await refreshMaterials();
      const importedDirectoryNames = (response.imported_materials ?? [])
        .map((item) => item.directory_name)
        .filter((directoryName) =>
          refreshedMaterials.some((material) => material.directory_name === directoryName),
        );
      setSelectedDirectoryNames(importedDirectoryNames);
      setSuccess(response.message || t("mat_gradient_library_import_success"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_gradient_library_import_failed"));
    } finally {
      setIsImporting(false);
    }
  }, [refreshMaterials, t]);

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="material-library-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <input
        ref={importInputRef}
        type="file"
        accept=".zip,application/zip"
        multiple
        className="hidden"
        data-testid="material-library-import-input"
        onChange={(event) => void handleImportArchives(event)}
      />

      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className={`${mutedSectionCardClass} flex flex-col gap-1 px-4 py-3`}>
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {tRuntime("mat_gradient_library_selection_summary", {
              selected: selectedCount,
              total: materials.length,
            })}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t("mat_gradient_library_import_hint")}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <Button
            label={t(
              allSelected
                ? "mat_gradient_library_clear_selection_btn"
                : "mat_gradient_library_select_all_btn",
            )}
            variant="secondary"
            onClick={toggleSelectAll}
            disabled={materials.length === 0 || isLoading || isExporting || isImporting}
          />
          <Button
            label={t("mat_gradient_library_import_btn")}
            variant="secondary"
            onClick={handleImportClick}
            disabled={isLoading || isExporting || pendingDeleteDirectoryName !== null}
            loading={isImporting}
          />
          <Button
            label={t("mat_gradient_library_export_btn")}
            variant="secondary"
            onClick={() => void handleExportSelected()}
            disabled={selectedCount === 0 || isLoading || isImporting || pendingDeleteDirectoryName !== null}
            loading={isExporting}
          />
          <Button
            label={t("mat_gradient_library_refresh_btn")}
            variant="secondary"
            onClick={() => void refreshMaterials()}
            disabled={isLoading || isImporting || isExporting}
            loading={isLoading}
          />
        </div>
      </div>

      {error ? (
        <StatusBanner data-testid="material-library-error" tone="error">
          {error}
        </StatusBanner>
      ) : null}

      {success ? (
        <StatusBanner data-testid="material-library-success" tone="success">
          {success}
        </StatusBanner>
      ) : null}

      {editingMaterial ? (
        <MaterialLibraryEditDialog
          item={editingMaterial}
          pending={pendingUpdateDirectoryName === editingMaterial.directory_name}
          onCancel={handleCloseEditDialog}
          onSave={handleSaveEditDialog}
        />
      ) : null}

      {historyMaterial ? (
        <div
          data-testid="material-library-history-dialog-overlay"
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "var(--surface-scrim)" }}
          onClick={handleCloseHistoryDialog}
        >
          <section
            data-testid="material-library-history-dialog"
            className="relative flex max-h-[85vh] w-full max-w-5xl flex-col gap-4 overflow-hidden rounded-[28px] border p-4 shadow-2xl sm:p-5"
            style={{
              borderColor: "var(--surface-outline)",
              background: "var(--surface-panel-strong)",
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
                  {t("mat_gradient_library_history_title")}
                </h3>
                <p className="mt-1 truncate text-sm text-slate-500 dark:text-slate-400">
                  {historyMaterial.material_name}
                </p>
              </div>
              <Button
                label={t("mat_gradient_library_history_close_btn")}
                variant="secondary"
                onClick={handleCloseHistoryDialog}
                className="w-full sm:w-auto"
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className={`${mutedSectionCardClass} px-4 py-3`}>
                <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  {t("mat_gradient_library_directory_label")}
                </dt>
                <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                  {historyMaterial.directory_name}
                </dd>
              </div>
              <div className={`${mutedSectionCardClass} px-4 py-3`}>
                <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  {t("mat_gradient_library_verification_count_label")}
                </dt>
                <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                  {Math.max(
                    historyMaterial.verification_history?.length ?? 0,
                    Number(historyMaterial.verification_count ?? 0),
                    0,
                  )}
                </dd>
              </div>
            </div>

            <div className="overflow-y-auto pr-1">
              {(historyMaterial.verification_history?.length ?? 0) === 0 ? (
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  {t("mat_gradient_library_history_empty")}
                </p>
              ) : (
                <div className="grid gap-3">
                  {[...(historyMaterial.verification_history ?? [])]
                    .sort((left, right) => right.verification_index - left.verification_index)
                    .map((historyItem) => {
                      const historyRgb = isRgbTriplet(historyItem.estimated_rgb)
                        ? historyItem.estimated_rgb
                        : null;
                      const historyHex = historyRgb ? toHex(historyRgb) : "-";
                      return (
                        <article
                          key={`${historyMaterial.directory_name}-history-${historyItem.verification_index}`}
                          data-testid="material-library-history-item"
                          className={`${mutedSectionCardClass} p-4`}
                        >
                          <div className="flex items-start gap-4">
                            <div
                              className="h-12 w-12 shrink-0 rounded-2xl border border-slate-200/80 dark:border-slate-700/80"
                              style={historyRgb ? { backgroundColor: toRgbCss(historyRgb) } : undefined}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                                  {tRuntime("mat_gradient_library_history_run_label", {
                                    index: historyItem.verification_index,
                                  })}
                                </h5>
                                <span className="text-xs text-slate-500 dark:text-slate-400">
                                  {formatCreatedAt(historyItem.captured_at)}
                                </span>
                              </div>
                              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                                {historyHex}
                              </p>
                            </div>
                          </div>

                          <dl className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_time_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatCreatedAt(historyItem.captured_at)}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_fit_error_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatNumericValue(historyItem.mean_delta_e, 2)}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_rmse_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatNumericValue(historyItem.rmse_linear, 4)}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_color_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {historyRgb ? historyRgb.join(", ") : "-"}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3 sm:col-span-2 xl:col-span-2`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_orientation_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {tRuntime("mat_gradient_library_history_orientation_value", {
                                  white: historyItem.white_detected_orientation || "-",
                                  black: historyItem.black_detected_orientation || "-",
                                })}
                              </dd>
                            </div>
                          </dl>

                          <dl className="mt-3 grid gap-3">
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_e_label")}
                              </dt>
                              <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatNumericVector(historyItem.e_values)}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_k_label")}
                              </dt>
                              <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatNumericVector(historyItem.k_values)}
                              </dd>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2">
                              <div className={`${mutedSectionCardClass} px-3 py-3`}>
                                <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                  {t("mat_gradient_library_history_white_c0_label")}
                                </dt>
                                <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                                  {formatNumericVector(historyItem.white_c0_values)}
                                </dd>
                              </div>
                              <div className={`${mutedSectionCardClass} px-3 py-3`}>
                                <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                  {t("mat_gradient_library_history_black_c0_label")}
                                </dt>
                                <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                                  {formatNumericVector(historyItem.black_c0_values)}
                                </dd>
                              </div>
                            </div>
                          </dl>
                        </article>
                      );
                    })}
                </div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {isLoading ? (
        <section className={`${resolveSectionCardClass(workspace.mode)} flex min-h-48 items-center justify-center`}>
          <p className="text-sm text-slate-500 dark:text-slate-400">{t("mat_gradient_library_loading")}</p>
        </section>
      ) : materials.length === 0 ? (
        <section className={`${resolveSectionCardClass(workspace.mode)} flex min-h-48 items-center justify-center`}>
          <p className="max-w-lg text-center text-sm text-slate-500 dark:text-slate-400">{t("mat_gradient_library_empty")}</p>
        </section>
      ) : (
        <div className="grid gap-6">
          {groupedMaterials.map(({ brand, items }) => {
            const groupKey = getMaterialBrandGroupKey(brand);
            const groupLabel = brand ?? t("mat_gradient_library_brand_unassigned");
            const isCollapsed = !expandedBrandGroupKeySet.has(groupKey);
            return (
              <section
                key={groupKey}
                data-testid="material-library-brand-group"
                data-brand={brand ?? ""}
                className="grid gap-3"
              >
                <button
                  type="button"
                  data-testid="material-library-brand-group-toggle"
                  aria-expanded={!isCollapsed}
                  onClick={() => toggleBrandGroupCollapsed(groupKey)}
                  className="flex w-full items-center justify-between gap-3 rounded-2xl border border-slate-200/80 px-3 py-2 text-left transition-colors hover:border-slate-300 hover:bg-slate-100/70 dark:border-slate-700/80 dark:hover:border-slate-600 dark:hover:bg-slate-800/70"
                >
                  <span className="flex min-w-0 flex-wrap items-center gap-3">
                    <span className="truncate text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {groupLabel}
                    </span>
                    <span className="rounded-full border border-slate-200/80 px-2 py-0.5 text-xs font-semibold text-slate-500 dark:border-slate-700/80 dark:text-slate-400">
                      {items.length}
                    </span>
                  </span>
                  <motion.svg
                    animate={{ rotate: isCollapsed ? 0 : 90 }}
                    transition={{ type: "spring", stiffness: 300, damping: 20 }}
                    className="h-4 w-4 shrink-0 text-slate-500 dark:text-slate-400"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <polyline points="9 18 15 12 9 6" />
                  </motion.svg>
                </button>
                {isCollapsed ? null : (
                  <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,19rem),1fr))]">
                {items.map((item) => {
                  const estimatedRgb = isRgbTriplet(item.estimated_rgb) ? item.estimated_rgb : null;
                  const estimatedHex = estimatedRgb ? toHex(estimatedRgb) : "-";
                  const itemBrand = getMaterialBrand(item);
                  const itemBrandLabel = itemBrand ?? t("mat_gradient_library_brand_unassigned");
                  return (
                    <section
                      key={`${item.directory_name}-${item.material_name}`}
                      data-testid="material-library-item"
                      className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}
                    >
                      <div className="flex items-start gap-4">
                        <label className="mt-1 flex shrink-0 items-center">
                          <input
                            type="checkbox"
                            data-testid={`material-library-select-${item.directory_name}`}
                            aria-label={tRuntime("mat_gradient_library_select_item_label", {
                              materialName: item.material_name,
                            })}
                            checked={selectedDirectoryNames.includes(item.directory_name)}
                            onChange={() => toggleMaterialSelection(item.directory_name)}
                            className="h-4 w-4 rounded border-slate-300 dark:border-slate-600"
                          />
                        </label>
                        <div className="flex min-w-0 flex-1 items-start gap-4">
                          <div
                            className="h-20 w-20 shrink-0 rounded-3xl border border-slate-200/80 dark:border-slate-700/80"
                            style={estimatedRgb ? { backgroundColor: toRgbCss(estimatedRgb) } : undefined}
                          />
                          <div className="min-w-0 flex-1">
                            <h3 className="flex min-w-0 flex-wrap items-center gap-2 text-base font-semibold text-slate-900 dark:text-slate-50">
                              <span
                                data-testid="material-library-brand-tag"
                                className="max-w-full truncate rounded-full border border-slate-200/80 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:border-slate-700/80 dark:text-slate-300"
                              >
                                {itemBrandLabel}
                              </span>
                              <span className="min-w-0 truncate">{item.material_name}</span>
                            </h3>
                            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{estimatedHex}</p>
                          </div>
                        </div>
                      </div>

                      <dl className="grid gap-3 sm:grid-cols-2">
                  <div className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_created_at_label")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {formatCreatedAt(item.created_at)}
                    </dd>
                  </div>
                  <div className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_updated_at_label")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {formatCreatedAt(item.updated_at)}
                    </dd>
                  </div>
                  <div className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_brand_label")}
                    </dt>
                    <dd
                      data-testid="material-library-item-brand"
                      className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-50"
                    >
                      {item.brand?.trim() || "-"}
                    </dd>
                  </div>
                  <div className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_directory_label")}
                    </dt>
                    <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {item.directory_name}
                    </dd>
                  </div>
                  <div className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_fit_error_label")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {typeof item.mean_delta_e === "number" ? item.mean_delta_e.toFixed(2) : "-"}
                    </dd>
                  </div>
                  <div className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_verification_count_label")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {Math.max(1, Number(item.verification_count ?? 1))}
                    </dd>
                  </div>
                  <div
                    data-testid="material-library-item-usage"
                    className={`${mutedSectionCardClass} px-4 py-3`}
                  >
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_usage_count_label")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {Number(item.usage_total ?? 0)}
                    </dd>
                    {item.usage_by_color_mode &&
                      Object.keys(item.usage_by_color_mode).length > 0 && (
                        <ul className="mt-2 grid gap-1 text-xs text-slate-500 dark:text-slate-400">
                          {Object.entries(item.usage_by_color_mode)
                            .sort((left, right) => right[1] - left[1])
                            .map(([mode, count]) => (
                              <li
                                key={mode}
                                className="flex items-center justify-between gap-2"
                              >
                                <span className="truncate">{mode}</span>
                                <span className="shrink-0 font-mono text-slate-700 dark:text-slate-200">
                                  {count}
                                </span>
                              </li>
                            ))}
                        </ul>
                      )}
                    {item.usage_last_used_at && (
                      <p className="mt-2 text-[11px] text-slate-400 dark:text-slate-500">
                        {tRuntime("mat_gradient_library_usage_last_used", {
                          when: formatCreatedAt(item.usage_last_used_at),
                        })}
                      </p>
                    )}
                  </div>
                  <div className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_layer_height_label")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {typeof item.layer_height_mm === "number" ? `${item.layer_height_mm.toFixed(2)} mm` : "-"}
                    </dd>
                  </div>
                      </dl>

                      <div className="grid gap-3">
                  <Button
                    label={t("mat_gradient_library_edit_btn")}
                    variant="secondary"
                    onClick={() => handleOpenEditDialog(item)}
                    disabled={pendingDeleteDirectoryName === item.directory_name}
                    className="w-full"
                  />
                  <Button
                    label={t("mat_gradient_library_reverify_btn")}
                    variant="secondary"
                    onClick={() => handleStartVerification(item)}
                    disabled={pendingDeleteDirectoryName === item.directory_name || pendingUpdateDirectoryName === item.directory_name}
                    className="w-full"
                  />
                  <Button
                    label={t("mat_gradient_library_show_history_btn")}
                    variant="secondary"
                    onClick={() => handleOpenHistoryDialog(item)}
                    disabled={pendingDeleteDirectoryName === item.directory_name || pendingUpdateDirectoryName === item.directory_name}
                    className="w-full"
                  />
                  <Button
                    label={t("mat_gradient_library_delete_btn")}
                    variant="secondary"
                    onClick={() => void handleDeleteMaterial(item)}
                    disabled={pendingDeleteDirectoryName === item.directory_name}
                    loading={pendingDeleteDirectoryName === item.directory_name}
                    className="w-full"
                  />
                      </div>
                    </section>
                  );
                })}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </motion.aside>
  );
}

interface MaterialLibraryEditDialogProps {
  item: SavedMaterialLibraryItem;
  pending: boolean;
  onCancel: () => void;
  onSave: (values: {
    materialName: string;
    brand: string | null;
    estimatedRgb: [number, number, number];
  }) => void;
}

function MaterialLibraryEditDialog({
  item,
  pending,
  onCancel,
  onSave,
}: MaterialLibraryEditDialogProps) {
  const { t } = useI18n();

  const initialColor = useMemo<[number, number, number]>(() => {
    if (!isRgbTriplet(item.estimated_rgb)) {
      return DEFAULT_EDIT_COLOR;
    }
    return [
      clampChannel(item.estimated_rgb[0]),
      clampChannel(item.estimated_rgb[1]),
      clampChannel(item.estimated_rgb[2]),
    ];
  }, [item.estimated_rgb]);

  const [materialName, setMaterialName] = useState(item.material_name);
  const [brand, setBrand] = useState(item.brand?.trim() || "");
  const [color, setColor] = useState<[number, number, number]>(initialColor);
  const [colorHex, setColorHex] = useState<string>(toHex(initialColor));
  const [colorHexError, setColorHexError] = useState<string | null>(null);

  const handleColorPickerChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const parsed = parseHexColor(event.target.value);
    if (!parsed) {
      return;
    }
    setColor(parsed);
    setColorHex(toHex(parsed));
    setColorHexError(null);
  }, []);

  const handleColorHexChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const raw = event.target.value;
      setColorHex(raw);
      const parsed = parseHexColor(raw);
      if (parsed) {
        setColor(parsed);
        setColorHexError(null);
      } else if (raw.trim() === "") {
        setColorHexError(null);
      } else {
        setColorHexError(t("mat_gradient_library_edit_color_invalid_hex"));
      }
    },
    [t],
  );

  const handleSave = useCallback(() => {
    const trimmedName = materialName.trim();
    if (!trimmedName || colorHexError) {
      return;
    }
    onSave({
      materialName: trimmedName,
      brand: brand.trim() || null,
      estimatedRgb: [clampChannel(color[0]), clampChannel(color[1]), clampChannel(color[2])],
    });
  }, [brand, color, colorHexError, materialName, onSave]);

  return (
    <div
      data-testid="material-library-edit-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "var(--surface-scrim)" }}
    >
      <section
        className="relative flex w-full max-w-lg flex-col gap-4 overflow-hidden rounded-[28px] border p-4 shadow-2xl sm:p-5"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
      >
        <div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_gradient_library_edit_title")}
          </h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {tRuntime("mat_gradient_library_edit_desc", {
              directoryName: item.directory_name,
            })}
          </p>
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_gradient_material_name_label")}
          </span>
          <input
            data-testid="material-library-edit-name-input"
            value={materialName}
            onChange={(event) => setMaterialName(event.target.value)}
            placeholder={t("mat_gradient_material_name_placeholder")}
            className={textInputClass}
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_gradient_brand_label")}
          </span>
          <input
            data-testid="material-library-edit-brand-input"
            value={brand}
            onChange={(event) => setBrand(event.target.value)}
            placeholder={t("mat_gradient_brand_placeholder")}
            className={textInputClass}
          />
        </label>

        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_gradient_library_edit_color_label")}
          </span>
          <div className="flex items-center gap-3">
            <input
              type="color"
              data-testid="material-library-edit-color-picker"
              value={toHex(color)}
              onChange={handleColorPickerChange}
              aria-label={t("mat_gradient_library_edit_color_label")}
              className={colorPickerInputClass}
            />
            <input
              type="text"
              data-testid="material-library-edit-color-hex-input"
              value={colorHex}
              onChange={handleColorHexChange}
              placeholder={t("mat_gradient_library_edit_color_hex_placeholder")}
              className={textInputClass}
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
            />
            <div
              data-testid="material-library-edit-color-swatch"
              aria-hidden="true"
              className="h-10 w-10 shrink-0 rounded-2xl border border-slate-200/80 dark:border-slate-700/80"
              style={{ backgroundColor: toRgbCss(color) }}
            />
          </div>
          {colorHexError ? (
            <p
              data-testid="material-library-edit-color-hex-error"
              className="text-xs font-medium text-rose-600 dark:text-rose-400"
            >
              {colorHexError}
            </p>
          ) : (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("mat_gradient_library_edit_color_hint")}
            </p>
          )}
        </div>

        <div className={`${mutedSectionCardClass} px-4 py-3`}>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            {t("mat_gradient_library_directory_label")}
          </p>
          <p className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
            {item.directory_name}
          </p>
        </div>

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button
            label={t("mat_gradient_library_edit_cancel_btn")}
            variant="secondary"
            onClick={onCancel}
            disabled={pending}
            className="w-full sm:w-auto"
          />
          <Button
            label={t("mat_gradient_library_edit_save_btn")}
            onClick={handleSave}
            disabled={!materialName.trim() || Boolean(colorHexError)}
            loading={pending}
            className="w-full sm:w-auto"
          />
        </div>
      </section>
    </div>
  );
}
