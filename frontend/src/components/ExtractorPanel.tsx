import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useExtractorStore, ACCEPT_EXTRACTOR_FORMATS } from "../stores/extractorStore";
import { buildCornerLabels } from "./ExtractorCanvas";
import { useI18n } from "../i18n/context";
import {
  EXTRACTOR_EIGHT_COLOR_FULL_TOTAL_PAGES,
  ExtractorColorMode,
  ExtractorPage,
} from "../api/types";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Checkbox from "./ui/Checkbox";
import Button from "./ui/Button";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "./ui/icons";
import ImageUpload from "./ui/ImageUpload";
import Switch from "./ui/Switch";
import HelpDot from "./ui/HelpDot";
import { ColorcheckerConfirmDialogInner } from "./ColorcheckerConfirmDialog";
import {
  cx,
  StatusBanner,
  panelSurfaceClass,
  sectionCardClass,
} from "./ui/panelPrimitives";

const colorModeOptions = Object.values(ExtractorColorMode).map((v) => ({
  label: v,
  value: v,
}));

/** 常见 Bambu Lab 耗材类型 */
const MATERIAL_OPTIONS = [
  "PLA",
  "PETG",
];

const materialOptions = MATERIAL_OPTIONS.map((material) => ({
  label: material,
  value: material,
}));

const textInputClass =
  "min-h-10 w-full rounded-2xl border border-slate-200/80 bg-white/90 px-3 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-100";

function formatEightColorPageLabel(pageNumber: number, t: (key: string) => string): string {
  return `${t("ext_page_number_prefix")}${pageNumber}${t("ext_page_number_suffix")}`;
}

