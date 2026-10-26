import CloseButton from "./ui/CloseButton";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ChangeEvent, PointerEvent as ReactPointerEvent } from "react";
import {
  colorcheckerCalibrate,
  colorcheckerDetectChart,
  colorcheckerListReferences,
  colorcheckerNormalizeReference,
  colorcheckerPrepareSource,
  colorcheckerRelease,
  colorcheckerWarpPreview,
  type ColorcheckerCalibrateOptions,
  type ColorcheckerDisplaySummary,
  type ColorcheckerPoint,
  type ColorcheckerReferenceSelection,
  type ColorcheckerReferenceSummary,
} from "../api/extractor";
import { apiErrorToVisibleMessage } from "../api/client";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import { useColorcheckerArtifactLease } from "../hooks/useColorcheckerArtifactLease";
import { useExtractorStore } from "../stores/extractorStore";
import {
  loadSelectedColorcheckerReferenceKey,
  loadStoredColorcheckerReferences,
  makeStoredColorcheckerReference,
  removeStoredColorcheckerReference,
  saveSelectedColorcheckerReferenceKey,
  type StoredColorcheckerReference,
  readColorcheckerReferenceWorkbook,
  upsertStoredColorcheckerReference,
} from "../utils/colorcheckerReferences";
import { normalizeResourceUrl } from "../utils/resourceUrl";
import Button from "./ui/Button";
import Checkbox from "./ui/Checkbox";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import { StatusBanner, cx } from "./ui/panelPrimitives";

type CornerPoint = [number, number];

interface ConfirmSourcePreviewContext {
  sourceFileId?: string | null;
  sourcePreviewUrl?: string | null;
}

export interface ColorcheckerConfirmDialogProps {
  phase: "calibrating" | "confirming" | "done" | null;
  colorcheckerTarget?: "white" | "black" | null;
  imageFile: File | null;
  originalPreviewUrl: string | null;
  calibratedPreviewUrl: string | null;
  colorcheckerFullFileId?: string | null;
  calibrationSummary?: ColorcheckerDisplaySummary | null;
  receiveCalibrated: (
    previewUrl: string,
    fullFileId: string,
    summary?: ColorcheckerDisplaySummary | null,
    dimensions?: {
      fullWidth: number;
      fullHeight: number;
      previewWidth: number;
      previewHeight: number;
    },
    context?: {
      imageFile: File | null;
      target?: "white" | "black" | null;
      sourcePreviewUrl?: string | null;
      sourcePreviewWidth?: number | null;
      sourcePreviewHeight?: number | null;
    },
  ) => void;
  confirmCalibrated: (context?: ConfirmSourcePreviewContext) => void;
  rejectCalibrated: () => void;
  closeDialog: () => void;
}

const PATCH_LAYOUT = "4x6";
const DEFAULT_REFERENCE_ID = "dafan";
const DEFAULT_REFERENCE_KEY = `server:${DEFAULT_REFERENCE_ID}`;
const CORNER_LABELS = ["TL", "TR", "BR", "BL"];

type CalibrationMode = NonNullable<ColorcheckerCalibrateOptions["calibrationMode"]>;
type SamplingMethod = NonNullable<ColorcheckerCalibrateOptions["method"]>;
type GrayAffineMode = NonNullable<ColorcheckerCalibrateOptions["grayAffineMode"]>;
type PatchOrientation = "normal" | "rotate_180" | "flip_horizontal" | "flip_vertical";
type DeltaMetricKind = "mean" | "median" | "p95" | "max";
type DeltaMetricTone = "success" | "warning" | "danger";

const CALIBRATION_MODE_OPTIONS: Array<{ labelKey: string; value: CalibrationMode }> = [
  { labelKey: "ext_cc_algorithm_matrix_3x3", value: "matrix_3x3" },
  { labelKey: "ext_cc_algorithm_matrix_3x4", value: "matrix_3x4" },
  { labelKey: "ext_cc_algorithm_root_polynomial", value: "root_polynomial" },
  { labelKey: "ext_cc_algorithm_auto", value: "auto" },
];

const SAMPLING_METHOD_OPTIONS: Array<{ labelKey: string; value: SamplingMethod }> = [
  { labelKey: "ext_cc_sampling_mean", value: "mean" },
  { labelKey: "ext_cc_sampling_median", value: "median" },
];

const GRAY_AFFINE_OPTIONS: Array<{ labelKey: string; value: GrayAffineMode }> = [
  { labelKey: "ext_cc_gray_affine_auto", value: "auto" },
  { labelKey: "ext_cc_gray_affine_enabled", value: "enabled" },
  { labelKey: "ext_cc_gray_affine_fallback", value: "fallback" },
];

const PATCH_ORIENTATION_OPTIONS: Array<{ labelKey: string; value: PatchOrientation }> = [
  { labelKey: "ext_cc_patch_orientation_normal", value: "normal" },
  { labelKey: "ext_cc_patch_orientation_rotate_180", value: "rotate_180" },
  { labelKey: "ext_cc_patch_orientation_flip_horizontal", value: "flip_horizontal" },
  { labelKey: "ext_cc_patch_orientation_flip_vertical", value: "flip_vertical" },
];
const PATCH_ORIENTATION_VALUES = new Set<PatchOrientation>(
  PATCH_ORIENTATION_OPTIONS.map((option) => option.value),
);
const DELTA_METRIC_LIMITS: Record<DeltaMetricKind, { high: number; acceptable: number }> = {
  mean: { high: 2, acceptable: 3 },
  median: { high: 1.5, acceptable: 3 },
  p95: { high: 3, acceptable: 6 },
  max: { high: 4, acceptable: 6 },
};
const FIT_DELTA_E_WARNING_RE =
  /^fit (mean|median|P95|max) ΔE00 ([0-9.]+) exceeds suggested ([0-9.]+) threshold\.$/;
const FIT_WARNING_KIND: Record<string, DeltaMetricKind> = {
  mean: "mean",
  median: "median",
  P95: "p95",
  max: "max",
};

function toCornerTuples(points: ColorcheckerPoint[]): CornerPoint[] {
  return points.map((point) => [point.x, point.y]);
}

function formatMetric(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "-";
}

function deltaMetricStatus(kind: DeltaMetricKind, value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const limit = DELTA_METRIC_LIMITS[kind];
  if (value <= limit.high) {
    return { labelKey: "ext_cc_delta_status_high_precision", tone: "success" as const };
  }
  if (value <= limit.acceptable) {
    return { labelKey: "ext_cc_delta_status_acceptable", tone: "warning" as const };
  }
  return { labelKey: "ext_cc_delta_status_check", tone: "danger" as const };
}

function deltaStatusClass(tone: DeltaMetricTone) {
  if (tone === "success") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800/70 dark:bg-emerald-950/40 dark:text-emerald-200";
  }
  if (tone === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800/70 dark:bg-amber-950/40 dark:text-amber-200";
  }
  return "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-800/70 dark:bg-rose-950/40 dark:text-rose-200";
}

function optionLabel(
  options: Array<{ labelKey: string; value: string }>,
  value: string | null | undefined,
  t: (key: string) => string,
) {
  return t(options.find((option) => option.value === value)?.labelKey ?? "ext_cc_unknown_value");
}

function normalizePatchOrientation(value: string | null | undefined): PatchOrientation {
  const normalized = (value || "normal").trim().toLowerCase() as PatchOrientation;
  return PATCH_ORIENTATION_VALUES.has(normalized) ? normalized : "normal";
}

