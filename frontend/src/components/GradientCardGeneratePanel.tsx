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
        title={t("mat_gradient_generate_title")}
        description={t("mat_gradient_generate_desc")}
      />

      <div className="flex flex-col gap-6 w-full">
        <div className="grid gap-6 lg:grid-cols-2 w-full">
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4 h-full`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("mat_gradient_generate_section_title")}
              </h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("mat_gradient_generate_section_desc")}
              </p>
            </div>

            <div className="flex flex-col gap-4 flex-1">
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
            </div>

            <div className="mt-auto pt-2">
              <Button
                label={t("mat_gradient_generate_btn")}
                variant="primary"
                onClick={() => void submitSingleStageGenerate()}
                disabled={isLoading}
                loading={isLoading}
                className="w-full"
              />
            </div>
          </section>

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4 h-full`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("mat_gradient_generate_notice_title")}
              </h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("mat_gradient_generate_notice_desc")}
              </p>
            </div>

            <div className="rounded-2xl border border-blue-200/80 bg-blue-50/50 p-4 text-sm leading-6 text-blue-800 dark:border-blue-900/30 dark:bg-blue-900/20 dark:text-blue-200 flex-1">
              <p>{t("mat_gradient_generate_notice_dual_print")}</p>
              <p className="mt-2">{t("mat_gradient_generate_notice_online_model")}</p>
              <div className="mt-4 flex flex-col gap-3">
                <a
                  href="https://makerworld.com.cn/zh/models/2394753-lumina2-0-ti-xing-xiao-se-se-qia-0-08ceng-gao-15ce#profileId-2721317"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 text-sm font-medium text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                  {t("mat_gradient_generate_online_model_link")}
                </a>
                <a
                  href="https://makerworld.com.cn/zh/models/2400920-can-shu-hua-lumina-2-0ti-du-se-qia-zi-ding-yi-shou#profileId-2729620"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 text-sm font-medium text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                  {t("mat_gradient_generate_parametric_box_link")}
                </a>
              </div>
            </div>
          </section>
        </div>

        {lastSubmittedWorkflow === "single-stage" && (statusMessage || error || downloadUrl) && (
          <div className="flex flex-col gap-4">
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
                  <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                    {t("mat_gradient_download_title")}
                  </h3>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {t("mat_gradient_download_desc")}
                  </p>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row mt-2">
                  <a
                    data-testid="download-link"
                    href={downloadUrl}
                    download
                    className="inline-flex min-h-11 items-center justify-center rounded-2xl bg-blue-600 px-6 py-2.5 text-sm font-medium text-white shadow-[var(--shadow-control-hover)] transition-colors hover:bg-blue-700"
                  >
                    <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                    {t("mat_gradient_download_btn")}
                  </a>
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </motion.aside>
  );
}
