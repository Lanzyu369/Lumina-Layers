import { motion } from "framer-motion";
import { useCalibrationStore, BACKING_THICKNESS_MIN_MM, BACKING_THICKNESS_MAX_MM, BACKING_THICKNESS_STEP_MM } from "../stores/calibrationStore";
import { useI18n } from "../i18n/context";
import { CalibrationColorMode } from "../api/types";
import { useState } from "react";
import LayerMaskViewerDialog from "./ui/LayerMaskViewerDialog";
import HelpDot from "./ui/HelpDot";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Switch from "./ui/Switch";
import SlicerSelector from "./sections/SlicerSelector";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import {
  StatusBanner,
  mutedSectionCardClass,
  desktopPrimaryColumnClass,
  desktopSecondaryColumnClass,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";
import { WIKI_DOCS } from "../utils/wikiDocs";

const colorModeOptions = Object.values(CalibrationColorMode).map((v) => ({
  label: v,
  value: v,
}));

export default function CalibrationPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const {
    color_mode,
    block_size,
    gap,
    backing_thickness,
    eight_color_full_export,
    lastSubmittedWorkflow,
    isLoading,
    error,
    downloadUrl,
    threemfDiskPath,
    previewImageUrl,
    layerImageUrls,
    statusMessage,
    warnings,
    setColorMode,
    setBlockSize,
    setGap,
    setBackingThickness,
    setEightColorFullExport,
    submitLegacyGenerate,
  } = useCalibrationStore();
  const [zoomedLayerIdx, setZoomedLayerIdx] = useState<number | null>(null);
  const activeLayerImages = layerImageUrls?.map((url, idx) => ({
    layer_index: idx,
    name: `${t("action_layer_nth")}${idx + 1}${t("action_layer_unit")}`,
    url
  })) ?? [];

  const showEightColorFullExport =
    color_mode === CalibrationColorMode.EIGHT_COLOR;
  const exportsZipPackage =
    color_mode === CalibrationColorMode.FIVE_COLOR_EXT ||
    color_mode === CalibrationColorMode.EIGHT_COLOR;

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="calibration-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <div className="grid min-h-0 gap-5 lg:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)] lg:items-stretch">
        <div className={desktopPrimaryColumnClass}>
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("cal_params")}</h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("cal_generate_btn")}</p>
            </div>

            <Dropdown
              label={t("cal_color_mode_label")}
              tooltip={t("cal_color_mode_hint")}
              wikiPath={WIKI_DOCS.calibrationBoard}
              value={color_mode}
              options={colorModeOptions}
              onChange={(v) => setColorMode(v as CalibrationColorMode)}
            />

            {showEightColorFullExport && (
              <div className={`${mutedSectionCardClass} flex items-start justify-between gap-4`}>
                <div className="space-y-1">
                  <p className="flex items-center gap-1.5 text-sm font-medium text-slate-900 dark:text-slate-100">
                    <span>{t("cal_8color_full_export_label")}</span>
                    <HelpDot
                      title={t("cal_8color_full_export_label")}
                      description={t("cal_8color_full_export_hint")}
                      wikiPath={WIKI_DOCS.calibrationBoard}
                    />
                  </p>
                </div>
                <Switch
                  checked={eight_color_full_export}
                  onChange={setEightColorFullExport}
                  checkedLabel={t("cal_8color_full_export_on")}
                  uncheckedLabel={t("cal_8color_full_export_off")}
                />
              </div>
            )}

            <Slider
              label={t("cal_block_size_label")}
              tooltip={t("cal_block_size_hint")}
              wikiPath={WIKI_DOCS.calibrationBoard}
              value={block_size}
              min={3}
              max={10}
              step={0.5}
              displayDecimals={2}
              minInputWidthCh={8}
              unit="mm"
              onChange={setBlockSize}
            />

            <Slider
              label={t("cal_gap_label")}
              tooltip={t("cal_gap_hint")}
              wikiPath={WIKI_DOCS.calibrationBoard}
              value={gap}
              min={0.4}
              max={2.0}
              step={0.01}
              displayDecimals={2}
              minInputWidthCh={8}
              unit="mm"
              onChange={setGap}
            />
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("cal_backing_thickness_label")}
                </span>
                <HelpDot
                  title={t("cal_backing_thickness_label")}
                  description={t("cal_backing_thickness_hint")}
                  wikiPath={WIKI_DOCS.calibrationBoard}
                />
              </div>
              <Slider
                label=""
                value={backing_thickness}
                min={BACKING_THICKNESS_MIN_MM}
                max={BACKING_THICKNESS_MAX_MM}
                step={BACKING_THICKNESS_STEP_MM}
                displayDecimals={2}
                minInputWidthCh={8}
                unit="mm"
                onChange={setBackingThickness}
                data-testid='backing-thickness-slider'
              />
            </div>


            <SlicerSelector
              threemfDiskPath={threemfDiskPath}
              downloadUrl={downloadUrl}
              canSubmit={!isLoading}
              largeFormat={exportsZipPackage}
              onAutoGenerate={async () => {
                await submitLegacyGenerate();
                const state = useCalibrationStore.getState();
                return state.downloadUrl ?? state.threemfDiskPath ?? null;
              }}
              getLatestDownloadUrl={() =>
                useCalibrationStore.getState().downloadUrl
              }
              getLatestThreemfDiskPath={() =>
                useCalibrationStore.getState().threemfDiskPath
              }
              onArtifactAction={() => undefined}
            />
          </section>
        </div>

        <div className={desktopSecondaryColumnClass}>
          {lastSubmittedWorkflow === "legacy" && statusMessage && (
            <StatusBanner data-testid="status-message" tone="success">
              {statusMessage}
            </StatusBanner>
          )}

          {lastSubmittedWorkflow === "legacy" &&
            downloadUrl &&
            warnings.includes("wipe_tower_manual_adjustment_required") && (
              <StatusBanner
                data-testid="calibration-placement-warning"
                tone="warning"
                title={t("wipe_tower_manual_adjustment_title")}
              >
                {t("wipe_tower_manual_adjustment_warning")}
              </StatusBanner>
            )}

          {lastSubmittedWorkflow === "legacy" && error && (
            <StatusBanner data-testid="error-message" tone="error">
              {error}
            </StatusBanner>
          )}

          {lastSubmittedWorkflow === "legacy" && downloadUrl && exportsZipPackage && (
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("cal_download")}</h3>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("cal_status")}</p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <a
                  data-testid="download-link"
                  href={downloadUrl}
                  download
                  className="inline-flex min-h-11 items-center justify-center rounded-2xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-[var(--shadow-control-hover)] transition-colors hover:bg-blue-700"
                >
                  {t("cal_download_3mf")}
                </a>
              </div>
            </section>
          )}

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-1 flex-col gap-4`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("cal_preview")}</h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("cal_preview_alt")}</p>
            </div>
            {lastSubmittedWorkflow === "legacy" && previewImageUrl ? (
              <div className="flex flex-col gap-3">
                <img
                  data-testid="preview-image"
                  src={previewImageUrl}
                  alt={t("cal_preview_alt")}
                  className="w-full rounded-[24px] border border-slate-200/80 object-contain shadow-[var(--shadow-control)] dark:border-slate-700/80 max-h-[60vh] bg-slate-50 dark:bg-slate-900"
                />
                
                {activeLayerImages.length > 0 && (
                  <div className="panel-section-muted rounded-[24px] p-4">
                    <h4 className="mb-3 text-sm font-medium text-slate-700 dark:text-slate-200">
                      {t("action_layers_title")}
                    </h4>
                    <div className={`grid gap-3 ${workspace.isCompact ? "grid-cols-3 sm:grid-cols-4" : "grid-cols-4 sm:grid-cols-5"}`}>
                      {activeLayerImages.map((layer, idx) => (
                        <div
                          key={layer.layer_index}
                          className="group flex cursor-pointer flex-col items-center gap-1.5"
                          onClick={() => setZoomedLayerIdx(idx)}
                        >
                          <div className="panel-section relative w-full overflow-hidden rounded-xl">
                            <img
                              src={layer.url}
                              alt={layer.name}
                              className="w-full aspect-square object-contain p-1 transition-transform group-hover:scale-105"
                              draggable={false}
                            />
                            <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/20 rounded-xl">
                              <span className="text-sm text-white opacity-0 transition-opacity group-hover:opacity-100">
                                {t("action_zoom_icon")}
                              </span>
                            </div>
                          </div>
                          <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                            {layer.name}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                
                <LayerMaskViewerDialog
                  open={zoomedLayerIdx !== null && !!activeLayerImages[zoomedLayerIdx]}
                  layers={activeLayerImages}
                  activeIndex={zoomedLayerIdx}
                  onChangeIndex={setZoomedLayerIdx}
                  onClose={() => setZoomedLayerIdx(null)}
                  isCompact={workspace.isCompact}
                />
              </div>
            ) : (

              <div className={`${mutedSectionCardClass} flex flex-1 min-h-[280px] flex-col justify-center gap-3`}>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{t("cal_status")}</p>
                <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">{t("cal_desc")}</p>
              </div>
            )}
          </section>
        </div>
      </div>
    </motion.aside>
  );
}
