import { motion } from "framer-motion";
import { useCalibrationStore } from "../stores/calibrationStore";
import { useI18n } from "../i18n/context";
import Dropdown from "./ui/Dropdown";
import Button from "./ui/Button";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { MATERIAL_PRESET_OPTIONS } from "../constants/materialPresets";
import {
  StatusBanner,
  resolvePanelSurfaceClass,
} from "./ui/panelPrimitives";
import HelpDot from "./ui/HelpDot";
import { WIKI_DOCS } from "../utils/wikiDocs";

const singleStageLayerHeightOptions = [0.04, 0.08, 0.1].map((value) => ({
  label: `${value.toFixed(2)} mm`,
  value: value.toString(),
}));

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
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="gradient-card-generate-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <div className="flex flex-col gap-6 w-full">
            <div>
                <span>{t("mat_gradient_generate_section_title")}</span>
                <HelpDot
                  title={t("mat_gradient_generate_section_title")}
                  description={t("mat_gradient_generate_section_desc")}
                  wikiPath={WIKI_DOCS.gradientCardGeneration}
                />
              </h3>
            </div>

            <div className="flex flex-col gap-4 flex-1">
              <Dropdown
                label={t("cal_single_stage_layer_height_label")}
                tooltip={t("mat_gradient_generate_section_desc")}
                wikiPath={WIKI_DOCS.gradientCardGeneration}
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

            <div>
                {t("mat_gradient_generate_notice_title")}
              </h3>
            </div>

              <p>{t("mat_gradient_generate_notice_dual_print")}</p>
                <a
                  href="https://makerworld.com.cn/zh/models/2394753-lumina2-0-ti-xing-xiao-se-se-qia-0-08ceng-gao-15ce#profileId-2721317"
                  target="_blank"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                  {t("mat_gradient_generate_online_model_link")}
                </a>
                <a
                  href="https://makerworld.com.cn/zh/models/2400920-can-shu-hua-lumina-2-0ti-du-se-qia-zi-ding-yi-shou#profileId-2729620"
                  target="_blank"
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
                <div>
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
