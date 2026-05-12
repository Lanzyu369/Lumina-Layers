import { createPortal } from "react-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { GradientCardSampleBox } from "../api/types";
import PreviewHoverInspector from "./ui/PreviewHoverInspector";
import CanvasPreviewSurface, {
  type CanvasPreviewSurfaceReadyPayload,
} from "./ui/CanvasPreviewSurface";
import type { CanvasPreviewHoverSample } from "./ui/canvasPreviewUtils";
import {
  HOVER_POPOVER_DELAY_MS,
  MAGNIFIER_SIZE_PX,
  MAGNIFIER_ZOOM,
  areHoverSamplesEqual,
  clampNumber,
  computeHoverInspectorStyle,
  mapPixelToBufferCoordinate,
  rgbToHex,
  type PreviewCanvasBuffer,
} from "./ui/previewHoverInspectorUtils";

interface GradientCardCanvasPreviewProps {
  title: string;
  hint?: string;
  imageUrl: string | null;
  alt: string;
  emptyText?: string;
  naturalWidth?: number | null;
  naturalHeight?: number | null;
  cornerPoints?: Array<[number, number]>;
  activePointIndex?: number | null;
  sampleBoxes?: GradientCardSampleBox[];
  warpWidth?: number | null;
  warpHeight?: number | null;
  onSelectPoint?: (point: [number, number]) => void;
  onImageLoad?: (width: number, height: number) => void;
  maxSelectablePoints?: number;
  dataTestId: string;
  emptyStateTestId?: string;
}

