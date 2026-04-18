import { motion } from "framer-motion";
import { useCalibrationStore } from "../stores/calibrationStore";
import { useI18n } from "../i18n/context";
import Dropdown from "./ui/Dropdown";
import Button from "./ui/Button";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { MATERIAL_PRESET_OPTIONS } from "../constants/materialPresets";
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

const singleStageLayerHeightOptions = [0.04, 0.08, 0.1].map((value) => ({
  label: `${value.toFixed(2)} mm`,
  value: value.toString(),
}));

const textInputClass =
  "min-h-10 w-full rounded-2xl border border-slate-200/80 bg-white/90 px-3 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-100";

export default function GradientCardGeneratePanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const {
    substrateId,
    substrateDisplayName,
    materialDefault,
    singleStageLayerHeightMm,
    lastSubmittedWorkflow,
    isLoading,
    error,
    downloadUrl,
    previewImageUrl,
    statusMessage,
    manifestUrl,
    setSubstrateId,
    setSubstrateDisplayName,
    setMaterialDefault,
    setSingleStageLayerHeightMm,
    submitSingleStageGenerate,
  } = useCalibrationStore();

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="gradient-card-generate-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <PanelIntro
        eyebrow={t("tab.materialManagement")}
        title={t("mat_gradient_generate_title")}
        description={t("mat_gradient_generate_desc")}
      />

      <div className={resolveDesktopSplitLayoutClass(workspace.mode)}>
        <div className={desktopPrimaryColumnClass}>
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("cal_params")}
              </h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("mat_gradient_generate_desc")}
              </p>
            </div>

            <Dropdown
              label={t("cal_single_stage_layer_height_label")}
              value={singleStageLayerHeightMm.toString()}
              options={singleStageLayerHeightOptions}
              onChange={(value) =>
                setSingleStageLayerHeightMm(Number.parseFloat(value))
              }
            />

            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("cal_substrate_id_label")}
              </span>
              <input
                className={textInputClass}
                value={substrateId}
                onChange={(event) => setSubstrateId(event.target.value)}
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("cal_substrate_name_label")}
              </span>
              <input
                className={textInputClass}
                value={substrateDisplayName}
                onChange={(event) => setSubstrateDisplayName(event.target.value)}
              />
            </label>

            <Dropdown
              label={t("cal_material_default_label")}
              value={materialDefault}
              options={[...MATERIAL_PRESET_OPTIONS]}
              onChange={(value) => setMaterialDefault(value)}
            />


            <Button
              label={t("cal_generate_single_stage_btn")}
              variant="primary"
              onClick={() => void submitSingleStageGenerate()}
              disabled={isLoading}
              loading={isLoading}
              className="w-full"
            />
          </section>
        </div>

        <div className={desktopSecondaryColumnClass}>
          {lastSubmittedWorkflow === "single-stage" && statusMessage && (
            <StatusBanner data-testid="status-message" tone="success">
              {statusMessage}
            </StatusBanner>
          )}

          {lastSubmittedWorkflow === "single-stage" && error && (
            <StatusBanner data-testid="error-message" tone="error">
              {error}
            </StatusBanner>
          )}

          {lastSubmittedWorkflow === "single-stage" && downloadUrl && (
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("cal_download")}
                </h3>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {t("cal_status")}
                </p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <a
                  data-testid="download-link"
                  href={downloadUrl}
                  download
                  className="inline-flex min-h-11 items-center justify-center rounded-2xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-[var(--shadow-control-hover)] transition-colors hover:bg-blue-700"
                >
                  {t("cal_download_kit")}
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

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("cal_preview")}
              </h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("cal_preview_alt")}
              </p>
            </div>
            {lastSubmittedWorkflow === "single-stage" && previewImageUrl ? (
              <img
                data-testid="preview-image"
                src={previewImageUrl}
                alt={t("cal_preview_alt")}
                className="w-full rounded-[24px] border border-slate-200/80 object-cover shadow-[var(--shadow-control)] dark:border-slate-700/80"
              />
            ) : (
              <div className={`${mutedSectionCardClass} flex min-h-[280px] flex-col justify-center gap-3`}>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("cal_status")}
                </p>
                <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {t("mat_gradient_generate_desc")}
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </motion.aside>
  );
}
