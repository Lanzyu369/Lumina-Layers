import CloseButton from "./CloseButton";
import { useCallback, useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"

import { useI18n } from "../../i18n/context"
import type { CanvasPreviewHoverSample } from "./canvasPreviewUtils"
import CanvasPreviewSurface, { type CanvasPreviewSurfaceReadyPayload } from "./CanvasPreviewSurface"
import PreviewHoverInspector from "./PreviewHoverInspector"
import {
  HOVER_POPOVER_DELAY_MS,
  MAGNIFIER_SIZE_PX,
  MAGNIFIER_ZOOM,
  type PreviewCanvasBuffer,
  areHoverSamplesEqual,
  clampNumber,
  computeHoverInspectorStyle,
  mapPixelToBufferCoordinate,
  rgbToHex,
  setBoundedCacheValue,
} from "./previewHoverInspectorUtils"

interface LayerMaskViewerDialogLayer {
  layer_index: number
  name: string
  url: string
}

interface LayerMaskViewerDialogProps {
  open: boolean
  layers: LayerMaskViewerDialogLayer[]
  activeIndex: number | null
  onChangeIndex: (index: number) => void
  onClose: () => void
  isCompact?: boolean
}

const SURFACE_CACHE_LIMIT = 256

export default function LayerMaskViewerDialog({
  open,
  layers,
  activeIndex,
  onChangeIndex,
  onClose,
  isCompact = false,
}: LayerMaskViewerDialogProps) {
  const { t } = useI18n()
  const activeLayer = activeIndex !== null ? layers[activeIndex] ?? null : null
  const [hoverSample, setHoverSample] = useState<CanvasPreviewHoverSample | null>(null)
  const [hoverSurfaceHex, setHoverSurfaceHex] = useState<string | null>(null)
  const [previewCanvasBuffer, setPreviewCanvasBuffer] = useState<PreviewCanvasBuffer | null>(null)
  const pendingHoverSampleRef = useRef<CanvasPreviewHoverSample | null>(null)
  const hoverDelayTimerRef = useRef<number | null>(null)
  const magnifierCanvasRef = useRef<HTMLCanvasElement>(null)
  const surfaceSampleCacheRef = useRef<Map<string, string | null>>(new Map())

  const clearHoverDelayTimer = useCallback(() => {
    if (hoverDelayTimerRef.current !== null) {
      window.clearTimeout(hoverDelayTimerRef.current)
      hoverDelayTimerRef.current = null
    }
  }, [])

  const handlePreviewSurfaceReady = useCallback((payload: CanvasPreviewSurfaceReadyPayload | null) => {
    setPreviewCanvasBuffer(payload?.previewBuffer ?? null)
    surfaceSampleCacheRef.current.clear()
  }, [])

  const handlePreviewHoverSample = useCallback((sample: CanvasPreviewHoverSample | null) => {
    pendingHoverSampleRef.current = sample
    clearHoverDelayTimer()

    if (sample === null) {
      setHoverSample((previous) => (previous === null ? previous : null))
      return
    }

    setHoverSample((previous) => (previous === null ? previous : null))
    hoverDelayTimerRef.current = window.setTimeout(() => {
      hoverDelayTimerRef.current = null
      const pending = pendingHoverSampleRef.current
      if (!pending) {
        return
      }
      setHoverSample((previous) => (areHoverSamplesEqual(previous, pending) ? previous : pending))
    }, HOVER_POPOVER_DELAY_MS)
  }, [clearHoverDelayTimer])

  useEffect(() => () => {
    clearHoverDelayTimer()
  }, [clearHoverDelayTimer])

  useEffect(() => {
    if (!open || activeIndex === null) {
      return
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key === "ArrowLeft" && activeIndex > 0) {
        event.preventDefault()
        onChangeIndex(activeIndex - 1)
        return
      }
      if (event.key === "ArrowRight" && activeIndex < layers.length - 1) {
        event.preventDefault()
        onChangeIndex(activeIndex + 1)
      }
    }
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [activeIndex, layers.length, onChangeIndex, onClose, open])

  useEffect(() => {
    clearHoverDelayTimer()
    pendingHoverSampleRef.current = null
    surfaceSampleCacheRef.current.clear()
    setHoverSample(null)
    setHoverSurfaceHex(null)
    setPreviewCanvasBuffer(null)
  }, [activeLayer?.url, clearHoverDelayTimer, open])

  useEffect(() => {
    if (!hoverSample) {
      setHoverSurfaceHex((previous) => (previous === null ? previous : null))
      return
    }

    const previewBuffer = previewCanvasBuffer
    if (!previewBuffer) {
      setHoverSurfaceHex((previous) => (previous === null ? previous : null))
      return
    }

    const surfaceCacheKey = `${hoverSample.pixelX},${hoverSample.pixelY}`
    const cachedSurface = surfaceSampleCacheRef.current.get(surfaceCacheKey)
    if (cachedSurface !== undefined) {
      setHoverSurfaceHex((previous) => (previous === cachedSurface ? previous : cachedSurface))
      return
    }

    let sampledSurface: string | null = null
    const x = mapPixelToBufferCoordinate(
      hoverSample.pixelX,
      hoverSample.naturalWidth,
      previewBuffer.width,
    )
    const y = mapPixelToBufferCoordinate(
      hoverSample.pixelY,
      hoverSample.naturalHeight,
      previewBuffer.height,
    )

    try {
      const rgba = previewBuffer.context.getImageData(x, y, 1, 1).data
      sampledSurface = rgba[3] <= 8 ? null : rgbToHex(rgba[0], rgba[1], rgba[2])
    } catch {
      sampledSurface = null
    }

    setBoundedCacheValue(
      surfaceSampleCacheRef.current,
      surfaceCacheKey,
      sampledSurface,
      SURFACE_CACHE_LIMIT,
    )
    setHoverSurfaceHex((previous) => (previous === sampledSurface ? previous : sampledSurface))
  }, [hoverSample, previewCanvasBuffer])

  useEffect(() => {
    const magnifierCanvas = magnifierCanvasRef.current
    const context = magnifierCanvas?.getContext("2d")
    if (!magnifierCanvas || !context) {
      return
    }

    context.clearRect(0, 0, magnifierCanvas.width, magnifierCanvas.height)

    if (!hoverSample) {
      return
    }

    const previewBuffer = previewCanvasBuffer
    if (!previewBuffer) {
      return
    }

    const centerX = mapPixelToBufferCoordinate(
      hoverSample.pixelX,
      hoverSample.naturalWidth,
      previewBuffer.width,
    )
    const centerY = mapPixelToBufferCoordinate(
      hoverSample.pixelY,
      hoverSample.naturalHeight,
      previewBuffer.height,
    )

    const sourceSize = MAGNIFIER_SIZE_PX / MAGNIFIER_ZOOM
    const maxSourceX = Math.max(0, previewBuffer.width - sourceSize)
    const maxSourceY = Math.max(0, previewBuffer.height - sourceSize)
    const sourceX = clampNumber(centerX - sourceSize / 2, 0, maxSourceX)
    const sourceY = clampNumber(centerY - sourceSize / 2, 0, maxSourceY)

    context.imageSmoothingEnabled = false
    context.drawImage(
      previewBuffer.context.canvas,
      sourceX,
      sourceY,
      sourceSize,
      sourceSize,
      0,
      0,
      magnifierCanvas.width,
      magnifierCanvas.height,
    )

    const center = magnifierCanvas.width / 2
    context.strokeStyle = "rgba(255, 255, 255, 0.9)"
    context.lineWidth = 1
    context.beginPath()
    context.moveTo(center, 0)
    context.lineTo(center, magnifierCanvas.height)
    context.moveTo(0, center)
    context.lineTo(magnifierCanvas.width, center)
    context.stroke()
  }, [hoverSample, previewCanvasBuffer])

  const hoverInspectorStyle = hoverSample
    ? (() => {
        const baseStyle = computeHoverInspectorStyle(hoverSample, {
          layerCount: 0,
          showMagnifier: true,
          showLayerDetails: false,
        })
        return baseStyle ? { ...baseStyle, zIndex: 10000 } : null
      })()
    : null

  if (!open || activeIndex === null || !activeLayer || typeof document === "undefined") {
    return null
  }

  const currentIndex = activeIndex
  const totalLayers = layers.length
  const dialogTitle = `${t("action_layer_nth")}${currentIndex + 1}${t("action_layer_unit")}`
  const canGoPrev = currentIndex > 0
  const canGoNext = currentIndex < totalLayers - 1
  const dialogWidthClass = isCompact
    ? "w-[94vw] max-w-[94vw]"
    : "w-[90vw] max-w-[1200px]"
  const bodyHeightClass = isCompact ? "h-[64vh]" : "h-[72vh]"
  const iconButtonClass =
    "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm transition-colors hover:bg-slate-200/60 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent dark:hover:bg-slate-700/50"

  return createPortal(
    <>
      <div
        className="fixed inset-0 z-[9999] flex items-center justify-center p-4 backdrop-blur-sm"
        style={{ background: "var(--surface-scrim)" }}
        onClick={onClose}
        data-testid="layer-mask-viewer-overlay"
      >
        <div
          role="dialog"
          aria-modal="true"
          aria-label={dialogTitle}
          className={`relative flex max-h-[95vh] flex-col overflow-hidden rounded-2xl border shadow-2xl ${dialogWidthClass}`}
          style={{
            borderColor: "var(--surface-outline)",
            background: "var(--surface-panel-strong)",
          }}
          onClick={(event) => event.stopPropagation()}
          data-testid="layer-mask-viewer-dialog"
        >
          <div
            className="flex shrink-0 items-center gap-3 border-b px-4 py-2.5"
            style={{ borderColor: "var(--surface-outline)" }}
          >
            <div className="flex min-w-0 flex-1 items-center gap-2.5">
              <span
                className="inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-semibold"
                style={{
                  background:
                    "color-mix(in srgb, var(--surface-text-muted) 16%, transparent)",
                  color: "var(--surface-text-muted)",
                }}
              >
                {dialogTitle}
              </span>
              {!isCompact && activeLayer.name ? (
                <span
                  className="truncate text-sm"
                  style={{ color: "var(--surface-text-muted)" }}
                  title={activeLayer.name}
                >
                  {activeLayer.name}
                </span>
              ) : null}
            </div>

            <div
              className="inline-flex shrink-0 items-center gap-0.5 rounded-xl border p-1"
              style={{
                borderColor: "var(--surface-outline)",
                background:
                  "color-mix(in srgb, var(--surface-panel-strong) 55%, transparent)",
              }}
            >
              <button
                type="button"
                className={iconButtonClass}
                style={{ color: "var(--surface-text-muted)" }}
                onClick={() => onChangeIndex(Math.max(0, currentIndex - 1))}
                disabled={!canGoPrev}
                aria-label={t("action_layer_prev")}
                title={t("action_layer_prev")}
              >
                {t("action_layer_prev_arrow")}
              </button>
              <span
                className="min-w-[3.25rem] select-none px-1 text-center text-xs font-medium tabular-nums"
                style={{ color: "var(--surface-text-muted)" }}
              >
                {currentIndex + 1} / {totalLayers}
              </span>
              <button
                type="button"
                className={iconButtonClass}
                style={{ color: "var(--surface-text-muted)" }}
                onClick={() =>
                  onChangeIndex(Math.min(totalLayers - 1, currentIndex + 1))
                }
                disabled={!canGoNext}
                aria-label={t("action_layer_next")}
                title={t("action_layer_next")}
              >
                {t("action_layer_next_arrow")}
              </button>
            </div>

            <CloseButton label={t("action_close_overlay")} onClick={onClose} />
          </div>

          <div className={`relative min-h-0 ${bodyHeightClass}`}>
            <CanvasPreviewSurface
              src={activeLayer.url}
              alt={dialogTitle}
              className="h-full w-full checkerboard-bg"
              surfaceClassName="cursor-grab active:cursor-grabbing"
              resetLabel={t("zoom_reset")}
              onHoverSample={handlePreviewHoverSample}
              onSurfaceReady={handlePreviewSurfaceReady}
            />
          </div>
        </div>
      </div>
      {hoverSample && hoverInspectorStyle ? (
        <PreviewHoverInspector
          dataTestId="layer-mask-hover-inspector"
          style={hoverInspectorStyle}
          magnifierCanvasRef={magnifierCanvasRef}
          pixelX={hoverSample.pixelX}
          pixelY={hoverSample.pixelY}
          surfaceHex={hoverSurfaceHex}
          hoverLayerColors={[]}
          layerImagesLoading={false}
          showLayerDetails={false}
        />
      ) : null}
    </>,
    document.body,
  )
}
