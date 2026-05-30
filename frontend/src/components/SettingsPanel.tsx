/**
 * SettingsPanel - System settings page.
 * 系统设置页面，包含切片软件设置和缓存清理功能。
 */

import { motion } from "framer-motion";
import { useState, useEffect } from "react";
import { useI18n } from "../i18n/context";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { clearCache, getPrinters, getSlicers } from "../api/system";
import {
  SVG_PIXELS_PER_MM_DEFAULT,
  SVG_PIXELS_PER_MM_MAX,
  SVG_PIXELS_PER_MM_MIN,
  SVG_PIXELS_PER_MM_STEP,
  SOLVER_CACHE_GRID_RESOLUTIONS,
  MLS_DEFAULT_BASE_URL,
  MLS_DEFAULT_BACKEND_URL,
  useSettingsStore,
  type SolverCacheGridResolution,
} from "../stores/settingsStore";
import { useSlicerStore } from "../stores/slicerStore";
import type { PrinterInfo, SlicerOption } from "../api/types";
import {
  filterCompatiblePrinters,
  isBambuFamilySlicer,
  resolveNozzleSizeOption,
  resolvePrinterOptionId,
  resolveSlicerOptionId,
} from "../utils/settingsOptionIds";
import { retryAsync } from "../utils/retryAsync";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Switch from "./ui/Switch";
import WikiTooltip from "./ui/WikiTooltip";
import {
  PanelIntro,
  StatusBanner,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
  workstationInputClass,
} from "./ui/panelPrimitives";

const SETTINGS_OPTIONS_RETRY_ATTEMPTS = 6;
const SETTINGS_OPTIONS_RETRY_DELAY_MS = 1000;