function localizeColorcheckerWarning(warning: string) {
  const fitWarning = parseFitDeltaEWarning(warning);
  if (fitWarning) {
    const metricKeys = {
      mean: "ext_cc_metric_mean",
      median: "ext_cc_metric_median",
      p95: "ext_cc_metric_p95",
      max: "ext_cc_metric_worst",
    } as const;
    const metricKey = metricKeys[fitWarning.kind];
    return tRuntime("ext_cc_warning_fit_metric", {
      metric: tRuntime(metricKey),
      value: fitWarning.valueText,
      threshold: fitWarning.thresholdText,
    });
  }
  const patchMatch = /^Patch validity risk: ([0-9]+)\/([0-9]+) patches were excluded from fitting(?: \((.*?)\))?\. The PNG was generated from the remaining patches only; check patch placement, orientation, sample radius, and (.*?) before trusting the result\.$/.exec(warning);
  if (patchMatch) {
    return tRuntime("ext_cc_warning_patch_validity", {
      invalid: patchMatch[1],
      total: patchMatch[2],
    });
  }
  const negativeMatch = /^Corrected image negative channel ratio is ([0-9.]+%)\.$/.exec(warning);
  if (negativeMatch) {
    return tRuntime("ext_cc_warning_negative_ratio", { value: negativeMatch[1] });
  }
  const clippingMatch = /^Corrected image gamut clipping ratio is ([0-9.]+%)\.$/.exec(warning);
  if (clippingMatch) {
    return tRuntime("ext_cc_warning_clipping_ratio", { value: clippingMatch[1] });
  }
  const grayDeltaMatch = /^Neutral gray Δ([ab])\* patch ([0-9]+) \((.*?)\) is (-?[0-9.]+) \(corrected (-?[0-9.]+) vs reference (-?[0-9.]+)\), exceeds suggested ([0-9.]+) threshold\.$/.exec(warning);
  if (grayDeltaMatch) {
    return tRuntime("ext_cc_warning_gray_reference_delta", {
      axis: grayDeltaMatch[1],
      index: grayDeltaMatch[2],
      label: grayDeltaMatch[3],
      delta: grayDeltaMatch[4],
      corrected: grayDeltaMatch[5],
      reference: grayDeltaMatch[6],
      threshold: grayDeltaMatch[7],
    });
  }
  if (warning === "Neutral gray L* values are not monotonic.") {
    return tRuntime("ext_cc_warning_gray_l_not_monotonic");
  }
  if (warning === "Neutral gray |a*| exceeds suggested 1.5 threshold.") {
    return tRuntime("ext_cc_warning_gray_a_threshold");
  }
  if (warning === "Neutral gray |b*| exceeds suggested 1.5 threshold.") {
    return tRuntime("ext_cc_warning_gray_b_threshold");
  }
  if (warning.includes("exposure-scale drift")) {
    return tRuntime("ext_cc_warning_exposure_drift");
  }
  if (warning.includes("affine bias")) {
    return tRuntime("ext_cc_warning_affine_bias");
  }
  return tRuntime("ext_cc_warning_generic");
}

function parseFitDeltaEWarning(warning: string) {
  const match = FIT_DELTA_E_WARNING_RE.exec(warning);
  if (!match) {
    return null;
  }
  const kind = FIT_WARNING_KIND[match[1]];
  const value = Number(match[2]);
  if (!kind || !Number.isFinite(value)) {
    return null;
  }
  return {
    kind,
    value,
    valueText: match[2],
    thresholdText: match[3],
  };
}

function shouldShowColorcheckerWarning(warning: string) {
  const fitWarning = parseFitDeltaEWarning(warning);
  if (!fitWarning) {
    return true;
  }
  return deltaMetricStatus(fitWarning.kind, fitWarning.value)?.tone === "danger";
}

function nearestCornerIndex(points: CornerPoint[], target: CornerPoint) {
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  points.forEach((point, index) => {
    const dx = point[0] - target[0];
    const dy = point[1] - target[1];
    const distance = dx * dx + dy * dy;
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function LuminanceCurve({
  summary,
  noCurveLabel,
  ariaLabel,
}: {
  summary: ColorcheckerDisplaySummary | null;
  noCurveLabel: string;
  ariaLabel: string;
}) {
  const points = summary?.luminanceCurve ?? [];
  const grayPoints = points.filter((point) => point.grayPatch && point.reference !== null);
  const source = grayPoints.length >= 2 ? grayPoints : points;
  const chartPoints = source
    .map((point) => ({
      x: point.captured,
      y: point.corrected ?? point.normalized ?? point.reference,
    }))
    .filter((point): point is { x: number; y: number } => point.x !== null && point.y !== null);

  if (chartPoints.length < 2) {
    return (
      <div className="flex min-h-24 items-center justify-center rounded-2xl border border-slate-200/80 text-xs text-slate-500 dark:border-slate-700/80 dark:text-slate-400">
        {noCurveLabel}
      </div>
    );
  }

  const minX = Math.min(...chartPoints.map((point) => point.x));
  const maxX = Math.max(...chartPoints.map((point) => point.x));
  const minY = Math.min(...chartPoints.map((point) => point.y));
  const maxY = Math.max(...chartPoints.map((point) => point.y));
  const scaleX = (value: number) =>
    12 + ((value - minX) / Math.max(1e-6, maxX - minX)) * 176;
  const scaleY = (value: number) =>
    88 - ((value - minY) / Math.max(1e-6, maxY - minY)) * 76;
  const path = chartPoints
    .map((point) => `${scaleX(point.x).toFixed(2)},${scaleY(point.y).toFixed(2)}`)
    .join(" ");

  return (
    <svg
      viewBox="0 0 200 100"
      className="h-24 w-full rounded-2xl border border-slate-200/80 bg-slate-100/70 dark:border-slate-700/80 dark:bg-slate-900/50"
      role="img"
      aria-label={ariaLabel}
    >
      <line x1="12" y1="88" x2="188" y2="88" stroke="currentColor" className="text-slate-300 dark:text-slate-700" />
      <line x1="12" y1="12" x2="12" y2="88" stroke="currentColor" className="text-slate-300 dark:text-slate-700" />
      <polyline points={path} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-blue-600 dark:text-blue-400" />
      {chartPoints.map((point, index) => (
        <circle
          key={`${point.x}-${point.y}-${index}`}
          cx={scaleX(point.x)}
          cy={scaleY(point.y)}
          r="2.5"
          fill="currentColor"
          className="text-blue-600 dark:text-blue-400"
        />
      ))}
    </svg>
  );
}

function CalibrationMetrics({
  summary,
  labels,
}: {
  summary: ColorcheckerDisplaySummary | null;
  labels: {
    mean: string;
    median: string;
    p95: string;
    worst: string;
    worstPatch: string;
    deltaE00: string;
  };
}) {
  const delta = summary?.deltaE00;
  const metrics = [
    { kind: "mean" as const, label: labels.mean, value: delta?.mean },
    { kind: "median" as const, label: labels.median, value: delta?.median },
    { kind: "p95" as const, label: labels.p95, value: delta?.p95 },
    { kind: "max" as const, label: labels.worst, value: delta?.max },
  ] as const;
  const worstPatchStatus = deltaMetricStatus("max", summary?.worstPatch?.deltaE00);

  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(12rem,18rem)]">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {metrics.map((metric) => {
          const status = deltaMetricStatus(metric.kind, metric.value);
          return (
            <div
              key={metric.kind}
              className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-700/80"
              style={{ background: "var(--surface-panel)" }}
            >
              <div className="flex min-h-5 items-start justify-between gap-2">
                <div className="min-w-0 text-[11px] font-medium uppercase text-slate-500 dark:text-slate-400">
                  {metric.label}
                </div>
                {status && (
                  <span
                    className={cx(
                      "shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-medium leading-none",
                      deltaStatusClass(status.tone),
                    )}
                  >
                    {tRuntime(status.labelKey)}
                  </span>
                )}
              </div>
              <div className="mt-1 text-lg font-semibold tabular-nums text-slate-900 dark:text-slate-50">
                {formatMetric(metric.value)}
              </div>
            </div>
          );
        })}
      </div>
      <div className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-700/80" style={{ background: "var(--surface-panel)" }}>
        <div className="flex min-h-5 items-start justify-between gap-2">
          <div className="min-w-0 text-[11px] font-medium uppercase text-slate-500 dark:text-slate-400">
            {labels.worstPatch}
          </div>
          {worstPatchStatus && (
            <span
              className={cx(
                "shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-medium leading-none",
                deltaStatusClass(worstPatchStatus.tone),
              )}
            >
              {tRuntime(worstPatchStatus.labelKey)}
            </span>
          )}
        </div>
        <div className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
          {summary?.worstPatch
            ? `${summary.worstPatch.index}. ${summary.worstPatch.label || "-"}`
            : "-"}
        </div>
        <div className="mt-1 text-xs tabular-nums text-slate-500 dark:text-slate-400">
          {labels.deltaE00} {formatMetric(summary?.worstPatch?.deltaE00)}
        </div>
      </div>
    </div>
  );
}

