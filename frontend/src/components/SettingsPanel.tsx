/**
 * SettingsPanel - System settings page.
 * 系统设置页面，包含切片软件设置和缓存清理功能。
 */

import { motion } from "framer-motion";
import { useState, useEffect, useCallback } from "react";
import { useI18n } from "../i18n/context";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { apiErrorToVisibleMessage } from "../api/client";
import { clearCache, getMachineRegistryAssetUrl, getPrinters, getSlicers } from "../api/system";
import {
  SVG_PIXELS_PER_MM_DEFAULT,
  SVG_PIXELS_PER_MM_MAX,
  SVG_PIXELS_PER_MM_MIN,
  SVG_PIXELS_PER_MM_STEP,
  SOLVER_CACHE_GRID_RESOLUTIONS,
  useSettingsStore,
  type SolverCacheGridResolution,
} from "../stores/settingsStore";
import { useSlicerStore } from "../stores/slicerStore";
import type { PrinterInfo, SlicerOption } from "../api/types";
import {
  filterCompatiblePrinters,
  getDetectedSlicerIdForSoftware,
  getPrinterNozzleSizeOptions,
  resolveDeviceProfileOptionId,
  resolveNozzleSizeOption,
  resolvePrinterOptionId,
  resolveSlicerOptionId,
  supportsLayerConfigRanges,
} from "../utils/settingsOptionIds";
import { retryAsync } from "../utils/retryAsync";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Switch from "./ui/Switch";
import WikiTooltip from "./ui/WikiTooltip";
import {
  cx,
  PanelIntro,
  StatusBanner,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
  workstationInputClass,
} from "./ui/panelPrimitives";

const SETTINGS_OPTIONS_RETRY_ATTEMPTS = 6;
const SETTINGS_OPTIONS_RETRY_DELAY_MS = 1000;
const SETTINGS_OPTIONS_NOT_CANCELLED = () => false;

type CancellationCheck = () => boolean;

function formatSettingsOptionsLoadError(template: string, error: unknown): string {
  return template.replace("{error}", apiErrorToVisibleMessage(error));
}

function getMachinePlaceholderLabel(printer: PrinterInfo): string {
  const compactBrand = printer.brand.replace(/\s+/g, "");
  return (compactBrand || printer.display_name).slice(0, 2).toUpperCase();
}

