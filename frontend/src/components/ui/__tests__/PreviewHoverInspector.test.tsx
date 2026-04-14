import { createRef } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import PreviewHoverInspector from "../PreviewHoverInspector"
import { computeHoverInspectorStyle } from "../previewHoverInspectorUtils"

vi.mock("../../../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}))

describe("PreviewHoverInspector", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 300 })
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 650 })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("switches the layer list to a compact grid when more than six layers are visible", () => {
    render(
      <PreviewHoverInspector
        dataTestId="hover-inspector"
        style={{ left: "0px", top: "0px" }}
        magnifierCanvasRef={createRef<HTMLCanvasElement>()}
        pixelX={12}
        pixelY={34}
        surfaceHex="ABCDEF"
        hoverLayerColors={Array.from({ length: 10 }, (_, index) => ({
          displayIndex: index + 1,
          layerName: `Layer ${index + 1}`,
          colorHex: index % 2 === 0 ? "112233" : null,
        }))}
        layerImagesLoading={false}
      />,
    )

    const list = screen.getByRole("list")
    expect(list.className).toContain("grid")
    expect(list.className).toContain("grid-cols-2")
    expect(list.className).not.toContain("overflow-y-auto")
    expect(screen.getAllByRole("listitem")).toHaveLength(10)
  })

  it("uses the larger layer count when estimating hover inspector placement", () => {
    const sample = {
      containerX: 120,
      containerY: 420,
      containerWidth: 100,
      containerHeight: 100,
      containerLeft: 100,
      containerTop: 400,
      pixelX: 40,
      pixelY: 50,
      naturalWidth: 200,
      naturalHeight: 200,
    }

    const compactStyle = computeHoverInspectorStyle(sample, {
      layerCount: 1,
      showMagnifier: true,
      showLayerDetails: true,
    })
    const expandedStyle = computeHoverInspectorStyle(sample, {
      layerCount: 10,
      showMagnifier: true,
      showLayerDetails: true,
    })

    expect(compactStyle).toEqual({ left: "44px", top: "72px" })
    expect(expandedStyle).toEqual({ left: "44px", top: "48px" })
  })
})