export default function ExtractorPanel() {
  const { t } = useI18n();
  const {
    color_mode,
    page,
    eight_color_full_export,
    imageFile,
    imagePreviewUrl,
    corner_points,
    nudge_step,
    active_corner_index,
    offset_x,
    offset_y,
    zoom,
    distortion,
    vignette_correction,
    auto_wb,
    colorchecker_enabled,
    colorchecker_phase,
    colorcheckerSummary,
    originalPreviewUrl,
    calibratedPreviewUrl,
    isLoading,
    error,
    lut_download_url,
    manualFixError,
    page1Extracted,
    page2Extracted,
    extractedEightColorFullPages,
    page1Extracted_5c,
    page2Extracted_5c,
    mergeLoading,
    mergeError,
    manufacturer,
    type: metadataType,
    defaultPalette,
    paletteConfirmed,
    paletteConfirmLoading,
    paletteConfirmError,
    setColorMode,
    setPage,
    setEightColorFullExport,
    setImageFile,
    setOffsetX,
    setOffsetY,
    setZoom,
    setDistortion,
    setVignetteCorrection,
    setAutoWb,
    setColorcheckerEnabled,
    receiveCalibratedFromCC,
    confirmCalibrated,
    rejectCalibrated,
    closeColorcheckerDialog,
    setManufacturer,
    setType,
    submitExtract,
    submitMerge,
    clearCornerPoints,
    setNudgeStep,
    setActiveCornerIndex,
    nudgeActiveCorner,
    updatePaletteEntry,
    submitConfirmPalette,
  } = useExtractorStore();

  const isEightColor = color_mode === ExtractorColorMode.EIGHT_COLOR;
  const isMultiPage =
    isEightColor || color_mode === ExtractorColorMode.FIVE_COLOR_EXT;

  const is5c = color_mode === ExtractorColorMode.FIVE_COLOR_EXT;
  const isEightColorFull = isEightColor && eight_color_full_export;
  const p1Done = is5c ? page1Extracted_5c : page1Extracted;
  const p2Done = is5c ? page2Extracted_5c : page2Extracted;
  const mergeTitle = is5c
    ? t("ext_merge_5c_title")
    : isEightColorFull
      ? t("ext_merge_8c_full_title")
      : t("ext_merge_8c_title");
  const mergeLabel = is5c
    ? t("ext_merge_5c_btn")
    : isEightColorFull
      ? t("ext_merge_8c_full_btn")
      : t("ext_merge_8c_btn");
  const extractedEightColorFullPageSet = new Set(extractedEightColorFullPages);
  const compactPageOptions = [
    {
      label: isEightColor ? formatEightColorPageLabel(1, t) : t("ext_page_1_label"),
      value: ExtractorPage.PAGE_1,
    },
    {
      label: isEightColor ? formatEightColorPageLabel(2, t) : t("ext_page_2_label"),
      value: ExtractorPage.PAGE_2,
    },
  ];
  const fullEightColorPageOptions = Array.from(
    { length: EXTRACTOR_EIGHT_COLOR_FULL_TOTAL_PAGES },
    (_, index) => ({
      label: formatEightColorPageLabel(index + 1, t),
      value: `Page ${index + 1}` as ExtractorPage,
    }),
  );
  const pageOptions = isEightColor
    ? isEightColorFull
      ? fullEightColorPageOptions
      : compactPageOptions
    : compactPageOptions;
  const mergeReady = isEightColorFull
    ? extractedEightColorFullPages.length === EXTRACTOR_EIGHT_COLOR_FULL_TOTAL_PAGES
    : p1Done && p2Done;

  const extractDisabled =
    imageFile === null || corner_points.length < 4 || isLoading ||
    colorchecker_phase === "calibrating";


  const [correctionOpen, setCorrectionOpen] = useState(false);
  const [nudgeOpen, setNudgeOpen] = useState(true);

  const cornerLabels = buildCornerLabels(color_mode, page, t);
  const placedCornerCount = corner_points.length;
  const nudgeEnabled =
    placedCornerCount > 0 && active_corner_index !== null;
  const activeCornerPoint =
    active_corner_index !== null &&
    active_corner_index >= 0 &&
    active_corner_index < corner_points.length
      ? corner_points[active_corner_index]
      : null;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const key = e.key;
      if (
        key !== "ArrowUp" &&
        key !== "ArrowDown" &&
        key !== "ArrowLeft" &&
        key !== "ArrowRight"
      ) {
        return;
      }
      // Ignore when typing into form controls or contentEditable elements.
      const target = e.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (
          tag === "INPUT" ||
          tag === "TEXTAREA" ||
          tag === "SELECT" ||
          target.isContentEditable
        ) {
          return;
        }
      }
      const {
        active_corner_index: activeIdx,
        corner_points: pts,
      } = useExtractorStore.getState();
      if (
        activeIdx === null ||
        activeIdx < 0 ||
        activeIdx >= pts.length
      ) {
        return;
      }
      e.preventDefault();
      switch (key) {
        case "ArrowUp":
          nudgeActiveCorner(0, -1);
          break;
        case "ArrowDown":
          nudgeActiveCorner(0, 1);
          break;
        case "ArrowLeft":
          nudgeActiveCorner(-1, 0);
          break;
        case "ArrowRight":
          nudgeActiveCorner(1, 0);
          break;
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [nudgeActiveCorner]);

  return (
    <motion.aside
      initial={{ opacity: 0, x: -30 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="extractor-panel"
      className={`${panelSurfaceClass} h-auto w-full overflow-y-auto xl:h-full xl:w-[400px] xl:shrink-0 2xl:w-[480px]`}
    >
      <div className="flex flex-col gap-2">
        <section className={`${sectionCardClass} flex flex-col gap-2`}>
          <div className="grid gap-2 lg:grid-cols-1 xl:grid-cols-1 2xl:grid-cols-1">
            <div data-testid="color-mode-select">
              <Dropdown
                label={t("ext_color_mode_label")}
                labelAccessory={
                  <HelpDot title={t("ext_color_mode_label")} description={t("ext_color_mode_hint")} />
                }
                value={color_mode}
                options={colorModeOptions}
                onChange={(v) => setColorMode(v as ExtractorColorMode)}
              />
            </div>

            {isMultiPage && (
              <div data-testid="page-select">
                <Dropdown
                  label={t("ext_page_label")}
                  labelAccessory={
                    <HelpDot title={t("ext_page_label")} description={t("ext_page_hint")} />
                  }
                  value={page}
                  options={pageOptions}
                  onChange={(v) => setPage(v as ExtractorPage)}
                />
              </div>
            )}

            {isEightColor && (
              <div data-testid="eight-color-full-toggle" className="flex flex-col gap-2 2xl:col-span-2">
                <div className="rounded-[22px] border border-slate-200/80 bg-slate-100/70 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-900/55">
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1">
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {t("ext_8color_full_export_label")}
                      </p>
                      <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                        {t("ext_8color_full_export_hint")}
                      </p>
                    </div>
                    <Switch
                      checked={eight_color_full_export}
                      onChange={setEightColorFullExport}
                      checkedLabel={t("ext_8color_full_export_on")}
                      uncheckedLabel={t("ext_8color_full_export_off")}
                    />
                  </div>
                </div>
              </div>
            )}

            <div data-testid="image-upload" className="flex flex-col gap-2 2xl:col-span-2">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-200">{t("ext_upload_label")}</label>
              <ImageUpload
                onFileSelect={(file) => setImageFile(file)}
                accept={ACCEPT_EXTRACTOR_FORMATS}
                preview={imagePreviewUrl ?? undefined}
              />
            </div>
          </div>
        </section>

        <section
          data-testid="correction-section"
          className={`${sectionCardClass} flex flex-col`}
        >
          <button
            type="button"
            onClick={() => setCorrectionOpen((prev) => !prev)}
            aria-expanded={correctionOpen}
            aria-controls="correction-panel"
            data-testid="correction-toggle"
            className="flex w-full items-center justify-between gap-2 text-left"
          >
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
              {t("ext_correction_section")}
            </h3>
            <motion.svg
              animate={{ rotate: correctionOpen ? 90 : 0 }}
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
          <AnimatePresence initial={false}>
            {correctionOpen && (
              <motion.div
                id="correction-panel"
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ type: "spring", bounce: 0, duration: 0.3 }}
                className="overflow-hidden"
              >
                <div className="flex flex-col gap-2 pt-4">
                  <div className="grid gap-2 lg:grid-cols-1 xl:grid-cols-1 2xl:grid-cols-1">
                    <Slider label={t("ext_offset_x_label")} tooltip={t("ext_offset_x_hint")} value={offset_x} min={-30} max={30} step={1} onChange={setOffsetX} />
                    <Slider label={t("ext_offset_y_label")} tooltip={t("ext_offset_y_hint")} value={offset_y} min={-30} max={30} step={1} onChange={setOffsetY} />
                    <Slider label={t("ext_zoom_label")} tooltip={t("ext_zoom_hint")} value={zoom} min={0.8} max={1.2} step={0.01} onChange={setZoom} />
                    <Slider label={t("ext_distortion_label")} tooltip={t("ext_distortion_hint")} value={distortion} min={-0.2} max={0.2} step={0.01} onChange={setDistortion} />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <Checkbox label={t("ext_vignette_label")} tooltip={t("ext_vignette_hint")} checked={vignette_correction} onChange={setVignetteCorrection} />
                    <Checkbox label={t("ext_auto_wb_label")} tooltip={t("ext_auto_wb_hint")} checked={auto_wb} onChange={(v) => void setAutoWb(v)} />
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </section>

        <section data-testid="colorchecker-toggle-section" className={`${sectionCardClass}`}>
          <Checkbox label={t("ext_colorchecker_label")} tooltip={t("ext_colorchecker_hint")} checked={colorchecker_enabled} onChange={setColorcheckerEnabled} />
        </section>

        <section
          data-testid="corner-nudge-section"
          className={`${sectionCardClass} flex flex-col`}
        >
          <button
            type="button"
            onClick={() => setNudgeOpen((prev) => !prev)}
            aria-expanded={nudgeOpen}
            aria-controls="corner-nudge-panel"
            data-testid="corner-nudge-toggle"
            className="flex w-full items-center justify-between gap-2 text-left"
          >
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
              {t("ext_nudge_section")}
            </h3>
            <motion.svg
              animate={{ rotate: nudgeOpen ? 90 : 0 }}
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
          {nudgeOpen && (
            <div id="corner-nudge-panel" className="flex flex-col gap-2 pt-4">
              {placedCornerCount === 0 ? (
                <StatusBanner tone="info">
                  {t("ext_nudge_hint_empty")}
                </StatusBanner>
              ) : (
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                    {t("ext_nudge_active_corner_label")}
                  </span>
                  <div
                    role="radiogroup"
                    aria-label={t("ext_nudge_active_corner_label")}
                    className="grid grid-cols-2 gap-2"
                    data-testid="corner-nudge-checkboxes"
                  >
                    {/* Display order matches geometric layout (TL, TR, BL, BR) */}
                    {[0, 1, 3, 2].map((idx) => {
                      const label = cornerLabels[idx];
                      const placed = idx < placedCornerCount;
                      const selected =
                        placed && active_corner_index === idx;
                      return (
                        <button
                          key={idx}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          disabled={!placed}
                          onClick={() => setActiveCornerIndex(idx)}
                          className={cx(
                            "flex min-h-11 items-center justify-center rounded-2xl border px-3 py-2 text-sm font-medium transition-colors",
                            selected
                              ? "border-blue-500 bg-blue-500 text-white shadow-[var(--shadow-control-hover)]"
                              : "border-slate-200/80 bg-white/70 text-slate-700 hover:border-slate-300 hover:bg-white/90 dark:border-slate-700/80 dark:bg-slate-900/55 dark:text-slate-200 dark:hover:border-slate-600",
                            !placed && "cursor-not-allowed opacity-45",
                          )}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              <Slider
                label={t("ext_nudge_step_label")}
                tooltip={t("ext_nudge_step_hint")}
                value={nudge_step}
                min={1}
                max={10}
                step={1}
                onChange={setNudgeStep}
              />

              <div
                className="grid grid-cols-3 gap-2 justify-items-center"
                data-testid="corner-nudge-buttons"
              >
                <div />
                <Button
                  label={t("ext_nudge_up")}
                  icon={<ChevronUp />}
                  variant="secondary"
                  size="icon"
                  onClick={() => nudgeActiveCorner(0, -1)}
                  disabled={!nudgeEnabled}
                />
                <div />
                <Button
                  label={t("ext_nudge_left")}
                  icon={<ChevronLeft />}
                  variant="secondary"
                  size="icon"
                  onClick={() => nudgeActiveCorner(-1, 0)}
                  disabled={!nudgeEnabled}
                />
                <div className="flex items-center justify-center text-xs tabular-nums text-slate-500 dark:text-slate-400">
                  {activeCornerPoint
                    ? `(${Math.round(activeCornerPoint[0])}, ${Math.round(activeCornerPoint[1])})`
                    : "—"}
                </div>
                <Button
                  label={t("ext_nudge_right")}
                  icon={<ChevronRight />}
                  variant="secondary"
                  size="icon"
                  onClick={() => nudgeActiveCorner(1, 0)}
                  disabled={!nudgeEnabled}
                />
                <div />
                <Button
                  label={t("ext_nudge_down")}
                  icon={<ChevronDown />}
                  variant="secondary"
                  size="icon"
                  onClick={() => nudgeActiveCorner(0, 1)}
                  disabled={!nudgeEnabled}
                />
                <div />
              </div>

              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t("ext_nudge_keyboard_hint")}
              </p>
            </div>
          )}
        </section>

        <AnimatePresence initial={false}>
          {colorchecker_enabled && (
            <motion.section
              data-testid="colorchecker-step-section"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ type: "spring", bounce: 0, duration: 0.3 }}
              className="overflow-hidden"
            >
              <div
                className={`${sectionCardClass} flex flex-col gap-3`}
                style={{ background: "var(--surface-panel)" }}
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                      {t("ext_cc_dialog_title")}
                    </h3>
                    <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {t("ext_colorchecker_hint")}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {colorchecker_phase === "done" && (
                      <span className="inline-flex items-center rounded-full border border-emerald-300/80 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:border-emerald-500/50 dark:text-emerald-300">
                        {t("ext_cc_calibrated_badge")}
                      </span>
                    )}
                  </div>
                </div>
                <ColorcheckerConfirmDialogInner
                  phase={colorchecker_phase ?? "calibrating"}
                  imageFile={imageFile}
                  originalPreviewUrl={originalPreviewUrl}
                  calibratedPreviewUrl={calibratedPreviewUrl}
                  calibrationSummary={colorcheckerSummary}
                  receiveCalibrated={receiveCalibratedFromCC}
                  confirmCalibrated={confirmCalibrated}
                  rejectCalibrated={rejectCalibrated}
                  closeDialog={closeColorcheckerDialog}
                />
                {colorcheckerSummary && (
                  <div className="grid gap-2 sm:grid-cols-4">
                    {[
                      [t("ext_cc_metric_mean"), colorcheckerSummary.deltaE00.mean],
                      [t("ext_cc_metric_median"), colorcheckerSummary.deltaE00.median],
                      [t("ext_cc_metric_p95"), colorcheckerSummary.deltaE00.p95],
                      [t("ext_cc_metric_worst"), colorcheckerSummary.deltaE00.max],
                    ].map(([label, value]) => (
                      <div
                        key={String(label)}
                        className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-700/80"
                        style={{ background: "var(--surface-panel-strong)" }}
                      >
                        <div className="text-[11px] font-medium uppercase text-slate-500 dark:text-slate-400">
                          {label}
                        </div>
                        <div className="mt-1 text-base font-semibold tabular-nums text-slate-900 dark:text-slate-50">
                          {typeof value === "number" ? value.toFixed(2) : "-"}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </motion.section>
          )}
        </AnimatePresence>

        <section className={`${sectionCardClass} flex flex-col gap-2 lg:flex-row`}>
          <div data-testid="extract-button" className="lg:flex-1 lg:min-w-0">
            <Button
              label={t("ext_extract_btn_label")}
              variant="primary"
              onClick={() => void submitExtract()}
              disabled={extractDisabled}
              loading={isLoading}
              className="w-full"
            />
          </div>
          <div data-testid="clear-corners-button" className="lg:flex-1 lg:min-w-0">
            <Button
              label={t("ext_clear_corners")}
              variant="secondary"
              onClick={clearCornerPoints}
              className="w-full"
            />
          </div>
        </section>

        {isMultiPage && (
          <section data-testid="merge-section" className={`${sectionCardClass} flex flex-col gap-2`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{mergeTitle}</h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {isEightColorFull ? t("ext_pages_extracted_label") : t("ext_page_label")}
              </p>
            </div>
            {isEightColorFull ? (
              <>
                <div className="flex items-center justify-between rounded-2xl border border-slate-200/80 bg-slate-100/70 px-3 py-2 text-sm dark:border-slate-700/80 dark:bg-slate-900/55">
                  <span className="text-slate-600 dark:text-slate-300">{t("ext_pages_extracted_label")}</span>
                  <span className="font-medium text-slate-800 dark:text-slate-100">
                    {extractedEightColorFullPages.length}/{EXTRACTOR_EIGHT_COLOR_FULL_TOTAL_PAGES}
                  </span>
                </div>
                <div className="grid gap-2 text-sm sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3">
                  {fullEightColorPageOptions.map((option, index) => {
                    const pageNumber = index + 1;
                    const extracted = extractedEightColorFullPageSet.has(pageNumber);
                    return (
                      <div
                        key={option.value}
                        className="flex items-center justify-between rounded-2xl border border-slate-200/80 bg-slate-100/70 px-3 py-2 dark:border-slate-700/80 dark:bg-slate-900/55"
                      >
                        <span className="text-slate-600 dark:text-slate-300">{option.label}</span>
                        <span className={extracted ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400 dark:text-slate-500"}>
                          {extracted ? t("ext_page_extracted") : t("ext_page_not_extracted")}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </>
            ) : (
              <div className="grid gap-2 text-sm lg:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                <div className="flex items-center justify-between rounded-2xl border border-slate-200/80 bg-slate-100/70 px-3 py-2 dark:border-slate-700/80 dark:bg-slate-900/55">
                  <span className="text-slate-600 dark:text-slate-300">{compactPageOptions[0].label}</span>
                  <span className={p1Done ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400 dark:text-slate-500"}>
                    {p1Done ? t("ext_page_extracted") : t("ext_page_not_extracted")}
                  </span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-slate-200/80 bg-slate-100/70 px-3 py-2 dark:border-slate-700/80 dark:bg-slate-900/55">
                  <span className="text-slate-600 dark:text-slate-300">{compactPageOptions[1].label}</span>
                  <span className={p2Done ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400 dark:text-slate-500"}>
                    {p2Done ? t("ext_page_extracted") : t("ext_page_not_extracted")}
                  </span>
                </div>
              </div>
            )}
            <Button
              label={mergeLabel}
              variant="primary"
              onClick={() => void submitMerge()}
              disabled={!mergeReady || mergeLoading}
              loading={mergeLoading}
              className="w-full"
            />
            {mergeError && <StatusBanner tone="error">{mergeError}</StatusBanner>}
          </section>
        )}

        {error && (
          <StatusBanner data-testid="error-message" tone="error">
            {error}
          </StatusBanner>
        )}

        {defaultPalette.length > 0 && !paletteConfirmed && (
          <section data-testid="palette-confirm-section" className={`${sectionCardClass} flex flex-col gap-2`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("ext_palette_title")}</h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("ext_palette_metadata_hint")}</p>
            </div>
            <div className="grid gap-2 lg:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("ext_manufacturer_label")}
                </span>
                <input
                  className={textInputClass}
                  value={manufacturer}
                  onChange={(e) => setManufacturer(e.target.value)}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("ext_type_label")}
                </span>
                <input
                  className={textInputClass}
                  value={metadataType}
                  onChange={(e) => setType(e.target.value)}
                />
              </label>
            </div>
            <Dropdown
              label={t("ext_material_type_label")}
              value={defaultPalette[0]?.material ?? "PLA"}
              options={materialOptions}
              onChange={(mat) => {
                defaultPalette.forEach((_, i) => updatePaletteEntry(i, { material: mat }));
              }}
            />
            <div className="flex flex-col gap-2">
              {defaultPalette.map((entry, idx) => (
                <div
                  key={`${entry.color}-${idx}`}
                  className="grid gap-2 rounded-[22px] border border-slate-200/80 bg-slate-100/70 px-3 py-3 dark:border-slate-700/80 dark:bg-slate-900/55 sm:grid-cols-[auto,1fr]"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="h-5 w-5 shrink-0 rounded-xl border border-slate-300/80 dark:border-slate-600/80"
                      style={{ backgroundColor: entry.hex_color || "#ccc" }}
                    />
                    <div className="flex flex-col">
                      <span className="text-xs uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
                        {t("ext_palette_internal_color_label")}
                      </span>
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                        {entry.color}
                      </span>
                    </div>
                  </div>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                      {t("ext_palette_color_name_label")}
                    </span>
                    <input
                      className={textInputClass}
                      value={entry.color_name ?? ""}
                      placeholder={entry.color}
                      onChange={(e) => updatePaletteEntry(idx, { color_name: e.target.value })}
                    />
                  </label>
                </div>
              ))}
            </div>
            <Button
              label={t("ext_confirm_palette_btn")}
              variant="primary"
              onClick={() => void submitConfirmPalette()}
              loading={paletteConfirmLoading}
              className="w-full"
            />
            {paletteConfirmError && <StatusBanner tone="error">{paletteConfirmError}</StatusBanner>}
          </section>
        )}

        {paletteConfirmed && (
          <StatusBanner data-testid="palette-confirmed" tone="success">
            {t("ext_palette_confirmed")}
          </StatusBanner>
        )}

        {lut_download_url && (
          <section className={`${sectionCardClass} flex flex-col gap-2`}>
            <a
              data-testid="lut-download-link"
              href={lut_download_url}
              download
              className="inline-flex min-h-11 items-center justify-center rounded-2xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-[var(--shadow-control-hover)] transition-colors hover:bg-blue-700"
            >
              {t("ext_download_lut")}
            </a>
            <StatusBanner data-testid="manual-fix-section" tone="info">
              {t("ext_manual_fix_hint")}
            </StatusBanner>
          </section>
        )}

        {manualFixError && (
          <StatusBanner data-testid="manual-fix-error" tone="error">
            {manualFixError}
          </StatusBanner>
        )}
      </div>

    </motion.aside>
  );
}
