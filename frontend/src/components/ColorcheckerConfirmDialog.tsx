import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import {
  colorcheckerCalibrate,
  colorcheckerDetectChart,
  colorcheckerWarpPreview,
  type ColorcheckerDisplaySummary,
  type ColorcheckerPoint,
} from "../api/extractor";
import { useI18n } from "../i18n/context";
import { useExtractorStore } from "../stores/extractorStore";
import { normalizeResourceUrl } from "../utils/resourceUrl";
import Button from "./ui/Button";
import { XIcon } from "./ui/icons";
import { StatusBanner, cx } from "./ui/panelPrimitives";

type CornerPoint = [number, number];

export interface ColorcheckerConfirmDialogProps {
  phase: "calibrating" | "confirming" | "done" | null;
  imageFile: File | null;
  originalPreviewUrl: string | null;
  calibratedPreviewUrl: string | null;
  calibrationSummary?: ColorcheckerDisplaySummary | null;
  receiveCalibrated: (
    imageUrl: string,
    summary?: ColorcheckerDisplaySummary | null,
  ) => void;
  confirmCalibrated: () => void;
  rejectCalibrated: () => void;
  closeDialog: () => void;
}

const PATCH_LAYOUT = "4x6";
const CORNER_LABELS = ["TL", "TR", "BR", "BL"];

function toCornerTuples(points: ColorcheckerPoint[]): CornerPoint[] {
  return points.map((point) => [point.x, point.y]);
}

function formatMetric(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "-";
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
      className="h-24 w-full rounded-2xl border border-slate-200/80 bg-slate-50/70 dark:border-slate-700/80 dark:bg-slate-900/50"
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
    [labels.mean, delta?.mean],
    [labels.median, delta?.median],
    [labels.p95, delta?.p95],
    [labels.worst, delta?.max],
  ] as const;

  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(12rem,18rem)]">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {metrics.map(([label, value]) => (
          <div
            key={label}
            className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-700/80"
            style={{ background: "var(--surface-panel)" }}
          >
            <div className="text-[11px] font-medium uppercase text-slate-500 dark:text-slate-400">
              {label}
            </div>
            <div className="mt-1 text-lg font-semibold tabular-nums text-slate-900 dark:text-slate-50">
              {formatMetric(value)}
            </div>
          </div>
        ))}
      </div>
      <div className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-700/80" style={{ background: "var(--surface-panel)" }}>
        <div className="text-[11px] font-medium uppercase text-slate-500 dark:text-slate-400">
          {labels.worstPatch}
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

