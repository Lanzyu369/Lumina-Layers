import { describe, expect, it } from "vitest"

import { resolvePreviewHoverPixel } from "./actionBarHoverUtils"

describe("resolvePreviewHoverPixel", () => {
  it("maps bed-rendered preview pixels back to raw preview pixels", () => {
    const resolved = resolvePreviewHoverPixel(
      {
        pixelX: 645,
        pixelY: 599,
        naturalWidth: 1246,
        naturalHeight: 1246,
      },
      {
        rawWidth: 300,
        rawHeight: 200,
        previewWidthMm: 60,
        bedLabel: "256×256 mm",
        bedSizes: [{ label: "256×256 mm", width_mm: 256, height_mm: 256 }],
      },
    )

    expect(resolved).toEqual({ pixelX: 150, pixelY: 100 })
  })

  it("returns null when the hover point is outside the model area", () => {
    const resolved = resolvePreviewHoverPixel(
      {
        pixelX: 100,
        pixelY: 100,
        naturalWidth: 1246,
        naturalHeight: 1246,
      },
      {
        rawWidth: 300,
        rawHeight: 200,
        previewWidthMm: 60,
        bedLabel: "256×256 mm",
        bedSizes: [{ label: "256×256 mm", width_mm: 256, height_mm: 256 }],
      },
    )

    expect(resolved).toBeNull()
  })

  it("passes through coordinates when the preview is already raw-aligned", () => {
    const resolved = resolvePreviewHoverPixel(
      {
        pixelX: 200,
        pixelY: 120,
        naturalWidth: 600,
        naturalHeight: 400,
      },
      {
        rawWidth: 600,
        rawHeight: 400,
        previewWidthMm: 60,
        bedLabel: "256×256 mm",
        bedSizes: [{ label: "256×256 mm", width_mm: 256, height_mm: 256 }],
      },
    )

    expect(resolved).toEqual({ pixelX: 200, pixelY: 120 })
  })
})
