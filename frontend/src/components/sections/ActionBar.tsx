import { useMemo, useState, useRef, useEffect, useCallback } from "react"
import { createPortal } from "react-dom"
import { buildLayerImagesSourceKey, resolveConverterSourceSelection, useConverterStore } from "../../stores/converter"
import Button from "../ui/Button"
import BatchResultSummary from "../ui/BatchResultSummary"
import CanvasPreviewSurface, { type CanvasPreviewSurfaceReadyPayload } from "../ui/CanvasPreviewSurface"
import LayerMaskViewerDialog from "../ui/LayerMaskViewerDialog"
import PreviewHoverInspector from "../ui/PreviewHoverInspector"
import {
  HOVER_POPOVER_DELAY_MS,
  HOVER_RESOURCE_RELEASE_DELAY_MS,
  MAGNIFIER_SIZE_PX,
  MAGNIFIER_ZOOM,
  type HoverLayerColorSample,
  type LayerCanvasBuffer,
  type PreviewCanvasBuffer,
  areHoverSamplesEqual,
  areLayerSamplesEqual,
  clampNumber,
  computeHoverInspectorStyle,
  mapPixelToBufferCoordinate,
  rgbToHex,
  setBoundedCacheValue,
} from "../ui/previewHoverInspectorUtils"
import type { CanvasPreviewHoverSample } from "../ui/canvasPreviewUtils"
import BedSizeSelector from "./BedSizeSelector"
import SlicerSelector from "./SlicerSelector"
import WikiTooltip from "../ui/WikiTooltip"
import { StatusBanner } from "../ui/panelPrimitives"
import { WIKI_DOCS } from "../../utils/wikiDocs"
import { resolvePreviewHoverPixel } from "./actionBarHoverUtils"
import { useI18n } from "../../i18n/context"
import { useWorkspaceMode } from "../../hooks/useWorkspaceMode"
import { apiErrorToVisibleMessage } from "../../api/client"
import {
  exportShareCard,
  exportSidecar,
  MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR,
} from "../../recipe/importFlow"

const EMPTY_LAYER_IMAGES: { layer_index: number; name: string; url: string }[] = []
const EXPORT_NO_IMAGE_MESSAGE = "No image file loaded"
const EXPORT_NO_PREVIEW_MESSAGE = "No preview available — please generate a preview first"
const EXPORT_PREVIEW_LOAD_MESSAGE = "Failed to load preview image for cover"
const GENERIC_HTTP_STATUS_ERROR_RE =
  /(?:Request failed with status code|HTTP(?:\s+error)?|status(?:\s+code)?)\s*\d{3}\b/i

function hasApiErrorResponse(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "response" in error)
}

function shouldUseApiErrorLanguage(error: unknown): boolean {
  if (hasApiErrorResponse(error)) {
    return true
  }
  const message = error instanceof Error ? error.message.trim() : ""
  return GENERIC_HTTP_STATUS_ERROR_RE.test(message)
}

function resolveRecipeExportError(error: unknown, t: (key: string) => string): string {
  if (error instanceof Error) {
    if (error.message === EXPORT_NO_IMAGE_MESSAGE) {
      return t("recipe_export_error_no_image")
    }
    if (error.message === EXPORT_NO_PREVIEW_MESSAGE) {
      return t("recipe_export_error_no_preview")
    }
    if (error.message === EXPORT_PREVIEW_LOAD_MESSAGE) {
      return t("recipe_export_error_preview_load")
    }
    if (error.message === MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR) {
      return t("recipe_export_model_surface_unavailable")
    }
  }
  if (shouldUseApiErrorLanguage(error)) {
    return apiErrorToVisibleMessage(error, t("recipe_export_error_unknown"))
  }
  return t("recipe_export_error_unknown")
}