export function ColorcheckerConfirmDialogInner({
  phase,
  imageFile,
  originalPreviewUrl,
  calibratedPreviewUrl,
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

  const [localPreviewUrl, setLocalPreviewUrl] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const [corners, setCorners] = useState<CornerPoint[]>([]);
  const [activeCornerIndex, setActiveCornerIndex] = useState<number | null>(null);
  const [dragCornerIndex, setDragCornerIndex] = useState<number | null>(null);
  const [warpPreviewUrl, setWarpPreviewUrl] = useState<string | null>(null);
  const [warpSize, setWarpSize] = useState<{ width: number; height: number } | null>(null);
  const [patchPoints, setPatchPoints] = useState<ColorcheckerPoint[] | null>(null);
  const [overlayPreviewUrl, setOverlayPreviewUrl] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [autoDetecting, setAutoDetecting] = useState(false);
  const [warping, setWarping] = useState(false);
  const [calibrating, setCalibrating] = useState(false);
  const [sliderPos, setSliderPos] = useState(50);
  const [localSummary, setLocalSummary] = useState<ColorcheckerDisplaySummary | null>(null);

  const imageRef = useRef<HTMLImageElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const compareRef = useRef<HTMLDivElement>(null);
  const compareDragging = useRef(false);
  const autoDetectAttempted = useRef(false);

  const sourceUrl = originalPreviewUrl ?? localPreviewUrl;
  const summary = calibrationSummary ?? localSummary;

  useEffect(() => {
    if (!open || !imageFile || originalPreviewUrl) {
      setLocalPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(imageFile);
    setLocalPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [imageFile, open, originalPreviewUrl]);

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
    setWarpSize(null);
    setOverlayPreviewUrl(null);
    setLocalSummary(null);
    setCorners([]);
    setActiveCornerIndex(null);
    autoDetectAttempted.current = false;
  }, [imageFile, open]);

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
    setWarpPreviewUrl(null);
    setPatchPoints(null);
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
    setActiveCornerIndex(index);
    setDragCornerIndex(index);
  };

  const runAutoDetect = useCallback(async () => {
    if (!imageFile) return;
    setAutoDetecting(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      const result = await colorcheckerDetectChart(imageFile, PATCH_LAYOUT);
      if (result.detected && result.corners.length === 4) {
        setCorners(toCornerTuples(result.corners));
        setActiveCornerIndex(0);
        setWarpPreviewUrl(null);
        setPatchPoints(null);
        setStatusMessage(`${t("ext_cc_auto_detect_success")} (${Math.round(result.confidence * 100)}%)`);
      } else {
        setStatusMessage(result.reason || t("ext_cc_auto_detect_failed"));
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t("ext_cc_auto_detect_failed"));
    } finally {
      setAutoDetecting(false);
    }
  }, [imageFile, t]);

  useEffect(() => {
    if (!isCalibrating || !imageFile || autoDetectAttempted.current) return;
    autoDetectAttempted.current = true;
    void runAutoDetect();
  }, [imageFile, isCalibrating, runAutoDetect]);

  const runWarpPreview = async () => {
    if (!imageFile || corners.length !== 4) return;
    setWarping(true);
    setErrorMessage(null);
    try {
      const result = await colorcheckerWarpPreview(imageFile, corners, PATCH_LAYOUT);
      setWarpPreviewUrl(normalizeResourceUrl(result.preview_url));
      setWarpSize({ width: result.preview_width, height: result.preview_height });
      setPatchPoints(result.auto_patch_points);
      setStatusMessage(t("ext_cc_warp_ready"));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t("ext_cc_warp_failed"));
    } finally {
      setWarping(false);
    }
  };

  const runCalibration = async () => {
    if (!imageFile || corners.length !== 4) return;
    setCalibrating(true);
    setErrorMessage(null);
    try {
      const result = await colorcheckerCalibrate(imageFile, corners, patchPoints, PATCH_LAYOUT);
      const calibratedUrl = normalizeResourceUrl(result.calibrated_url) ?? result.calibrated_url;
      setOverlayPreviewUrl(normalizeResourceUrl(result.overlay_url));
      setLocalSummary(result.display_summary);
      receiveCalibrated(calibratedUrl, result.display_summary);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t("ext_cc_calibrate_failed"));
    } finally {
      setCalibrating(false);
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

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center px-3 py-4 backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
    >
      <div
        className="relative flex max-h-[94vh] w-full max-w-6xl flex-col overflow-hidden rounded-[28px] border shadow-2xl"
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
          <Button
            label={t("ext_cc_close_btn")}
            variant="secondary"
            size="icon"
            icon={<XIcon />}
            onClick={closeDialog}
            className="shrink-0"
          />
        </div>

        {isCalibrating && (
          <div className="grid min-h-0 flex-1 gap-4 overflow-auto p-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(20rem,0.75fr)]">
            <div className="flex min-h-0 flex-col gap-3">
              <div className="relative flex min-h-[22rem] items-center justify-center overflow-hidden rounded-[24px] border border-slate-200/80 bg-slate-950/5 p-3 dark:border-slate-700/80 dark:bg-slate-950/40">
                {sourceUrl ? (
                  <div className="relative inline-block max-h-[58vh] max-w-full">
                    <img
                      ref={imageRef}
                      src={sourceUrl}
                      alt={t("ext_cc_dialog_title")}
                      className="block max-h-[58vh] max-w-full select-none rounded-2xl object-contain"
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
                  <span className="text-sm text-slate-500 dark:text-slate-400">
                    {t("ext_cc_missing_image")}
                  </span>
                )}
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <Button
                  label={t("ext_cc_auto_detect_btn")}
                  variant="secondary"
                  onClick={() => void runAutoDetect()}
                  disabled={!imageFile || autoDetecting}
                  loading={autoDetecting}
                  className="w-full"
                />
                <Button
                  label={t("ext_cc_warp_btn")}
                  variant="secondary"
                  onClick={() => void runWarpPreview()}
                  disabled={!imageFile || corners.length !== 4 || warping}
                  loading={warping}
                  className="w-full"
                />
                <Button
                  label={t("ext_cc_calibrate_btn")}
                  variant="primary"
                  onClick={() => void runCalibration()}
                  disabled={!imageFile || corners.length !== 4 || calibrating}
                  loading={calibrating}
                  className="w-full"
                />
              </div>
            </div>

            <div className="flex min-w-0 flex-col gap-3">
              {errorMessage && <StatusBanner tone="error">{errorMessage}</StatusBanner>}
              {statusMessage && <StatusBanner tone="info">{statusMessage}</StatusBanner>}
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
            <div
              ref={compareRef}
              className="relative min-h-[24rem] cursor-col-resize select-none overflow-hidden bg-slate-950/5 dark:bg-slate-950/50"
              onPointerDown={handleCompareDown}
            >
              {originalPreviewUrl && (
                <img
                  src={originalPreviewUrl}
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
              {overlayPreviewUrl && (
                <img
                  src={overlayPreviewUrl}
                  alt={t("ext_cc_step_review_title")}
                  className="absolute bottom-3 right-3 max-h-32 max-w-[35%] rounded-2xl border border-slate-200/80 object-contain shadow-lg dark:border-slate-700/80"
                  draggable={false}
                />
              )}
            </div>

            <div className="flex flex-col gap-3 border-t border-slate-200/80 p-4 dark:border-slate-700/80">
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
                {summary?.warnings?.length ? (
                  <StatusBanner tone="warning">
                    {summary.warnings.slice(0, 2).join(" ")}
                  </StatusBanner>
                ) : (
                  <StatusBanner tone="success">
                    {t("ext_cc_result_ready")}
                  </StatusBanner>
                )}
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
                  onClick={confirmCalibrated}
                  className="w-full sm:w-auto"
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

export default function ColorcheckerConfirmDialogExtractor() {
  const phase = useExtractorStore((s) => s.colorchecker_phase);
  const imageFile = useExtractorStore((s) => s.imageFile);
  const originalPreviewUrl = useExtractorStore((s) => s.originalPreviewUrl);
  const calibratedPreviewUrl = useExtractorStore((s) => s.calibratedPreviewUrl);
  const calibrationSummary = useExtractorStore((s) => s.colorcheckerSummary);
  const receiveCalibrated = useExtractorStore((s) => s.receiveCalibratedFromCC);
  const confirmCalibrated = useExtractorStore((s) => s.confirmCalibrated);
  const rejectCalibrated = useExtractorStore((s) => s.rejectCalibrated);
  const closeDialog = useExtractorStore((s) => s.closeColorcheckerDialog);

  return (
    <ColorcheckerConfirmDialogInner
      phase={phase}
      imageFile={imageFile}
      originalPreviewUrl={originalPreviewUrl}
      calibratedPreviewUrl={calibratedPreviewUrl}
      calibrationSummary={calibrationSummary}
      receiveCalibrated={receiveCalibrated}
      confirmCalibrated={confirmCalibrated}
      rejectCalibrated={rejectCalibrated}
      closeDialog={closeDialog}
    />
  );
}
