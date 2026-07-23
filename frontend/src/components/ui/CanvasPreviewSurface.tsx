import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react"

import {
  clampCanvasPreviewScale,
  computeCanvasPreviewZoomTranslate,
  createCanvasPreviewBuffer,
  createHoverSampleEmitter,
  drawCanvasPreviewFrame,
  mapPointerToCanvasPreviewHoverSample,
  resolveCanvasPreviewImageRect,
  type CanvasPreviewBuffer,
  type CanvasPreviewHoverSample,
  type CanvasPreviewRenderingQuality,
} from "./canvasPreviewUtils"
import { useI18n } from "../../i18n/context"
import {
  useSpacePanModifier,
  type SpacePanDeactivateReason,
} from "../../hooks/useSpacePanModifier"

export interface CanvasPreviewSurfaceReadyPayload {
  image: HTMLImageElement
  previewBuffer: CanvasPreviewBuffer | null
}

interface CanvasPreviewSurfaceDragContext {
  scale: number
}

interface CanvasPreviewSurfaceProps {
  src: string
  alt: string
  dataTestId?: string
  className?: string
  surfaceClassName?: string
  imageClassName?: string
  overlay?: ReactNode
  floatingOverlay?: ReactNode
  interactionsDisabled?: boolean
  resetLabel?: string
  minScale?: number
  maxScale?: number
  wheelZoomEnabled?: boolean
  wheelZoomSensitivity?: number
  wheelZoomStepMultiplier?: number
  resetOnDoubleClick?: boolean
  middleButtonPanEnabled?: boolean
  spacePanEnabled?: boolean
  renderingQuality?: CanvasPreviewRenderingQuality
  onHoverSample?: (sample: CanvasPreviewHoverSample | null) => void
  onClickSample?: (sample: CanvasPreviewHoverSample, event: ReactMouseEvent<HTMLDivElement>) => void
  onScaleChange?: (scale: number) => void
  onSurfaceReady?: (payload: CanvasPreviewSurfaceReadyPayload | null) => void
  canStartDrag?: (
    event: PointerEvent<HTMLDivElement>,
    context: CanvasPreviewSurfaceDragContext,
  ) => boolean
}

