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
  renderingQuality = "default",
  onHoverSample,
  onClickSample,
  onScaleChange,
  onSurfaceReady,
  canStartDrag,
}: CanvasPreviewSurfaceProps) {
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
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 })
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 })
  const [scale, setScale] = useState(1)
  const [translate, setTranslate] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)

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
    activePointerIdRef.current = null
    setIsDragging(false)
    emitHoverSample(null)
  }, [emitHoverSample, src])

  useEffect(() => {
    if (!interactionsDisabled) {
      return
    }

    lastPointerClientRef.current = null
    dragMovedRef.current = false
    activePointerIdRef.current = null
    setIsDragging(false)
    emitHoverSample(null)
  }, [emitHoverSample, interactionsDisabled])

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

  // React's synthetic `onWheel` registers as a passive listener at the root,
  // so `event.preventDefault()` inside a React handler cannot stop the page
  // from scrolling while the user zooms the preview. We therefore attach a
  // native `wheel` listener with `{ passive: false }` directly on the
  // container element.
  // React 合成事件 `onWheel` 在根节点是 passive 注册的，React 回调里调用
  // `event.preventDefault()` 无法阻止页面滚动。因此我们改为在容器上直接挂
  // 一个 `{ passive: false }` 的原生 `wheel` 监听器。
  useEffect(() => {
    const container = containerRef.current
    if (!container || !wheelZoomEnabled) {
      return
    }

    const handleNativeWheel = (event: globalThis.WheelEvent) => {
      event.preventDefault()
      if (interactionsDisabled) {
        lastPointerClientRef.current = null
        emitHoverSample(null)
        return
      }
      lastPointerClientRef.current = null
      emitHoverSample(null)
      const rect = container.getBoundingClientRect()

      const mousePos = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      }
      const currentScale = scaleRef.current
      const currentTranslate = translateRef.current
      const nextScale = clampCanvasPreviewScale(
        wheelZoomStepMultiplier
          ? currentScale * (event.deltaY < 0 ? wheelZoomStepMultiplier : 1 / wheelZoomStepMultiplier)
          : currentScale * (1 - event.deltaY * wheelZoomSensitivity),
        minScale,
        maxScale,
      )
      const nextTranslate = computeCanvasPreviewZoomTranslate(
        mousePos,
        currentTranslate,
        currentScale,
        nextScale,
      )

      setScale(nextScale)
      setTranslate(nextTranslate)
    }

    container.addEventListener("wheel", handleNativeWheel, { passive: false })
    return () => {
      container.removeEventListener("wheel", handleNativeWheel)
    }
  }, [
    emitHoverSample,
    interactionsDisabled,
    maxScale,
    minScale,
    wheelZoomEnabled,
    wheelZoomSensitivity,
    wheelZoomStepMultiplier,
  ])

  const handlePointerDown = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (interactionsDisabled) {
        event.preventDefault()
        lastPointerClientRef.current = null
        emitHoverSample(null)
        return
      }

      const dragAllowed = canStartDrag
        ? canStartDrag(event, { scale: scaleRef.current })
        : true
      if (!dragAllowed) {
        return
      }

      event.preventDefault()
      lastPointerClientRef.current = null
      emitHoverSample(null)
      dragMovedRef.current = false
      activePointerIdRef.current = event.pointerId
      setIsDragging(true)
      dragStartRef.current = { x: event.clientX, y: event.clientY }
      translateAtDragStartRef.current = { ...translate }
      event.currentTarget.setPointerCapture?.(event.pointerId)
    },
    [canStartDrag, emitHoverSample, interactionsDisabled, translate],
  )

  const handlePointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (interactionsDisabled) {
        lastPointerClientRef.current = null
        emitHoverSample(null)
        return
      }

      if (isDragging && activePointerIdRef.current === event.pointerId) {
        const dx = event.clientX - dragStartRef.current.x
        const dy = event.clientY - dragStartRef.current.y
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
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
    [emitHoverSample, interactionsDisabled, isDragging, mapPointerToHoverSample],
  )

  const endPointerDrag = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (activePointerIdRef.current !== null && activePointerIdRef.current === event.pointerId) {
      event.currentTarget.releasePointerCapture?.(event.pointerId)
    }
    activePointerIdRef.current = null
    setIsDragging(false)
  }, [])

  const handlePointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
    endPointerDrag(event)
  }, [endPointerDrag])

  const handlePointerCancel = useCallback((event: PointerEvent<HTMLDivElement>) => {
    endPointerDrag(event)
    dragMovedRef.current = false
    lastPointerClientRef.current = null
    emitHoverSample(null)
  }, [emitHoverSample, endPointerDrag])

  const handleLostPointerCapture = useCallback(() => {
    activePointerIdRef.current = null
    setIsDragging(false)
  }, [])

  const handlePointerLeave = useCallback(() => {
    if (isDragging) {
      return
    }
    setIsDragging(false)
    dragMovedRef.current = false
    lastPointerClientRef.current = null
    emitHoverSample(null)
  }, [emitHoverSample, isDragging])

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
        className={`relative h-full w-full overflow-hidden ${className ?? ""} ${surfaceClassName ?? "cursor-grab active:cursor-grabbing"}`.trim()}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        onPointerLeave={handlePointerLeave}
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
