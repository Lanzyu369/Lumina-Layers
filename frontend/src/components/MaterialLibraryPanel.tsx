import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";

import { tRuntime } from "../i18n/runtime";
import { deleteGradientCardMaterial, listGradientCardMaterials } from "../api/extractor";
import type { SavedMaterialLibraryItem } from "../api/types";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useWidgetStore } from "../stores/widgetStore";
import { normalizeResourceUrl } from "../utils/resourceUrl";
import Button from "./ui/Button";
import {
  PanelIntro,
  StatusBanner,
  mutedSectionCardClass,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

const isRgbTriplet = (value: number[] | null | undefined): value is [number, number, number] =>
  Array.isArray(value) && value.length === 3;

const toRgbCss = (rgb: [number, number, number]) => `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;

const toHex = (rgb: [number, number, number]) =>
  `#${rgb
    .map((channel) => Math.max(0, Math.min(255, channel)).toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;

const formatNumericValue = (value: number | null | undefined, digits = 3) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";

const formatNumericVector = (values: number[] | null | undefined, digits = 3) =>
  Array.isArray(values) && values.length > 0
    ? values.map((value) => formatNumericValue(value, digits)).join(", ")
    : "-";

export default function MaterialLibraryPanel() {
  const { t, lang } = useI18n();
  const workspace = useWorkspaceMode();
  const setActiveTab = useWidgetStore((state) => state.setActiveTab);
  const startMaterialVerification = useSingleStageStore((state) => state.startMaterialVerification);
  const [materials, setMaterials] = useState<SavedMaterialLibraryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingDeleteDirectoryName, setPendingDeleteDirectoryName] = useState<string | null>(null);
  const [expandedHistoryDirectoryNames, setExpandedHistoryDirectoryNames] = useState<string[]>([]);

  const refreshMaterials = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listGradientCardMaterials();
      const nextMaterials = (response.materials ?? []).map((item) => ({
          ...item,
          material_file_url: normalizeResourceUrl(item.material_file_url) ?? item.material_file_url,
          stage_a_params_url: normalizeResourceUrl(item.stage_a_params_url) ?? item.stage_a_params_url,
        }));
      setMaterials(nextMaterials);
      setExpandedHistoryDirectoryNames((previous) =>
        previous.filter((directoryName) =>
          nextMaterials.some((item) => item.directory_name === directoryName),
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_gradient_library_load_failed"));
      setMaterials([]);
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

  const handleStartVerification = useCallback((item: SavedMaterialLibraryItem) => {
    startMaterialVerification({
      materialName: item.material_name,
      directoryName: item.directory_name,
      verificationCount: item.verification_count ?? 1,
    });
    setActiveTab("gradient-card-extract");
  }, [setActiveTab, startMaterialVerification]);

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
      setExpandedHistoryDirectoryNames((previous) =>
        previous.filter((directoryName) => directoryName !== item.directory_name),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_gradient_library_load_failed"));
    } finally {
      setPendingDeleteDirectoryName(null);
    }
  }, [t]);

  const toggleHistoryExpanded = useCallback((directoryName: string) => {
    setExpandedHistoryDirectoryNames((previous) =>
      previous.includes(directoryName)
        ? previous.filter((item) => item !== directoryName)
        : [...previous, directoryName],
    );
  }, []);

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="material-library-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <PanelIntro
        eyebrow={t("tab.materialManagement")}
        title={t("mat_gradient_library_title")}
        description={t("mat_gradient_library_desc")}
      />

      <div className="flex items-center justify-end">
        <Button
          label={t("mat_gradient_library_refresh_btn")}
          variant="secondary"
          onClick={() => void refreshMaterials()}
          disabled={isLoading}
          loading={isLoading}
        />
      </div>

      {error ? (
        <StatusBanner data-testid="material-library-error" tone="error">
          {error}
        </StatusBanner>
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
        <div className="grid gap-4 xl:grid-cols-2">
          {materials.map((item) => {
            const estimatedRgb = isRgbTriplet(item.estimated_rgb) ? item.estimated_rgb : null;
            const estimatedHex = estimatedRgb ? toHex(estimatedRgb) : "-";
            const verificationHistory = item.verification_history ?? [];
            const isHistoryExpanded = expandedHistoryDirectoryNames.includes(item.directory_name);
            return (
              <section
                key={`${item.directory_name}-${item.material_name}`}
                data-testid="material-library-item"
                className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}
              >
                <div className="flex items-start gap-4">
                  <div
                    className="h-20 w-20 shrink-0 rounded-3xl border border-slate-200/80 dark:border-slate-700/80"
                    style={estimatedRgb ? { backgroundColor: toRgbCss(estimatedRgb) } : undefined}
                  />
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-base font-semibold text-slate-900 dark:text-slate-50">
                      {item.material_name}
                    </h3>
                    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{estimatedHex}</p>
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
                      {t("mat_gradient_library_directory_label")}
                    </dt>
                    <dd className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
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
                  <div className={`${mutedSectionCardClass} px-4 py-3`}>
                    <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_library_layer_height_label")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {typeof item.layer_height_mm === "number" ? `${item.layer_height_mm.toFixed(2)} mm` : "-"}
                    </dd>
                  </div>
                </dl>

                <div className="grid gap-3 sm:grid-cols-3">
                  <Button
                    label={t("mat_gradient_library_reverify_btn")}
                    variant="secondary"
                    onClick={() => handleStartVerification(item)}
                    className="w-full"
                  />
                  <Button
                    label={t(
                      isHistoryExpanded
                        ? "mat_gradient_library_hide_history_btn"
                        : "mat_gradient_library_show_history_btn",
                    )}
                    variant="secondary"
                    onClick={() => toggleHistoryExpanded(item.directory_name)}
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

                {isHistoryExpanded ? (
                  <section
                    data-testid={`material-library-history-${item.directory_name}`}
                    className={`${mutedSectionCardClass} flex flex-col gap-3 px-4 py-4`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {t("mat_gradient_library_history_title")}
                      </h4>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {Math.max(verificationHistory.length, Number(item.verification_count ?? 0), 0)}
                      </span>
                    </div>
                    {verificationHistory.length === 0 ? (
                      <p className="text-sm text-slate-500 dark:text-slate-400">
                        {t("mat_gradient_library_history_empty")}
                      </p>
                    ) : (
                      <div className="grid gap-3">
                        {[...verificationHistory]
                          .sort((left, right) => right.verification_index - left.verification_index)
                          .map((historyItem) => {
                            const historyRgb = isRgbTriplet(historyItem.estimated_rgb)
                              ? historyItem.estimated_rgb
                              : null;
                            const historyHex = historyRgb ? toHex(historyRgb) : "-";
                            return (
                              <article
                                key={`${item.directory_name}-history-${historyItem.verification_index}`}
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
                  </section>
                ) : null}

                <div className="grid gap-3 sm:grid-cols-2">
                  <a
                    href={item.material_file_url}
                    download
                    className="inline-flex min-h-11 items-center justify-center rounded-2xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-[var(--shadow-control-hover)] transition-colors hover:bg-blue-700"
                  >
                    {t("mat_gradient_download_material_btn")}
                  </a>
                  {item.stage_a_params_url ? (
                    <a
                      href={item.stage_a_params_url}
                      download
                      className="inline-flex min-h-11 items-center justify-center rounded-2xl border border-slate-300/80 px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:text-slate-900 dark:border-slate-600/80 dark:text-slate-200"
                    >
                      {t("ext_single_stage_download_stage_a")}
                    </a>
                  ) : null}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </motion.aside>
  );
}
