/**
 * SettingsPanel - System settings page.
 * 系统设置页面，包含切片软件设置和缓存清理功能。
 */

import { motion } from "framer-motion";
import { useState, useEffect } from "react";
import { useI18n } from "../i18n/context";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { clearCache, getPrinters, getSlicers } from "../api/system";
import { useSettingsStore } from "../stores/settingsStore";
import type { PrinterInfo, SlicerOption } from "../api/types";
import {
  filterCompatiblePrinters,
  resolveNozzleSizeOption,
  resolvePrinterOptionId,
  resolveSlicerOptionId,
} from "../utils/settingsOptionIds";
import { retryAsync } from "../utils/retryAsync";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import Switch from "./ui/Switch";
import { PanelIntro, StatusBanner, resolvePanelSurfaceClass, resolveSectionCardClass } from "./ui/panelPrimitives";

const SETTINGS_OPTIONS_RETRY_ATTEMPTS = 6;
const SETTINGS_OPTIONS_RETRY_DELAY_MS = 1000;

export default function SettingsPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();

  const [clearing, setClearing] = useState(false);
  const [cacheResult, setCacheResult] = useState<string | null>(null);

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
  const nozzleSize = useSettingsStore((s) => s.nozzleSize);
  const setNozzleSize = useSettingsStore((s) => s.setNozzleSize);
  const setLastBedLabel = useSettingsStore((s) => s.setLastBedLabel);
  const syncToBackend = useSettingsStore((s) => s.syncToBackend);
  const enableWittyLoading = useSettingsStore((s) => s.enableWittyLoading);
  const setEnableWittyLoading = useSettingsStore((s) => s.setEnableWittyLoading);

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
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
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