export default function ActionBar() {
  const SURFACE_CACHE_LIMIT = 256
  const LAYER_CACHE_LIMIT = 128
  const { t } = useI18n()
  const workspace = useWorkspaceMode()
  const [zoomedLayerIdx, setZoomedLayerIdx] = useState<number | null>(null)
  const [hoverSample, setHoverSample] = useState<CanvasPreviewHoverSample | null>(null)
  const [hoverLayerColors, setHoverLayerColors] = useState<HoverLayerColorSample[]>([])
  const [hoverSurfaceHex, setHoverSurfaceHex] = useState<string | null>(null)
  const [previewCanvasBuffer, setPreviewCanvasBuffer] = useState<PreviewCanvasBuffer | null>(null)
  const [layerCanvasBuffers, setLayerCanvasBuffers] = useState<LayerCanvasBuffer[]>([])
  const pendingHoverSampleRef = useRef<CanvasPreviewHoverSample | null>(null)
  const hoverDelayTimerRef = useRef<number | null>(null)
  const hoverResourceReleaseTimerRef = useRef<number | null>(null)
  const magnifierCanvasRef = useRef<HTMLCanvasElement>(null)
  const fetchedLayerSourceRef = useRef<string | null>(null)
  const needsLayerHoverData = hoverSample !== null
  const layerSampleCacheRef = useRef<Map<string, HoverLayerColorSample[]>>(new Map())
  const surfaceSampleCacheRef = useRef<Map<string, string | null>>(new Map())

  const imageFile = useConverterStore((s) => s.imageFile)
  const lut_name = useConverterStore((s) => s.lut_name)
  const lut_names = useConverterStore((s) => s.lut_names)
  const lutListFull = useConverterStore((s) => s.lutListFull)
  const legacyCatalogGroups = useConverterStore((s) => s.legacyCatalogGroups)
  const sourceVersion = useConverterStore((s) => s.source_version)
  const selectedNativeBrandKey = useConverterStore((s) => s.selectedNativeBrandKey)
  const selectedNativeDbNames = useConverterStore((s) => s.selectedNativeDbNames)
  const nativeBrandGroups = useConverterStore((s) => s.nativeBrandGroups)
  const nativeColorLayers = useConverterStore((s) => s.color_layers)
  const nativeLayerHeightMm = useConverterStore((s) => s.layer_height_mm)
  const selectedMaterialDirNames = useConverterStore((s) => s.selectedMaterialDirNames)
  const materialLayerCount = useConverterStore((s) => s.materialLayerCount)
  const materialLayerHeightMm = useConverterStore((s) => s.materialLayerHeightMm)
  const isLoading = useConverterStore((s) => s.isLoading)
  const isGenerating = useConverterStore((s) => s.isGenerating)
  const replacePreviewLoading = useConverterStore((s) => s.replacePreviewLoading)
  const contentCommitStatus = useConverterStore((s) => s.contentCommitStatus)
  const reconcileUnknownContentCommit = useConverterStore((s) => s.reconcileUnknownContentCommit)
  const error = useConverterStore((s) => s.error)
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl)
  const previewBaseImageUrl = useConverterStore((s) => s.previewBaseImageUrl)
  const previewWidthMm = useConverterStore((s) => s.preview_width_mm)
  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth)
  const previewPixelHeight = useConverterStore((s) => s.previewPixelHeight)
  const puzzleOverlayUrl = useConverterStore((s) => s.puzzleOverlayUrl)
  const bedLabel = useConverterStore((s) => s.bed_label)
  const bedSizes = useConverterStore((s) => s.bedSizes)
  const submitPreview = useConverterStore((s) => s.submitPreview)
  const submitGenerate = useConverterStore((s) => s.submitGenerate)
  const submitFullPipeline = useConverterStore((s) => s.submitFullPipeline)
  const threemfDiskPath = useConverterStore((s) => s.threemfDiskPath)
  const downloadUrl = useConverterStore((s) => s.downloadUrl)
  const generateWarnings = useConverterStore((s) => s.generateWarnings)
  const sessionId = useConverterStore((s) => s.sessionId)
  const largeFormatEnabled = useConverterStore((s) => s.largeFormatEnabled)
  const modelSurfaceEnabled = useConverterStore((s) => s.modelSurfaceEnabled)

  const batchMode = useConverterStore((s) => s.batchMode)
  const batchFiles = useConverterStore((s) => s.batchFiles)
  const batchLoading = useConverterStore((s) => s.batchLoading)
  const batchResult = useConverterStore((s) => s.batchResult)
  const submitBatch = useConverterStore((s) => s.submitBatch)

  const fetchLayerImages = useConverterStore((s) => s.fetchLayerImages)
  const layerImagesLoading = useConverterStore((s) => s.layerImagesLoading)
  const layerImages = useConverterStore((s) => s.layerImages)
  const layerImagesSourceKey = useConverterStore((s) => s.layerImagesSourceKey)
  const layerImagesCurrentKey = useConverterStore(buildLayerImagesSourceKey)
  const sourceSelection = useMemo(
    () =>
      resolveConverterSourceSelection({
        source_version: sourceVersion,
        lut_name,
        lut_names,
        nativeBrandGroups,
        selectedNativeBrandKey,
        selectedNativeDbNames,
        color_layers: nativeColorLayers,
        layer_height_mm: nativeLayerHeightMm,
        selectedMaterialDirNames,
        materialLayerCount,
        materialLayerHeightMm,
        lutListFull,
        legacyCatalogGroups,
      }),
    [
      sourceVersion,
      lut_name,
      lut_names,
      nativeBrandGroups,
      selectedNativeBrandKey,
      selectedNativeDbNames,
      nativeColorLayers,
      nativeLayerHeightMm,
      selectedMaterialDirNames,
      materialLayerCount,
      materialLayerHeightMm,
      lutListFull,
      legacyCatalogGroups,
    ],
  )

  const [isExporting, setIsExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const canSubmit = !!imageFile && sourceSelection.isReady
  const canGenerate = canSubmit && !!sessionId
  const canBatchSubmit = batchFiles.length > 0 && sourceSelection.isReady
  const singleSourceHintKey =
    sourceVersion === "material"
      ? "action_select_material_hint"
      : sourceVersion === "native"
        ? "action_select_native_hint"
        : "action_select_lut_hint"
  const singleCombinedHintKey =
    sourceVersion === "material"
      ? "action_upload_hint_material"
      : sourceVersion === "native"
        ? "action_upload_hint_native"
        : "action_upload_hint"
  const singleSubmitHintKey = canSubmit
    ? null
    : imageFile
      ? singleSourceHintKey
      : sourceSelection.isReady
        ? "action_upload_image_hint"
        : singleCombinedHintKey
  const batchUploadHintKey =
    sourceVersion === "material"
      ? "action_batch_upload_hint_material"
      : sourceVersion === "native"
        ? "action_batch_upload_hint_native"
        : "action_batch_upload_hint"
  const previewDisplayUrl = puzzleOverlayUrl
    ? (previewBaseImageUrl ?? previewImageUrl)
    : previewImageUrl
  const activeLayerImages =
    layerImagesSourceKey === layerImagesCurrentKey ? layerImages : EMPTY_LAYER_IMAGES
  const hasPreview = !!previewDisplayUrl && !!sessionId

  const previewOverlay = useMemo(() => {
    if (!puzzleOverlayUrl) {
      return null
    }

    return (
      <>
        {puzzleOverlayUrl ? (
          <img
            src={puzzleOverlayUrl}
            alt=""
            className="pointer-events-none absolute inset-0 h-full w-full"
            draggable={false}
          />
        ) : null}
      </>
    )
  }, [puzzleOverlayUrl])

  const previewDebugOverlay = useMemo(() => (
    <div
      className="pointer-events-none absolute inset-0 border-2"
      style={{ borderColor: "var(--warning-border)" }}
      aria-hidden="true"
    />
  ), [])

  const handlePreviewSurfaceReady = useCallback((payload: CanvasPreviewSurfaceReadyPayload | null) => {
    setPreviewCanvasBuffer(payload?.previewBuffer ?? null)
    surfaceSampleCacheRef.current.clear()
  }, [])

  useEffect(() => {
    if (!sessionId) {
      fetchedLayerSourceRef.current = null
      return
    }

    if (
      !hasPreview ||
      !layerImagesCurrentKey ||
      layerImagesLoading ||
      activeLayerImages.length > 0
    ) {
      return
    }

    if (fetchedLayerSourceRef.current === layerImagesCurrentKey) {
      return
    }

    fetchedLayerSourceRef.current = layerImagesCurrentKey
    void fetchLayerImages(layerImagesCurrentKey)
  }, [
    activeLayerImages.length,
    fetchLayerImages,
    hasPreview,
    layerImagesCurrentKey,
    layerImagesLoading,
    sessionId,
  ])

  useEffect(() => {
    setZoomedLayerIdx(null)
  }, [sessionId])

  useEffect(() => {
    setZoomedLayerIdx((previous) => {
      if (previous === null) {
        return previous
      }
      return activeLayerImages[previous] ? previous : null
    })
  }, [activeLayerImages])

  useEffect(() => {
    if (hoverResourceReleaseTimerRef.current !== null) {
      window.clearTimeout(hoverResourceReleaseTimerRef.current)
      hoverResourceReleaseTimerRef.current = null
    }
    if (!previewDisplayUrl) {
      setPreviewCanvasBuffer(null)
      setLayerCanvasBuffers([])
      layerSampleCacheRef.current.clear()
      surfaceSampleCacheRef.current.clear()
      setHoverSample(null)
      setHoverLayerColors([])
      setHoverSurfaceHex(null)
      return
    }

    layerSampleCacheRef.current.clear()
    surfaceSampleCacheRef.current.clear()
    setLayerCanvasBuffers([])
    setHoverSample(null)
    setHoverLayerColors([])
    setHoverSurfaceHex(null)
  }, [previewDisplayUrl])

  useEffect(() => {
    let cancelled = false

    if (!needsLayerHoverData) {
      return () => {
        cancelled = true
      }
    }

    if (activeLayerImages.length === 0) {
      setLayerCanvasBuffers([])
      layerSampleCacheRef.current.clear()
      return () => {
        cancelled = true
      }
    }

    const buildBuffers = async () => {
      const loaded = await Promise.all(
        activeLayerImages.map(
          (layer) =>
            new Promise<LayerCanvasBuffer | null>((resolve) => {
              const image = new Image()
              image.crossOrigin = "anonymous"
              image.onload = () => {
                const width = image.naturalWidth || image.width
                const height = image.naturalHeight || image.height
                if (width <= 0 || height <= 0) {
                  resolve(null)
                  return
                }
                const canvas = document.createElement("canvas")
                canvas.width = width
                canvas.height = height
                const context = canvas.getContext("2d", { willReadFrequently: true })
                if (!context) {
                  resolve(null)
                  return
                }
                context.drawImage(image, 0, 0)
                resolve({
                  layerIndex: layer.layer_index,
                  name: layer.name,
                  width,
                  height,
                  context,
                })
              }
              image.onerror = () => resolve(null)
              image.src = layer.url
            }),
        ),
      )

      if (cancelled) return
      setLayerCanvasBuffers(loaded.filter((entry): entry is LayerCanvasBuffer => entry !== null))
      layerSampleCacheRef.current.clear()
    }

    void buildBuffers()

    return () => {
      cancelled = true
    }
  }, [activeLayerImages, needsLayerHoverData])

  useEffect(() => {
    return () => {
      if (hoverDelayTimerRef.current !== null) {
        window.clearTimeout(hoverDelayTimerRef.current)
        hoverDelayTimerRef.current = null
      }
      if (hoverResourceReleaseTimerRef.current !== null) {
        window.clearTimeout(hoverResourceReleaseTimerRef.current)
        hoverResourceReleaseTimerRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (!hoverSample) {
      setHoverLayerColors((previous) => (previous.length === 0 ? previous : []))
      setHoverSurfaceHex((previous) => (previous === null ? previous : null))
      return
    }

    const surfaceCacheKey = `${hoverSample.pixelX},${hoverSample.pixelY}`
    const resolvedLayerPixel = resolvePreviewHoverPixel(hoverSample, {
      rawWidth: previewPixelWidth,
      rawHeight: previewPixelHeight,
      previewWidthMm,
      bedLabel,
      bedSizes,
    })
    const layerBaseWidth =
      previewPixelWidth && previewPixelWidth > 0 ? previewPixelWidth : hoverSample.naturalWidth
    const layerBaseHeight =
      previewPixelHeight && previewPixelHeight > 0 ? previewPixelHeight : hoverSample.naturalHeight

    const previewBuffer = previewCanvasBuffer
    if (!previewBuffer) {
      setHoverSurfaceHex((previous) => (previous === null ? previous : null))
    } else {
      const cachedSurface = surfaceSampleCacheRef.current.get(surfaceCacheKey)
      if (cachedSurface !== undefined) {
        setHoverSurfaceHex((previous) => (previous === cachedSurface ? previous : cachedSurface))
      } else {
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
      }
    }

    const buffers = layerCanvasBuffers
    if (!resolvedLayerPixel || buffers.length === 0) {
      setHoverLayerColors((previous) => (previous.length === 0 ? previous : []))
      return
    }

    const layerCacheKey = `${resolvedLayerPixel.pixelX},${resolvedLayerPixel.pixelY}`
    const cachedLayers = layerSampleCacheRef.current.get(layerCacheKey)
    if (cachedLayers) {
      setHoverLayerColors((previous) => (
        areLayerSamplesEqual(previous, cachedLayers) ? previous : cachedLayers
      ))
      return
    }

    const sampledLayers = buffers.map((layer, index) => {
      const x = mapPixelToBufferCoordinate(resolvedLayerPixel.pixelX, layerBaseWidth, layer.width)
      const y = mapPixelToBufferCoordinate(resolvedLayerPixel.pixelY, layerBaseHeight, layer.height)

      try {
        const rgba = layer.context.getImageData(x, y, 1, 1).data
        const alpha = rgba[3]
        return {
          displayIndex: index + 1,
          layerName: layer.name,
          colorHex: alpha <= 8 ? null : rgbToHex(rgba[0], rgba[1], rgba[2]),
        }
      } catch {
        return {
          displayIndex: index + 1,
          layerName: layer.name,
          colorHex: null,
        }
      }
    })

    setBoundedCacheValue(
      layerSampleCacheRef.current,
      layerCacheKey,
      sampledLayers,
      LAYER_CACHE_LIMIT,
    )
    setHoverLayerColors((previous) => (
      areLayerSamplesEqual(previous, sampledLayers) ? previous : sampledLayers
    ))
  }, [
    hoverSample,
    previewPixelWidth,
    previewPixelHeight,
    previewWidthMm,
    bedLabel,
    bedSizes,
    previewCanvasBuffer,
    layerCanvasBuffers,
    SURFACE_CACHE_LIMIT,
    LAYER_CACHE_LIMIT,
  ])

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

  const handlePreviewHoverSample = useCallback((sample: CanvasPreviewHoverSample | null) => {
    pendingHoverSampleRef.current = sample

    if (hoverDelayTimerRef.current !== null) {
      window.clearTimeout(hoverDelayTimerRef.current)
      hoverDelayTimerRef.current = null
    }
    if (hoverResourceReleaseTimerRef.current !== null) {
      window.clearTimeout(hoverResourceReleaseTimerRef.current)
      hoverResourceReleaseTimerRef.current = null
    }

    if (sample === null) {
      setHoverSample((previous) => (previous === null ? previous : null))
      hoverResourceReleaseTimerRef.current = window.setTimeout(() => {
        hoverResourceReleaseTimerRef.current = null
        setLayerCanvasBuffers((previous) => (previous.length === 0 ? previous : []))
        layerSampleCacheRef.current.clear()
        surfaceSampleCacheRef.current.clear()
      }, HOVER_RESOURCE_RELEASE_DELAY_MS)
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
  }, [])

  const hoverInspectorStyle = hoverSample ? computeHoverInspectorStyle(hoverSample, {
    layerCount: hoverLayerColors.length,
    showMagnifier: true,
    showLayerDetails: true,
  }) : null

  const hoverInspectorContent = hoverSample && hoverInspectorStyle ? (
    <PreviewHoverInspector
      dataTestId="action-hover-inspector"
      style={hoverInspectorStyle}
      magnifierCanvasRef={magnifierCanvasRef}
      pixelX={hoverSample.pixelX}
      pixelY={hoverSample.pixelY}
      surfaceHex={hoverSurfaceHex}
      hoverLayerColors={hoverLayerColors}
      layerImagesLoading={layerImagesLoading}
    />
  ) : null

  const hoverInspectorOverlay = hoverInspectorContent && typeof document !== "undefined"
    ? createPortal(hoverInspectorContent, document.body)
    : null
  const previewAspectRatio = (
    previewPixelWidth && previewPixelWidth > 0 && previewPixelHeight && previewPixelHeight > 0
  )
    ? `${previewPixelWidth} / ${previewPixelHeight}`
    : undefined
  const previewSurfaceClassName = workspace.isCompact ? "min-h-[12rem]" : "min-h-[16rem]"
  const previewSurfaceOverlay = previewOverlay ? (
    <div className="absolute inset-0">
      {previewOverlay}
    </div>
  ) : null

  return (
    <div className="flex flex-col gap-3">
      {batchMode ? (
        <>
          {!canBatchSubmit && (
            <p className="text-xs text-yellow-600 dark:text-yellow-400">
              {t(batchUploadHintKey)}
            </p>
          )}

          <div className={`gap-2 ${workspace.isCompact ? "grid grid-cols-1" : "flex flex-wrap"}`}>
            <Button
              label={t("action_batch_generate")}
              variant="primary"
              onClick={() => void submitBatch()}
              disabled={!canBatchSubmit || batchLoading}
              loading={batchLoading}
            />
          </div>

          {batchResult && <BatchResultSummary result={batchResult} />}
        </>
      ) : (
        <>
          {contentCommitStatus === "unknown" && (
            <StatusBanner tone="warning" title={t("action_sync_editor_commit") }>
              <div className="flex flex-col gap-2">
                <span>{t("action_sync_editor_commit_hint")}</span>
                <Button
                  label={t("action_sync_editor_commit")}
                  variant="secondary"
                  onClick={() => void reconcileUnknownContentCommit()}
                  disabled={replacePreviewLoading || isGenerating}
                  className="w-full"
                />
              </div>
            </StatusBanner>
          )}
          {!canSubmit && (
            <p className="text-xs text-yellow-600 dark:text-yellow-400">
              {singleSubmitHintKey ? t(singleSubmitHintKey) : null}
            </p>
          )}

          <div className="grid grid-cols-1 gap-2">
            <Button
              label={t("action_preview")}
              variant="secondary"
              onClick={submitPreview}
              disabled={!canSubmit || isLoading}
              loading={isLoading}
              className="w-full"
            />
            <WikiTooltip
              title={t("action_generate_model_title")}
              description={t("action_generate_model_desc")}
              wikiPath={WIKI_DOCS.generateActions}
            >
              <Button
                label={t("action_generate")}
                variant="primary"
                onClick={() => void submitGenerate()}
                disabled={!canGenerate || isLoading || isGenerating || replacePreviewLoading}
                loading={isGenerating}
                className="w-full"
              />
            </WikiTooltip>
            {hasPreview && (
              <Button
                label={layerImagesLoading ? t("action_layers_loading") : t("action_view_layers")}
                variant="secondary"
                onClick={() => void fetchLayerImages(layerImagesCurrentKey)}
                disabled={layerImagesLoading}
                loading={layerImagesLoading}
                className="w-full"
              />
            )}
            {hasPreview && (
              <div className="flex gap-2">
                <Button
                  label={isExporting ? t("recipe_export_loading") : t("recipe_export_btn")}
                  variant="secondary"
                  onClick={() => {
                    setIsExporting(true)
                    setExportError(null)
                    exportShareCard()
                      .then(() => setExportError(null))
                      .catch((err: unknown) => {
                        setExportError(resolveRecipeExportError(err, t))
                      })
                      .finally(() => setIsExporting(false))
                  }}
                  disabled={isExporting || modelSurfaceEnabled}
                  loading={isExporting}
                  title={modelSurfaceEnabled ? t("recipe_export_model_surface_unavailable") : undefined}
                  className="flex-1"
                />
                <Button
                  label={t("recipe_export_sidecar_btn")}
                  variant="secondary"
                  onClick={() => {
                    setIsExporting(true)
                    setExportError(null)
                    exportSidecar()
                      .then(() => setExportError(null))
                      .catch((err: unknown) => {
                        setExportError(resolveRecipeExportError(err, t))
                      })
                      .finally(() => setIsExporting(false))
                  }}
                  disabled={isExporting || modelSurfaceEnabled}
                  title={modelSurfaceEnabled ? t("recipe_export_model_surface_unavailable") : undefined}
                  className="flex-1"
                />
              </div>
            )}
            {hasPreview && modelSurfaceEnabled && (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t("recipe_export_model_surface_unavailable")}
              </p>
            )}
            {exportError && (
              <div className="text-xs text-red-500 dark:text-red-400">
                {t("recipe_export_error").replace("{error}", exportError)}
              </div>
            )}
          </div>
        </>
      )}

      {error && (
        <div className="text-xs text-red-500 dark:text-red-400">{t(error)}</div>
      )}

      <BedSizeSelector />

      {previewDisplayUrl && (
        <div
          className={`w-full overflow-hidden rounded-[22px] border border-slate-300 dark:border-slate-700 ${previewSurfaceClassName}`}
          style={previewAspectRatio ? { aspectRatio: previewAspectRatio } : undefined}
        >
          <CanvasPreviewSurface
            src={previewDisplayUrl}
            alt={t("action_preview_alt")}
            className="h-full w-full"
            surfaceClassName="cursor-grab active:cursor-grabbing"
            overlay={previewSurfaceOverlay}
            floatingOverlay={previewDebugOverlay}
            resetLabel={t("zoom_reset")}
            // Quantized previews must downsample with nearest-neighbor so each
            // discrete color block keeps its identity in the thumbnail. Bilinear
            // smoothing averages a small bright cell with its (often differently
            // colored) neighbours, which makes 2D thumbs look "muddier" than
            // the 3D viewer where every pixel is its own mesh face.
            // 量化预览必须用最近邻缩放，否则小色块会被周围颜色"污染"，导致
            // 缩略图色感与 3D / 实物打印明显不一致。
            renderingQuality="crisp"
            onHoverSample={handlePreviewHoverSample}
            onSurfaceReady={handlePreviewSurfaceReady}
          />
        </div>
      )}
      {hoverInspectorOverlay}

      <LayerMaskViewerDialog
        open={zoomedLayerIdx !== null && !!activeLayerImages[zoomedLayerIdx]}
        layers={activeLayerImages}
        activeIndex={zoomedLayerIdx}
        onChangeIndex={setZoomedLayerIdx}
        onClose={() => setZoomedLayerIdx(null)}
        isCompact={workspace.isCompact}
      />

      {activeLayerImages.length > 0 && (
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <h4 className="mb-2 text-xs font-medium text-slate-600 dark:text-slate-400">
            {t("action_layers_title")}
          </h4>
          <div
            className={`grid gap-2 ${workspace.isCompact ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-3 sm:grid-cols-4 md:grid-cols-5"}`}
          >
            {activeLayerImages.map((layer, idx) => (
              <div
                key={layer.layer_index}
                className="group flex cursor-pointer flex-col items-center gap-1"
                onClick={() => setZoomedLayerIdx(idx)}
              >
                <div className="relative w-full overflow-hidden rounded border border-slate-200 dark:border-slate-600">
                  <img
                    src={layer.url}
                    alt={`${t("action_layer_nth")}${idx + 1}${t("action_layer_unit")}`}
                    className="w-full transition-transform group-hover:scale-105"
                    draggable={false}
                  />
                  <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/20">
                    <span className="text-sm text-white opacity-0 transition-opacity group-hover:opacity-100">
                      {t("action_zoom_icon")}
                    </span>
                  </div>
                </div>
                <span className="text-[11px] text-slate-600 dark:text-slate-400">
                  {t("action_layer_nth")}{idx + 1}{t("action_layer_unit")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {downloadUrl &&
        generateWarnings.includes("wipe_tower_manual_adjustment_required") && (
          <StatusBanner
            tone="warning"
            title={t("wipe_tower_manual_adjustment_title")}
          >
            {t("wipe_tower_manual_adjustment_warning")}
          </StatusBanner>
        )}

      <SlicerSelector
        threemfDiskPath={threemfDiskPath}
        downloadUrl={downloadUrl}
        canSubmit={batchMode ? canBatchSubmit && !batchLoading : canSubmit}
        largeFormat={batchMode ? false : largeFormatEnabled}
        onAutoGenerate={async () => {
          if (batchMode) {
            await submitBatch()
            const state = useConverterStore.getState()
            return state.downloadUrl ?? state.threemfDiskPath ?? null
          }
          await submitFullPipeline()
          const state = useConverterStore.getState()
          return state.downloadUrl ?? state.threemfDiskPath ?? null
        }}
      />
    </div>
  )
}