export default function GradientCardCanvasPreview({
  title,
  hint,
  imageUrl,
  alt,
  emptyText,
  naturalWidth,
  naturalHeight,
  cornerPoints = [],
  activePointIndex = null,
  sampleBoxes = [],
  warpWidth,
  warpHeight,
  onSelectPoint,
  onImageLoad,
  maxSelectablePoints = 4,
  dataTestId,
  emptyStateTestId,
}: GradientCardCanvasPreviewProps) {
  const [previewCanvasBuffer, setPreviewCanvasBuffer] = useState<PreviewCanvasBuffer | null>(null);
  const [hoverSample, setHoverSample] = useState<CanvasPreviewHoverSample | null>(null);
  const [hoverSurfaceHex, setHoverSurfaceHex] = useState<string | null>(null);
  const pendingHoverSampleRef = useRef<CanvasPreviewHoverSample | null>(null);
  const hoverDelayTimerRef = useRef<number | null>(null);
  const magnifierCanvasRef = useRef<HTMLCanvasElement>(null);

  const resolvedNaturalWidth = naturalWidth ?? previewCanvasBuffer?.width ?? null;
  const resolvedNaturalHeight = naturalHeight ?? previewCanvasBuffer?.height ?? null;
  const overlayWidth = warpWidth ?? resolvedNaturalWidth;
  const overlayHeight = warpHeight ?? resolvedNaturalHeight;
  const previewAspectRatio = resolvedNaturalWidth && resolvedNaturalHeight
    ? `${resolvedNaturalWidth} / ${resolvedNaturalHeight}`
    : undefined;

  const clearHoverDelayTimer = useCallback(() => {
    if (hoverDelayTimerRef.current !== null) {
      window.clearTimeout(hoverDelayTimerRef.current);
      hoverDelayTimerRef.current = null;
    }
  }, []);

  const handleHoverSample = useCallback(
    (sample: CanvasPreviewHoverSample | null) => {
      pendingHoverSampleRef.current = sample;
      clearHoverDelayTimer();
      if (sample === null) {
        setHoverSample((previous) => (previous === null ? previous : null));
        return;
      }
      setHoverSample((previous) => (previous === null ? previous : null));
      hoverDelayTimerRef.current = window.setTimeout(() => {
        hoverDelayTimerRef.current = null;
        const pendingSample = pendingHoverSampleRef.current;
        if (!pendingSample) {
          return;
        }
        setHoverSample((previous) => (
          areHoverSamplesEqual(previous, pendingSample) ? previous : pendingSample
        ));
      }, HOVER_POPOVER_DELAY_MS);
    },
    [clearHoverDelayTimer],
  );

  useEffect(() => {
    clearHoverDelayTimer();
    pendingHoverSampleRef.current = null;
    setPreviewCanvasBuffer(null);
    setHoverSample(null);
    setHoverSurfaceHex(null);
  }, [clearHoverDelayTimer, imageUrl]);

  useEffect(() => {
    return () => {
      clearHoverDelayTimer();
    };
  }, [clearHoverDelayTimer]);

  const handleSurfaceReady = useCallback(
    (payload: CanvasPreviewSurfaceReadyPayload | null) => {
      setPreviewCanvasBuffer(payload?.previewBuffer ?? null);
      setHoverSurfaceHex(null);
      if (payload) {
        onImageLoad?.(payload.image.naturalWidth, payload.image.naturalHeight);
      }
    },
    [onImageLoad],
  );

  useEffect(() => {
    if (!hoverSample || !previewCanvasBuffer) {
      setHoverSurfaceHex((previous) => (previous === null ? previous : null));
      return;
    }

    const x = mapPixelToBufferCoordinate(
      hoverSample.pixelX,
      hoverSample.naturalWidth,
      previewCanvasBuffer.width,
    );
    const y = mapPixelToBufferCoordinate(
      hoverSample.pixelY,
      hoverSample.naturalHeight,
      previewCanvasBuffer.height,
    );

    let sampledSurface: string | null = null;
    try {
      const rgba = previewCanvasBuffer.context.getImageData(x, y, 1, 1).data;
      sampledSurface = rgba[3] <= 8 ? null : rgbToHex(rgba[0], rgba[1], rgba[2]);
    } catch {
      sampledSurface = null;
    }
    setHoverSurfaceHex((previous) => (
      previous === sampledSurface ? previous : sampledSurface
    ));
  }, [hoverSample, previewCanvasBuffer]);

  useEffect(() => {
    const magnifierCanvas = magnifierCanvasRef.current;
    const context = magnifierCanvas?.getContext("2d");
    if (!magnifierCanvas || !context) {
      return;
    }

    context.clearRect(0, 0, magnifierCanvas.width, magnifierCanvas.height);
    if (!hoverSample || !previewCanvasBuffer) {
      return;
    }

    const centerX = mapPixelToBufferCoordinate(
      hoverSample.pixelX,
      hoverSample.naturalWidth,
      previewCanvasBuffer.width,
    );
    const centerY = mapPixelToBufferCoordinate(
      hoverSample.pixelY,
      hoverSample.naturalHeight,
      previewCanvasBuffer.height,
    );
    const sourceSize = MAGNIFIER_SIZE_PX / MAGNIFIER_ZOOM;
    const maxSourceX = Math.max(0, previewCanvasBuffer.width - sourceSize);
    const maxSourceY = Math.max(0, previewCanvasBuffer.height - sourceSize);
    const sourceX = clampNumber(centerX - sourceSize / 2, 0, maxSourceX);
    const sourceY = clampNumber(centerY - sourceSize / 2, 0, maxSourceY);

    context.imageSmoothingEnabled = false;
    context.drawImage(
      previewCanvasBuffer.context.canvas,
      sourceX,
      sourceY,
      sourceSize,
      sourceSize,
      0,
      0,
      magnifierCanvas.width,
      magnifierCanvas.height,
    );

    const center = magnifierCanvas.width / 2;
    context.strokeStyle = "rgba(255, 255, 255, 0.9)";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(center, 0);
    context.lineTo(center, magnifierCanvas.height);
    context.moveTo(0, center);
    context.lineTo(magnifierCanvas.width, center);
    context.stroke();
  }, [hoverSample, previewCanvasBuffer]);

  const handleClickSample = useCallback(
    (sample: CanvasPreviewHoverSample) => {
      if (!onSelectPoint || cornerPoints.length >= maxSelectablePoints) {
        return;
      }
      onSelectPoint([sample.pixelX, sample.pixelY]);
    },
    [cornerPoints.length, maxSelectablePoints, onSelectPoint],
  );

  const overlay = useMemo(() => {
    const hasCornerOverlay = cornerPoints.length > 0 && !!resolvedNaturalWidth && !!resolvedNaturalHeight;
    const hasSampleOverlay = sampleBoxes.length > 0 && !!overlayWidth && !!overlayHeight;
    if (!hasCornerOverlay && !hasSampleOverlay) {
      return null;
    }

    return (
      <div className="relative h-full w-full">
        {hasSampleOverlay ? (
          <svg
            viewBox={`0 0 ${overlayWidth} ${overlayHeight}`}
            className="absolute inset-0 h-full w-full"
            preserveAspectRatio="none"
          >
            {sampleBoxes.map((box) => (
              <rect
                key={`${dataTestId}-${box.row}-${box.col}-${box.x}-${box.y}`}
                data-testid={`${dataTestId}-sample-box`}
                x={box.x}
                y={box.y}
                width={box.width}
                height={box.height}
                rx={Math.max(4, Math.min(box.width, box.height) * 0.08)}
                ry={Math.max(4, Math.min(box.width, box.height) * 0.08)}
                fill="rgba(15, 23, 42, 0.12)"
                stroke="rgba(248, 250, 252, 0.95)"
                strokeWidth={Math.max(1, (overlayWidth ?? 1) / 620)}
              >
                <title>{`r${box.row + 1} c${box.col + 1} • ${box.thickness_layers}L`}</title>
              </rect>
            ))}
          </svg>
        ) : null}
        {hasCornerOverlay ? (
          <svg
            viewBox={`0 0 ${resolvedNaturalWidth} ${resolvedNaturalHeight}`}
            className="absolute inset-0 h-full w-full"
            preserveAspectRatio="none"
          >
            {cornerPoints.map(([x, y], index) => (
              <g key={`${dataTestId}-corner-${index}-${x}-${y}`} transform={`translate(${x} ${y})`}>
                <circle r={16} fill="rgba(15, 23, 42, 0.96)" stroke={index === activePointIndex ? "#3b82f6" : "rgba(248, 250, 252, 0.95)"} strokeWidth={index === activePointIndex ? "3" : "2"} />
                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill="rgba(248, 250, 252, 0.98)"
                  fontSize="14"
                  fontWeight="700"
                >
                  {index + 1}
                </text>
              </g>
            ))}
          </svg>
        ) : null}
      </div>
    );
  }, [
    activePointIndex,
    cornerPoints,
    dataTestId,
    overlayHeight,
    overlayWidth,
    resolvedNaturalHeight,
    resolvedNaturalWidth,
    sampleBoxes,
  ]);

  const hoverInspectorStyle = hoverSample
    ? computeHoverInspectorStyle(hoverSample, {
        layerCount: 0,
        showMagnifier: true,
        showLayerDetails: false,
      })
    : null;
  const hoverInspectorOverlay = hoverSample && hoverInspectorStyle && typeof document !== "undefined"
    ? createPortal(
        <PreviewHoverInspector
          dataTestId={`${dataTestId}-hover-inspector`}
          style={hoverInspectorStyle}
          magnifierCanvasRef={magnifierCanvasRef}
          pixelX={hoverSample.pixelX}
          pixelY={hoverSample.pixelY}
          surfaceHex={hoverSurfaceHex}
          hoverLayerColors={[]}
          layerImagesLoading={false}
          showMagnifier
          showLayerDetails={false}
        />,
        document.body,
      )
    : null;

  return (
    <section className="flex flex-col gap-3 rounded-3xl border border-slate-200/80 bg-slate-50/80 p-4 shadow-[var(--shadow-panel)] dark:border-slate-700/80 dark:bg-slate-900/70">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50">{title}</h3>
        {hint ? <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p> : null}
      </div>

      {!imageUrl ? (
        <div
          data-testid={emptyStateTestId}
          className="flex min-h-64 items-center justify-center rounded-2xl border border-dashed border-slate-300/80 bg-slate-50/80 px-4 text-center text-sm text-slate-500 dark:border-slate-700/80 dark:bg-slate-950/60 dark:text-slate-400"
        >
          {emptyText}
        </div>
      ) : (
        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/60 p-3 dark:border-slate-700/80 dark:bg-slate-950/50">
          <div className="relative mx-auto w-full max-w-full">
            <div
              className="relative min-h-64 w-full overflow-hidden rounded-xl border border-slate-200/80 bg-slate-950/5 dark:border-slate-700/80 dark:bg-slate-950/30"
              style={previewAspectRatio ? { aspectRatio: previewAspectRatio } : undefined}
            >
              <CanvasPreviewSurface
                src={imageUrl}
                alt={alt}
                dataTestId={dataTestId}
                className={previewAspectRatio ? "h-full w-full" : "h-full min-h-64 w-full"}
                surfaceClassName={onSelectPoint ? "cursor-crosshair active:cursor-crosshair" : "cursor-grab active:cursor-grabbing"}
                imageClassName="object-contain"
                overlay={overlay}
                onSurfaceReady={handleSurfaceReady}
                onHoverSample={handleHoverSample}
                onClickSample={handleClickSample}
                canStartDrag={(_, context) => context.scale > 1}
                wheelZoomEnabled={false}
                renderingQuality="crisp"
              />
            </div>
          </div>
        </div>
      )}
      {hoverInspectorOverlay}
    </section>
  );
}
