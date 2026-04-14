import { motion } from "framer-motion";
import { useExtractorStore, ACCEPT_EXTRACTOR_FORMATS } from "../stores/extractorStore";
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
import ImageUpload from "./ui/ImageUpload";
import Switch from "./ui/Switch";
import {
  PanelIntro,
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
    offset_x,
    offset_y,
    zoom,
    distortion,
    vignette_correction,
    auto_wb,
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
    setManufacturer,
    setType,
    submitExtract,
    submitMerge,
    clearCornerPoints,
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
    imageFile === null || corner_points.length < 4 || isLoading;

  return (
    <motion.aside
      initial={{ opacity: 0, x: -30 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="extractor-panel"
      className={`${panelSurfaceClass} h-auto w-full overflow-y-auto xl:h-full xl:w-[400px] xl:shrink-0 2xl:w-[480px]`}
    >
      <div className="flex flex-col gap-5">
        <PanelIntro
          eyebrow={t("tab.extractor")}
          title={t("ext_title")}
          description={t("ext_desc")}
        />

        <section className={`${sectionCardClass} flex flex-col gap-4`}>
          <div className="grid gap-4 2xl:grid-cols-2">
            <div data-testid="color-mode-select">
              <Dropdown
                label={t("ext_color_mode_label")}
                value={color_mode}
                options={colorModeOptions}
                onChange={(v) => setColorMode(v as ExtractorColorMode)}
              />
            </div>

            {isMultiPage && (
              <div data-testid="page-select">
                <Dropdown
                  label={t("ext_page_label")}
                  value={page}
                  options={pageOptions}
                  onChange={(v) => setPage(v as ExtractorPage)}
                />
              </div>
            )}

            {isEightColor && (
              <div data-testid="eight-color-full-toggle" className="flex flex-col gap-3 2xl:col-span-2">
                <div className="rounded-[22px] border border-slate-200/80 bg-slate-100/70 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-900/55">
                  <div className="flex items-start justify-between gap-4">
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

        <section className={`${sectionCardClass} flex flex-col gap-4`}>
          <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("ext_correction_section")}</h3>
          <div className="grid gap-4 2xl:grid-cols-2">
            <Slider label={t("ext_offset_x_label")} value={offset_x} min={-30} max={30} step={1} onChange={setOffsetX} />
            <Slider label={t("ext_offset_y_label")} value={offset_y} min={-30} max={30} step={1} onChange={setOffsetY} />
            <Slider label={t("ext_zoom_label")} value={zoom} min={0.8} max={1.2} step={0.01} onChange={setZoom} />
            <Slider label={t("ext_distortion_label")} value={distortion} min={-0.2} max={0.2} step={0.01} onChange={setDistortion} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Checkbox label={t("ext_vignette_label")} checked={vignette_correction} onChange={setVignetteCorrection} />
            <Checkbox label={t("ext_auto_wb_label")} checked={auto_wb} onChange={(v) => void setAutoWb(v)} />
          </div>
        </section>

        <section className={`${sectionCardClass} flex flex-col gap-3 lg:flex-row`}>
          <div data-testid="extract-button">
            <Button
              label={t("ext_extract_btn_label")}
              variant="primary"
              onClick={() => void submitExtract()}
              disabled={extractDisabled}
              loading={isLoading}
              className="w-full lg:min-w-[12rem]"
            />
          </div>
          <div data-testid="clear-corners-button">
            <Button
              label={t("ext_clear_corners")}
              variant="secondary"
              onClick={clearCornerPoints}
              className="w-full lg:min-w-[12rem]"
            />
          </div>
        </section>

        {isMultiPage && (
          <section data-testid="merge-section" className={`${sectionCardClass} flex flex-col gap-3`}>
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
          <section data-testid="palette-confirm-section" className={`${sectionCardClass} flex flex-col gap-3`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("ext_palette_title")}</h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("ext_palette_metadata_hint")}</p>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
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
            <div className="flex flex-col gap-3">
              {defaultPalette.map((entry, idx) => (
                <div
                  key={`${entry.color}-${idx}`}
                  className="grid gap-3 rounded-[22px] border border-slate-200/80 bg-slate-100/70 px-3 py-3 dark:border-slate-700/80 dark:bg-slate-900/55 sm:grid-cols-[auto,1fr]"
                >
                  <div className="flex items-center gap-3">
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
          <section className={`${sectionCardClass} flex flex-col gap-3`}>
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