export default function SettingsPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();

  const [clearing, setClearing] = useState(false);
  const [cacheResult, setCacheResult] = useState<string | null>(null);
  const [customSlicerPathInput, setCustomSlicerPathInput] = useState("");

  // Printer list state (task 5.2)
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [printersLoading, setPrintersLoading] = useState(true);
  const [printerOptionsError, setPrinterOptionsError] = useState<string | null>(null);

  // Slicer list state
  const [slicers, setSlicers] = useState<SlicerOption[]>([]);
  const [slicersLoading, setSlicersLoading] = useState(true);
  const [slicerOptionsError, setSlicerOptionsError] = useState<string | null>(null);

  // Store state (task 5.3)
  const printerModel = useSettingsStore((s) => s.printerModel);
  const setPrinterModel = useSettingsStore((s) => s.setPrinterModel);
  const slicerSoftware = useSettingsStore((s) => s.slicerSoftware);
  const setSlicerSoftware = useSettingsStore((s) => s.setSlicerSoftware);
  const deviceProfileId = useSettingsStore((s) => s.deviceProfileId);
  const setDeviceProfileId = useSettingsStore((s) => s.setDeviceProfileId);
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
  const isValidatingCustomPath = useSlicerStore(
    (s) => s.isValidatingCustomPath,
  );
  const detectedSlicers = useSlicerStore((s) => s.slicers);
  const selectedDetectedSlicerId = useSlicerStore((s) => s.selectedSlicerId);
  const setSelectedDetectedSlicerId = useSlicerStore((s) => s.setSelectedSlicerId);
  const customPathMessage = useSlicerStore((s) => s.customPathMessage);
  const customPathError = useSlicerStore((s) => s.customPathError);
  const validateAndSaveCustomSlicerPath = useSlicerStore(
    (s) => s.validateAndSaveCustomSlicerPath,
  );
  const clearCustomSlicerPath = useSlicerStore((s) => s.clearCustomSlicerPath);

  useEffect(() => {
    setCustomSlicerPathInput(customSlicerPath);
  }, [customSlicerPath]);

  const loadPrinterOptions = useCallback(async (
    isCancelled: CancellationCheck = SETTINGS_OPTIONS_NOT_CANCELLED,
  ) => {
    setPrintersLoading(true);
    setPrinterOptionsError(null);
    try {
      const list = await retryAsync(getPrinters, {
        attempts: SETTINGS_OPTIONS_RETRY_ATTEMPTS,
        delayMs: SETTINGS_OPTIONS_RETRY_DELAY_MS,
      });
      if (!isCancelled()) {
        setPrinters(list);
      }
    } catch (error) {
      console.warn("[SettingsPanel] Failed to load printer options", error);
      if (!isCancelled()) {
        setPrinterOptionsError(
          formatSettingsOptionsLoadError(t("settings.printer_options_load_failed"), error),
        );
      }
    } finally {
      if (!isCancelled()) {
        setPrintersLoading(false);
      }
    }
  }, [t]);

  const loadSlicerOptions = useCallback(async (
    isCancelled: CancellationCheck = SETTINGS_OPTIONS_NOT_CANCELLED,
  ) => {
    setSlicersLoading(true);
    setSlicerOptionsError(null);
    try {
      const list = await retryAsync(getSlicers, {
        attempts: SETTINGS_OPTIONS_RETRY_ATTEMPTS,
        delayMs: SETTINGS_OPTIONS_RETRY_DELAY_MS,
      });
      if (!isCancelled()) {
        setSlicers(list);
      }
    } catch (error) {
      console.warn("[SettingsPanel] Failed to load slicer options", error);
      if (!isCancelled()) {
        setSlicerOptionsError(
          formatSettingsOptionsLoadError(t("settings.slicer_options_load_failed"), error),
        );
      }
    } finally {
      if (!isCancelled()) {
        setSlicersLoading(false);
      }
    }
  }, [t]);

  // Load printers and slicers on mount.
  useEffect(() => {
    let cancelled = false;

    void loadPrinterOptions(() => cancelled);
    void loadSlicerOptions(() => cancelled);

    return () => { cancelled = true; };
  }, [loadPrinterOptions, loadSlicerOptions]);

  const resolvedSlicerSoftware = resolveSlicerOptionId(slicerSoftware, slicers);
  const resolvedPrinterModel = resolvePrinterOptionId(
    printerModel,
    printers,
    resolvedSlicerSoftware
  );
  const selectedPrinter = printers.find((p) => p.id === resolvedPrinterModel);
  const resolvedNozzleSize = resolveNozzleSizeOption(
    nozzleSize,
    selectedPrinter,
    resolvedSlicerSoftware,
  );
  const resolvedDeviceProfileId = resolveDeviceProfileOptionId(
    deviceProfileId,
    selectedPrinter,
    resolvedSlicerSoftware,
    resolvedNozzleSize,
  );
  const selectedDeviceProfile =
    selectedPrinter?.device_profiles?.find(
      (profile) => profile.device_profile_id === resolvedDeviceProfileId,
    ) ?? null;
  const selectedPrinterThumbnailUrl = getMachineRegistryAssetUrl(selectedPrinter?.thumbnail);

  useEffect(() => {
    if (slicersLoading || printersLoading || slicers.length === 0 || printers.length === 0) {
      return;
    }

    const nextSlicer = resolveSlicerOptionId(slicerSoftware, slicers);
    const nextPrinter = resolvePrinterOptionId(printerModel, printers, nextSlicer);
    const nextPrinterInfo = printers.find((printer) => printer.id === nextPrinter);
    const nextNozzleSize = resolveNozzleSizeOption(nozzleSize, nextPrinterInfo, nextSlicer);
    const nextDeviceProfileId = resolveDeviceProfileOptionId(
      deviceProfileId,
      nextPrinterInfo,
      nextSlicer,
      nextNozzleSize,
    );

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

    if (nextDeviceProfileId !== deviceProfileId) {
      setDeviceProfileId(nextDeviceProfileId);
      didNormalize = true;
    }

    if (didNormalize) {
      void syncToBackend();
    }
  }, [
    deviceProfileId,
    printerModel,
    printers,
    printersLoading,
    setDeviceProfileId,
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
      const nextNozzleSize = resolveNozzleSizeOption(nozzleSize, selected, resolvedSlicerSoftware);
      if (nextNozzleSize !== nozzleSize) {
        setNozzleSize(nextNozzleSize as "0.2" | "0.4");
      }
      const nextDeviceProfileId = resolveDeviceProfileOptionId(
        deviceProfileId,
        selected,
        resolvedSlicerSoftware,
        nextNozzleSize,
      );
      if (nextDeviceProfileId !== deviceProfileId) {
        setDeviceProfileId(nextDeviceProfileId);
      }
    }
    syncToBackend();
  };

  // Handle slicer selection change — auto-select first compatible printer
  const handleSlicerChange = (id: string) => {
    setSlicerSoftware(id);
    const preferredDetectedSlicerId = getDetectedSlicerIdForSoftware(id);
    const nextDetectedSlicerId =
      preferredDetectedSlicerId &&
      detectedSlicers.some((slicer) => slicer.id === preferredDetectedSlicerId)
        ? preferredDetectedSlicerId
        : null;
    if (nextDetectedSlicerId !== selectedDetectedSlicerId) {
      setSelectedDetectedSlicerId(nextDetectedSlicerId);
    }
    // If current printer doesn't support the new slicer, switch to first compatible
    const compatible = filterCompatiblePrinters(printers, id);
    const currentStillValid = compatible.some((p) => p.id === resolvedPrinterModel);
    let resolvedPrinter =
      compatible.find((p) => p.id === resolvedPrinterModel) ?? compatible[0];
    if (!currentStillValid && compatible.length > 0) {
      setPrinterModel(compatible[0].id);
      setLastBedLabel(
        `${compatible[0].bed_width}×${compatible[0].bed_depth} mm`
      );
      resolvedPrinter = compatible[0];
    }
    const nextNozzleSize = resolveNozzleSizeOption(nozzleSize, resolvedPrinter, id);
    if (nextNozzleSize !== nozzleSize) {
      setNozzleSize(nextNozzleSize as "0.2" | "0.4");
    }
    const nextDeviceProfileId = resolveDeviceProfileOptionId(
      deviceProfileId,
      resolvedPrinter,
      id,
      nextNozzleSize,
    );
    if (nextDeviceProfileId !== deviceProfileId) {
      setDeviceProfileId(nextDeviceProfileId);
    }
    syncToBackend();
  };

  const handlePrinterNozzleChange = (printer: PrinterInfo, value: string) => {
    if (printer.id !== printerModel) {
      setPrinterModel(printer.id);
      setLastBedLabel(`${printer.bed_width}×${printer.bed_depth} mm`);
    }
    if (value !== nozzleSize) {
      setNozzleSize(value as "0.2" | "0.4");
    }
    const nextDeviceProfileId = resolveDeviceProfileOptionId(
      deviceProfileId,
      printer,
      resolvedSlicerSoftware,
      value,
    );
    if (nextDeviceProfileId !== deviceProfileId) {
      setDeviceProfileId(nextDeviceProfileId);
    }
    void syncToBackend();
  };

  const handleSaveCustomSlicerPath = () => {
    void validateAndSaveCustomSlicerPath(customSlicerPathInput);
  };

  const handleClearCustomSlicerPath = () => {
    setCustomSlicerPathInput("");
    clearCustomSlicerPath();
  };

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
        {slicerOptionsError && (
          <StatusBanner
            role="alert"
            tone="error"
            action={(
              <Button
                label={t("widget_retry")}
                variant="secondary"
                size="sm"
                loading={slicersLoading}
                onClick={() => { void loadSlicerOptions(); }}
              />
            )}
          >
            {slicerOptionsError}
          </StatusBanner>
        )}
        {printerOptionsError && (
          <StatusBanner
            role="alert"
            tone="error"
            action={(
              <Button
                label={t("widget_retry")}
                variant="secondary"
                size="sm"
                loading={printersLoading}
                onClick={() => { void loadPrinterOptions(); }}
              />
            )}
          >
            {printerOptionsError}
          </StatusBanner>
        )}
        <div className="grid gap-4">
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
        </div>
        <div className="flex min-w-0 flex-col gap-2">
          <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {t("settings.printer_model")}
          </label>
          <div
            data-testid="machine-adapter-grid"
            className="grid max-h-[28rem] gap-3 overflow-y-auto pr-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
          >
            {filteredPrinters.map((printer) => {
              const isSelected = printer.id === resolvedPrinterModel;
              const thumbnailUrl = getMachineRegistryAssetUrl(printer.thumbnail);
              const nozzleOptions = getPrinterNozzleSizeOptions(printer, resolvedSlicerSoftware);

              return (
                <div
                  key={printer.id}
                  className={cx(
                    "group rounded-lg border bg-white/72 p-3 shadow-[var(--shadow-control)] transition-all duration-200 hover:border-blue-300 hover:bg-white/92 dark:bg-slate-900/60 dark:hover:bg-slate-900/82",
                    isSelected
                      ? "border-blue-400 ring-2 ring-blue-200/80 dark:border-blue-300 dark:ring-blue-500/20"
                      : "border-slate-200/80 dark:border-slate-700/80",
                  )}
                >
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    data-testid={`machine-adapter-card-${printer.id}`}
                    onClick={() => handlePrinterChange(printer.id)}
                    disabled={printersLoading}
                    className="grid w-full min-h-[7.25rem] grid-cols-[5.5rem_minmax(0,1fr)] gap-3 text-left outline-none transition-opacity disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <span className="flex h-24 w-[5.5rem] items-center justify-center overflow-hidden rounded-md border border-slate-200/70 bg-slate-100/80 dark:border-slate-700/70 dark:bg-slate-800/70">
                      {thumbnailUrl ? (
                        <img
                          src={thumbnailUrl}
                          alt={printer.display_name}
                          className="h-full w-full object-contain p-1.5"
                          loading="lazy"
                        />
                      ) : (
                        <span className="text-lg font-semibold text-slate-400 dark:text-slate-500">
                          {getMachinePlaceholderLabel(printer)}
                        </span>
                      )}
                    </span>
                    <span className="flex min-w-0 flex-col gap-1.5">
                      <span className="truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {printer.display_name}
                      </span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {printer.brand}
                      </span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {t("settings.bed_size")}: {printer.bed_width}&times;{printer.bed_depth} {t("common_unit_mm")}
                      </span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {t("settings.nozzle_size")}: {nozzleOptions.map((size) => `${size} ${t("common_unit_mm")}`).join(", ")}
                      </span>
                    </span>
                  </button>
                  <div className="mt-3 flex flex-wrap gap-1.5 border-t border-slate-200/70 pt-3 dark:border-slate-700/70">
                    {nozzleOptions.map((size) => {
                      const isNozzleSelected = isSelected && size === resolvedNozzleSize;
                      return (
                        <button
                          key={size}
                          type="button"
                          aria-pressed={isNozzleSelected}
                          aria-label={`${printer.display_name} ${size} ${t("common_unit_mm")}`}
                          data-testid={`machine-adapter-nozzle-${printer.id}-${size.replace(/\./g, "_")}`}
                          onClick={() => handlePrinterNozzleChange(printer, size)}
                          disabled={printersLoading}
                          className={cx(
                            "min-h-8 rounded-md border px-2.5 text-xs font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-45",
                            isNozzleSelected
                              ? "border-blue-400 bg-blue-50 text-blue-700 dark:border-blue-300 dark:bg-blue-500/15 dark:text-blue-200"
                              : "border-slate-200/80 bg-slate-50/80 text-slate-600 hover:border-blue-300 hover:text-blue-600 dark:border-slate-700/80 dark:bg-slate-800/72 dark:text-slate-300 dark:hover:border-blue-400 dark:hover:text-blue-200",
                          )}
                        >
                          {size} {t("common_unit_mm")}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        {selectedPrinter && (
          <div
            data-testid="machine-adapter-summary"
            className="flex min-w-0 items-center gap-3 text-xs text-slate-500 dark:text-slate-400"
          >
            {selectedPrinterThumbnailUrl && (
              <img
                src={selectedPrinterThumbnailUrl}
                alt=""
                className="h-16 w-16 shrink-0 object-contain"
                loading="lazy"
              />
            )}
            <div className="flex min-w-0 flex-col gap-1">
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-medium text-slate-700 dark:text-slate-200">
                  {selectedPrinter.display_name}
                </span>
                <span>
                  {t("settings.bed_size")}: {selectedPrinter.bed_width}&times;{selectedPrinter.bed_depth} {t("common_unit_mm")}
                </span>
                <span>
                  {t("settings.nozzle_size")}: {resolvedNozzleSize} {t("common_unit_mm")}
                </span>
              </div>
              {selectedDeviceProfile && (
                <span className="truncate">
                  {t("settings.device_profile")}: {selectedDeviceProfile.source_profile_name}
                </span>
              )}
            </div>
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
        {supportsLayerConfigRanges(resolvedSlicerSoftware) && (
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

    </motion.aside>
  );
}
