export interface HoverInspectorAnchorSample {
  containerX: number
  containerY: number
  containerWidth: number
  containerHeight: number
  containerLeft: number
  containerTop: number
}

interface HoverInspectorEqualitySample extends HoverInspectorAnchorSample {
  pixelX: number
  pixelY: number
  naturalWidth: number
  naturalHeight: number
}

export interface HoverLayerColorSample {
  displayIndex: number
  layerName: string
  colorHex: string | null
}

export interface LayerCanvasBuffer {
  layerIndex: number
  name: string
  width: number
  height: number
  context: CanvasRenderingContext2D
}

export interface PreviewCanvasBuffer {
  width: number
  height: number
  context: CanvasRenderingContext2D
}

export const HOVER_POPOVER_DELAY_MS = 180
export const HOVER_RESOURCE_RELEASE_DELAY_MS = 1500
export const MAGNIFIER_SIZE_PX = 152
export const MAGNIFIER_ZOOM = 3

const MAGNIFIER_OFFSET_PX = 18
const INSPECTOR_WIDTH_PX = 248
const INSPECTOR_EDGE_MARGIN_PX = 8
const INSPECTOR_MIN_HEIGHT_PX = 310
const INSPECTOR_PADDING_PX = 16
const INSPECTOR_MAGNIFIER_HEIGHT_PX = 152
const INSPECTOR_MAGNIFIER_SECTION_GAP_PX = 8
const INSPECTOR_META_SECTION_HEIGHT_PX = 34
const INSPECTOR_LAYER_TITLE_HEIGHT_PX = 18
const INSPECTOR_LAYER_ROW_HEIGHT_PX = 18
const INSPECTOR_LAYER_ROW_GAP_PX = 4
const INSPECTOR_COMPACT_GRID_THRESHOLD = 6
const INSPECTOR_COMPACT_GRID_COLUMNS = 2

export interface HoverInspectorLayout {
  columns: number
  isCompactGrid: boolean
  estimatedHeightPx: number
}

export interface HoverInspectorPlacementOptions {
  layerCount?: number
  showMagnifier?: boolean
  showLayerDetails?: boolean
}

function estimateHoverInspectorContentHeight(
  layerCount: number,
  showMagnifier: boolean,
  showLayerDetails: boolean,
): HoverInspectorLayout {
  const isCompactGrid = showLayerDetails && layerCount > INSPECTOR_COMPACT_GRID_THRESHOLD
  const columns = isCompactGrid ? INSPECTOR_COMPACT_GRID_COLUMNS : 1
  const rows = showLayerDetails && layerCount > 0
    ? Math.ceil(layerCount / columns)
    : 0

  const layerSectionHeightPx = showLayerDetails
    ? INSPECTOR_LAYER_TITLE_HEIGHT_PX
      + rows * INSPECTOR_LAYER_ROW_HEIGHT_PX
      + Math.max(0, rows - 1) * INSPECTOR_LAYER_ROW_GAP_PX
    : 0

  const estimatedHeightPx = Math.max(
    showLayerDetails ? INSPECTOR_MIN_HEIGHT_PX : 0,
    INSPECTOR_PADDING_PX
      + (showMagnifier ? INSPECTOR_MAGNIFIER_HEIGHT_PX + INSPECTOR_MAGNIFIER_SECTION_GAP_PX : 0)
      + INSPECTOR_META_SECTION_HEIGHT_PX
      + layerSectionHeightPx,
  )

  return {
    columns,
    isCompactGrid,
    estimatedHeightPx,
  }
}

export function getHoverInspectorLayout(
  layerCount: number,
  showLayerDetails = true,
): HoverInspectorLayout {
  return estimateHoverInspectorContentHeight(layerCount, true, showLayerDetails)
}

