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
  type CanvasPreviewPoint,
  type CanvasPreviewRect,
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

export interface CanvasPreviewSurfaceViewport {
  containerSize: { width: number; height: number }
  naturalSize: { width: number; height: number }
  imageRect: CanvasPreviewRect
  imageScreenRect: CanvasPreviewRect
  scale: number
  translate: CanvasPreviewPoint
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
  screenSpaceOverlay?: ReactNode | ((viewport: CanvasPreviewSurfaceViewport) => ReactNode)
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
  onClickSample?: (
    sample: CanvasPreviewHoverSample,
    event: ReactMouseEvent<HTMLDivElement> | PointerEvent<HTMLDivElement>,
  ) => void
  onStrokeStart?: (sample: CanvasPreviewHoverSample, event: PointerEvent<HTMLDivElement>) => void
  onStrokeMove?: (sample: CanvasPreviewHoverSample, event: PointerEvent<HTMLDivElement>) => void
  onStrokeEnd?: (sample: CanvasPreviewHoverSample | null, event: PointerEvent<HTMLDivElement>) => void
  onStrokeCancel?: () => void
  onScaleChange?: (scale: number) => void
  onSurfaceReady?: (payload: CanvasPreviewSurfaceReadyPayload | null) => void
  canStartDrag?: (
    event: PointerEvent<HTMLDivElement>,
    context: CanvasPreviewSurfaceDragContext,
  ) => boolean
  /**
   * 为 true 时，指针移出图像渲染区域（只要仍在容器内）hover 采样不再返回 null，
   * 而是返回带 isOutOfImage 标记的采样点。配合选区画笔等"光标需越过图像边缘"
   * 的场景使用。笔划采样（onStrokeStart/Move/End）不受影响，仍然仅限图像内部。
   */
  allowOutOfImageHover?: boolean
}

