export interface CanvasPreviewHoverSample {
  containerX: number
  containerY: number
  containerWidth: number
  containerHeight: number
  containerLeft: number
  containerTop: number
  pixelX: number
  pixelY: number
  naturalWidth: number
  naturalHeight: number
}

export interface CanvasPreviewBuffer {
  width: number
  height: number
  context: CanvasRenderingContext2D
}

export type CanvasPreviewRenderingQuality = "default" | "crisp"

export interface CanvasPreviewPoint {
  x: number
  y: number
}

export interface CanvasPreviewRect {
  x: number
  y: number
  width: number
  height: number
}

export interface CanvasPreviewContainerRect {
  left: number
  top: number
  width: number
  height: number
}

interface DrawCanvasPreviewFrameOptions {
  canvas: HTMLCanvasElement
  context: CanvasRenderingContext2D
  image: CanvasImageSource
  containerSize: { width: number; height: number }
  imageRect: CanvasPreviewRect
  scale: number
  translate: CanvasPreviewPoint
  devicePixelRatio?: number
  renderingQuality?: CanvasPreviewRenderingQuality
}

interface MapPointerToCanvasPreviewHoverSampleOptions {
  clientX: number
  clientY: number
  containerRect: CanvasPreviewContainerRect
  imageRect: CanvasPreviewRect
  naturalWidth: number
  naturalHeight: number
  scale: number
  translate: CanvasPreviewPoint
}

/** Clamp preview scale to the allowed zoom range. */
export function clampCanvasPreviewScale(
  value: number,
  minScale = 0.5,
  maxScale = 5,
): number {
  return Math.min(maxScale, Math.max(minScale, value))
}

/**
 * Keep the pointer-anchored image point fixed while zooming.
 *
 * Formula: newTranslate = pointer - (pointer - oldTranslate) * (newScale / oldScale)
 */
export function computeCanvasPreviewZoomTranslate(
  mousePos: CanvasPreviewPoint,
  oldTranslate: CanvasPreviewPoint,
  oldScale: number,
  newScale: number,
): CanvasPreviewPoint {
  const ratio = newScale / oldScale
  return {
    x: mousePos.x - (mousePos.x - oldTranslate.x) * ratio,
    y: mousePos.y - (mousePos.y - oldTranslate.y) * ratio,
  }
}

export function resolveCanvasPreviewImageRect(
  container: { width: number; height: number },
  image: { width: number; height: number },
): CanvasPreviewRect | null {
  if (container.width <= 0 || container.height <= 0 || image.width <= 0 || image.height <= 0) {
    return null
  }

  const fitScale = Math.min(container.width / image.width, container.height / image.height)
  const width = image.width * fitScale
  const height = image.height * fitScale

  return {
    x: (container.width - width) / 2,
    y: (container.height - height) / 2,
    width,
    height,
  }
}

export function mapPointerToCanvasPreviewHoverSample(
  options: MapPointerToCanvasPreviewHoverSampleOptions,
): CanvasPreviewHoverSample | null {
  const {
    clientX,
    clientY,
    containerRect,
    imageRect,
    naturalWidth,
    naturalHeight,
    scale,
    translate,
  } = options

  if (
    containerRect.width <= 0
    || containerRect.height <= 0
    || imageRect.width <= 0
    || imageRect.height <= 0
    || naturalWidth <= 0
    || naturalHeight <= 0
    || scale <= 0
  ) {
    return null
  }

  const relX = clientX - containerRect.left
  const relY = clientY - containerRect.top
  const imageX = (relX - translate.x) / scale - imageRect.x
  const imageY = (relY - translate.y) / scale - imageRect.y

  if (imageX < 0 || imageX >= imageRect.width || imageY < 0 || imageY >= imageRect.height) {
    return null
  }

  const pixelX = Math.floor((imageX / imageRect.width) * naturalWidth)
  const pixelY = Math.floor((imageY / imageRect.height) * naturalHeight)

  return {
    containerX: Math.round(relX),
    containerY: Math.round(relY),
    containerWidth: Math.round(containerRect.width),
    containerHeight: Math.round(containerRect.height),
    containerLeft: Math.round(containerRect.left),
    containerTop: Math.round(containerRect.top),
    pixelX: Math.max(0, Math.min(naturalWidth - 1, pixelX)),
    pixelY: Math.max(0, Math.min(naturalHeight - 1, pixelY)),
    naturalWidth,
    naturalHeight,
  }
}

export function createCanvasPreviewBuffer(image: HTMLImageElement): CanvasPreviewBuffer | null {
  const width = image.naturalWidth || image.width
  const height = image.naturalHeight || image.height
  if (width <= 0 || height <= 0) {
    return null
  }

  const canvas = document.createElement("canvas")
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext("2d", { willReadFrequently: true })
  if (!context) {
    return null
  }

  context.drawImage(image, 0, 0)
  return { width, height, context }
}

export function drawCanvasPreviewFrame(options: DrawCanvasPreviewFrameOptions): boolean {
  const {
    canvas,
    context,
    image,
    containerSize,
    imageRect,
    scale,
    translate,
    devicePixelRatio = 1,
    renderingQuality = "default",
  } = options

  if (
    containerSize.width <= 0
    || containerSize.height <= 0
    || imageRect.width <= 0
    || imageRect.height <= 0
    || scale <= 0
  ) {
    canvas.width = 0
    canvas.height = 0
    return false
  }

  const cssWidth = Math.round(containerSize.width)
  const cssHeight = Math.round(containerSize.height)
  const dpr = Math.max(devicePixelRatio, 1)

  canvas.width = Math.round(cssWidth * dpr)
  canvas.height = Math.round(cssHeight * dpr)
  canvas.style.width = `${cssWidth}px`
  canvas.style.height = `${cssHeight}px`

  context.imageSmoothingEnabled = renderingQuality !== "crisp"
  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  context.clearRect(0, 0, cssWidth, cssHeight)
  context.save()
  context.translate(translate.x, translate.y)
  context.scale(scale, scale)
  context.drawImage(image, imageRect.x, imageRect.y, imageRect.width, imageRect.height)
  context.restore()

  return true
}

function buildHoverSampleSignature(sample: CanvasPreviewHoverSample | null): string {
  if (!sample) {
    return "__null__"
  }

  return [
    sample.containerX,
    sample.containerY,
    sample.containerWidth,
    sample.containerHeight,
    sample.containerLeft,
    sample.containerTop,
    sample.pixelX,
    sample.pixelY,
    sample.naturalWidth,
    sample.naturalHeight,
  ].join(",")
}

export function createHoverSampleEmitter(
  onHoverSample?: (sample: CanvasPreviewHoverSample | null) => void,
): (sample: CanvasPreviewHoverSample | null) => void {
  let lastSignature = ""

  return (sample) => {
    if (!onHoverSample) {
      return
    }

    const signature = buildHoverSampleSignature(sample)
    if (signature === lastSignature) {
      return
    }

    lastSignature = signature
    onHoverSample(sample)
  }
}
