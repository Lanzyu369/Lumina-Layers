import { useRef } from "react";
import { motion } from "framer-motion";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import { useSingleStageStore } from "../stores/singleStageStore";
import Button from "./ui/Button";
import GradientCardCornerSelector from "./GradientCardCornerSelector";
import GradientCardWarpPreview from "./GradientCardWarpPreview";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import {
  MANUAL_ORIENTATION_LABELS,
  type ManualOrientationLabel,
  type SubstrateOrientationInfo,
} from "../api/types";
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

const isRgbTriplet = (value: number[] | null | undefined): value is [number, number, number] =>
  Array.isArray(value) && value.length === 3;

const toRgbCss = (rgb: [number, number, number]) =>
  `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;

const toHex = (rgb: [number, number, number]) =>
  `#${rgb
    .map((channel) => Math.max(0, Math.min(255, channel)).toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;

const formatMetricValue = (value: number | null | undefined, digits = 3) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";

const AUTO_ORIENTATION_VALUE = "__auto__";

const selectClass =
  "min-h-10 w-full rounded-2xl border border-slate-200/80 bg-white/90 px-3 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-100";

const badgeClass =
  "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold leading-4";

const badgeToneFlat = `${badgeClass} bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300`;
const badgeToneManual = `${badgeClass} bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300`;

const orientationOptionKey = (label: ManualOrientationLabel) =>
  `mat_gradient_orientation_option_${label}` as const;

const OrientationSelect = ({
  label,
  value,
  onChange,
  testId,
}: {
  label: string;
  value: ManualOrientationLabel | null;
  onChange: (value: ManualOrientationLabel | null) => void;
  testId: string;
}) => {
  const { t } = useI18n();
  const selectValue = value ?? AUTO_ORIENTATION_VALUE;
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
        {label}
      </span>
      <select
        data-testid={testId}
        value={selectValue}
        onChange={(event) => {
          const next = event.target.value;
          onChange(
            next === AUTO_ORIENTATION_VALUE
              ? null
              : (next as ManualOrientationLabel),
          );
        }}
        className={selectClass}
      >
        <option value={AUTO_ORIENTATION_VALUE}>
          {t("mat_gradient_orientation_option_auto")}
        </option>
        {MANUAL_ORIENTATION_LABELS.map((orientation) => (
          <option key={orientation} value={orientation}>
            {t(orientationOptionKey(orientation))}
          </option>
        ))}
      </select>
    </label>
  );
};