function CalibrationReferenceInfo({
  summary,
}: {
  summary: ColorcheckerDisplaySummary | null;
}) {
  const { t } = useI18n();
  const reference = summary?.reference;
  const settings = summary?.settings;
  const sourceName = reference?.sourceName || t("ext_cc_reference_builtin");
  const selectedModel = settings?.calibrationMode || "matrix_3x3";
  return (
    <div className="grid gap-2 text-xs sm:grid-cols-2">
      <div
        className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-700/80"
        style={{ background: "var(--surface-panel)" }}
      >
        <div className="font-medium text-slate-500 dark:text-slate-400">
          {t("ext_cc_reference_label")}
        </div>
        <div className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
          {sourceName}
        </div>
        <div className="mt-1 text-slate-500 dark:text-slate-400">
          {tRuntime("ext_cc_reference_meta", {
            count: String(reference?.patchCount ?? 24),
            whitePoint: String(reference?.labWhitePoint ?? "D50"),
          })}
        </div>
      </div>
      <div
        className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-700/80"
        style={{ background: "var(--surface-panel)" }}
      >
        <div className="font-medium text-slate-500 dark:text-slate-400">
          {t("ext_cc_algorithm_label")}
        </div>
        <div className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
          {optionLabel(CALIBRATION_MODE_OPTIONS, selectedModel, t)}
        </div>
        <div className="mt-1 text-slate-500 dark:text-slate-400">
          {tRuntime("ext_cc_algorithm_meta", {
            method: optionLabel(SAMPLING_METHOD_OPTIONS, settings?.method ?? "mean", t),
            gray: optionLabel(GRAY_AFFINE_OPTIONS, settings?.grayAffineMode ?? "auto", t),
          })}
        </div>
      </div>
    </div>
  );
}

function ColorcheckerWarningCards({
  warnings,
}: {
  warnings: string[] | undefined;
}) {
  const { t } = useI18n();
  const visibleWarnings = warnings?.filter(shouldShowColorcheckerWarning) ?? [];
  if (!visibleWarnings.length) {
    return (
      <StatusBanner tone="success">
        {t("ext_cc_result_ready")}
      </StatusBanner>
    );
  }
  return (
    <div className="grid gap-2" data-testid="colorchecker-warning-cards">
      {visibleWarnings.map((warning, index) => (
        <StatusBanner
          key={`${warning}-${index}`}
          tone="warning"
          title={t("ext_cc_warning_title")}
        >
          {localizeColorcheckerWarning(warning)}
        </StatusBanner>
      ))}
    </div>
  );
}

function isRequestTimeoutError(error: unknown): boolean {
  const maybeError = error as { code?: unknown; message?: unknown } | null;
  const message =
    typeof maybeError?.message === "string" ? maybeError.message.toLowerCase() : "";
  return maybeError?.code === "ECONNABORTED" || message.includes("timeout");
}

function resolveStageErrorMessage(
  error: unknown,
  timeoutMessage: string,
  fallbackMessage: string,
): string {
  if (isRequestTimeoutError(error)) {
    return timeoutMessage;
  }
  return fallbackMessage;
}

function resolveReferenceErrorMessage(error: unknown, fallbackMessage: string): string {
  return apiErrorToVisibleMessage(error, fallbackMessage);
}