export default function SettingsPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();

  const [clearing, setClearing] = useState(false);
  const [cacheResult, setCacheResult] = useState<string | null>(null);
  const [customSlicerPathInput, setCustomSlicerPathInput] = useState("");
  const [mlsBaseUrlInput, setMlsBaseUrlInput] = useState("");
  const [mlsBackendUrlInput, setMlsBackendUrlInput] = useState("");

  // Printer list state (task 5.2)
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [printersLoading, setPrintersLoading] = useState(true);

  // Slicer list state
  const [slicers, setSlicers] = useState<SlicerOption[]>([]);
  const [slicersLoading, setSlicersLoading] = useState(true);

  // Store state (task 5.3)
  const printerModel = useSettingsStore((s) => s.printerModel);
  const setPrinterModel = useSettingsStore((s) => s.setPrinterModel);
  const slicerSoftware = useSettingsStore((s) => s.slicerSoftware);
  const setSlicerSoftware = useSettingsStore((s) => s.setSlicerSoftware);
  const customSlicerPath = useSettingsStore((s) => s.customSlicerPath);
  const nozzleSize = useSettingsStore((s) => s.nozzleSize);
  const setNozzleSize = useSettingsStore((s) => s.setNozzleSize);
  const enableBaseLayerHeightModifier = useSettingsStore(
    (s) => s.enableBaseLayerHeightModifier,
  );
  const setEnableBaseLayerHeightModifier = useSettingsStore(
    (s) => s.setEnableBaseLayerHeightModifier,
  );
  const setLastBedLabel = useSettingsStore((s) => s.setLastBedLabel);
  const syncToBackend = useSettingsStore((s) => s.syncToBackend);
  const enableWittyLoading = useSettingsStore((s) => s.enableWittyLoading);
  const setEnableWittyLoading = useSettingsStore((s) => s.setEnableWittyLoading);
  const enableSolverCacheGridSelection = useSettingsStore(
    (s) => s.enableSolverCacheGridSelection,
  );
  const setEnableSolverCacheGridSelection = useSettingsStore(
    (s) => s.setEnableSolverCacheGridSelection,
  );
  const solverCacheGridResolution = useSettingsStore(
    (s) => s.solverCacheGridResolution,
  );
  const setSolverCacheGridResolution = useSettingsStore(
    (s) => s.setSolverCacheGridResolution,
  );
  const svgPixelsPerMm = useSettingsStore((s) => s.svgPixelsPerMm);
  const setSvgPixelsPerMm = useSettingsStore((s) => s.setSvgPixelsPerMm);
  const resetSvgPixelsPerMm = useSettingsStore(
    (s) => s.resetSvgPixelsPerMm,
  );
  const autoReplaceGradientBanding = useSettingsStore(
    (s) => s.autoReplaceGradientBanding,
  );
  const setAutoReplaceGradientBanding = useSettingsStore(
    (s) => s.setAutoReplaceGradientBanding,
  );
  const mlsEnabled = useSettingsStore((s) => s.mlsEnabled);
  const setMlsEnabled = useSettingsStore((s) => s.setMlsEnabled);
  const mlsBaseUrl = useSettingsStore((s) => s.mlsBaseUrl);
  const setMlsBaseUrl = useSettingsStore((s) => s.setMlsBaseUrl);
  const mlsBackendUrl = useSettingsStore((s) => s.mlsBackendUrl);
  const setMlsBackendUrl = useSettingsStore((s) => s.setMlsBackendUrl);
  const isValidatingCustomPath = useSlicerStore(
    (s) => s.isValidatingCustomPath,
  );
  const customPathMessage = useSlicerStore((s) => s.customPathMessage);
  const customPathError = useSlicerStore((s) => s.customPathError);
  const validateAndSaveCustomSlicerPath = useSlicerStore(
    (s) => s.validateAndSaveCustomSlicerPath,
  );
  const clearCustomSlicerPath = useSlicerStore((s) => s.clearCustomSlicerPath);

  useEffect(() => {
    setCustomSlicerPathInput(customSlicerPath);
  }, [customSlicerPath]);

  useEffect(() => {
    setMlsBaseUrlInput(mlsBaseUrl);
  }, [mlsBaseUrl]);

  useEffect(() => {
    setMlsBackendUrlInput(mlsBackendUrl);
  }, [mlsBackendUrl]);

  // Load printers and slicers on mount
  useEffect(() => {
    let cancelled = false;
    setPrintersLoading(true);
    setSlicersLoading(true);

    void retryAsync(getPrinters, {
      attempts: SETTINGS_OPTIONS_RETRY_ATTEMPTS,
      delayMs: SETTINGS_OPTIONS_RETRY_DELAY_MS,
    })
      .then((list) => {
        if (!cancelled) setPrinters(list);
      })
      .catch((error) => {
        console.warn("[SettingsPanel] Failed to load printer options", error);
      })
      .finally(() => {
        if (!cancelled) setPrintersLoading(false);
      });

    void retryAsync(getSlicers, {
      attempts: SETTINGS_OPTIONS_RETRY_ATTEMPTS,
      delayMs: SETTINGS_OPTIONS_RETRY_DELAY_MS,
    })
      .then((list) => {
        if (!cancelled) setSlicers(list);
      })
      .catch((error) => {
        console.warn("[SettingsPanel] Failed to load slicer options", error);
      })
      .finally(() => {
        if (!cancelled) setSlicersLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  const resolvedSlicerSoftware = resolveSlicerOptionId(slicerSoftware, slicers);
  const resolvedPrinterModel = resolvePrinterOptionId(
    printerModel,
    printers,
    resolvedSlicerSoftware
  );

  useEffect(() => {
    if (slicersLoading || printersLoading || slicers.length === 0 || printers.length === 0) {
      return;
    }

    const nextSlicer = resolveSlicerOptionId(slicerSoftware, slicers);
    const nextPrinter = resolvePrinterOptionId(printerModel, printers, nextSlicer);
    const nextPrinterInfo = printers.find((printer) => printer.id === nextPrinter);
    const nextNozzleSize = resolveNozzleSizeOption(nozzleSize, nextPrinterInfo);

    let didNormalize = false;

    if (nextSlicer && nextSlicer !== slicerSoftware) {
      setSlicerSoftware(nextSlicer);
      didNormalize = true;
    }

    if (nextPrinter && nextPrinter !== printerModel) {
      setPrinterModel(nextPrinter);
      if (nextPrinterInfo) {
        setLastBedLabel(`${nextPrinterInfo.bed_width}×${nextPrinterInfo.bed_depth} mm`);
      }
      didNormalize = true;
    }

    if (nextNozzleSize !== nozzleSize) {
      setNozzleSize(nextNozzleSize as "0.2" | "0.4");
      didNormalize = true;
    }

    if (didNormalize) {
      void syncToBackend();
    }
  }, [
    printerModel,
    printers,
    printersLoading,
    setLastBedLabel,
    setPrinterModel,
    setNozzleSize,
    setSlicerSoftware,
    nozzleSize,
    slicerSoftware,
    slicers,
    slicersLoading,
    syncToBackend,
  ]);

  // Filter printers by selected slicer
  const filteredPrinters = filterCompatiblePrinters(printers, resolvedSlicerSoftware);

  // Handle printer selection change (task 5.3 + 6.1)
  const handlePrinterChange = (id: string) => {
    setPrinterModel(id);
    const selected = printers.find((p) => p.id === id);
    if (selected) {
      setLastBedLabel(`${selected.bed_width}×${selected.bed_depth} mm`);
      const nextNozzleSize = resolveNozzleSizeOption(nozzleSize, selected);
      if (nextNozzleSize !== nozzleSize) {
        setNozzleSize(nextNozzleSize as "0.2" | "0.4");
      }
    }
    syncToBackend();
  };

  // Handle slicer selection change — auto-select first compatible printer
  const handleSlicerChange = (id: string) => {
    setSlicerSoftware(id);
    // If current printer doesn't support the new slicer, switch to first compatible
    const compatible = filterCompatiblePrinters(printers, id);
    const currentStillValid = compatible.some((p) => p.id === resolvedPrinterModel);
    if (!currentStillValid && compatible.length > 0) {
      setPrinterModel(compatible[0].id);
      setLastBedLabel(
        `${compatible[0].bed_width}×${compatible[0].bed_depth} mm`
      );
    }
    const resolvedPrinter =
      compatible.find((p) => p.id === resolvedPrinterModel) ?? compatible[0];
    const nextNozzleSize = resolveNozzleSizeOption(nozzleSize, resolvedPrinter);
    if (nextNozzleSize !== nozzleSize) {
      setNozzleSize(nextNozzleSize as "0.2" | "0.4");
    }
    syncToBackend();
  };

  const handleNozzleSizeChange = (value: string) => {
    setNozzleSize(value as "0.2" | "0.4");
    void syncToBackend();
  };

  const handleSaveCustomSlicerPath = () => {
    void validateAndSaveCustomSlicerPath(customSlicerPathInput);
  };

  const handleClearCustomSlicerPath = () => {
    setCustomSlicerPathInput("");
    clearCustomSlicerPath();
  };

  const resolvedMlsBaseUrl = (mlsBaseUrl || MLS_DEFAULT_BASE_URL).replace(/\/+$/, "");

  const handleSaveMlsBaseUrl = () => {
    const trimmed = mlsBaseUrlInput.trim();
    setMlsBaseUrl(trimmed || MLS_DEFAULT_BASE_URL);
  };

  const handleSaveMlsBackendUrl = () => {
    const trimmed = mlsBackendUrlInput.trim();
    setMlsBackendUrl(trimmed || MLS_DEFAULT_BACKEND_URL);
  };

  const handleOpenMls = () => {
    const target = (mlsBaseUrlInput.trim() || resolvedMlsBaseUrl).replace(/\/+$/, "");
    window.open(target, "_blank", "noopener,noreferrer");
  };

  const selectedPrinter = printers.find((p) => p.id === resolvedPrinterModel);

  const handleClearCache = async () => {
    setClearing(true);
    setCacheResult(null);
    try {
      const res = await clearCache();
      const size = res.freed_bytes < 1024 * 1024
        ? `${(res.freed_bytes / 1024).toFixed(1)} KB`
        : `${(res.freed_bytes / (1024 * 1024)).toFixed(1)} MB`;
      setCacheResult(
        t("settings.cache_cleared_detail")
          .replace("{count}", String(res.deleted_files))
          .replace("{size}", size)
      );
    } catch {
      setCacheResult(t("settings.cache_clear_failed"));
    } finally {
      setClearing(false);
    }
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="settings-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
      >
      <PanelIntro
        eyebrow={t("tab.settings")}
        title={t("settings.title")}
        description={t("settings.desc")}
      />

      <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
            {t("settings.slicer_settings")}
          </p>
          <h4 className="mt-1 text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("settings.printer_model")}
          </h4>
        </div>
        <div className={`grid gap-4 ${workspace.isCompact ? "" : "xl:grid-cols-3"}`}>
          <div>
            <Dropdown
              label={t("settings.slicer_software")}
              value={resolvedSlicerSoftware}
              onChange={handleSlicerChange}
              disabled={slicersLoading}
              options={slicers.map((s) => ({
                label: s.display_name,
                value: s.id,
              }))}
            />
          </div>
          <div>
            <Dropdown
              label={t("settings.printer_model")}
              value={resolvedPrinterModel}
              onChange={handlePrinterChange}
              disabled={printersLoading}
              options={filteredPrinters.map((p) => ({
                label: p.display_name,
                value: p.id,
              }))}
            />
          </div>
          <div>
            <Dropdown
              label={t("settings.nozzle_size")}
              value={resolveNozzleSizeOption(nozzleSize, selectedPrinter)}
              onChange={handleNozzleSizeChange}
              disabled={printersLoading || !selectedPrinter}
              options={(selectedPrinter?.supported_nozzle_sizes ?? ["0.2", "0.4"]).map((size) => ({
                label: `${size} mm`,
                value: size,
              }))}
            />
          </div>
        </div>
        {selectedPrinter && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
            <span>
              {t("settings.bed_size")}: {selectedPrinter.bed_width}&times;{selectedPrinter.bed_depth} {t("common_unit_mm")}
            </span>
            <span className="text-slate-300 dark:text-slate-600">|</span>
            <span>
              {t("settings.nozzle_size")}: {resolveNozzleSizeOption(nozzleSize, selectedPrinter)} {t("common_unit_mm")}
            </span>
          </div>
        )}
        <div className="flex flex-col gap-3 border-t border-slate-200/60 pt-4 dark:border-slate-700/60">
          <div>
            <label
              htmlFor="custom-slicer-path"
              className="text-sm font-medium text-slate-900 dark:text-slate-50"
            >
              {t("settings.custom_slicer_path")}
            </label>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {t("settings.custom_slicer_path_help")}
            </p>
          </div>
          <div className={`grid gap-3 ${workspace.isCompact ? "" : "lg:grid-cols-[minmax(0,1fr)_auto_auto]"}`}>
            <input
              id="custom-slicer-path"
              value={customSlicerPathInput}
              onChange={(event) => setCustomSlicerPathInput(event.target.value)}
              placeholder={t("settings.custom_slicer_path_placeholder")}
              className={workstationInputClass}
            />
            <Button
              label={t("settings.custom_slicer_save")}
              onClick={handleSaveCustomSlicerPath}
              loading={isValidatingCustomPath}
              disabled={!customSlicerPathInput.trim()}
              className={workspace.isCompact ? "w-full" : ""}
            />
            <Button
              label={t("settings.custom_slicer_clear")}
              onClick={handleClearCustomSlicerPath}
              variant="secondary"
              disabled={!customSlicerPath && !customSlicerPathInput}
              className={workspace.isCompact ? "w-full" : ""}
            />
          </div>
          {customPathMessage && (
            <p className="text-xs text-emerald-600 dark:text-emerald-400">
              {customPathMessage}
            </p>
          )}
          {customPathError && (
            <p className="text-xs text-red-500 dark:text-red-400">
              {customPathError}
            </p>
          )}
        </div>
        {isBambuFamilySlicer(resolvedSlicerSoftware) && (
          <div
            data-testid="base-layer-height-modifier-row"
            className="flex items-center justify-between gap-3 border-t border-slate-200/60 pt-4 dark:border-slate-700/60"
          >
            <span className="text-sm font-medium text-slate-900 dark:text-slate-50">
              {t("settings.base_layer_height_modifier")}
            </span>
            <WikiTooltip
              title={t("settings.base_layer_height_modifier")}
              description={t("settings.base_layer_height_modifier_desc")}
              placement="left"
            >
              <Switch
                checked={enableBaseLayerHeightModifier}
                onChange={(enabled) => {
                  setEnableBaseLayerHeightModifier(enabled);
                  void syncToBackend();
                }}
                ariaLabel={t("settings.base_layer_height_modifier")}
              />
            </WikiTooltip>
          </div>
        )}
      </section>

      <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
            {t("settings.maintenance")}
          </p>
          <h4 className="mt-1 text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("settings.cache")}
          </h4>
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t("settings.cache_summary")}
        </p>
        <StatusBanner tone="info">{t("settings.clear_cache_desc")}</StatusBanner>
        <div className="flex items-center gap-3">
          <Button
            label={t("settings.clear_cache")}
            onClick={handleClearCache}
            loading={clearing}
            variant="secondary"
          />
        </div>
        {cacheResult && (
          <StatusBanner tone={cacheResult === t("settings.cache_clear_failed") ? "error" : "success"}>
            {cacheResult}
          </StatusBanner>
        )}
      </section>

      <section
        data-testid="settings-advanced-section"
        className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-5`}
      >
        <div>
          <h4 className="text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("settings.advanced")}
          </h4>
        </div>

        <div
          data-testid="settings-solver-cache-density-section"
          className="flex flex-col gap-4"
        >
          <div>
            <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
              {t("settings.solver_cache_density_heading")}
            </h5>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t("settings.solver_cache_density_description")}
            </p>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-slate-900 dark:text-slate-50">
              {t("settings.solver_cache_density_enable_label")}
            </span>
            <WikiTooltip
              title={t("settings.solver_cache_density_enable_label")}
              description={t("settings.solver_cache_density_tip")}
              placement="left"
            >
              <Switch
                checked={enableSolverCacheGridSelection}
                onChange={setEnableSolverCacheGridSelection}
                ariaLabel={t("settings.solver_cache_density_enable_label")}
              />
            </WikiTooltip>
          </div>
          {enableSolverCacheGridSelection ? (
            <div
              data-testid="settings-solver-cache-density-dropdown-row"
              className="border-t border-slate-200/60 pt-4 dark:border-slate-700/60"
            >
              <Dropdown
                label={t("settings.solver_cache_density_select_label")}
                value={String(solverCacheGridResolution)}
                onChange={(value) =>
                  setSolverCacheGridResolution(
                    Number(value) as SolverCacheGridResolution,
                  )
                }
                options={SOLVER_CACHE_GRID_RESOLUTIONS.map((grid) => ({
                  value: String(grid),
                  label: t(`settings.solver_cache_density_option_${grid}`),
                }))}
              />
              <StatusBanner tone="info">
                {t("settings.solver_cache_density_tip")}
              </StatusBanner>
            </div>
          ) : (
            <StatusBanner tone="info">
              {t("settings.solver_cache_density_default_hint")}
            </StatusBanner>
          )}
        </div>

        <div
          data-testid="settings-svg-raster-density-section"
          className="flex flex-col gap-4 border-t border-slate-200/60 pt-5 dark:border-slate-700/60"
        >
          <div>
            <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
              {t("settings.svg_pixels_per_mm_heading")}
            </h5>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t("settings.svg_pixels_per_mm_description")}
            </p>
          </div>
          <div className="grid gap-3 min-[960px]:grid-cols-[minmax(0,1fr)_max-content]">
            <Slider
              label={t("settings.svg_pixels_per_mm_label")}
              tooltip={t("settings.svg_pixels_per_mm_tip")}
              value={svgPixelsPerMm}
              min={SVG_PIXELS_PER_MM_MIN}
              max={SVG_PIXELS_PER_MM_MAX}
              step={SVG_PIXELS_PER_MM_STEP}
              displayDecimals={1}
              minInputWidthCh={4}
              unit={t("common_unit_px_per_mm")}
              onChange={setSvgPixelsPerMm}
            />
            <Button
              label={t("settings.svg_pixels_per_mm_reset")}
              onClick={resetSvgPixelsPerMm}
              variant="secondary"
              disabled={svgPixelsPerMm === SVG_PIXELS_PER_MM_DEFAULT}
              className="w-full min-[960px]:w-auto min-[960px]:min-w-max min-[960px]:self-end"
            />
          </div>
          <StatusBanner tone="info">
            {t("settings.svg_pixels_per_mm_default_hint")}
          </StatusBanner>
        </div>

        <div
          data-testid="settings-auto-replace-gradient-section"
          className="flex flex-col gap-4 border-t border-slate-200/60 pt-5 dark:border-slate-700/60"
        >
          <div>
            <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
              {t("settings.auto_replace_gradient_heading")}
            </h5>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t("settings.auto_replace_gradient_description")}
            </p>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-slate-900 dark:text-slate-50">
              {t("settings.auto_replace_gradient_label")}
            </span>
            <WikiTooltip
              title={t("settings.auto_replace_gradient_label")}
              description={t("settings.auto_replace_gradient_tip")}
              placement="left"
            >
              <Switch
                checked={autoReplaceGradientBanding}
                onChange={setAutoReplaceGradientBanding}
                ariaLabel={t("settings.auto_replace_gradient_label")}
              />
            </WikiTooltip>
          </div>
          {!autoReplaceGradientBanding && (
            <StatusBanner tone="info">
              {t("settings.auto_replace_gradient_default_hint")}
            </StatusBanner>
          )}
        </div>
      </section>

      <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
            {t("settings.maintenance")}
          </p>
          <h4 className="mt-1 text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("settings.witty_loading")}
          </h4>
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t("settings.witty_loading_desc")}
        </p>
        <div className="flex items-center gap-3">
          <Switch
            checked={enableWittyLoading}
            onChange={setEnableWittyLoading}
            ariaLabel={t("settings.witty_loading")}
          />
        </div>
      </section>

      <section
        data-testid="settings-mls-section"
        className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}
      >
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
            {t("settings.advanced")}
          </p>
          <h4 className="mt-1 text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("settings.mls_heading")}
          </h4>
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t("settings.mls_description")}
        </p>
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-slate-900 dark:text-slate-50">
            {t("settings.mls_enable_label")}
          </span>
          <WikiTooltip
            title={t("settings.mls_enable_label")}
            description={t("settings.mls_enable_tip")}
            placement="left"
          >
            <Switch
              checked={mlsEnabled}
              onChange={setMlsEnabled}
              ariaLabel={t("settings.mls_enable_label")}
            />
          </WikiTooltip>
        </div>
        {mlsEnabled ? (
          <div className="flex flex-col gap-3 border-t border-slate-200/60 pt-4 dark:border-slate-700/60">
            <div>
              <label
                htmlFor="mls-base-url"
                className="text-sm font-medium text-slate-900 dark:text-slate-50"
              >
                {t("settings.mls_base_url_label")}
              </label>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {t("settings.mls_base_url_help")}
              </p>
            </div>
            <div className={`grid gap-3 ${workspace.isCompact ? "" : "lg:grid-cols-[minmax(0,1fr)_auto_auto]"}`}>
              <input
                id="mls-base-url"
                value={mlsBaseUrlInput}
                onChange={(event) => setMlsBaseUrlInput(event.target.value)}
                onBlur={handleSaveMlsBaseUrl}
                placeholder={t("settings.mls_base_url_placeholder")}
                className={workstationInputClass}
              />
              <Button
                label={t("settings.custom_slicer_save")}
                onClick={handleSaveMlsBaseUrl}
                variant="secondary"
                disabled={mlsBaseUrlInput.trim() === mlsBaseUrl}
                className={workspace.isCompact ? "w-full" : ""}
              />
              <Button
                label={t("settings.mls_open_button")}
                onClick={handleOpenMls}
                className={workspace.isCompact ? "w-full" : ""}
              />
            </div>

            <div className="border-t border-slate-200/60 pt-3 dark:border-slate-700/60">
              <label
                htmlFor="mls-backend-url"
                className="text-sm font-medium text-slate-900 dark:text-slate-50"
              >
                {t("settings.mls_backend_url_label")}
              </label>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {t("settings.mls_backend_url_help")}
              </p>
            </div>
            <div className={`grid gap-3 ${workspace.isCompact ? "" : "lg:grid-cols-[minmax(0,1fr)_auto]"}`}>
              <input
                id="mls-backend-url"
                value={mlsBackendUrlInput}
                onChange={(event) => setMlsBackendUrlInput(event.target.value)}
                onBlur={handleSaveMlsBackendUrl}
                placeholder={t("settings.mls_backend_url_placeholder")}
                className={workstationInputClass}
              />
              <Button
                label={t("settings.custom_slicer_save")}
                onClick={handleSaveMlsBackendUrl}
                variant="secondary"
                disabled={mlsBackendUrlInput.trim() === mlsBackendUrl}
                className={workspace.isCompact ? "w-full" : ""}
              />
            </div>
          </div>
        ) : (
          <StatusBanner tone="info">
            {t("settings.mls_disabled_hint")}
          </StatusBanner>
        )}
      </section>
    </motion.aside>
  );
}
