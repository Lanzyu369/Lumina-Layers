import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import { listGradientCardMaterials } from "../api/extractor";
import { useSingleStageStore } from "../stores/singleStageStore";
import Button from "./ui/Button";
import Slider from "./ui/Slider";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "./ui/icons";
import GradientCardCornerSelector from "./GradientCardCornerSelector";
import GradientCardWarpPreview from "./GradientCardWarpPreview";
import Dropdown from "./ui/Dropdown";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { type SubstrateOrientationInfo } from "../api/types";
import {
  GRADIENT_CARD_ANCHOR_CORNERS,
  type GradientCardAnchorCorner,
} from "../utils/gradientCardAnchor";
import {
  PanelIntro,
  StatusBanner,
  cx,
  mutedSectionCardClass,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";
import WikiTooltip from "./ui/WikiTooltip";

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

const AUTO_ANCHOR_VALUE = "__auto__";

const badgeClass =
  "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold leading-4";

const badgeToneFlat = `${badgeClass} bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300`;
const badgeToneManual = `${badgeClass} bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300`;

const anchorOptionKey = (corner: GradientCardAnchorCorner) =>
  `mat_gradient_anchor_option_${corner}` as const;

const brandMenuClass =
  "absolute z-20 mt-2 w-full overflow-hidden rounded-2xl border border-slate-200/85 bg-slate-100/96 shadow-[var(--shadow-control)] backdrop-blur-xl dark:border-slate-700/85 dark:bg-slate-950/96";

const brandMenuOptionClass =
  "flex w-full items-start rounded-[18px] px-3 py-2.5 text-left text-sm leading-6 text-slate-700 transition-colors duration-150 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-900";

const AnchorCornerSelect = ({
  label,
  value,
  onChange,
  testId,
  tooltip,
}: {
  label: string;
  value: GradientCardAnchorCorner | null;
  onChange: (value: GradientCardAnchorCorner | null) => void;
  testId: string;
  tooltip?: string;
}) => {
  const { t } = useI18n();

  const options = [
    { label: t("mat_gradient_anchor_option_auto"), value: AUTO_ANCHOR_VALUE },
    ...GRADIENT_CARD_ANCHOR_CORNERS.map((corner) => ({
      label: t(anchorOptionKey(corner)),
      value: corner,
    })),
  ];

  return (
    <div data-testid={testId}>
      <Dropdown
        label={label}
        value={value ?? AUTO_ANCHOR_VALUE}
        onChange={(next) =>
          onChange(
            next === AUTO_ANCHOR_VALUE
              ? null
              : (next as GradientCardAnchorCorner),
          )
        }
        options={options}
        labelAccessory={
          tooltip ? (
            <WikiTooltip title={label} description={tooltip}>
              <span className="flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-slate-200 text-[10px] font-bold text-slate-500 transition-colors hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-400 dark:hover:bg-slate-600">
                ?
              </span>
            </WikiTooltip>
          ) : undefined
        }
      />
    </div>
  );
};

const BrandSelect = ({
  value,
  onChange,
  options,
  isLoading,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  isLoading: boolean;
}) => {
  const { t } = useI18n();
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);

  const normalizedValue = value.trim().toLocaleLowerCase();
  const filteredOptions = useMemo(() => {
    if (!normalizedValue) {
      return options;
    }
    return options.filter((option) => option.toLocaleLowerCase().includes(normalizedValue));
  }, [normalizedValue, options]);

  const hasExactMatch = useMemo(
    () => options.some((option) => option.toLocaleLowerCase() === normalizedValue),
    [normalizedValue, options],
  );

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [open]);

  const showCreateOption = value.trim().length > 0 && !hasExactMatch;

  return (
    <div ref={rootRef} className="flex flex-col gap-2">
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
      <div className="relative">
        <input
          id="gradient-card-material-brand"
          value={value}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setOpen(false);
            }
            if (event.key === "Enter" && value.trim()) {
              setOpen(false);
            }
          }}
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          aria-label={t("mat_gradient_brand_label")}
          placeholder={t("mat_gradient_brand_placeholder")}
          className={`${textInputClass} pr-10`}
          data-testid="gradient-card-material-brand-input"
        />
        <button
          type="button"
          onClick={() => setOpen((previous) => !previous)}
          className="absolute inset-y-0 right-2 inline-flex items-center justify-center rounded-lg px-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
          aria-label={t("mat_gradient_brand_label")}
          data-testid="gradient-card-material-brand-toggle"
        >
          <svg className={`h-4 w-4 transition-transform duration-200 ${open ? "rotate-180" : ""}`} viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.1 1.02l-4.25 4.52a.75.75 0 01-1.1 0L5.21 8.25a.75.75 0 01.02-1.04z" />
          </svg>
        </button>

        {open ? (
          <div className={brandMenuClass}>
            <div role="listbox" className="max-h-64 overflow-y-auto p-2">
              {isLoading ? (
                <div
                  className="px-3 py-2 text-sm text-slate-500 dark:text-slate-400"
                  data-testid="gradient-card-material-brand-loading"
                >
                  {t("mat_gradient_brand_loading")}
                </div>
              ) : (
                <>
                  {showCreateOption ? (
                    <button
                      type="button"
                      role="option"
                      onClick={() => {
                        onChange(value.trim());
                        setOpen(false);
                      }}
                      className={brandMenuOptionClass}
                      data-testid="gradient-card-material-brand-create-option"
                    >
                      {tRuntime("mat_gradient_brand_create_option", { brand: value.trim() })}
                    </button>
                  ) : null}
                  {filteredOptions.map((option) => (
                    <button
                      key={option}
                      type="button"
                      role="option"
                      aria-selected={option.toLocaleLowerCase() === normalizedValue}
                      onClick={() => {
                        onChange(option);
                        setOpen(false);
                      }}
                      className={brandMenuOptionClass}
                    >
                      {option}
                    </button>
                  ))}
                  {!showCreateOption && filteredOptions.length === 0 ? (
                    <div
                      className="px-3 py-2 text-sm text-slate-500 dark:text-slate-400"
                      data-testid="gradient-card-material-brand-empty"
                    >
                      {t("mat_gradient_brand_empty")}
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
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

const CornerNudgeControl = ({
  cornerPoints,
  activePointIndex,
  onActivePointChange,
  nudgeStep,
  onNudgeStepChange,
  onNudge,
}: {
  cornerPoints: [number, number][];
  activePointIndex: number | null;
  onActivePointChange: (index: number | null) => void;
  nudgeStep: number;
  onNudgeStepChange: (val: number) => void;
  onNudge: (dx: number, dy: number) => void;
}) => {
  const { t } = useI18n();
  const placedCornerCount = cornerPoints.length;
  const nudgeEnabled = placedCornerCount > 0 && activePointIndex !== null;
  const activeCornerPoint = activePointIndex !== null && activePointIndex >= 0 && activePointIndex < placedCornerCount ? cornerPoints[activePointIndex] : null;

  return (
    <div className="flex flex-col gap-4 mt-2">
      {placedCornerCount === 0 ? (
        <StatusBanner tone="info">
          {t("ext_nudge_hint_empty")}
        </StatusBanner>
      ) : (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {t("ext_nudge_active_corner_label")}
          </span>
          <div role="radiogroup" aria-label={t("ext_nudge_active_corner_label")} className="grid grid-cols-4 gap-2">
            {[0, 1, 2, 3].map((idx) => {
              const placed = idx < placedCornerCount;
              const selected = placed && activePointIndex === idx;
              return (
                <button
                  key={idx}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={!placed}
                  onClick={() => onActivePointChange(idx)}
                  className={cx(
                    "flex min-h-9 items-center justify-center rounded-xl border px-2 py-1 text-sm font-medium transition-colors",
                    selected
                      ? "border-blue-500 bg-blue-500 text-white shadow-[var(--shadow-control-hover)]"
                      : "border-slate-200/80 bg-white/70 text-slate-700 hover:border-slate-300 hover:bg-white/90 dark:border-slate-700/80 dark:bg-slate-900/55 dark:text-slate-200 dark:hover:border-slate-600",
                    !placed && "cursor-not-allowed opacity-45"
                  )}
                >
                  {idx + 1}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <Slider
        label={t("ext_nudge_step_label")}
        value={nudgeStep}
        min={1}
        max={10}
        step={1}
        onChange={onNudgeStepChange}
      />
      <div className="grid grid-cols-3 gap-2 justify-items-center">
        <div />
        <Button label={t("ext_nudge_up")} icon={<ChevronUp />} variant="secondary" size="icon" onClick={() => onNudge(0, -1)} disabled={!nudgeEnabled} />
        <div />
        <Button label={t("ext_nudge_left")} icon={<ChevronLeft />} variant="secondary" size="icon" onClick={() => onNudge(-1, 0)} disabled={!nudgeEnabled} />
        <div className="flex items-center justify-center text-xs tabular-nums text-slate-500 dark:text-slate-400">
          {activeCornerPoint ? `(${Math.round(activeCornerPoint[0])}, ${Math.round(activeCornerPoint[1])})` : "—"}
        </div>
        <Button label={t("ext_nudge_right")} icon={<ChevronRight />} variant="secondary" size="icon" onClick={() => onNudge(1, 0)} disabled={!nudgeEnabled} />
        <div />
        <Button label={t("ext_nudge_down")} icon={<ChevronDown />} variant="secondary" size="icon" onClick={() => onNudge(0, 1)} disabled={!nudgeEnabled} />
        <div />
      </div>
    </div>
  );
};

const InlineStatusMessage = ({
  tone,
  message,
  onDismiss,
  testId,
}: {
  tone: "error" | "success" | "info" | "warning";
  message: string;
  onDismiss: () => void;
  testId?: string;
}) => {
  useEffect(() => {
    const timer = setTimeout(() => {
      onDismiss();
    }, 5000);
    return () => clearTimeout(timer);
  }, [message, onDismiss]);

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 10 }}
      transition={{ duration: 0.2 }}
    >
      <StatusBanner data-testid={testId} tone={tone}>
        {message}
      </StatusBanner>
    </motion.div>
  );
};

export default function GradientCardExtractPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const datasetInputRef = useRef<HTMLInputElement>(null);
  const whiteImageInputRef = useRef<HTMLInputElement>(null);
  const blackImageInputRef = useRef<HTMLInputElement>(null);
  const [detailsDialogOpen, setDetailsDialogOpen] = useState(false);
  const [brandOptions, setBrandOptions] = useState<string[]>([]);
  const [brandOptionsLoading, setBrandOptionsLoading] = useState(false);
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
    activeCanvas,
    activeCornerIndex,
    nudgeStep,
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
    manualWhiteAnchor,
    manualBlackAnchor,
    materialName,
    materialBrand,
    verificationTargetDirectoryName,
    verificationTargetCount,
    isSaving,
    saveError,
    saveSuccess,
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
    setActiveCanvasAndCorner,
    setNudgeStep,
    nudgeActiveCorner,
    setMaterialName,
    setMaterialBrand,
    setManualWhiteAnchor,
    setManualBlackAnchor,
    clearMaterialVerification,
    submitExtract,
    submitSave,
    clearExtractError,
    clearSaveMessages,
  } = useSingleStageStore();

  const buildCornerHint = (count: number) =>
    count >= 4
      ? t("mat_gradient_corner_complete")
      : `${t("mat_gradient_corner_hint_prefix")}: ${count}/4 · ${t("mat_gradient_corner_pick_order_hint")}`;

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
  const hasDetailInfo = !!stageAParamsUrl || !!materialSummary || !!fitSummary || !!savedMaterialSummary;

  useEffect(() => {
    if (isVerificationMode) {
      setBrandOptions([]);
      setBrandOptionsLoading(false);
      return undefined;
    }

    let cancelled = false;
    setBrandOptionsLoading(true);

    void listGradientCardMaterials()
      .then((response) => {
        if (cancelled) {
          return;
        }
        const nextOptions = Array.from(new Set(
          (response.materials ?? [])
            .map((item) => (typeof item.brand === "string" ? item.brand.trim() : ""))
            .filter((brand) => brand.length > 0),
        )).sort((left, right) => left.localeCompare(right));
        setBrandOptions(nextOptions);
      })
      .catch(() => {
        if (!cancelled) {
          setBrandOptions([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setBrandOptionsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [isVerificationMode]);

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
        activeCanvas,
        activeCornerIndex: activeIdx,
      } = useSingleStageStore.getState();
      if (activeCanvas === null || activeIdx === null) {
        return;
      }
      e.preventDefault();
      switch (key) {
        case "ArrowUp":
          useSingleStageStore.getState().nudgeActiveCorner(0, -1);
          break;
        case "ArrowDown":
          useSingleStageStore.getState().nudgeActiveCorner(0, 1);
          break;
        case "ArrowLeft":
          useSingleStageStore.getState().nudgeActiveCorner(-1, 0);
          break;
        case "ArrowRight":
          useSingleStageStore.getState().nudgeActiveCorner(1, 0);
          break;
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="gradient-card-extract-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <PanelIntro
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

      <div className="flex flex-col gap-6 w-full">
        <div className="grid gap-6 lg:grid-cols-2 w-full">
<section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4 h-full`}>
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
              {t("mat_gradient_upload_title")}
            </h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t("mat_gradient_upload_desc")}
            </p>
          </div>
            <div className="flex flex-col gap-3 mt-auto">
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
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
        </section>
<section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4 h-full`}>
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
            <div className="flex flex-col gap-4 flex-1">
              <input
                value={materialName}
                onChange={(event) => setMaterialName(event.target.value)}
                placeholder={t("mat_gradient_material_name_placeholder")}
                className={textInputClass}
                disabled={isVerificationMode}
              />
              {!isVerificationMode && (
                <BrandSelect
                  value={materialBrand}
                  onChange={setMaterialBrand}
                  options={brandOptions}
                  isLoading={brandOptionsLoading}
                />
              )}
            </div>
            <div className="mt-auto pt-2">
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
            </div>
          </section>
</div>

        <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-5 xl:grid xl:grid-cols-[minmax(20rem,24rem)_minmax(0,1fr)] xl:items-stretch`}>
          <div className="flex flex-col gap-4">
            <div className={`${mutedSectionCardClass} flex flex-col gap-3`}>
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("mat_gradient_white_image_label")}
                </span>
                <span className="text-sm text-slate-500 dark:text-slate-400 break-all">
                  {whiteImageFile?.name ?? t("mat_gradient_no_image_selected")}
                </span>
              </div>
              <Button
                label={t("mat_gradient_select_image_btn")}
                variant="secondary"
                onClick={() => whiteImageInputRef.current?.click()}
                className="w-full"
              />
              <div className="grid gap-3 grid-cols-2">
                <Button
                  label={t("mat_gradient_rotate_ccw_btn")}
                  variant="secondary"
                  onClick={() => void rotateWhiteImage("ccw")}
                  disabled={!whiteImageFile || isRotatingWhite}
                  loading={isRotatingWhite}
                  className="w-full"
                  data-testid="white-rotate-ccw-btn"
                />
                <Button
                  label={t("mat_gradient_rotate_cw_btn")}
                  variant="secondary"
                  onClick={() => void rotateWhiteImage("cw")}
                  disabled={!whiteImageFile || isRotatingWhite}
                  loading={isRotatingWhite}
                  className="w-full"
                  data-testid="white-rotate-cw-btn"
                />
              </div>
              <Button
                label={t("mat_gradient_clear_points_btn")}
                variant="secondary"
                onClick={clearWhiteCornerPoints}
                disabled={whiteCornerPoints.length === 0}
                className="w-full"
              />
            </div>
            <div className={`${mutedSectionCardClass} flex flex-col gap-3`}>
              <AnchorCornerSelect
                label={t("mat_gradient_white_anchor_label")}
                value={manualWhiteAnchor}
                onChange={setManualWhiteAnchor}
                testId="manual-white-anchor-select"
                tooltip={t("mat_gradient_anchor_section_desc")}
              />
            </div>
            <div className={`${mutedSectionCardClass} flex flex-col gap-3`}>
              <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                {t("ext_nudge_section")}
              </h4>
              <CornerNudgeControl
                 cornerPoints={whiteCornerPoints}
                 activePointIndex={activeCanvas === "white" ? activeCornerIndex : null}
                 onActivePointChange={(idx) => setActiveCanvasAndCorner("white", idx)}
                 nudgeStep={nudgeStep}
                 onNudgeStepChange={setNudgeStep}
                 onNudge={nudgeActiveCorner}
              />
            </div>
          </div>
          <div className="flex min-w-0 flex-col xl:[&>section]:flex-1 xl:[&>section]:min-h-0 xl:[&>section>div:last-child]:flex-1">
            <GradientCardCornerSelector
              title={t("mat_gradient_white_canvas_title")}
              hint={buildCornerHint(whiteCornerPoints.length)}
              imageUrl={whiteImagePreviewUrl}
              naturalWidth={whiteImageNaturalWidth}
              naturalHeight={whiteImageNaturalHeight}
              cornerPoints={whiteCornerPoints}
              activePointIndex={activeCanvas === "white" ? activeCornerIndex : null}
              emptyText={t("mat_gradient_empty_white_canvas")}
              dataTestId="white-corner-selector-preview"
              emptyStateTestId="white-corner-selector-empty-state"
              onSelectPoint={addWhiteCornerPoint}
              onImageLoad={setWhiteImageNaturalSize}
            />
          </div>
        </section>

        <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-5 xl:grid xl:grid-cols-[minmax(20rem,24rem)_minmax(0,1fr)] xl:items-stretch`}>
          <div className="flex flex-col gap-4">
            <div className={`${mutedSectionCardClass} flex flex-col gap-3`}>
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("mat_gradient_black_image_label")}
                </span>
                <span className="text-sm text-slate-500 dark:text-slate-400 break-all">
                  {blackImageFile?.name ?? t("mat_gradient_no_image_selected")}
                </span>
              </div>
              <Button
                label={t("mat_gradient_select_image_btn")}
                variant="secondary"
                onClick={() => blackImageInputRef.current?.click()}
                className="w-full"
              />
              <div className="grid gap-3 grid-cols-2">
                <Button
                  label={t("mat_gradient_rotate_ccw_btn")}
                  variant="secondary"
                  onClick={() => void rotateBlackImage("ccw")}
                  disabled={!blackImageFile || isRotatingBlack}
                  loading={isRotatingBlack}
                  className="w-full"
                  data-testid="black-rotate-ccw-btn"
                />
                <Button
                  label={t("mat_gradient_rotate_cw_btn")}
                  variant="secondary"
                  onClick={() => void rotateBlackImage("cw")}
                  disabled={!blackImageFile || isRotatingBlack}
                  loading={isRotatingBlack}
                  className="w-full"
                  data-testid="black-rotate-cw-btn"
                />
              </div>
              <Button
                label={t("mat_gradient_clear_points_btn")}
                variant="secondary"
                onClick={clearBlackCornerPoints}
                disabled={blackCornerPoints.length === 0}
                className="w-full"
              />
            </div>
            <div className={`${mutedSectionCardClass} flex flex-col gap-3`}>
              <AnchorCornerSelect
                label={t("mat_gradient_black_anchor_label")}
                value={manualBlackAnchor}
                onChange={setManualBlackAnchor}
                testId="manual-black-anchor-select"
                tooltip={t("mat_gradient_anchor_section_desc")}
              />
            </div>
            <div className={`${mutedSectionCardClass} flex flex-col gap-3`}>
              <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                {t("ext_nudge_section")}
              </h4>
              <CornerNudgeControl
                 cornerPoints={blackCornerPoints}
                 activePointIndex={activeCanvas === "black" ? activeCornerIndex : null}
                 onActivePointChange={(idx) => setActiveCanvasAndCorner("black", idx)}
                 nudgeStep={nudgeStep}
                 onNudgeStepChange={setNudgeStep}
                 onNudge={nudgeActiveCorner}
              />
            </div>
          </div>
          <div className="flex min-w-0 flex-col xl:[&>section]:flex-1 xl:[&>section]:min-h-0 xl:[&>section>div:last-child]:flex-1">
            <GradientCardCornerSelector
              title={t("mat_gradient_black_canvas_title")}
              hint={buildCornerHint(blackCornerPoints.length)}
              imageUrl={blackImagePreviewUrl}
              naturalWidth={blackImageNaturalWidth}
              naturalHeight={blackImageNaturalHeight}
              cornerPoints={blackCornerPoints}
              activePointIndex={activeCanvas === "black" ? activeCornerIndex : null}
              emptyText={t("mat_gradient_empty_black_canvas")}
              dataTestId="black-corner-selector-preview"
              emptyStateTestId="black-corner-selector-empty-state"
              onSelectPoint={addBlackCornerPoint}
              onImageLoad={setBlackImageNaturalSize}
            />
          </div>
        </section>

        <div className="flex flex-col gap-5">
          <AnimatePresence mode="popLayout">
            {extractError && (
              <InlineStatusMessage
                key="extractError"
                testId="extract-error"
                tone="error"
                message={extractError}
                onDismiss={clearExtractError}
              />
            )}
            {saveError && (
              <InlineStatusMessage
                key="saveError"
                testId="save-error"
                tone="error"
                message={saveError}
                onDismiss={clearSaveMessages}
              />
            )}
            {saveSuccess && (
              <InlineStatusMessage
                key="saveSuccess"
                testId="save-success"
                tone="success"
                message={saveSuccess}
                onDismiss={clearSaveMessages}
              />
            )}
          </AnimatePresence>
          <div data-testid="extract-action-container">
            <Button
              label={t("mat_gradient_compute_btn")}
              variant="primary"
              onClick={() => void submitExtract()}
              disabled={!canExtract || isExtracting}
              loading={isExtracting}
              className="w-full !py-4 text-base"
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
              {hasDetailInfo ? (
                <div className="flex justify-end">
                  <Button
                    label={t("mat_gradient_view_details_btn")}
                    variant="secondary"
                    onClick={() => setDetailsDialogOpen(true)}
                    className="w-full sm:w-auto"
                  />
                </div>
              ) : null}
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

          

          {detailsDialogOpen && hasDetailInfo ? (
            <div
              className="fixed inset-0 z-[9999] flex items-center justify-center backdrop-blur-sm"
              style={{ background: "var(--surface-scrim)" }}
              onClick={() => setDetailsDialogOpen(false)}
              data-testid="gradient-card-details-dialog-overlay"
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="gradient-card-details-dialog-title"
                className="relative mx-4 flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border shadow-2xl"
                style={{
                  borderColor: "var(--surface-outline)",
                  background: "var(--surface-panel-strong)",
                }}
                onClick={(event) => event.stopPropagation()}
                data-testid="gradient-card-details-dialog"
              >
                <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 dark:border-slate-700">
                  <div className="flex flex-col gap-1">
                    <h3
                      id="gradient-card-details-dialog-title"
                      className="text-base font-semibold text-slate-900 dark:text-slate-50"
                    >
                      {t("mat_gradient_details_dialog_title")}
                    </h3>
                    <p className="text-sm text-slate-500 dark:text-slate-400">
                      {t("mat_gradient_details_dialog_desc")}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setDetailsDialogOpen(false)}
                    className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                    aria-label={t("mat_gradient_details_close_btn")}
                  >
                    ✕
                  </button>
                </div>

                <div className="flex-1 overflow-y-auto px-5 py-4">
                  <div className="flex flex-col gap-4">
                    {stageAParamsUrl ? (
                      <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
                        <div>
                          <h4 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                            {t("mat_gradient_fit_output_title")}
                          </h4>
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
                    ) : null}

                    {materialSummary ? (
                      <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
                        <div>
                          <h4 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                            {t("mat_gradient_extract_output_title")}
                          </h4>
                        </div>
                        <pre
                          data-testid="material-summary-json"
                          className={`${mutedSectionCardClass} overflow-x-auto text-xs leading-6 text-slate-700 dark:text-slate-200`}
                        >
                          {JSON.stringify(materialSummary, null, 2)}
                        </pre>
                      </section>
                    ) : null}

                    {fitSummary ? (
                      <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
                        <div>
                          <h4 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                            {t("ext_single_stage_fit_summary_title")}
                          </h4>
                        </div>
                        <pre
                          data-testid="fit-summary-json"
                          className={`${mutedSectionCardClass} overflow-x-auto text-xs leading-6 text-slate-700 dark:text-slate-200`}
                        >
                          {JSON.stringify(fitSummary, null, 2)}
                        </pre>
                      </section>
                    ) : null}
                  </div>
                </div>

                <div className="border-t border-slate-200 px-5 py-4 dark:border-slate-700">
                  <div className="flex justify-end">
                    <Button
                      label={t("mat_gradient_details_close_btn")}
                      variant="secondary"
                      onClick={() => setDetailsDialogOpen(false)}
                      className="w-full sm:w-auto"
                    />
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </motion.aside>
  );
}