export function ColorcheckerConfirmDialogInner({
  phase,
  colorcheckerTarget = null,
  imageFile,
  calibratedPreviewUrl,
  colorcheckerFullFileId,
  calibrationSummary,
  receiveCalibrated,
  confirmCalibrated,
  rejectCalibrated,
  closeDialog,
}: ColorcheckerConfirmDialogProps) {
  const { t } = useI18n();
  const isCalibrating = phase === "calibrating";
  const isConfirming = phase === "confirming";
  const open = isCalibrating || isConfirming;

  const [sourceFileId, setSourceFileId] = useState<string | null>(null);
  const [sourcePreviewUrl, setSourcePreviewUrl] = useState<string | null>(null);
  const [sourceContext, setSourceContext] = useState<{
    imageFile: File;
    target: "white" | "black" | null;
  } | null>(null);
  const [sourcePreparing, setSourcePreparing] = useState(false);
  const [sourceUploadProgress, setSourceUploadProgress] = useState<number | null>(null);
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const [corners, setCorners] = useState<CornerPoint[]>([]);
  const [activeCornerIndex, setActiveCornerIndex] = useState<number | null>(null);
  const [dragCornerIndex, setDragCornerIndex] = useState<number | null>(null);
  const [warpPreviewUrl, setWarpPreviewUrl] = useState<string | null>(null);
  const [warpSize, setWarpSize] = useState<{ width: number; height: number } | null>(null);
  const [patchPoints, setPatchPoints] = useState<ColorcheckerPoint[] | null>(null);
  const [patchOrientation, setPatchOrientation] = useState<PatchOrientation>("normal");
  const [overlayPreviewUrl, setOverlayPreviewUrl] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [storageNoticeMessage, setStorageNoticeMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [autoDetecting, setAutoDetecting] = useState(false);
  const [warping, setWarping] = useState(false);
  const [calibrating, setCalibrating] = useState(false);
  const [sliderPos, setSliderPos] = useState(50);
  const [localSummary, setLocalSummary] = useState<ColorcheckerDisplaySummary | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [calibrationMode, setCalibrationMode] = useState<CalibrationMode>("matrix_3x3");
  const [samplingMethod, setSamplingMethod] = useState<SamplingMethod>("mean");
  const [grayAffineMode, setGrayAffineMode] = useState<GrayAffineMode>("auto");
  const [sampleRadius, setSampleRadius] = useState(12);
  const [blurRadius, setBlurRadius] = useState(0);
  const [serverReferences, setServerReferences] = useState<ColorcheckerReferenceSummary[]>([]);
  const [defaultReferenceId, setDefaultReferenceId] = useState(DEFAULT_REFERENCE_ID);
  const [customReferences, setCustomReferences] = useState<StoredColorcheckerReference[]>(
    () => loadStoredColorcheckerReferences(),
  );
  const [selectedReferenceKey, setSelectedReferenceKey] = useState(
    () => loadSelectedColorcheckerReferenceKey() ?? DEFAULT_REFERENCE_KEY,
  );
  const [referenceLoading, setReferenceLoading] = useState(false);
  const [referenceUploading, setReferenceUploading] = useState(false);

  const imageRef = useRef<HTMLImageElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const compareRef = useRef<HTMLDivElement>(null);
  const referenceInputRef = useRef<HTMLInputElement>(null);
  const compareDragging = useRef(false);
  const autoDetectAttempted = useRef(false);
  const sourceRunRef = useRef(0);
  const detectionRunRef = useRef(0);
  const warpRunRef = useRef(0);
  const calibrationRunRef = useRef(0);
  const deferredUnmountCleanupRef = useRef<number | null>(null);
  const activeSourceFileId =
    sourceContext?.imageFile === imageFile && sourceContext.target === colorcheckerTarget
      ? sourceFileId
      : null;
  const serverReferenceKey = selectedReferenceKey.startsWith("server:")
    ? selectedReferenceKey.slice("server:".length)
    : defaultReferenceId;
  const selectedCustomReference = customReferences.find(
    (item) => item.key === selectedReferenceKey,
  ) ?? null;
  const selectedServerReference = serverReferences.find(
    (item) => item.id === serverReferenceKey,
  ) ?? null;
  const referenceSelectionReady = !selectedReferenceKey.startsWith("server:")
    || serverReferenceKey === defaultReferenceId
    || serverReferences.some((item) => item.id === serverReferenceKey);
  const selectedReferenceRequest = useMemo<ColorcheckerReferenceSelection>(() => {
    if (selectedCustomReference) {
      return {
        kind: "custom",
        referencePatches: selectedCustomReference.patches,
        referenceSource: selectedCustomReference.source,
      };
    }
    return {
      kind: "server",
      referenceId: serverReferenceKey || defaultReferenceId || DEFAULT_REFERENCE_ID,
    };
  }, [defaultReferenceId, selectedCustomReference, serverReferenceKey]);
  const sourcePreparingLabel =
    sourcePreparing && sourceUploadProgress !== null && sourceUploadProgress < 100
      ? tRuntime("ext_cc_upload_progress", {
          percent: sourceUploadProgress,
        })
      : t("ext_cc_status_preparing");
  const calibrateBlockedReason = !imageFile
    ? t("ext_cc_missing_image")
    : sourcePreparing
      ? null
      : !activeSourceFileId || !imageSize
        ? t("ext_cc_status_preparing")
        : !referenceSelectionReady || referenceLoading
          ? t("ext_cc_reference_select_hint")
          : corners.length !== 4
            ? t("ext_cc_step1_hint")
            : null;
  const selectedReferenceMeta = selectedCustomReference
    ? selectedCustomReference.source
    : selectedServerReference?.source ?? {
        sourceName: selectedServerReference?.name ?? "大凡光学",
        patchCount: selectedServerReference?.patchCount ?? 24,
        labWhitePoint: selectedServerReference?.labWhitePoint ?? "D50",
      };
  const referenceOptions = useMemo(
    () => [
      {
        label: t("ext_cc_reference_group_server"),
        options: (serverReferences.length
          ? serverReferences
          : [
              {
                id: DEFAULT_REFERENCE_ID,
                name: "大凡光学",
                patchCount: 24,
              } as ColorcheckerReferenceSummary,
            ]).map((item) => ({
          label: item.name,
          value: `server:${item.id}`,
        })),
      },
      {
        label: t("ext_cc_reference_group_custom"),
        options: customReferences.map((item) => ({
          label: item.name,
          value: item.key,
        })),
      },
    ],
    [customReferences, serverReferences, t],
  );
  const latestCalibrationContext = useRef({
    phase,
    open,
    imageFile,
    colorcheckerTarget,
    sourceFileId: activeSourceFileId,
    referenceKey: selectedReferenceKey,
  });
  latestCalibrationContext.current = {
    phase,
    open,
    imageFile,
    colorcheckerTarget,
    sourceFileId: activeSourceFileId,
    referenceKey: selectedReferenceKey,
  };

  const sourceUrl = activeSourceFileId ? sourcePreviewUrl : null;
  const summary = calibrationSummary ?? localSummary;

  useColorcheckerArtifactLease(
    [colorcheckerFullFileId, activeSourceFileId],
    open,
    [calibratedPreviewUrl, sourceUrl, warpPreviewUrl, overlayPreviewUrl],
  );

  useEffect(() => {
    if (deferredUnmountCleanupRef.current !== null) {
      window.clearTimeout(deferredUnmountCleanupRef.current);
      deferredUnmountCleanupRef.current = null;
    }
    return () => {
      deferredUnmountCleanupRef.current = window.setTimeout(() => {
        closeDialog();
        deferredUnmountCleanupRef.current = null;
      }, 0);
    };
  }, [closeDialog]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setReferenceLoading(true);
    colorcheckerListReferences()
      .then((result) => {
        if (cancelled) return;
        setServerReferences(result.references);
        setDefaultReferenceId(result.defaultReferenceId || DEFAULT_REFERENCE_ID);
      })
      .catch((error) => {
        if (!cancelled) {
          setErrorMessage(
            resolveReferenceErrorMessage(
              error,
              t("ext_cc_reference_load_failed"),
            ),
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setReferenceLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, t]);

  useEffect(() => {
    const fallback = `server:${defaultReferenceId || DEFAULT_REFERENCE_ID}`;
    const fallbackToDefaultReference = () => {
      if (selectedReferenceKey === fallback) return;
      setSelectedReferenceKey(fallback);
      saveSelectedColorcheckerReferenceKey(fallback);
      detectionRunRef.current += 1;
      warpRunRef.current += 1;
      calibrationRunRef.current += 1;
      autoDetectAttempted.current = false;
      setAutoDetecting(false);
      setWarping(false);
      setCalibrating(false);
      setWarpPreviewUrl(null);
      setWarpSize(null);
      setPatchPoints(null);
      setOverlayPreviewUrl(null);
      setLocalSummary(null);
      setStatusMessage(null);
    };
    if (selectedReferenceKey.startsWith("custom:")) {
      if (!customReferences.some((item) => item.key === selectedReferenceKey)) {
        fallbackToDefaultReference();
      }
      return;
    }
    if (selectedReferenceKey.startsWith("server:")) {
      if (serverReferences.length > 0) {
        const serverId = selectedReferenceKey.slice("server:".length);
        if (!serverReferences.some((item) => item.id === serverId)) {
          fallbackToDefaultReference();
        }
      }
      return;
    }
    fallbackToDefaultReference();
  }, [customReferences, defaultReferenceId, selectedReferenceKey, serverReferences]);

  useEffect(() => {
    const runId = ++sourceRunRef.current;
    let released = false;
    let registeredSourceId: string | null = null;
    const releaseRegisteredSource = () => {
      if (!registeredSourceId || released) return;
      released = true;
      void colorcheckerRelease(registeredSourceId).catch(() => {});
    };
    setSourceFileId(null);
    setSourcePreviewUrl(null);
    setSourceContext(null);
    setSourceUploadProgress(null);
    setImageSize(null);
    if (!open || !imageFile) {
      setSourcePreparing(false);
      return releaseRegisteredSource;
    }
    const requestImageFile = imageFile;
    const requestTarget = colorcheckerTarget;
    setSourcePreparing(true);
    setSourceUploadProgress(0);
    setErrorMessage(null);
    colorcheckerPrepareSource(imageFile, {
      onUploadProgress: (progress) => {
        if (sourceRunRef.current !== runId) return;
        setSourceUploadProgress(progress.percent);
      },
    })
      .then((result) => {
        registeredSourceId = result.colorchecker_source_file_id;
        const latest = latestCalibrationContext.current;
        if (
          sourceRunRef.current !== runId ||
          !latest.open ||
          latest.imageFile !== requestImageFile ||
          latest.colorcheckerTarget !== requestTarget
        ) {
          releaseRegisteredSource();
          return;
        }
        setSourceFileId(result.colorchecker_source_file_id);
        setSourceContext({
          imageFile: requestImageFile,
          target: requestTarget ?? null,
        });
        setSourcePreviewUrl(
          normalizeResourceUrl(result.source_preview_url) ?? result.source_preview_url,
        );
        setImageSize({
          width: result.preview_width,
          height: result.preview_height,
        });
      })
      .catch((error) => {
        if (sourceRunRef.current === runId) {
          setErrorMessage(
            resolveStageErrorMessage(
              error,
              t("ext_cc_source_prepare_timeout"),
              t("ext_cc_source_prepare_failed"),
            ),
          );
        }
      })
      .finally(() => {
        if (sourceRunRef.current === runId) {
          setSourcePreparing(false);
          setSourceUploadProgress(null);
        }
      });
    return () => {
      sourceRunRef.current += 1;
      releaseRegisteredSource();
    };
  }, [colorcheckerTarget, imageFile, open, t]);

  useEffect(() => {
    if (!open) {
      autoDetectAttempted.current = false;
      return;
    }
    setStatusMessage(null);
    setErrorMessage(null);
    setWarpPreviewUrl(null);
    setWarpSize(null);
    setPatchPoints(null);
    setPatchOrientation("normal");
    setOverlayPreviewUrl(null);
    setLocalSummary(null);
    setCorners([]);
    setActiveCornerIndex(null);
    setAutoDetecting(false);
    setWarping(false);
    setCalibrating(false);
    autoDetectAttempted.current = false;
  }, [colorcheckerTarget, imageFile, open]);

  useEffect(() => {
    detectionRunRef.current += 1;
    warpRunRef.current += 1;
    calibrationRunRef.current += 1;
  }, [imageFile, open, colorcheckerTarget, selectedReferenceKey]);

  const pointFromPointer = useCallback((clientX: number, clientY: number): CornerPoint | null => {
    const image = imageRef.current;
    if (!image) return null;
    const rect = image.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const naturalWidth = imageSize?.width || image.naturalWidth || rect.width;
    const naturalHeight = imageSize?.height || image.naturalHeight || rect.height;
    const x = Math.max(0, Math.min(naturalWidth, ((clientX - rect.left) / rect.width) * naturalWidth));
    const y = Math.max(0, Math.min(naturalHeight, ((clientY - rect.top) / rect.height) * naturalHeight));
    return [x, y];
  }, [imageSize]);

  const updateCorner = useCallback((index: number, point: CornerPoint) => {
    setCorners((current) => current.map((corner, i) => (i === index ? point : corner)));
  }, []);

  const invalidateManualGeometry = useCallback(() => {
    detectionRunRef.current += 1;
    warpRunRef.current += 1;
    calibrationRunRef.current += 1;
    setAutoDetecting(false);
    setWarping(false);
    setCalibrating(false);
    setWarpPreviewUrl(null);
    setWarpSize(null);
    setPatchPoints(null);
    setStatusMessage(null);
  }, []);

  const invalidateReferenceState = useCallback(() => {
    detectionRunRef.current += 1;
    warpRunRef.current += 1;
    calibrationRunRef.current += 1;
    autoDetectAttempted.current = false;
    setAutoDetecting(false);
    setWarping(false);
    setCalibrating(false);
    setWarpPreviewUrl(null);
    setWarpSize(null);
    setPatchPoints(null);
    setOverlayPreviewUrl(null);
    setLocalSummary(null);
    setStatusMessage(null);
  }, []);

  const handleReferenceChange = useCallback((nextKey: string) => {
    if (nextKey === selectedReferenceKey) return;
    setSelectedReferenceKey(nextKey);
    saveSelectedColorcheckerReferenceKey(nextKey);
    setStorageNoticeMessage(null);
    invalidateReferenceState();
  }, [invalidateReferenceState, selectedReferenceKey]);

  const handleReferenceUpload = useCallback(async (file: File) => {
    setReferenceUploading(true);
    setErrorMessage(null);
    setStatusMessage(null);
    setStorageNoticeMessage(null);
    try {
      const parsed = await readColorcheckerReferenceWorkbook(file);
      const normalized = await colorcheckerNormalizeReference({
        patches: parsed.patches,
        source: parsed.source,
      });
      const stored = makeStoredColorcheckerReference(
        normalized,
        file.name.replace(/\.[^.]+$/, ""),
      );
      const storedResult = upsertStoredColorcheckerReference(stored);
      setCustomReferences(storedResult.references);
      setSelectedReferenceKey(stored.key);
      const selectedPersisted = saveSelectedColorcheckerReferenceKey(stored.key);
      invalidateReferenceState();
      if (!storedResult.persisted || !selectedPersisted) {
        setStorageNoticeMessage(t("ext_cc_reference_upload_ready_session_only"));
      } else {
        setStatusMessage(
          normalized.warnings.length
            ? tRuntime("ext_cc_reference_upload_ready_with_warnings", {
                count: normalized.warnings.length,
              })
            : t("ext_cc_reference_upload_ready"),
        );
      }
    } catch (error) {
      setErrorMessage(
        resolveReferenceErrorMessage(error, t("ext_cc_reference_upload_failed")),
      );
    } finally {
      setReferenceUploading(false);
    }
  }, [invalidateReferenceState, t]);

  const handleReferenceFileChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0] ?? null;
    event.currentTarget.value = "";
    if (file) {
      void handleReferenceUpload(file);
    }
  }, [handleReferenceUpload]);

  const handleDeleteSelectedReference = useCallback(() => {
    if (!selectedCustomReference) return;
    const storedResult = removeStoredColorcheckerReference(selectedCustomReference.key);
    setCustomReferences(storedResult.references);
    const fallback = `server:${defaultReferenceId || DEFAULT_REFERENCE_ID}`;
    setSelectedReferenceKey(fallback);
    saveSelectedColorcheckerReferenceKey(fallback);
    setStorageNoticeMessage(null);
    invalidateReferenceState();
  }, [defaultReferenceId, invalidateReferenceState, selectedCustomReference]);

  const handlePatchOrientationChange = useCallback((value: string) => {
    setPatchOrientation(normalizePatchOrientation(value));
    invalidateManualGeometry();
  }, [invalidateManualGeometry]);

  useEffect(() => {
    if (dragCornerIndex === null) return;
    const handleMove = (event: PointerEvent) => {
      const point = pointFromPointer(event.clientX, event.clientY);
      if (point) updateCorner(dragCornerIndex, point);
    };
    const handleUp = () => setDragCornerIndex(null);
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [dragCornerIndex, pointFromPointer, updateCorner]);

  const handleImagePointerDown = (event: ReactPointerEvent<HTMLImageElement>) => {
    const point = pointFromPointer(event.clientX, event.clientY);
    if (!point) return;
    setErrorMessage(null);
    invalidateManualGeometry();
    if (corners.length < 4) {
      setCorners((current) => [...current, point]);
      setActiveCornerIndex(corners.length);
      return;
    }
    const nextIndex = activeCornerIndex ?? nearestCornerIndex(corners, point);
    setActiveCornerIndex(nextIndex);
    updateCorner(nextIndex, point);
  };

  const handleCornerPointerDown = (
    event: ReactPointerEvent<HTMLButtonElement>,
    index: number,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    invalidateManualGeometry();
    setActiveCornerIndex(index);
    setDragCornerIndex(index);
  };

  const runAutoDetect = useCallback(async () => {
    if (!imageFile || !activeSourceFileId || !referenceSelectionReady) return;
    const runId = ++detectionRunRef.current;
    const requestImageFile = imageFile;
    const requestTarget = colorcheckerTarget;
    const requestSourceId = activeSourceFileId;
    const requestReferenceKey = selectedReferenceKey;
    setAutoDetecting(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      const result = await colorcheckerDetectChart(
        activeSourceFileId,
        PATCH_LAYOUT,
        null,
        selectedReferenceRequest,
      );
      const latest = latestCalibrationContext.current;
      if (
        detectionRunRef.current !== runId ||
        latest.phase !== "calibrating" ||
        !latest.open ||
        latest.imageFile !== requestImageFile ||
        latest.colorcheckerTarget !== requestTarget ||
        latest.sourceFileId !== requestSourceId ||
        latest.referenceKey !== requestReferenceKey
      ) {
        return;
      }
      if (result.detected && result.corners.length === 4) {
        setCorners(toCornerTuples(result.corners));
        setPatchOrientation(normalizePatchOrientation(result.patchOrientation));
        setActiveCornerIndex(0);
        setWarpPreviewUrl(null);
        setPatchPoints(null);
        setStatusMessage(`${t("ext_cc_auto_detect_success")} (${Math.round(result.confidence * 100)}%)`);
      } else {
        setStatusMessage(result.reason || t("ext_cc_auto_detect_failed"));
      }
    } catch (error) {
      if (detectionRunRef.current === runId) {
        setErrorMessage(
          resolveStageErrorMessage(
            error,
            t("ext_cc_auto_detect_timeout"),
            t("ext_cc_auto_detect_failed"),
          ),
        );
      }
    } finally {
      if (detectionRunRef.current === runId) {
        setAutoDetecting(false);
      }
    }
  }, [activeSourceFileId, colorcheckerTarget, imageFile, referenceSelectionReady, selectedReferenceKey, selectedReferenceRequest, t]);

  useEffect(() => {
    if (
      !isCalibrating ||
      !imageFile ||
      !activeSourceFileId ||
      !referenceSelectionReady ||
      autoDetectAttempted.current
    ) return;
    autoDetectAttempted.current = true;
    void runAutoDetect();
  }, [activeSourceFileId, imageFile, isCalibrating, referenceSelectionReady, runAutoDetect, selectedReferenceKey]);

  const runWarpPreview = async () => {
    if (!imageFile || !activeSourceFileId || !imageSize || !referenceSelectionReady || corners.length !== 4) return;
    const runId = ++warpRunRef.current;
    const requestImageFile = imageFile;
    const requestTarget = colorcheckerTarget;
    const requestSourceId = activeSourceFileId;
    const requestReferenceKey = selectedReferenceKey;
    setWarping(true);
    setErrorMessage(null);
    try {
      const result = await colorcheckerWarpPreview(
        activeSourceFileId,
        corners,
        imageSize,
        PATCH_LAYOUT,
        patchOrientation,
      );
      const latest = latestCalibrationContext.current;
      if (
        warpRunRef.current !== runId ||
        latest.phase !== "calibrating" ||
        !latest.open ||
        latest.imageFile !== requestImageFile ||
        latest.colorcheckerTarget !== requestTarget ||
        latest.sourceFileId !== requestSourceId ||
        latest.referenceKey !== requestReferenceKey
      ) {
        return;
      }
      setWarpPreviewUrl(normalizeResourceUrl(result.preview_url));
      setWarpSize({ width: result.preview_width, height: result.preview_height });
      setPatchPoints(result.auto_patch_points);
      setStatusMessage(t("ext_cc_warp_ready"));
    } catch (error) {
      if (warpRunRef.current === runId) {
        setErrorMessage(
          resolveStageErrorMessage(
            error,
            t("ext_cc_warp_timeout"),
            t("ext_cc_warp_failed"),
          ),
        );
      }
    } finally {
      if (warpRunRef.current === runId) {
        setWarping(false);
      }
    }
  };

  const runCalibration = async () => {
    if (!imageFile || !activeSourceFileId || !imageSize || !referenceSelectionReady || corners.length !== 4) return;
    const runId = ++calibrationRunRef.current;
    const requestImageFile = imageFile;
    const requestTarget = colorcheckerTarget;
    const requestSourceId = activeSourceFileId;
    const requestReferenceKey = selectedReferenceKey;
    setCalibrating(true);
    setErrorMessage(null);
    try {
      const options: ColorcheckerCalibrateOptions | null = advancedOpen
        ? {
            calibrationMode,
            method: samplingMethod,
            grayAffineMode,
            sampleRadius,
            blurRadius,
          }
        : null;
      const result = await colorcheckerCalibrate(
        activeSourceFileId,
        corners,
        imageSize,
        patchPoints,
        PATCH_LAYOUT,
        options,
        patchOrientation,
        selectedReferenceRequest,
      );
      const latest = latestCalibrationContext.current;
      if (
        calibrationRunRef.current !== runId ||
        latest.phase !== "calibrating" ||
        !latest.open ||
        latest.imageFile !== requestImageFile ||
        latest.colorcheckerTarget !== requestTarget ||
        latest.sourceFileId !== requestSourceId ||
        latest.referenceKey !== requestReferenceKey
      ) {
        void colorcheckerRelease(result.calibrated_full_file_id).catch(() => {});
        return;
      }
      const calibratedUrl = normalizeResourceUrl(result.calibrated_preview_url) ?? result.calibrated_preview_url;
      setOverlayPreviewUrl(normalizeResourceUrl(result.overlay_url));
      setLocalSummary(result.display_summary);
      receiveCalibrated(
        calibratedUrl,
        result.calibrated_full_file_id,
        result.display_summary,
        {
          fullWidth: result.full_width,
          fullHeight: result.full_height,
          previewWidth: result.preview_width,
          previewHeight: result.preview_height,
        },
        {
          imageFile,
          target: colorcheckerTarget,
          sourcePreviewUrl: sourceUrl,
          sourcePreviewWidth: imageSize.width,
          sourcePreviewHeight: imageSize.height,
        },
      );
    } catch (error) {
      if (calibrationRunRef.current === runId) {
        setErrorMessage(
          resolveStageErrorMessage(
            error,
            t("ext_cc_calibrate_timeout"),
            t("ext_cc_calibrate_failed"),
          ),
        );
      }
    } finally {
      if (calibrationRunRef.current === runId) {
        setCalibrating(false);
      }
    }
  };

  const handleCompareMove = useCallback((event: PointerEvent) => {
    if (!compareDragging.current || !compareRef.current) return;
    const rect = compareRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(event.clientX - rect.left, rect.width));
    setSliderPos((x / rect.width) * 100);
  }, []);

  const handleCompareUp = useCallback(() => {
    compareDragging.current = false;
    window.removeEventListener("pointermove", handleCompareMove);
    window.removeEventListener("pointerup", handleCompareUp);
  }, [handleCompareMove]);

  const handleCompareDown = useCallback(() => {
    compareDragging.current = true;
    window.addEventListener("pointermove", handleCompareMove);
    window.addEventListener("pointerup", handleCompareUp);
  }, [handleCompareMove, handleCompareUp]);

  const cornerOverlays = useMemo(() => {
    const image = imageRef.current;
    if (!image || !imageSize) return [];
    return corners.map((point, index) => ({
      index,
      left: `${(point[0] / imageSize.width) * 100}%`,
      top: `${(point[1] / imageSize.height) * 100}%`,
    }));
  }, [corners, imageSize]);

  if (!open) return null;

  return (
    <div data-testid="colorchecker-inline-tool" className="min-w-0">
      <div
        className="relative flex w-full flex-col overflow-hidden rounded-[24px] border shadow-[var(--shadow-control)]"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
      >
        <div className="flex items-center justify-between gap-3 border-b border-slate-200/80 px-5 py-3 dark:border-slate-700/80">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-50">
              {isConfirming ? t("ext_cc_confirm_title") : t("ext_cc_dialog_title")}
            </h2>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
              {isConfirming ? t("ext_cc_confirm_body") : t("ext_cc_step1_hint")}
            </p>
          </div>
        </div>

        {isCalibrating && (
          <div className="grid min-h-0 flex-1 gap-4 p-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(18rem,0.75fr)]">
            <div className="flex min-h-0 flex-col gap-3">
              <div className="relative flex min-h-72 items-center justify-center overflow-hidden rounded-[24px] border border-slate-200/80 bg-slate-950/5 p-3 dark:border-slate-700/80 dark:bg-slate-950/40">
                {sourceUrl ? (
                  <div className="relative inline-block max-h-[48vh] max-w-full">
                    <img
                      ref={imageRef}
                      src={sourceUrl}
                      alt={t("ext_cc_dialog_title")}
                      className="block max-h-[48vh] max-w-full select-none rounded-2xl object-contain"
                      draggable={false}
                      onLoad={(event) => {
                        setImageSize({
                          width: event.currentTarget.naturalWidth,
                          height: event.currentTarget.naturalHeight,
                        });
                      }}
                      onPointerDown={handleImagePointerDown}
                    />
                    {cornerOverlays.map((corner) => (
                      <button
                        key={corner.index}
                        type="button"
                        onPointerDown={(event) => handleCornerPointerDown(event, corner.index)}
                        className={cx(
                          "absolute flex h-7 w-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 text-[11px] font-bold shadow-lg",
                          activeCornerIndex === corner.index
                            ? "border-blue-500 bg-blue-500 text-white"
                            : "border-white bg-slate-900/80 text-white",
                        )}
                        style={{ left: corner.left, top: corner.top }}
                        aria-label={`${t("ext_cc_corner_label")} ${corner.index + 1}`}
                      >
                        {CORNER_LABELS[corner.index]}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="flex w-full max-w-sm flex-col gap-2">
                    <span className="text-sm text-slate-500 dark:text-slate-400">
                      {sourcePreparing ? sourcePreparingLabel : t("ext_cc_missing_image")}
                    </span>
                    {sourcePreparing && sourceUploadProgress !== null && (
                      <div
                        aria-label={t("ext_cc_upload_progress_label")}
                        aria-valuemax={100}
                        aria-valuemin={0}
                        aria-valuenow={sourceUploadProgress}
                        className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
                        role="progressbar"
                      >
                        <div
                          className="h-full rounded-full bg-blue-500 transition-[width]"
                          style={{ width: `${sourceUploadProgress}%` }}
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <Button
                  label={t("ext_cc_auto_detect_btn")}
                  variant="secondary"
                  onClick={() => void runAutoDetect()}
                  disabled={!imageFile || !activeSourceFileId || !referenceSelectionReady || autoDetecting || sourcePreparing}
                  loading={autoDetecting}
                  className="w-full"
                />
                <Button
                  label={t("ext_cc_warp_btn")}
                  variant="secondary"
                  onClick={() => void runWarpPreview()}
                  disabled={!imageFile || !activeSourceFileId || !imageSize || !referenceSelectionReady || corners.length !== 4 || warping}
                  loading={warping}
                  className="w-full"
                />
                <Button
                  label={t("ext_cc_calibrate_btn")}
                  variant="primary"
                  onClick={() => void runCalibration()}
                  disabled={!imageFile || !activeSourceFileId || !imageSize || !referenceSelectionReady || corners.length !== 4 || calibrating}
                  loading={calibrating}
                  className="w-full"
                />
              </div>
              {calibrateBlockedReason && !calibrating && (
                <div data-testid="colorchecker-calibrate-blocked-reason">
                  <StatusBanner tone="info">{calibrateBlockedReason}</StatusBanner>
                </div>
              )}
            </div>

            <div className="flex min-w-0 flex-col gap-3">
              {errorMessage && <StatusBanner tone="error">{errorMessage}</StatusBanner>}
              {storageNoticeMessage && <StatusBanner tone="info">{storageNoticeMessage}</StatusBanner>}
              {statusMessage && <StatusBanner tone="info">{statusMessage}</StatusBanner>}
              <div className="rounded-[24px] border border-slate-200/80 p-4 dark:border-slate-700/80" style={{ background: "var(--surface-panel)" }}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {t("ext_cc_reference_select_title")}
                    </h3>
                    <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {t("ext_cc_reference_select_hint")}
                    </p>
                  </div>
                </div>
                <div className="mt-3">
                  <Dropdown
                    label={t("ext_cc_reference_select_label")}
                    value={selectedReferenceKey}
                    groupedOptions={referenceOptions}
                    onChange={handleReferenceChange}
                    disabled={referenceLoading || referenceUploading}
                  />
                </div>
                <div className="mt-3 grid gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <div>
                    {tRuntime("ext_cc_reference_meta", {
                      count: String(selectedReferenceMeta.patchCount ?? 24),
                      whitePoint: String(selectedReferenceMeta.labWhitePoint ?? "D50"),
                    })}
                  </div>
                  {selectedReferenceMeta.serialNumber && (
                    <div>
                      {tRuntime("ext_cc_reference_serial", {
                        serial: String(selectedReferenceMeta.serialNumber),
                      })}
                    </div>
                  )}
                </div>
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <Button
                    label={t("ext_cc_reference_upload_btn")}
                    variant="secondary"
                    size="sm"
                    loading={referenceUploading}
                    onClick={() => referenceInputRef.current?.click()}
                    className="w-full sm:w-auto"
                  />
                  <Button
                    label={t("ext_cc_reference_delete_btn")}
                    variant="secondary"
                    size="sm"
                    disabled={!selectedCustomReference || referenceUploading}
                    onClick={handleDeleteSelectedReference}
                    className="w-full sm:w-auto"
                    tone="danger"
                  />
                  <input
                    ref={referenceInputRef}
                    type="file"
                    accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    className="hidden"
                    onChange={handleReferenceFileChange}
                  />
                </div>
              </div>
              <div className="rounded-[24px] border border-slate-200/80 p-4 dark:border-slate-700/80" style={{ background: "var(--surface-panel)" }}>
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                    {t("ext_cc_step1_title")}
                  </h3>
                  <span className="text-xs tabular-nums text-slate-500 dark:text-slate-400">
                    {corners.length}/4
                  </span>
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {t("ext_cc_corner_adjust_hint")}
                </p>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {CORNER_LABELS.map((label, index) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => setActiveCornerIndex(index < corners.length ? index : null)}
                      disabled={index >= corners.length}
                      className={cx(
                        "min-h-10 rounded-2xl border px-3 text-sm font-medium transition-colors",
                        activeCornerIndex === index
                          ? "border-blue-500 bg-blue-500 text-white"
                          : "border-slate-200/80 text-slate-700 hover:border-slate-300 dark:border-slate-700/80 dark:text-slate-200",
                        index >= corners.length && "cursor-not-allowed opacity-45",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="mt-3">
                  <Dropdown
                    label={t("ext_cc_patch_orientation_label")}
                    value={patchOrientation}
                    options={PATCH_ORIENTATION_OPTIONS.map((option) => ({
                      label: t(option.labelKey),
                      value: option.value,
                    }))}
                    onChange={handlePatchOrientationChange}
                  />
                </div>
              </div>

              <div className="rounded-[24px] border border-slate-200/80 p-4 dark:border-slate-700/80" style={{ background: "var(--surface-panel)" }}>
                <Checkbox
                  label={t("ext_cc_advanced_toggle")}
                  tooltip={t("ext_cc_advanced_hint")}
                  checked={advancedOpen}
                  onChange={setAdvancedOpen}
                />
                {advancedOpen && (
                  <div className="mt-4 grid gap-3">
                    <Dropdown
                      label={t("ext_cc_algorithm_label")}
                      value={calibrationMode}
                      options={CALIBRATION_MODE_OPTIONS.map((option) => ({
                        label: t(option.labelKey),
                        value: option.value,
                      }))}
                      onChange={(value) => setCalibrationMode(value as CalibrationMode)}
                    />
                    <Dropdown
                      label={t("ext_cc_sampling_method_label")}
                      value={samplingMethod}
                      options={SAMPLING_METHOD_OPTIONS.map((option) => ({
                        label: t(option.labelKey),
                        value: option.value,
                      }))}
                      onChange={(value) => setSamplingMethod(value as SamplingMethod)}
                    />
                    <Dropdown
                      label={t("ext_cc_gray_affine_label")}
                      value={grayAffineMode}
                      options={GRAY_AFFINE_OPTIONS.map((option) => ({
                        label: t(option.labelKey),
                        value: option.value,
                      }))}
                      onChange={(value) => setGrayAffineMode(value as GrayAffineMode)}
                    />
                    <Slider
                      label={t("ext_cc_sample_radius_label")}
                      value={sampleRadius}
                      min={2}
                      max={64}
                      step={1}
                      onChange={setSampleRadius}
                    />
                    <Slider
                      label={t("ext_cc_blur_radius_label")}
                      value={blurRadius}
                      min={0}
                      max={10}
                      step={0.5}
                      onChange={setBlurRadius}
                    />
                  </div>
                )}
              </div>

              {warpPreviewUrl && (
                <div className="rounded-[24px] border border-slate-200/80 p-4 dark:border-slate-700/80" style={{ background: "var(--surface-panel)" }}>
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                    {t("ext_cc_step_review_title")}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {t("ext_cc_step_review_hint")}
                  </p>
                  <div ref={previewRef} className="relative mt-3 overflow-hidden rounded-2xl border border-slate-200/80 dark:border-slate-700/80">
                    <img
                      src={warpPreviewUrl}
                      alt={t("ext_cc_step_review_title")}
                      className="block w-full"
                      draggable={false}
                    />
                    {patchPoints?.map((point, index) => (
                      <span
                        key={`${point.x}-${point.y}-${index}`}
                        className="absolute flex h-5 w-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-blue-600 text-[9px] font-semibold text-white shadow"
                        style={{
                          left: `${(point.x / (warpSize?.width ?? 600)) * 100}%`,
                          top: `${(point.y / (warpSize?.height ?? 400)) * 100}%`,
                        }}
                      >
                        {index + 1}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {isConfirming && (
          <div className="flex min-h-0 flex-1 flex-col overflow-auto">
            <div className="grid gap-3 p-4 xl:grid-cols-[minmax(0,1fr)_minmax(16rem,0.45fr)]">
              <div
                ref={compareRef}
                className="relative min-h-[22rem] cursor-col-resize select-none overflow-hidden rounded-[24px] border border-slate-200/80 bg-slate-950/5 dark:border-slate-700/80 dark:bg-slate-950/50"
                onPointerDown={handleCompareDown}
              >
                {sourceUrl && (
                  <img
                    src={sourceUrl}
                    alt={t("ext_cc_compare_original")}
                    className="absolute inset-0 h-full w-full object-contain"
                    draggable={false}
                  />
                )}
                {calibratedPreviewUrl && (
                  <div
                    className="absolute inset-0 overflow-hidden"
                    style={{ clipPath: `inset(0 ${100 - sliderPos}% 0 0)` }}
                  >
                    <img
                      src={calibratedPreviewUrl}
                      alt={t("ext_cc_compare_calibrated")}
                      className="absolute inset-0 h-full w-full object-contain"
                      draggable={false}
                    />
                  </div>
                )}
                <div
                  className="absolute bottom-0 top-0 z-10 w-0.5 shadow-lg"
                  style={{ left: `${sliderPos}%`, transform: "translateX(-50%)", background: "var(--surface-overlay)" }}
                >
                  <div className="absolute left-1/2 top-1/2 flex h-8 w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full text-xs font-bold shadow" style={{ background: "var(--surface-panel)" }}>
                    ||
                  </div>
                </div>
              </div>
              <div className="flex min-h-[16rem] flex-col gap-2 rounded-[24px] border border-slate-200/80 p-3 dark:border-slate-700/80" style={{ background: "var(--surface-panel)" }}>
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                  {t("ext_cc_overlay_title")}
                </h3>
                <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-2xl bg-slate-950/5 dark:bg-slate-950/40">
                  {overlayPreviewUrl ? (
                    <img
                      src={overlayPreviewUrl}
                      alt={t("ext_cc_step_review_title")}
                      className="max-h-[min(48vh,34rem)] w-full object-contain"
                      draggable={false}
                    />
                  ) : (
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {t("ext_cc_no_overlay")}
                    </span>
                  )}
                </div>
              </div>
            </div>

            <div className="flex flex-col gap-3 border-t border-slate-200/80 p-4 dark:border-slate-700/80">
              <CalibrationReferenceInfo summary={summary ?? null} />
              <CalibrationMetrics
                summary={summary ?? null}
                labels={{
                  mean: t("ext_cc_metric_mean"),
                  median: t("ext_cc_metric_median"),
                  p95: t("ext_cc_metric_p95"),
                  worst: t("ext_cc_metric_worst"),
                  worstPatch: t("ext_cc_metric_worst_patch"),
                  deltaE00: t("ext_cc_metric_delta_e00"),
                }}
              />
              <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.75fr)]">
                <LuminanceCurve
                  summary={summary ?? null}
                  noCurveLabel={t("ext_cc_no_curve")}
                  ariaLabel={t("ext_cc_luminance_curve")}
                />
                <ColorcheckerWarningCards warnings={summary?.warnings} />
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                <Button
                  label={t("ext_cc_confirm_reject")}
                  variant="secondary"
                  onClick={rejectCalibrated}
                  className="w-full sm:w-auto"
                />
                <Button
                  label={t("ext_cc_confirm_accept")}
                  variant="primary"
                  onClick={() =>
                    confirmCalibrated({
                      sourceFileId: activeSourceFileId,
                      sourcePreviewUrl: sourceUrl,
                    })
                  }
                  className="w-full sm:w-auto"
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Shared modal shell for the ColorChecker calibration tool.
 * ColorChecker 校色工具的通用模态外壳。
 *
 * Renders a centered, scrollable overlay via a portal with a close button,
 * Escape-to-close and click-outside-to-close. Both the extractor and the
 * gradient-card extraction flows wrap ``ColorcheckerConfirmDialogInner`` with
 * this shell so the calibration UI shows up as a popup instead of an inline
 * panel that forces scrolling.
 * 通过 portal 渲染居中、可滚动的覆盖层，带关闭按钮、Esc 关闭与点击遮罩关闭。
 * 颜色提取与梯度卡提取两条流程都用此外壳包裹 ``ColorcheckerConfirmDialogInner``，
 * 让校色界面以弹窗形式出现，而不是内联面板导致反复滚动。
 */
export function ColorcheckerModalShell({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      data-testid="colorchecker-modal-backdrop"
      className="fixed inset-0 z-[9999] flex items-center justify-center p-3 backdrop-blur-sm sm:p-5"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
        className="relative flex max-h-[94vh] w-full max-w-6xl flex-col overflow-hidden rounded-[24px]"
      >
        <div className="absolute right-4 top-4 z-10"><CloseButton label={t("announcement_close")} onClick={onClose} /></div>
        <div className="min-h-0 flex-1 overflow-auto overscroll-y-contain">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

/**
 * Extractor-side ColorChecker tool, presented as a centered modal overlay.
 * 提取器侧的 ColorChecker 校色工具，以居中模态弹窗形式呈现。
 *
 * The modal opens automatically when ColorChecker is enabled and an image is
 * uploaded (the store moves ``colorchecker_phase`` to ``calibrating``). The
 * user picks corners, calibrates and confirms inside the dialog without
 * scrolling the main extractor panel; accepting the result closes the modal
 * and applies the calibrated image to the extraction flow.
 * 当启用 ColorChecker 并上传图片后（store 将 ``colorchecker_phase`` 置为
 * ``calibrating``），弹窗自动打开。用户在弹窗内完成点选、校色与确认，无需
 * 滚动主面板；确认后弹窗关闭并把校准结果应用到后续提取流程。
 */
export default function ColorcheckerConfirmDialogExtractor() {
  const { t } = useI18n();
  const enabled = useExtractorStore((s) => s.colorchecker_enabled);
  const phase = useExtractorStore((s) => s.colorchecker_phase);
  const imageFile = useExtractorStore((s) => s.imageFile);
  const originalPreviewUrl = useExtractorStore((s) => s.originalPreviewUrl);
  const calibratedPreviewUrl = useExtractorStore((s) => s.calibratedPreviewUrl);
  const colorcheckerFullFileId = useExtractorStore((s) => s.calibratedFullFileId);
  const calibrationSummary = useExtractorStore((s) => s.colorcheckerSummary);
  const receiveCalibrated = useExtractorStore((s) => s.receiveCalibratedFromCC);
  const confirmCalibrated = useExtractorStore((s) => s.confirmCalibrated);
  const rejectCalibrated = useExtractorStore((s) => s.rejectCalibrated);
  const closeDialog = useExtractorStore((s) => s.closeColorcheckerDialog);

  const resolvedPhase = enabled ? phase : null;
  const open =
    imageFile !== null &&
    (resolvedPhase === "calibrating" || resolvedPhase === "confirming");

  return (
    <ColorcheckerModalShell open={open} title={t("ext_cc_dialog_title")} onClose={closeDialog}>
      <ColorcheckerConfirmDialogInner
        phase={resolvedPhase}
        colorcheckerTarget={null}
        imageFile={imageFile}
        originalPreviewUrl={originalPreviewUrl}
        calibratedPreviewUrl={calibratedPreviewUrl}
        colorcheckerFullFileId={colorcheckerFullFileId}
        calibrationSummary={calibrationSummary}
        receiveCalibrated={receiveCalibrated}
        confirmCalibrated={confirmCalibrated}
        rejectCalibrated={rejectCalibrated}
        closeDialog={closeDialog}
      />
    </ColorcheckerModalShell>
  );
}