const SubstrateSignalCard = ({
  label,
  info,
  testId,
}: {
  label: string;
  info: SubstrateOrientationInfo | null | undefined;
  testId: string;
}) => {
  const { t } = useI18n();
  if (!info) {
    return null;
  }
  return (
    <div
      data-testid={testId}
      className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50"
    >
      <dt className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
        <span>{label}</span>
        {info.flat ? (
          <span data-testid={`${testId}-flat-badge`} className={badgeToneFlat}>
            {t("mat_gradient_signal_flat_badge")}
          </span>
        ) : null}
        {info.manual_override ? (
          <span data-testid={`${testId}-manual-badge`} className={badgeToneManual}>
            {t("mat_gradient_manual_override_badge")}
          </span>
        ) : null}
      </dt>
      <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
        {formatMetricValue(info.signal_strength, 4)}
      </dd>
    </div>
  );
};

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
    orientationRanking,
    manualWhiteOrientation,
    manualBlackOrientation,
    materialName,
    materialBrand,
    verificationTargetDirectoryName,
    verificationTargetCount,
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
    setMaterialBrand,
    setManualWhiteOrientation,
    setManualBlackOrientation,
    clearMaterialVerification,
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

  const estimatedRgb = isRgbTriplet(materialSummary?.estimated_rgb)
    ? materialSummary.estimated_rgb
    : null;
  const estimatedRgbLabel = estimatedRgb ? estimatedRgb.join(", ") : "-";
  const estimatedHex = estimatedRgb ? toHex(estimatedRgb) : "-";
  const meanDeltaE = fitSummary?.overall_validation?.mean_delta_e ?? null;
  const maxDeltaE = fitSummary?.overall_validation?.max_delta_e ?? null;
  const rmseLinear = fitSummary?.overall_validation?.rmse_linear ?? null;
  const channelRmse = fitSummary?.overall_validation?.channel_rmse ?? [];
  const channelRmseLabel = channelRmse.length >= 3
    ? tRuntime("mat_gradient_channel_rmse_value", {
        r: formatMetricValue(channelRmse[0], 4),
        g: formatMetricValue(channelRmse[1], 4),
        b: formatMetricValue(channelRmse[2], 4),
      })
    : "-";
  const sampleBoxes = materialSummary?.sample_boxes ?? [];
  const warpWidth = materialSummary?.warp_width_px ?? null;
  const warpHeight = materialSummary?.warp_height_px ?? null;
  const bestCandidate = orientationRanking?.top_candidates?.[0] ?? null;
  const orientationReliable = orientationRanking?.orientation_reliable ?? null;
  const deltaEGap = orientationRanking?.delta_e_gap ?? null;
  const whiteOrientationInfo = orientationRanking?.white_orientation_info ?? null;
  const blackOrientationInfo = orientationRanking?.black_orientation_info ?? null;
  const flatSubstrateHintVisible =
    (whiteOrientationInfo?.flat && !whiteOrientationInfo.manual_override) ||
    (blackOrientationInfo?.flat && !blackOrientationInfo.manual_override);
  const isVerificationMode = !!verificationTargetDirectoryName;
  const verificationRunCount = Math.max(
    1,
    Number(savedMaterialSummary?.verification_count ?? verificationTargetCount ?? 1),
  );
  const saveButtonLabel = isVerificationMode
    ? t("mat_gradient_save_verification_btn")
    : t("mat_gradient_save_material_btn");

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

      {isVerificationMode ? (
        <StatusBanner
          data-testid="gradient-card-verification-mode-banner"
          tone="info"
          title={t("mat_gradient_verification_mode_title")}
        >
          {tRuntime("mat_gradient_verification_mode_desc", {
            materialName: materialName || "-",
            count: verificationRunCount,
          })}
        </StatusBanner>
      ) : null}

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

            <div
              data-testid="orientation-control-card"
              className={`${mutedSectionCardClass} flex flex-col gap-3`}
            >
              <div>
                <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                  {t("mat_gradient_manual_orientation_title")}
                </h4>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {t("mat_gradient_manual_orientation_desc")}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <OrientationSelect
                  label={t("mat_gradient_manual_white_orientation_label")}
                  value={manualWhiteOrientation}
                  onChange={setManualWhiteOrientation}
                  testId="manual-white-orientation-select"
                />
                <OrientationSelect
                  label={t("mat_gradient_manual_black_orientation_label")}
                  value={manualBlackOrientation}
                  onChange={setManualBlackOrientation}
                  testId="manual-black-orientation-select"
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
              dataTestId="white-corner-selector-preview"
              emptyStateTestId="white-corner-selector-empty-state"
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
              dataTestId="black-corner-selector-preview"
              emptyStateTestId="black-corner-selector-empty-state"
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
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {t("mat_gradient_sample_boxes_hint")}
                </p>
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                {whiteWarpPreviewUrl && (
                  <GradientCardWarpPreview
                    title={t("mat_gradient_white_canvas_title")}
                    imageUrl={whiteWarpPreviewUrl}
                    alt={t("mat_gradient_white_canvas_title")}
                    sampleBoxes={sampleBoxes}
                    warpWidth={warpWidth}
                    warpHeight={warpHeight}
                    testIdPrefix="white-warp-preview"
                  />
                )}
                {blackWarpPreviewUrl && (
                  <GradientCardWarpPreview
                    title={t("mat_gradient_black_canvas_title")}
                    imageUrl={blackWarpPreviewUrl}
                    alt={t("mat_gradient_black_canvas_title")}
                    sampleBoxes={sampleBoxes}
                    warpWidth={warpWidth}
                    warpHeight={warpHeight}
                    testIdPrefix="black-warp-preview"
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
              <div className="grid gap-3 lg:grid-cols-[minmax(0,11rem)_minmax(0,1fr)]">
                <div
                  data-testid="estimated-material-color"
                  className="min-h-40 rounded-3xl border border-slate-200/80 dark:border-slate-700/80"
                  style={estimatedRgb ? { backgroundColor: toRgbCss(estimatedRgb) } : undefined}
                />
                <div className={`${mutedSectionCardClass} flex flex-col justify-between gap-4`}>
                  <div>
                    <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {t("mat_gradient_estimated_color_title")}
                    </h4>
                  </div>
                  <dl className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50">
                      <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                        {t("mat_gradient_rgb_label")}
                      </dt>
                      <dd data-testid="estimated-material-color-rgb" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {estimatedRgbLabel}
                      </dd>
                    </div>
                    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50">
                      <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                        {t("mat_gradient_hex_label")}
                      </dt>
                      <dd data-testid="estimated-material-color-hex" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {estimatedHex}
                      </dd>
                    </div>
                  </dl>
                  <dl className="grid gap-3 sm:grid-cols-3">
                    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50">
                      <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                        {t("mat_gradient_mean_delta_e_label")}
                      </dt>
                      <dd data-testid="estimated-material-fit-mean-delta-e" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {formatMetricValue(meanDeltaE, 3)}
                      </dd>
                    </div>
                    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50">
                      <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                        {t("mat_gradient_max_delta_e_label")}
                      </dt>
                      <dd data-testid="estimated-material-fit-max-delta-e" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {formatMetricValue(maxDeltaE, 3)}
                      </dd>
                    </div>
                    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50">
                      <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                        {t("mat_gradient_rmse_linear_label")}
                      </dt>
                      <dd data-testid="estimated-material-fit-rmse-linear" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {formatMetricValue(rmseLinear, 4)}
                      </dd>
                    </div>
                    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50 sm:col-span-3">
                      <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                        {t("mat_gradient_channel_rmse_label")}
                      </dt>
                      <dd data-testid="estimated-material-fit-channel-rmse" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                        {channelRmseLabel}
                      </dd>
                    </div>
                  </dl>
                  {bestCandidate && (
                    <div className="mt-2 space-y-2">
                      <div className="flex items-center gap-2">
                        <h5 className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
                          {t("mat_gradient_orientation_title")}
                        </h5>
                        {orientationReliable !== null && (
                          <span
                            data-testid="orientation-reliability-badge"
                            className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold leading-4 ${
                              orientationReliable
                                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                                : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
                            }`}
                          >
                            {orientationReliable
                              ? t("mat_gradient_orientation_reliable")
                              : t("mat_gradient_orientation_unreliable")}
                          </span>
                        )}
                      </div>
                      <dl className="grid gap-3 sm:grid-cols-3">
                        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50">
                          <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                            {t("mat_gradient_white_orientation_label")}
                          </dt>
                          <dd data-testid="orientation-white" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                            {bestCandidate.white_orientation}
                          </dd>
                        </div>
                        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50">
                          <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                            {t("mat_gradient_black_orientation_label")}
                          </dt>
                          <dd data-testid="orientation-black" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                            {bestCandidate.black_orientation}
                          </dd>
                        </div>
                        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-700/80 dark:bg-slate-950/50">
                          <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                            {t("mat_gradient_delta_e_gap_label")}
                          </dt>
                          <dd data-testid="orientation-delta-e-gap" className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                            {formatMetricValue(deltaEGap, 4)}
                          </dd>
                        </div>
                        <SubstrateSignalCard
                          label={t("mat_gradient_white_signal_label")}
                          info={whiteOrientationInfo}
                          testId="white-orientation-signal"
                        />
                        <SubstrateSignalCard
                          label={t("mat_gradient_black_signal_label")}
                          info={blackOrientationInfo}
                          testId="black-orientation-signal"
                        />
                      </dl>
                      {flatSubstrateHintVisible ? (
                        <StatusBanner
                          data-testid="orientation-flat-substrate-hint"
                          tone="warning"
                        >
                          {t("mat_gradient_signal_flat_hint")}
                        </StatusBanner>
                      ) : null}
                    </div>
                  )}
                </div>
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

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {isVerificationMode
                  ? t("mat_gradient_verification_name_label")
                  : t("mat_gradient_material_name_label")}
              </h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {isVerificationMode
                  ? tRuntime("mat_gradient_verification_name_desc", {
                      count: verificationRunCount,
                    })
                  : t("mat_gradient_material_name_placeholder")}
              </p>
            </div>
            <input
              value={materialName}
              onChange={(event) => setMaterialName(event.target.value)}
              placeholder={t("mat_gradient_material_name_placeholder")}
              className={textInputClass}
              disabled={isVerificationMode}
            />
            {!isVerificationMode && (
              <div className="flex flex-col gap-2">
                <div className="flex items-baseline justify-between gap-3">
                  <label
                    htmlFor="gradient-card-material-brand"
                    className="text-sm font-semibold text-slate-900 dark:text-slate-50"
                  >
                    {t("mat_gradient_brand_label")}
                  </label>
                  <span className="text-xs text-slate-400 dark:text-slate-500">
                    {t("mat_gradient_brand_hint")}
                  </span>
                </div>
                <input
                  id="gradient-card-material-brand"
                  value={materialBrand}
                  onChange={(event) => setMaterialBrand(event.target.value)}
                  placeholder={t("mat_gradient_brand_placeholder")}
                  className={textInputClass}
                  data-testid="gradient-card-material-brand-input"
                />
              </div>
            )}
            {isVerificationMode ? (
              <div className="grid gap-3 sm:grid-cols-3">
                <Button
                  label={t("mat_gradient_save_merge_btn")}
                  variant="primary"
                  onClick={() => void submitSave("merge")}
                  disabled={!sessionId || !materialName.trim() || isSaving}
                  loading={isSaving}
                  className="w-full"
                />
                <Button
                  label={t("mat_gradient_save_override_btn")}
                  variant="secondary"
                  onClick={() => void submitSave("override")}
                  disabled={!sessionId || !materialName.trim() || isSaving}
                  loading={isSaving}
                  className="w-full"
                />
                <Button
                  label={t("mat_gradient_cancel_verification_btn")}
                  variant="secondary"
                  onClick={clearMaterialVerification}
                  disabled={isSaving}
                  className="w-full"
                />
              </div>
            ) : (
              <Button
                label={saveButtonLabel}
                variant="primary"
                onClick={() => void submitSave()}
                disabled={!sessionId || !materialName.trim() || isSaving}
                loading={isSaving}
                className="w-full"
              />
            )}
          </section>
        </div>
      </div>
    </motion.aside>
  );
}
