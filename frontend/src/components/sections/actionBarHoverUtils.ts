import type { CanvasPreviewHoverSample } from "../ui/canvasPreviewUtils"

const BED_TARGET_CANVAS_PX = 1200
const BED_MARGIN_MM = 10
const DEFAULT_NOZZLE_WIDTH_MM = 0.42

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function getBedSizeMm(
  bedLabel: string,
  bedSizes: Array<{ label: string; width_mm: number; height_mm: number }>,
): { widthMm: number; heightMm: number } {
  const matchedBed = bedSizes.find((bed) => bed.label === bedLabel)
  if (matchedBed) {
    return { widthMm: matchedBed.width_mm, heightMm: matchedBed.height_mm }
  }

  const parsed = bedLabel.match(/(\d+)\D+(\d+)\s*mm/i)
  if (parsed) {
    return {
      widthMm: Number(parsed[1]),
      heightMm: Number(parsed[2]),
    }
  }

  return { widthMm: 256, heightMm: 256 }
}

export function resolvePreviewHoverPixel(
  sample: Pick<CanvasPreviewHoverSample, "pixelX" | "pixelY" | "naturalWidth" | "naturalHeight">,
  options: {
    rawWidth: number | null
    rawHeight: number | null
    previewWidthMm: number | null
    bedLabel: string
    bedSizes: Array<{ label: string; width_mm: number; height_mm: number }>
  },
): { pixelX: number; pixelY: number } | null {
  const rawWidth = options.rawWidth && options.rawWidth > 0 ? options.rawWidth : sample.naturalWidth
  const rawHeight = options.rawHeight && options.rawHeight > 0 ? options.rawHeight : sample.naturalHeight

  if (rawWidth <= 0 || rawHeight <= 0) {
    return null
  }

  if (sample.naturalWidth === rawWidth && sample.naturalHeight === rawHeight) {
    return {
      pixelX: clampNumber(sample.pixelX, 0, Math.max(rawWidth - 1, 0)),
      pixelY: clampNumber(sample.pixelY, 0, Math.max(rawHeight - 1, 0)),
    }
  }

  const { widthMm: bedWidthMm, heightMm: bedHeightMm } = getBedSizeMm(options.bedLabel, options.bedSizes)
  const ppm = BED_TARGET_CANVAS_PX / Math.max(bedWidthMm, bedHeightMm, 1)
  const margin = Math.floor(BED_MARGIN_MM * ppm)
  const canvasWidth = Math.floor(bedWidthMm * ppm)
  const canvasHeight = Math.floor(bedHeightMm * ppm)
  const modelWidthMm = options.previewWidthMm && options.previewWidthMm > 0
    ? options.previewWidthMm
    : rawWidth * DEFAULT_NOZZLE_WIDTH_MM
  const modelHeightMm = modelWidthMm * rawHeight / Math.max(rawWidth, 1)
  const modelWidth = Math.max(1, Math.floor(modelWidthMm * ppm))
  const modelHeight = Math.max(1, Math.floor(modelHeightMm * ppm))
  const modelX = margin + Math.floor((canvasWidth - modelWidth) / 2)
  const modelY = Math.floor((canvasHeight - modelHeight) / 2)

  if (
    sample.pixelX < modelX ||
    sample.pixelX >= modelX + modelWidth ||
    sample.pixelY < modelY ||
    sample.pixelY >= modelY + modelHeight
  ) {
    return null
  }

  return {
    pixelX: clampNumber(
      Math.round(((sample.pixelX - modelX) / Math.max(modelWidth - 1, 1)) * (rawWidth - 1)),
      0,
      Math.max(rawWidth - 1, 0),
    ),
    pixelY: clampNumber(
      Math.round(((sample.pixelY - modelY) / Math.max(modelHeight - 1, 1)) * (rawHeight - 1)),
      0,
      Math.max(rawHeight - 1, 0),
    ),
  }
}
