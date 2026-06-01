import { useEffect } from "react";
import { useLutManagerStore } from "../stores/lutManagerStore";
import { useI18n } from "../i18n/context";
import { useMlsReadOnly } from "../hooks/useMlsReadOnly";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Button from "./ui/Button";
import { motion } from "framer-motion";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import {
  StatusBanner,
  desktopPrimaryColumnClass,
  desktopSecondaryColumnClass,
  resolveDesktopSplitLayoutClass,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

function localizeLutCapability(
  capability: string,
  t: (key: string) => string,
): string {
  switch (capability) {
    case "legacy_lookup":
      return t("lut_info_capability_legacy_lookup");
    case "predictive_match":
      return t("lut_info_capability_predictive_match");
    case "predictive_model":
      return t("lut_info_capability_predictive_model");
    case "dynamic_layer_height":
      return t("lut_info_capability_dynamic_layer_height");
    case "dynamic_layer_count":
      return t("lut_info_capability_dynamic_layer_count");
    case "custom_recipe":
      return t("lut_info_capability_custom_recipe");
    case "native_reference":
      return t("lut_info_capability_native_reference");
    default:
      return capability;
  }
}

function renderLutInfoDetail(
  info: {
    schema_version?: string;
    capabilities?: string[];
    source_kind?: string;
    supported_modes?: Array<{ color_layers: number; layer_height_mm: number }>;
    supports_predictive_match?: boolean;
    supports_dynamic_layer_height?: boolean;
    supports_dynamic_layer_count?: boolean;
    supports_custom_recipe?: boolean;
  },
  t: (key: string) => string,
): string {
  const capabilityLabels = (info.capabilities ?? []).map((capability) =>
    localizeLutCapability(capability, t),
  );
  const summary = [
    `${t("lut_info_schema_label")}: ${info.schema_version ?? "1.0"}`,
    `${t("lut_info_source_kind_label")}: ${info.source_kind ?? "legacy_lookup"}`,
    info.supports_predictive_match
      ? t("lut_info_predictive_enabled")
      : t("lut_info_predictive_disabled"),
    info.supports_dynamic_layer_height
      ? t("lut_info_dynamic_enabled")
      : t("lut_info_dynamic_disabled"),
    info.supports_dynamic_layer_count
      ? t("lut_info_dynamic_count_enabled")
      : t("lut_info_dynamic_count_disabled"),
    info.supports_custom_recipe
      ? t("lut_info_custom_recipe_enabled")
      : t("lut_info_custom_recipe_disabled"),
  ];
  if (capabilityLabels.length > 0) {
    summary.push(
      `${t("lut_info_capabilities_label")}: ${capabilityLabels.join(", ")}`,
    );
  }
  if ((info.supported_modes ?? []).length > 0) {
    summary.push(
      `${t("lut_info_supported_modes_label")}: ${(info.supported_modes ?? [])
        .map((mode) => `${mode.color_layers}L@${mode.layer_height_mm.toFixed(2)}mm`)
        .join(", ")}`,
    );
  }
  return summary.join(" | ");
}

export default function LutManagerPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const readOnly = useMlsReadOnly();
  const {
    lutList,
    lutListLoading,
    primaryName,
    primaryInfo,
    primaryLoading,
    secondaryNames,
    secondaryInfos,
    filteredSecondaryOptions,
    dedupThreshold,
    merging,
    mergeResult,
    error,
    fetchLutList,
    selectPrimary,
    setSecondaryNames,
    setDedupThreshold,
    executeMerge,
    clearError,
  } = useLutManagerStore();

  useEffect(() => {
    void fetchLutList();
  }, [fetchLutList]);

  const allDisabled = merging;

  const primaryOptions = lutList.map((lut) => ({
    label: lut.name,
    value: lut.name,
  }));

  const isPrimaryModeInvalid =
    primaryInfo !== null &&
    !primaryInfo.color_mode.startsWith("6-Color") &&
    !primaryInfo.color_mode.startsWith("8-Color");

  const mergeDisabled =
    merging ||
    !primaryName ||
    secondaryNames.length === 0 ||
    isPrimaryModeInvalid;

  const handleSecondaryToggle = (name: string) => {
    if (allDisabled) return;
    const updated = secondaryNames.includes(name)
      ? secondaryNames.filter((n) => n !== name)
      : [...secondaryNames, name];
    setSecondaryNames(updated);
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="lut-manager-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
      >
      <div className={resolveDesktopSplitLayoutClass(workspace.mode)}>
          <div className={desktopPrimaryColumnClass}>
           <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`} data-testid="primary-dropdown">
            <Dropdown
              label={t("lut_manager_primary_label")}
              value={primaryName}
              options={primaryOptions}
              onChange={(v) => void selectPrimary(v)}
              disabled={allDisabled || lutListLoading}
              placeholder={t("lut_manager_primary_placeholder")}
            />
            {primaryLoading && (
              <StatusBanner data-testid="loading-indicator" tone="info">
                {t("lut_manager_loading")}
              </StatusBanner>
            )}
            {primaryInfo && (
              <div className="rounded-2xl border border-slate-200/80 bg-slate-100/70 px-3 py-2 text-sm text-slate-600 dark:border-slate-700/80 dark:bg-slate-900/55 dark:text-slate-300">
                <div>
                  {t("lut_manager_mode_summary")
                    .replace("{mode}", primaryInfo.color_mode)
                    .replace("{count}", String(primaryInfo.color_count))}
                </div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {renderLutInfoDetail(primaryInfo, t)}
                </div>
              </div>
            )}
            {isPrimaryModeInvalid && (
              <StatusBanner tone="warning">{t("lut_manager_primary_mode_invalid")}</StatusBanner>
            )}
          </section>

           <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <Slider
              label={t("lut_manager_dedup_label")}
              tooltip={t("lut_manager_dedup_hint")}
              value={dedupThreshold}
              min={0}
              max={20}
              step={0.5}
              onChange={setDedupThreshold}
              disabled={allDisabled}
            />
          </section>

          <Button
            label={t("lut_manager_merge_btn")}
            variant="primary"
            onClick={() => void executeMerge()}
            disabled={mergeDisabled}
            loading={merging}
            className={`w-full xl:w-auto ${readOnly ? "hidden" : ""}`}
          />

          {mergeResult && (
            <StatusBanner data-testid="merge-result" tone="success" title={t("lut_manager_merge_success")}>
              <p>
                {t("lut_manager_merge_before")}: {mergeResult.stats.total_before} → {t("lut_manager_merge_after")}: {mergeResult.stats.total_after}
              </p>
              <p>
                {t("lut_manager_exact_dupes")}: {mergeResult.stats.exact_dupes} | {t("lut_manager_similar_removed")}: {mergeResult.stats.similar_removed}
              </p>
              <p>{t("lut_manager_file")}: {mergeResult.filename}</p>
            </StatusBanner>
          )}

          {error && (
            <StatusBanner
              data-testid="error-message"
              tone="error"
              action={
                <button
                  onClick={clearError}
                  className="rounded-full border border-current/20 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-300"
                  aria-label={t("lut_manager_close_error")}
                >
                  ×
                </button>
              }
            >
              {error}
            </StatusBanner>
          )}
        </div>

        <div className={desktopSecondaryColumnClass}>
           <section data-testid="secondary-list" className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <div className="flex items-center justify-between gap-3">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-200">{t("lut_manager_secondary_label")}</label>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {t("lut_manager_selected_count").replace("{count}", String(secondaryNames.length))}
              </span>
            </div>
            <div className="max-h-64 overflow-y-auto rounded-[24px] border border-slate-200/80 bg-slate-100/70 p-2 shadow-[var(--shadow-control)] xl:max-h-[70vh] dark:border-slate-700/80 dark:bg-slate-900/55">
              {filteredSecondaryOptions.length === 0 ? (
                <p className="px-2 py-3 text-sm text-slate-500 dark:text-slate-400">
                  {primaryName ? t("lut_manager_no_secondary") : t("lut_manager_select_primary_first")}
                </p>
              ) : (
                filteredSecondaryOptions.map((name) => {
                  const info = secondaryInfos.get(name);
                  return (
                    <label
                      key={name}
                      className="flex cursor-pointer items-center gap-3 rounded-2xl px-3 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-100/80 dark:text-slate-200 dark:hover:bg-slate-900/75"
                    >
                      <input
                        type="checkbox"
                        checked={secondaryNames.includes(name)}
                        onChange={() => handleSecondaryToggle(name)}
                        disabled={allDisabled}
                        className="h-4 w-4 rounded border-slate-300 bg-slate-100 accent-blue-500 dark:border-slate-600 dark:bg-slate-800"
                      />
                      <span className="truncate">{name}</span>
                      {info && (
                        <span className="ml-auto shrink-0 text-right text-xs text-slate-500 dark:text-slate-400">
                          <span>{info.color_mode} ({info.color_count})</span>
                          <span className="block">
                            {renderLutInfoDetail(info, t)}
                          </span>
                        </span>
                      )}
                    </label>
                  );
                })
              )}
            </div>
          </section>
        </div>
      </div>
    </motion.aside>
  );
}
