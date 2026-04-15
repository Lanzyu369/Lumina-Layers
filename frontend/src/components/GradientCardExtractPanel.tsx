import { useRef } from "react";
import { motion } from "framer-motion";
import { useI18n } from "../i18n/context";
import { useSingleStageStore } from "../stores/singleStageStore";
import Button from "./ui/Button";
import GradientCardCornerSelector from "./GradientCardCornerSelector";
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

const textInputClass =
  "min-h-10 w-full rounded-2xl border border-slate-200/80 bg-white/90 px-3 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-100";

export default function GradientCardExtractPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const datasetInputRef = useRef<HTMLInputElement>(null);
  const whiteImageInputRef = useRef<HTMLInputElement>(null);
  const blackImageInputRef = useRef<HTMLInputElement>(null);
  const {
    datasetFile,
    whiteImageFile,
    whiteImagePreviewUrl,
    whiteImageNaturalWidth,
    whiteImageNaturalHeight,
    whiteCornerPoints,
    blackImageFile,
    blackImagePreviewUrl,
    blackImageNaturalWidth,
    blackImageNaturalHeight,
    blackCornerPoints,
    isRotatingWhite,
    isRotatingBlack,
    isExtracting,
    extractError,
    sessionId,
    warnings,
    stageAParamsUrl,
    whiteWarpPreviewUrl,
    blackWarpPreviewUrl,
    fitSummary,
    materialSummary,
    materialName,
    isSaving,
    saveError,
    saveSuccess,
    materialFileUrl,
    savedStageAParamsUrl,
    savedMaterialSummary,
    setDatasetFile,
    setWhiteImageFile,
    setBlackImageFile,
    setWhiteImageNaturalSize,
    setBlackImageNaturalSize,
    rotateWhiteImage,
    rotateBlackImage,
    addWhiteCornerPoint,
    addBlackCornerPoint,
    clearWhiteCornerPoints,
    clearBlackCornerPoints,
    setMaterialName,
    submitExtract,
    submitSave,
  } = useSingleStageStore();

  const buildCornerHint = (count: number) =>
    count >= 4
      ? t("mat_gradient_corner_complete")
      : `${t("mat_gradient_corner_hint_prefix")}: ${count}/4`;

  const canExtract =
    !!datasetFile &&
    !!whiteImageFile &&
    !!blackImageFile &&
    whiteCornerPoints.length === 4 &&
    blackCornerPoints.length === 4;

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="gradient-card-extract-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <PanelIntro
        eyebrow={t("tab.materialManagement")}
        title={t("mat_gradient_extract_title")}
        description={t("mat_gradient_extract_desc")}
      />

      <input
        ref={datasetInputRef}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0] ?? null;
          setDatasetFile(file);
          event.target.value = "";
        }}
      />
      <input
        ref={whiteImageInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0] ?? null;
          setWhiteImageFile(file);
          event.target.value = "";
        }}
      />
      <input
        ref={blackImageInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0] ?? null;
          setBlackImageFile(file);
          event.target.value = "";
        }}
      />

      <div className={resolveDesktopSplitLayoutClass(workspace.mode)}>
        <div className={desktopPrimaryColumnClass}>
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("mat_gradient_upload_title")}
              </h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("mat_gradient_upload_desc")}
              </p>
            </div>

            <div className={`${mutedSectionCardClass} flex flex-col gap-3`}>
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("ext_single_stage_zip_label")}
                </span>
                <span className="text-sm text-slate-500 dark:text-slate-400">
                  {datasetFile?.name ?? t("mat_gradient_no_dataset_selected")}
                </span>
              </div>
              <Button
                label={t("mat_gradient_select_dataset_btn")}
                variant="secondary"
                onClick={() => datasetInputRef.current?.click()}
                className="w-full"
              />
            </div>

            <div className={`${mutedSectionCardClass} flex flex-col gap-3`}>
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("mat_gradient_white_image_label")}
                </span>
                <span className="text-sm text-slate-500 dark:text-slate-400">
                  {whiteImageFile?.name ?? t("mat_gradient_no_image_selected")}
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <Button
                  label={t("mat_gradient_select_image_btn")}
                  variant="secondary"
                  onClick={() => whiteImageInputRef.current?.click()}
                  className="w-full"
                />
                <Button
                  label={t("mat_gradient_rotate_image_btn")}
                  variant="secondary"
                  onClick={() => void rotateWhiteImage()}
                  disabled={!whiteImageFile || isRotatingWhite}
                  loading={isRotatingWhite}
                  className="w-full"
                />
                <Button
                  label={t("mat_gradient_clear_points_btn")}
                  variant="secondary"
                  onClick={clearWhiteCornerPoints}
                  disabled={whiteCornerPoints.length === 0}
                  className="w-full"
                />
              </div>
            </div>

            <div className={`${mutedSectionCardClass} flex flex-col gap-3`}>
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("mat_gradient_black_image_label")}
                </span>
                <span className="text-sm text-slate-500 dark:text-slate-400">
                  {blackImageFile?.name ?? t("mat_gradient_no_image_selected")}
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <Button
                  label={t("mat_gradient_select_image_btn")}
                  variant="secondary"
                  onClick={() => blackImageInputRef.current?.click()}
                  className="w-full"
                />
                <Button
                  label={t("mat_gradient_rotate_image_btn")}
                  variant="secondary"
                  onClick={() => void rotateBlackImage()}
                  disabled={!blackImageFile || isRotatingBlack}
                  loading={isRotatingBlack}
                  className="w-full"
                />
                <Button
                  label={t("mat_gradient_clear_points_btn")}
                  variant="secondary"
                  onClick={clearBlackCornerPoints}
                  disabled={blackCornerPoints.length === 0}
                  className="w-full"
                />
              </div>
            </div>

            <Button
              label={t("mat_gradient_compute_btn")}
              variant="primary"
              onClick={() => void submitExtract()}
              disabled={!canExtract || isExtracting}
              loading={isExtracting}
              className="w-full"
            />
          </section>

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("mat_gradient_material_name_label")}
              </h3>
            </div>
            <input
              value={materialName}
              onChange={(event) => setMaterialName(event.target.value)}
              placeholder={t("mat_gradient_material_name_placeholder")}
              className={textInputClass}
            />
            <Button
              label={t("mat_gradient_save_material_btn")}
              variant="primary"
              onClick={() => void submitSave()}
              disabled={!sessionId || !materialName.trim() || isSaving}
              loading={isSaving}
              className="w-full"
            />
          </section>
        </div>

        <div className={desktopSecondaryColumnClass}>
          {datasetFile && (
            <StatusBanner tone="info" title={t("mat_gradient_dataset_selected")}>
              {datasetFile.name}
            </StatusBanner>
          )}

          {extractError && (
            <StatusBanner data-testid="extract-error" tone="error">
              {extractError}
            </StatusBanner>
          )}

          {saveError && (
            <StatusBanner data-testid="save-error" tone="error">
              {saveError}
            </StatusBanner>
          )}

          {saveSuccess && (
            <StatusBanner data-testid="save-success" tone="success">
              {saveSuccess}
            </StatusBanner>
          )}

          <div className="grid gap-4 xl:grid-cols-2">
            <GradientCardCornerSelector
              title={t("mat_gradient_white_canvas_title")}
              hint={buildCornerHint(whiteCornerPoints.length)}
              imageUrl={whiteImagePreviewUrl}
              naturalWidth={whiteImageNaturalWidth}
              naturalHeight={whiteImageNaturalHeight}
              cornerPoints={whiteCornerPoints}
              emptyText={t("mat_gradient_empty_white_canvas")}
              onSelectPoint={addWhiteCornerPoint}
              onImageLoad={setWhiteImageNaturalSize}
            />
            <GradientCardCornerSelector
              title={t("mat_gradient_black_canvas_title")}
              hint={buildCornerHint(blackCornerPoints.length)}
              imageUrl={blackImagePreviewUrl}
              naturalWidth={blackImageNaturalWidth}
              naturalHeight={blackImageNaturalHeight}
              cornerPoints={blackCornerPoints}
              emptyText={t("mat_gradient_empty_black_canvas")}
              onSelectPoint={addBlackCornerPoint}
              onImageLoad={setBlackImageNaturalSize}
            />
          </div>

          {(whiteWarpPreviewUrl || blackWarpPreviewUrl) && (
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("mat_gradient_warp_preview_title")}
                </h3>
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                {whiteWarpPreviewUrl && (
                  <img
                    data-testid="white-warp-preview"
                    src={whiteWarpPreviewUrl}
                    alt={t("mat_gradient_white_canvas_title")}
                    className="w-full rounded-2xl border border-slate-200/80 dark:border-slate-700/80"
                  />
                )}
                {blackWarpPreviewUrl && (
                  <img
                    data-testid="black-warp-preview"
                    src={blackWarpPreviewUrl}
                    alt={t("mat_gradient_black_canvas_title")}
                    className="w-full rounded-2xl border border-slate-200/80 dark:border-slate-700/80"
                  />
                )}
              </div>
            </section>
          )}

          {stageAParamsUrl && (
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("mat_gradient_fit_output_title")}
                </h3>
              </div>
              <a
                data-testid="stage-a-link"
                href={stageAParamsUrl}
                download
                className="inline-flex min-h-11 items-center justify-center rounded-2xl border border-slate-300/80 px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:text-slate-900 dark:border-slate-600/80 dark:text-slate-200"
              >
                {t("ext_single_stage_download_stage_a")}
              </a>
            </section>
          )}

          {(materialFileUrl || savedStageAParamsUrl) && (
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("mat_gradient_saved_material_title")}
                </h3>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {materialFileUrl && (
                  <a
                    data-testid="material-link"
                    href={materialFileUrl}
                    download
                    className="inline-flex min-h-11 items-center justify-center rounded-2xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-[var(--shadow-control-hover)] transition-colors hover:bg-blue-700"
                  >
                    {t("mat_gradient_download_material_btn")}
                  </a>
                )}
                {savedStageAParamsUrl && (
                  <a
                    data-testid="saved-stage-a-link"
                    href={savedStageAParamsUrl}
                    download
                    className="inline-flex min-h-11 items-center justify-center rounded-2xl border border-slate-300/80 px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:text-slate-900 dark:border-slate-600/80 dark:text-slate-200"
                  >
                    {t("ext_single_stage_download_stage_a")}
                  </a>
                )}
              </div>
            </section>
          )}

          {materialSummary && (
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("mat_gradient_extract_output_title")}
                </h3>
              </div>
              <pre className={`${mutedSectionCardClass} overflow-x-auto text-xs leading-6 text-slate-700 dark:text-slate-200`}>
                {JSON.stringify(materialSummary, null, 2)}
              </pre>
            </section>
          )}

          {fitSummary && (
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("ext_single_stage_fit_summary_title")}
                </h3>
              </div>
              <pre className={`${mutedSectionCardClass} overflow-x-auto text-xs leading-6 text-slate-700 dark:text-slate-200`}>
                {JSON.stringify(fitSummary, null, 2)}
              </pre>
            </section>
          )}

          {savedMaterialSummary && (
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("mat_gradient_saved_material_title")}
                </h3>
              </div>
              <pre className={`${mutedSectionCardClass} overflow-x-auto text-xs leading-6 text-slate-700 dark:text-slate-200`}>
                {JSON.stringify(savedMaterialSummary, null, 2)}
              </pre>
            </section>
          )}

          {warnings.length > 0 && (
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("ext_single_stage_warnings_title")}
                </h3>
              </div>
              <div className="grid gap-2">
                {warnings.map((warning, index) => (
                  <StatusBanner key={`${warning}-${index}`} tone="warning">
                    {warning}
                  </StatusBanner>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </motion.aside>
  );
}