export function buildPreviewCanvasBuffer(image: HTMLImageElement): PreviewCanvasBuffer | null {
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

export function clampNumber(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

export function mapPixelToBufferCoordinate(pixel: number, sourceSize: number, bufferSize: number): number {
  return clampNumber(
    Math.round((pixel / Math.max(sourceSize - 1, 1)) * (bufferSize - 1)),
    0,
    Math.max(bufferSize - 1, 0),
  )
}

export function computeHoverInspectorStyle(
  sample: HoverInspectorAnchorSample,
  options: HoverInspectorPlacementOptions = {},
): { left: string; top: string } | null {
  if (typeof window === "undefined") {
    return null
  }

  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  if (viewportWidth <= 0 || viewportHeight <= 0) {
    return null
  }

  const containerLeft = sample.containerLeft
  const containerTop = sample.containerTop
  const containerRight = containerLeft + sample.containerWidth
  const containerBottom = containerTop + sample.containerHeight
  const pointerX = containerLeft + sample.containerX
  const pointerY = containerTop + sample.containerY
  const layout = estimateHoverInspectorContentHeight(
    options.layerCount ?? 0,
    options.showMagnifier ?? true,
    options.showLayerDetails ?? true,
  )

  const requiredHorizontal = INSPECTOR_WIDTH_PX + MAGNIFIER_OFFSET_PX
  const requiredVertical = layout.estimatedHeightPx + MAGNIFIER_OFFSET_PX

  const spaceRight = viewportWidth - containerRight - INSPECTOR_EDGE_MARGIN_PX
  const spaceLeft = containerLeft - INSPECTOR_EDGE_MARGIN_PX
  const spaceBelow = viewportHeight - containerBottom - INSPECTOR_EDGE_MARGIN_PX
  const spaceAbove = containerTop - INSPECTOR_EDGE_MARGIN_PX

  const canPlaceRight = spaceRight >= requiredHorizontal
  const canPlaceLeft = spaceLeft >= requiredHorizontal
  const canPlaceBelow = spaceBelow >= requiredVertical
  const canPlaceAbove = spaceAbove >= requiredVertical

  let left = pointerX - INSPECTOR_WIDTH_PX / 2
  let top = pointerY - layout.estimatedHeightPx / 2

  if (canPlaceRight || canPlaceLeft) {
    left = canPlaceRight && (!canPlaceLeft || spaceRight >= spaceLeft)
      ? containerRight + MAGNIFIER_OFFSET_PX
      : containerLeft - INSPECTOR_WIDTH_PX - MAGNIFIER_OFFSET_PX
  } else if (canPlaceBelow || canPlaceAbove) {
    top = canPlaceBelow && (!canPlaceAbove || spaceBelow >= spaceAbove)
      ? containerBottom + MAGNIFIER_OFFSET_PX
      : containerTop - layout.estimatedHeightPx - MAGNIFIER_OFFSET_PX
  } else {
    const horizontalShortfall = Math.max(0, requiredHorizontal - Math.max(spaceRight, spaceLeft))
    const verticalShortfall = Math.max(0, requiredVertical - Math.max(spaceBelow, spaceAbove))
    if (horizontalShortfall <= verticalShortfall) {
      left = spaceRight >= spaceLeft
        ? containerRight + MAGNIFIER_OFFSET_PX
        : containerLeft - INSPECTOR_WIDTH_PX - MAGNIFIER_OFFSET_PX
    } else {
      top = spaceBelow >= spaceAbove
        ? containerBottom + MAGNIFIER_OFFSET_PX
        : containerTop - layout.estimatedHeightPx - MAGNIFIER_OFFSET_PX
    }
  }

  const maxLeft = Math.max(INSPECTOR_EDGE_MARGIN_PX, viewportWidth - INSPECTOR_WIDTH_PX - INSPECTOR_EDGE_MARGIN_PX)
  const maxTop = Math.max(INSPECTOR_EDGE_MARGIN_PX, viewportHeight - layout.estimatedHeightPx - INSPECTOR_EDGE_MARGIN_PX)

  return {
    left: `${clampNumber(left, INSPECTOR_EDGE_MARGIN_PX, maxLeft)}px`,
    top: `${clampNumber(top, INSPECTOR_EDGE_MARGIN_PX, maxTop)}px`,
  }
}

export function rgbToHex(r: number, g: number, b: number): string {
  const toHex = (component: number) => component.toString(16).padStart(2, "0").toUpperCase()
  return `${toHex(r)}${toHex(g)}${toHex(b)}`
}

export function areLayerSamplesEqual(left: HoverLayerColorSample[], right: HoverLayerColorSample[]): boolean {
  if (left === right) return true
  if (left.length !== right.length) return false
  for (let i = 0; i < left.length; i += 1) {
    const a = left[i]
    const b = right[i]
    if (a.displayIndex !== b.displayIndex || a.layerName !== b.layerName || a.colorHex !== b.colorHex) {
      return false
    }
  }
  return true
}

export function areHoverSamplesEqual(
  left: HoverInspectorEqualitySample | null,
  right: HoverInspectorEqualitySample | null,
): boolean {
  if (left === right) return true
  if (!left || !right) return false
  return (
    left.containerX === right.containerX
    && left.containerY === right.containerY
    && left.containerWidth === right.containerWidth
    && left.containerHeight === right.containerHeight
    && left.containerLeft === right.containerLeft
    && left.containerTop === right.containerTop
    && left.pixelX === right.pixelX
    && left.pixelY === right.pixelY
    && left.naturalWidth === right.naturalWidth
    && left.naturalHeight === right.naturalHeight
  )
}

export function setBoundedCacheValue<T>(cache: Map<string, T>, key: string, value: T, limit: number): void {
  if (cache.has(key)) {
    cache.delete(key)
  }
  cache.set(key, value)

  while (cache.size > limit) {
    const oldestKey = cache.keys().next().value
    if (typeof oldestKey !== "string") {
      break
    }
    cache.delete(oldestKey)
  }
}
