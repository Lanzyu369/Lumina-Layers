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
    statusMessage,
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

            <div className="rounded-2xl border border-slate-200/80 bg-slate-50/90 p-4 text-sm leading-6 text-slate-600 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300">
              <p>{t("mat_gradient_generate_notice_dual_print")}</p>
              <p className="mt-2">{t("mat_gradient_generate_notice_online_model")}</p>
              <div className="mt-3 flex flex-col gap-2">
                <a
                  href="https://makerworld.com.cn/zh/models/2394753-lumina2-0-ti-xing-xiao-se-se-qia-0-08ceng-gao-15ce#profileId-2721317"
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm font-medium text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200"
                >
                  {t("mat_gradient_generate_online_model_link")}
                </a>
                <a
                  href="https://makerworld.com.cn/zh/models/2400920-can-shu-hua-lumina-2-0ti-du-se-qia-zi-ding-yi-shou#profileId-2729620"
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm font-medium text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200"
                >
                  {t("mat_gradient_generate_parametric_box_link")}
                </a>
              </div>
            </div>

            <Dropdown
              label={t("cal_single_stage_layer_height_label")}
              value={singleStageLayerHeightMm.toString()}
              options={singleStageLayerHeightOptions}
              onChange={(value) =>
                setSingleStageLayerHeightMm(Number.parseFloat(value))
              }
            />

            <div style={{ display: "none" }}>
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
            </div>

            <div style={{ display: "none" }}>
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
            </div>

            <div style={{ display: "none" }}>
              <Dropdown
                label={t("cal_material_default_label")}
                value={materialDefault}
                options={[...MATERIAL_PRESET_OPTIONS]}
                onChange={(value) => setMaterialDefault(value)}
              />
            </div>

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
              </div>
            </section>
          )}
        </div>
      </div>
    </motion.aside>
  );
}
