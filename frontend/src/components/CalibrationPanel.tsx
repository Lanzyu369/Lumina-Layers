import { motion } from "framer-motion";
import { useCalibrationStore } from "../stores/calibrationStore";
import { useI18n } from "../i18n/context";
import { CalibrationColorMode, BackingColor } from "../api/types";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Button from "./ui/Button";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import {
  PanelIntro,
  StatusBanner,
  mutedSectionCardClass,
  desktopPrimaryColumnClass,
  desktopSecondaryColumnClass,
  resolveDesktopSplitLayoutClass,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

const colorModeOptions = Object.values(CalibrationColorMode).map((v) => ({
  label: v,
  value: v,
}));

const backingColorOptions = Object.values(BackingColor).map((v) => ({
  label: v,
  value: v,
}));

const textInputClass =
  "min-h-10 w-full rounded-2xl border border-slate-200/80 bg-white/90 px-3 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-100";

export default function CalibrationPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const {
    workflow,
    color_mode,
    block_size,
    gap,
    backing,
    substrateId,
    substrateDisplayName,
    materialDefault,
    isLoading,
    error,
    downloadUrl,
    previewImageUrl,
    statusMessage,
    manifestUrl,
    singleStageJobs,
    setWorkflow,
    setColorMode,
    setBlockSize,
    setGap,
    setBacking,
    setSubstrateId,
    setSubstrateDisplayName,
    setMaterialDefault,
    submitGenerate,
  } = useCalibrationStore();

  const workflowOptions = [
    { label: t("cal_workflow_legacy"), value: "legacy" },
    { label: t("cal_workflow_single_stage"), value: "single-stage" },
  ];

  const backingDisabled =
    color_mode === CalibrationColorMode.EIGHT_COLOR ||
    color_mode === CalibrationColorMode.FIVE_COLOR_EXT ||
    color_mode === CalibrationColorMode.SIX_COLOR ||
    color_mode === CalibrationColorMode.SIX_COLOR_RYBW;

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="calibration-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <PanelIntro
        eyebrow={t("tab.calibration")}
        title={t("cal_title")}
        description={t("cal_desc")}
      />

      <div className={resolveDesktopSplitLayoutClass(workspace.mode)}>
        <div className={desktopPrimaryColumnClass}>
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("cal_params")}</h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("cal_generate_btn")}</p>
            </div>

            <Dropdown
              label={t("cal_workflow_label")}
              value={workflow}
              options={workflowOptions}
              onChange={(value) => setWorkflow(value as "legacy" | "single-stage")}
            />

            {workflow === "legacy" ? (
              <>
                <Dropdown
                  label={t("cal_color_mode_label")}
                  value={color_mode}
                  options={colorModeOptions}
                  onChange={(v) => setColorMode(v as CalibrationColorMode)}
                />

                <Slider
                  label={t("cal_block_size_label")}
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
                  value={gap}
                  min={0.4}
                  max={2.0}
                  step={0.01}
                  displayDecimals={2}
                  minInputWidthCh={8}
                  unit="mm"
                  onChange={setGap}
                />

                <Dropdown
                  label={t("cal_backing_label")}
                  value={backing}
                  options={backingColorOptions}
                  onChange={(v) => setBacking(v as BackingColor)}
                  disabled={backingDisabled}
                />
              </>
            ) : (
              <div className="flex flex-col gap-4" data-testid="single-stage-config">
                <Dropdown
                  label={t("cal_color_mode_label")}
                  value={color_mode}
                  options={colorModeOptions}
                  onChange={(v) => setColorMode(v as CalibrationColorMode)}
                />
                <label className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("cal_substrate_id_label")}
                  </span>
                  <input
                    className={textInputClass}
                    value={substrateId}
                    onChange={(e) => setSubstrateId(e.target.value)}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("cal_substrate_name_label")}
                  </span>
                  <input
                    className={textInputClass}
                    value={substrateDisplayName}
                    onChange={(e) => setSubstrateDisplayName(e.target.value)}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("cal_material_default_label")}
                  </span>
                  <input
                    className={textInputClass}
                    value={materialDefault}
                    onChange={(e) => setMaterialDefault(e.target.value)}
                  />
                </label>
              </div>
            )}

            <Button
              label={
                workflow === "single-stage"
                  ? t("cal_generate_single_stage_btn")
                  : t("cal_generate_btn_panel")
              }
              variant="primary"
              onClick={() => void submitGenerate()}
              disabled={isLoading}
              loading={isLoading}
              className="w-full"
            />
          </section>
        </div>

        <div className={desktopSecondaryColumnClass}>
          {statusMessage && (
            <StatusBanner data-testid="status-message" tone="success">
              {statusMessage}
            </StatusBanner>
          )}

          {error && (
            <StatusBanner data-testid="error-message" tone="error">
              {error}
            </StatusBanner>
          )}

          {downloadUrl && (
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
                  {workflow === "single-stage"
                    ? t("cal_download_kit")
                    : t("cal_download_3mf")}
                </a>
                {manifestUrl && (
                  <a
                    data-testid="manifest-link"
                    href={manifestUrl}
                    download
                    className="inline-flex min-h-11 items-center justify-center rounded-2xl border border-slate-300/80 px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:text-slate-900 dark:border-slate-600/80 dark:text-slate-200"
                  >
                    {t("cal_download_manifest")}
                  </a>
                )}
              </div>
            </section>
          )}

          {singleStageJobs.length > 0 && (
            <section
              data-testid="single-stage-jobs"
              className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}
            >
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("cal_single_stage_jobs_title")}
                </h3>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {t("cal_single_stage_jobs_desc")}
                </p>
              </div>
              <div className="grid gap-2">
                {singleStageJobs.map((job) => (
                  <div
                    key={job.filename}
                    className="rounded-[22px] border border-slate-200/80 bg-slate-100/70 px-3 py-3 text-sm dark:border-slate-700/80 dark:bg-slate-900/55"
                  >
                    <div className="font-medium text-slate-800 dark:text-slate-100">{job.color_name}</div>
                    <div className="mt-1 text-slate-500 dark:text-slate-400">{job.filename}</div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("cal_preview")}</h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("cal_preview_alt")}</p>
            </div>
            {previewImageUrl ? (
              <img
                data-testid="preview-image"
                src={previewImageUrl}
                alt={t("cal_preview_alt")}
                className="w-full rounded-[24px] border border-slate-200/80 object-cover shadow-[var(--shadow-control)] dark:border-slate-700/80"
              />
            ) : (
              <div className={`${mutedSectionCardClass} flex min-h-[280px] flex-col justify-center gap-3`}>
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