export default function CanvasPreviewSurface({
  src,
  alt,
  dataTestId = "canvas-preview-surface",
  className,
  surfaceClassName,
  imageClassName,
  overlay,
  screenSpaceOverlay,
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
  onStrokeStart,
  onStrokeMove,
  onStrokeEnd,
  onStrokeCancel,
  onScaleChange,
  onSurfaceReady,
  canStartDrag,
  allowOutOfImageHover = false,
}: CanvasPreviewSurfaceProps) {
  const { t } = useI18n()
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const hoverSampleCallbackRef = useRef(onHoverSample)
  const surfaceReadyCallbackRef = useRef(onSurfaceReady)
  const clickSampleCallbackRef = useRef(onClickSample)
  const allowOutOfImageHoverRef = useRef(allowOutOfImageHover)
  const strokeStartCallbackRef = useRef(onStrokeStart)
  const strokeMoveCallbackRef = useRef(onStrokeMove)
  const strokeEndCallbackRef = useRef(onStrokeEnd)
  const strokeCancelCallbackRef = useRef(onStrokeCancel)
  const scaleChangeCallbackRef = useRef(onScaleChange)
  const lastPointerClientRef = useRef<{ x: number; y: number } | null>(null)
  const dragStartRef = useRef({ x: 0, y: 0 })
  const translateAtDragStartRef = useRef({ x: 0, y: 0 })
  const dragMovedRef = useRef(false)
  const activePointerIdRef = useRef<number | null>(null)
  const activeStrokePointerIdRef = useRef<number | null>(null)
  const clickCandidateRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    moved: boolean
  } | null>(null)
  const pointerUpClickRef = useRef<{
    clientX: number
    clientY: number
    timeStamp: number
  } | null>(null)
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
  allowOutOfImageHoverRef.current = allowOutOfImageHover
  surfaceReadyCallbackRef.current = onSurfaceReady
  clickSampleCallbackRef.current = onClickSample
  strokeStartCallbackRef.current = onStrokeStart
  strokeMoveCallbackRef.current = onStrokeMove
  strokeEndCallbackRef.current = onStrokeEnd
  strokeCancelCallbackRef.current = onStrokeCancel
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
        allowOutOfImage: allowOutOfImageHoverRef.current,
      })
    },
    [],
  )

  // 笔划（画笔落笔）采样永远限制在图像内部，不受 allowOutOfImageHover 影响。
  const mapPointerToStrokeSample = useCallback(
    (clientX: number, clientY: number): CanvasPreviewHoverSample | null => {
      const sample = mapPointerToHoverSample(clientX, clientY)
      if (sample?.isOutOfImage) {
        return null
      }
      return sample
    },
    [mapPointerToHoverSample],
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
    activeStrokePointerIdRef.current = null
    emitHoverSample(null)
  }, [emitHoverSample, finishActiveDrag, src])

  useEffect(() => {
    if (!interactionsDisabled) {
      return
    }

    lastPointerClientRef.current = null
    dragMovedRef.current = false
    finishActiveDrag(undefined, true)
    activeStrokePointerIdRef.current = null
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
      const nextNaturalSize = { width: image.naturalWidth, height: image.naturalHeight }
      naturalSizeRef.current = nextNaturalSize
      setNaturalSize(nextNaturalSize)
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
  const viewport = useMemo<CanvasPreviewSurfaceViewport | null>(() => {
    if (!imageRect) {
      return null
    }

    return {
      containerSize,
      naturalSize,
      imageRect,
      imageScreenRect: {
        x: translate.x + imageRect.x * scale,
        y: translate.y + imageRect.y * scale,
        width: imageRect.width * scale,
        height: imageRect.height * scale,
      },
      scale,
      translate,
    }
  }, [containerSize, imageRect, naturalSize, scale, translate])
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
        clickCandidateRef.current = null
        emitHoverSample(null)
        return
      }

      const isSpaceLeftDrag = spacePanEnabled
        && isSpacePanActiveRef.current
        && event.button === 0
      const isMiddleButtonDrag = middleButtonPanEnabled && event.button === 1

      // Space+left is an explicit pan intent and must win over brush strokes:
      // otherwise the brush tool (which registers onStrokeStart) would silently
      // swallow space-pan inside the image.
      // 空格+左键是明确的平移意图，优先级高于画笔笔划；否则画笔工具
      // （注册了 onStrokeStart）会在图像内把空格平移静默吞掉。
      if (!isSpaceLeftDrag && onStrokeStart && event.button === 0) {
        const sample = mapPointerToStrokeSample(event.clientX, event.clientY)
        if (sample) {
          event.preventDefault()
          activeStrokePointerIdRef.current = event.pointerId
          clickCandidateRef.current = null
          event.currentTarget.setPointerCapture?.(event.pointerId)
          strokeStartCallbackRef.current?.(sample, event)
          return
        }
      }

      const dragAllowed = isSpaceLeftDrag || isMiddleButtonDrag || (canStartDrag
        ? canStartDrag(event, { scale: scaleRef.current })
        : true)
      if (!dragAllowed) {
        clickCandidateRef.current = event.button === 0
          ? {
              pointerId: event.pointerId,
              startX: event.clientX,
              startY: event.clientY,
              moved: false,
            }
          : null
        dragMovedRef.current = false
        activePointerIdRef.current = null
        return
      }

      event.preventDefault()
      lastPointerClientRef.current = null
      clickCandidateRef.current = null
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
      mapPointerToHoverSample,
      middleButtonPanEnabled,
      onStrokeStart,
      spacePanEnabled,
      translate,
    ],
  )

  const handlePointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (interactionsDisabled) {
        lastPointerClientRef.current = null
        clickCandidateRef.current = null
        emitHoverSample(null)
        return
      }

      if (activeStrokePointerIdRef.current === event.pointerId) {
        const sample = mapPointerToStrokeSample(event.clientX, event.clientY)
        if (sample) strokeMoveCallbackRef.current?.(sample, event)
        // 笔划期间画笔指示圈需要持续跟随指针：越过图像边缘时照常更新 hover
        // 采样（消费方据此切换系统光标/隐藏指示圈；笔迹点本身仅限图像内）。
        lastPointerClientRef.current = { x: event.clientX, y: event.clientY }
        emitHoverSample(mapPointerToHoverSample(event.clientX, event.clientY))
        return
      }

      const clickCandidate = clickCandidateRef.current
      if (clickCandidate && clickCandidate.pointerId === event.pointerId) {
        const dx = event.clientX - clickCandidate.startX
        const dy = event.clientY - clickCandidate.startY
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
          clickCandidate.moved = true
        }
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

  const endPointerDrag = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (activePointerIdRef.current !== null && activePointerIdRef.current === event.pointerId) {
      event.currentTarget.releasePointerCapture?.(event.pointerId)
    }
    activePointerIdRef.current = null
    activeStrokePointerIdRef.current = null
    activeDragButtonRef.current = null
    activeDragSourceRef.current = null
  }, [])

  const handlePointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (activeStrokePointerIdRef.current === event.pointerId) {
      const sample = mapPointerToStrokeSample(event.clientX, event.clientY)
      activeStrokePointerIdRef.current = null
      event.currentTarget.releasePointerCapture?.(event.pointerId)
      strokeEndCallbackRef.current?.(sample, event)
      return
    }
    const clickCandidate = clickCandidateRef.current
    clickCandidateRef.current = null
    if (
      !interactionsDisabled &&
      event.button === 0 &&
      !dragMovedRef.current &&
      clickCandidate?.pointerId === event.pointerId &&
      !clickCandidate.moved
    ) {
      const sample = mapPointerToHoverSample(event.clientX, event.clientY)
      // 允许越界 hover 采样时，落在图像之外的"点击"不下发（那些坐标没有
      // 可操作的像素，消费方语义未定义）。
      if (sample && !sample.isOutOfImage) {
        pointerUpClickRef.current = {
          clientX: event.clientX,
          clientY: event.clientY,
          timeStamp: event.timeStamp,
        }
        clickSampleCallbackRef.current?.(sample, event)
      }
    }
    endPointerDrag(event)
  }, [endPointerDrag, interactionsDisabled, mapPointerToHoverSample, mapPointerToStrokeSample])

  const handlePointerCancel = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (activeStrokePointerIdRef.current === event.pointerId) {
      activeStrokePointerIdRef.current = null
      strokeCancelCallbackRef.current?.()
    }
    endPointerDrag(event)
    dragMovedRef.current = false
    clickCandidateRef.current = null
    lastPointerClientRef.current = null
    emitHoverSample(null)
  }, [emitHoverSample, endPointerDrag])

  const handleLostPointerCapture = useCallback(() => {
    if (activeStrokePointerIdRef.current !== null) {
      activeStrokePointerIdRef.current = null
      strokeCancelCallbackRef.current?.()
    }
    activePointerIdRef.current = null
    clickCandidateRef.current = null
    activeDragButtonRef.current = null
    activeDragSourceRef.current = null
  }, [])

  const handlePointerLeave = useCallback(() => {
    if (activePointerIdRef.current !== null) {
      return
    }
    dragMovedRef.current = false
    clickCandidateRef.current = null
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

      const pointerUpClick = pointerUpClickRef.current
      if (
        pointerUpClick &&
        Math.abs(pointerUpClick.clientX - event.clientX) <= 1 &&
        Math.abs(pointerUpClick.clientY - event.clientY) <= 1 &&
        event.timeStamp >= pointerUpClick.timeStamp &&
        event.timeStamp - pointerUpClick.timeStamp < 1000
      ) {
        pointerUpClickRef.current = null
        return
      }
      pointerUpClickRef.current = null

      if (dragMovedRef.current) {
        dragMovedRef.current = false
        return
      }

      const sample = mapPointerToHoverSample(event.clientX, event.clientY)
      if (!sample || sample.isOutOfImage) {
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
        {screenSpaceOverlay && viewport ? (
          <div className="pointer-events-none absolute inset-0">
            {typeof screenSpaceOverlay === "function"
              ? screenSpaceOverlay(viewport)
              : screenSpaceOverlay}
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
          className="action-control absolute right-2 top-2 rounded border px-2 py-1 text-xs transition-opacity"
        >
          {resetLabel}
        </button>
      ) : null}
    </div>
  )
}