export default function CanvasPreviewSurface({
  src,
  alt,
  dataTestId = "canvas-preview-surface",
  className,
  surfaceClassName,
  imageClassName,
  overlay,
  floatingOverlay,
  interactionsDisabled = false,
  resetLabel,
  minScale = 0.5,
  maxScale = 5,
  wheelZoomEnabled = true,
  wheelZoomSensitivity = 0.001,
  wheelZoomStepMultiplier,
  resetOnDoubleClick = false,
  middleButtonPanEnabled = false,
  spacePanEnabled = false,
  renderingQuality = "default",
  onHoverSample,
  onClickSample,
  onScaleChange,
  onSurfaceReady,
  canStartDrag,
}: CanvasPreviewSurfaceProps) {
  const { t } = useI18n()
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const hoverSampleCallbackRef = useRef(onHoverSample)
  const surfaceReadyCallbackRef = useRef(onSurfaceReady)
  const clickSampleCallbackRef = useRef(onClickSample)
  const scaleChangeCallbackRef = useRef(onScaleChange)
  const lastPointerClientRef = useRef<{ x: number; y: number } | null>(null)
  const dragStartRef = useRef({ x: 0, y: 0 })
  const translateAtDragStartRef = useRef({ x: 0, y: 0 })
  const dragMovedRef = useRef(false)
  const activePointerIdRef = useRef<number | null>(null)
  const activeDragButtonRef = useRef<number | null>(null)
  const activeDragSourceRef = useRef<"pointer" | "space-left" | null>(null)
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 })
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 })
  const [scale, setScale] = useState(1)
  const [translate, setTranslate] = useState({ x: 0, y: 0 })
  const [failedSrc, setFailedSrc] = useState<string | null>(null)

  const finishActiveDrag = useCallback((pointerId?: number, cancelled = false) => {
    const activePointerId = activePointerIdRef.current
    if (activePointerId === null || (pointerId !== undefined && pointerId !== activePointerId)) {
      return
    }

    const container = containerRef.current
    try {
      container?.releasePointerCapture?.(activePointerId)
    } catch {
      // The browser may already have released capture after pointercancel/lostcapture.
    }
    activePointerIdRef.current = null
    activeDragButtonRef.current = null
    activeDragSourceRef.current = null
    if (cancelled) {
      dragMovedRef.current = false
    }
  }, [])

  const handleSpacePanDeactivate = useCallback(
    (reason: SpacePanDeactivateReason) => {
      if (activeDragSourceRef.current !== "space-left") {
        return
      }
      finishActiveDrag(undefined, reason !== "keyup")
    },
    [finishActiveDrag],
  )
  const {
    isActive: isSpacePanActive,
    isActiveRef: isSpacePanActiveRef,
    handlePointerEnter: handleSpacePanPointerEnter,
    handlePointerLeave: handleSpacePanPointerLeave,
  } = useSpacePanModifier({
    enabled: spacePanEnabled,
    onDeactivate: handleSpacePanDeactivate,
  })

  const naturalSizeRef = useRef(naturalSize)
  const scaleRef = useRef(scale)
  const translateRef = useRef(translate)

  hoverSampleCallbackRef.current = onHoverSample
  surfaceReadyCallbackRef.current = onSurfaceReady
  clickSampleCallbackRef.current = onClickSample
  scaleChangeCallbackRef.current = onScaleChange
  naturalSizeRef.current = naturalSize
  scaleRef.current = scale
  translateRef.current = translate

  const updateContainerSize = useCallback(() => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) {
      return
    }

    setContainerSize({
      width: rect.width,
      height: rect.height,
    })
  }, [])

  const emitHoverSample = useMemo(
    () => createHoverSampleEmitter((sample) => {
      hoverSampleCallbackRef.current?.(sample)
    }),
    [],
  )

  const notifySurfaceReady = useCallback((payload: CanvasPreviewSurfaceReadyPayload | null) => {
    surfaceReadyCallbackRef.current?.(payload)
  }, [])

  const mapPointerToHoverSample = useCallback(
    (clientX: number, clientY: number): CanvasPreviewHoverSample | null => {
      const rect = containerRef.current?.getBoundingClientRect()
      const currentNaturalSize = naturalSizeRef.current
      if (!rect) {
        return null
      }

      const currentImageRect = resolveCanvasPreviewImageRect(
        { width: rect.width, height: rect.height },
        currentNaturalSize,
      )
      if (!currentImageRect) {
        return null
      }

      return mapPointerToCanvasPreviewHoverSample({
        clientX,
        clientY,
        containerRect: rect,
        imageRect: currentImageRect,
        naturalWidth: currentNaturalSize.width,
        naturalHeight: currentNaturalSize.height,
        scale: scaleRef.current,
        translate: translateRef.current,
      })
    },
    [],
  )

  const syncHoverSample = useCallback(() => {
    const lastPointer = lastPointerClientRef.current
    if (!lastPointer) {
      emitHoverSample(null)
      return
    }

    emitHoverSample(mapPointerToHoverSample(lastPointer.x, lastPointer.y))
  }, [emitHoverSample, mapPointerToHoverSample])

  useEffect(() => {
    updateContainerSize()
    const container = containerRef.current
    if (!container || typeof ResizeObserver === "undefined") {
      return
    }

    const observer = new ResizeObserver(() => {
      updateContainerSize()
      syncHoverSample()
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [syncHoverSample, updateContainerSize])

  useEffect(() => {
    const handleWindowLayoutChange = () => {
      updateContainerSize()
      syncHoverSample()
    }

    window.addEventListener("resize", handleWindowLayoutChange)
    window.addEventListener("scroll", handleWindowLayoutChange, true)
    return () => {
      window.removeEventListener("resize", handleWindowLayoutChange)
      window.removeEventListener("scroll", handleWindowLayoutChange, true)
    }
  }, [syncHoverSample, updateContainerSize])

  useEffect(() => {
    lastPointerClientRef.current = null
    dragMovedRef.current = false
    finishActiveDrag(undefined, true)
    emitHoverSample(null)
  }, [emitHoverSample, finishActiveDrag, src])

  useEffect(() => {
    if (!interactionsDisabled) {
      return
    }

    lastPointerClientRef.current = null
    dragMovedRef.current = false
    finishActiveDrag(undefined, true)
    emitHoverSample(null)
  }, [emitHoverSample, finishActiveDrag, interactionsDisabled])

  useEffect(() => {
    const handleWindowPointerUp = (event: globalThis.PointerEvent) => {
      finishActiveDrag(event.pointerId)
    }
    const handleWindowPointerCancel = (event: globalThis.PointerEvent) => {
      finishActiveDrag(event.pointerId, true)
    }
    const handleWindowBlur = () => finishActiveDrag(undefined, true)

    window.addEventListener("pointerup", handleWindowPointerUp)
    window.addEventListener("pointercancel", handleWindowPointerCancel)
    window.addEventListener("blur", handleWindowBlur)
    return () => {
      window.removeEventListener("pointerup", handleWindowPointerUp)
      window.removeEventListener("pointercancel", handleWindowPointerCancel)
      window.removeEventListener("blur", handleWindowBlur)
      finishActiveDrag(undefined, true)
    }
  }, [finishActiveDrag])

  useEffect(() => {
    notifySurfaceReady(null)
  }, [notifySurfaceReady])

  useEffect(() => {
    scaleChangeCallbackRef.current?.(scale)
  }, [scale])

  useEffect(() => {
    let cancelled = false

    const image = new Image()
    image.crossOrigin = "anonymous"

    image.onload = () => {
      if (cancelled) {
        return
      }

      imageRef.current = image
      setFailedSrc(null)
      setScale(1)
      setTranslate({ x: 0, y: 0 })
      updateContainerSize()
      setNaturalSize({ width: image.naturalWidth, height: image.naturalHeight })
      notifySurfaceReady({
        image,
        previewBuffer: createCanvasPreviewBuffer(image),
      })
    }

    image.onerror = () => {
      if (cancelled) {
        return
      }

      imageRef.current = null
      setFailedSrc(src)
      setNaturalSize({ width: 0, height: 0 })
      lastPointerClientRef.current = null
      emitHoverSample(null)
      notifySurfaceReady(null)
    }

    image.src = src

    return () => {
      cancelled = true
      image.onload = null
      image.onerror = null
    }
  }, [emitHoverSample, notifySurfaceReady, src, updateContainerSize])

  const imageRect = useMemo(
    () => resolveCanvasPreviewImageRect(containerSize, naturalSize),
    [containerSize, naturalSize],
  )
  const loadFailed = failedSrc === src

  useEffect(() => {
    const canvas = canvasRef.current
    const image = imageRef.current
    const context = canvas?.getContext("2d")
    if (!canvas || !context) {
      return
    }

    if (!image || !imageRect) {
      canvas.width = 0
      canvas.height = 0
      return
    }

    drawCanvasPreviewFrame({
      canvas,
      context,
      image,
      containerSize,
      imageRect,
      scale,
      translate,
      devicePixelRatio: window.devicePixelRatio,
      renderingQuality,
    })
  }, [containerSize, imageRect, renderingQuality, scale, translate])

  const resetZoom = useCallback(() => {
    setScale(1)
    setTranslate({ x: 0, y: 0 })
    lastPointerClientRef.current = null
    emitHoverSample(null)
  }, [emitHoverSample])

  // Native non-passive wheel listener: React delegates wheel as passive
  // since v17, so preventDefault() inside a synthetic onWheel handler is a
  // no-op and the surrounding ActionBar dock still consumes the wheel while
  // the user tries to zoom the embedded 2D preview. Binding via
  // addEventListener with { passive: false } guarantees zoom-in-preview
  // does not also scroll the surrounding dock. stopPropagation() keeps any
  // other parent scroll containers unaffected.
  const handleWheelRef = useRef<(event: globalThis.WheelEvent) => void>(() => {})
  handleWheelRef.current = (event: globalThis.WheelEvent) => {
    if (!wheelZoomEnabled) {
      return
    }
    event.preventDefault()
    event.stopPropagation()
    if (interactionsDisabled) {
      lastPointerClientRef.current = null
      emitHoverSample(null)
      return
    }
    lastPointerClientRef.current = null
    emitHoverSample(null)
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) {
      return
    }

    const mousePos = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    }
    const nextScale = clampCanvasPreviewScale(
      wheelZoomStepMultiplier
        ? scale * (event.deltaY < 0 ? wheelZoomStepMultiplier : 1 / wheelZoomStepMultiplier)
        : scale * (1 - event.deltaY * wheelZoomSensitivity),
      minScale,
      maxScale,
    )
    const nextTranslate = computeCanvasPreviewZoomTranslate(mousePos, translate, scale, nextScale)

    setScale(nextScale)
    setTranslate(nextTranslate)
  }

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      return
    }
    const listener = (event: globalThis.WheelEvent) => handleWheelRef.current(event)
    container.addEventListener("wheel", listener, { passive: false })
    return () => container.removeEventListener("wheel", listener)
  }, [])

  const handlePointerDown = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (interactionsDisabled) {
        event.preventDefault()
        lastPointerClientRef.current = null
        emitHoverSample(null)
        return
      }

      const isSpaceLeftDrag = spacePanEnabled
        && isSpacePanActiveRef.current
        && event.button === 0
      const isMiddleButtonDrag = middleButtonPanEnabled && event.button === 1
      const dragAllowed = isSpaceLeftDrag || isMiddleButtonDrag || (canStartDrag
        ? canStartDrag(event, { scale: scaleRef.current })
        : true)
      if (!dragAllowed) {
        return
      }

      event.preventDefault()
      lastPointerClientRef.current = null
      emitHoverSample(null)
      // A Space+left gesture must never fall through to the normal click
      // selection path, even when the pointer barely moves.
      dragMovedRef.current = isSpaceLeftDrag
      activePointerIdRef.current = event.pointerId
      activeDragButtonRef.current = event.button
      activeDragSourceRef.current = isSpaceLeftDrag ? "space-left" : "pointer"
      dragStartRef.current = { x: event.clientX, y: event.clientY }
      translateAtDragStartRef.current = { ...translateRef.current }
      event.currentTarget.setPointerCapture?.(event.pointerId)
    },
    [
      canStartDrag,
      emitHoverSample,
      interactionsDisabled,
      isSpacePanActiveRef,
      middleButtonPanEnabled,
      spacePanEnabled,
    ],
  )

  const handlePointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (interactionsDisabled) {
        lastPointerClientRef.current = null
        emitHoverSample(null)
        return
      }

      if (activePointerIdRef.current === event.pointerId) {
        const dx = event.clientX - dragStartRef.current.x
        const dy = event.clientY - dragStartRef.current.y
        if (
          activeDragButtonRef.current === 0
          && (Math.abs(dx) > 3 || Math.abs(dy) > 3)
        ) {
          dragMovedRef.current = true
        }
        setTranslate({
          x: translateAtDragStartRef.current.x + dx,
          y: translateAtDragStartRef.current.y + dy,
        })
        lastPointerClientRef.current = null
        emitHoverSample(null)
        return
      }

      lastPointerClientRef.current = { x: event.clientX, y: event.clientY }
      emitHoverSample(mapPointerToHoverSample(event.clientX, event.clientY))
    },
    [emitHoverSample, interactionsDisabled, mapPointerToHoverSample],
  )

  const handlePointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
    finishActiveDrag(event.pointerId)
  }, [finishActiveDrag])

  const handlePointerCancel = useCallback((event: PointerEvent<HTMLDivElement>) => {
    finishActiveDrag(event.pointerId, true)
    lastPointerClientRef.current = null
    emitHoverSample(null)
  }, [emitHoverSample, finishActiveDrag])

  const handleLostPointerCapture = useCallback(() => {
    activePointerIdRef.current = null
    activeDragButtonRef.current = null
    activeDragSourceRef.current = null
  }, [])

  const handlePointerLeave = useCallback(() => {
    if (activePointerIdRef.current !== null) {
      return
    }
    dragMovedRef.current = false
    lastPointerClientRef.current = null
    emitHoverSample(null)
  }, [emitHoverSample])

  const handleMouseDown = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    if (
      (middleButtonPanEnabled && event.button === 1)
      || (spacePanEnabled && isSpacePanActiveRef.current && event.button === 0)
    ) {
      event.preventDefault()
    }
  }, [isSpacePanActiveRef, middleButtonPanEnabled, spacePanEnabled])

  const handleAuxClick = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    if (middleButtonPanEnabled && event.button === 1) {
      event.preventDefault()
    }
  }, [middleButtonPanEnabled])

  const handleSurfacePointerLeave = useCallback(() => {
    handleSpacePanPointerLeave()
    handlePointerLeave()
  }, [handlePointerLeave, handleSpacePanPointerLeave])

  const handleClick = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (interactionsDisabled) {
        return
      }

      if (dragMovedRef.current) {
        dragMovedRef.current = false
        return
      }

      const sample = mapPointerToHoverSample(event.clientX, event.clientY)
      if (!sample) {
        return
      }

      clickSampleCallbackRef.current?.(sample, event)
    },
    [interactionsDisabled, mapPointerToHoverSample],
  )

  const handleDoubleClick = useCallback(() => {
    if (!resetOnDoubleClick || interactionsDisabled) {
      return
    }
    resetZoom()
  }, [interactionsDisabled, resetOnDoubleClick, resetZoom])

  return (
    <div className="relative h-full w-full">
      <div
        ref={containerRef}
        data-testid={dataTestId}
        data-space-pan-active={isSpacePanActive || undefined}
        data-preview-translate-x={translate.x}
        data-preview-translate-y={translate.y}
        className={`relative h-full w-full overflow-hidden ${className ?? ""} ${surfaceClassName ?? "cursor-grab active:cursor-grabbing"}`.trim()}
        onContextMenu={(event) => event.preventDefault()}
        onMouseDown={handleMouseDown}
        onAuxClick={handleAuxClick}
        onPointerEnter={handleSpacePanPointerEnter}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        onPointerLeave={handleSurfacePointerLeave}
        onLostPointerCapture={handleLostPointerCapture}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
      >
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={alt}
          className={`block h-full w-full select-none ${imageClassName ?? ""}`.trim()}
        />
        {loadFailed ? (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center p-4">
            <div
              role="alert"
              className="status-banner max-w-sm text-center text-sm font-medium"
              data-tone="error"
            >
              {t("canvas_preview_load_failed")}
            </div>
          </div>
        ) : null}
        {overlay && imageRect ? (
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              transformOrigin: "0 0",
              transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
            }}
          >
            <div
              className="absolute"
              style={{
                left: `${imageRect.x}px`,
                top: `${imageRect.y}px`,
                width: `${imageRect.width}px`,
                height: `${imageRect.height}px`,
              }}
            >
              {overlay}
            </div>
          </div>
        ) : null}
      </div>
      {floatingOverlay ? (
        <div className="pointer-events-none absolute inset-0 z-10">
          {floatingOverlay}
        </div>
      ) : null}
      {resetLabel ? (
        <button
          type="button"
          onClick={resetZoom}
          disabled={interactionsDisabled}
          className="absolute right-2 top-2 rounded border px-2 py-1 text-xs transition-opacity hover:opacity-90 disabled:opacity-60"
          style={{
            borderColor: "var(--surface-outline)",
            background: "color-mix(in srgb, var(--surface-panel-strong) 88%, transparent)",
            color: "var(--surface-text-muted)",
          }}
        >
          {resetLabel}
        </button>
      ) : null}
    </div>
  )
}
