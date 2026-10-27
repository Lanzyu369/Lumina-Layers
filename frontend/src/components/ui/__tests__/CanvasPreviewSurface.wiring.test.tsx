import { render } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

describe("CanvasPreviewSurface shared hover emitter wiring", () => {
  afterEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    vi.doUnmock("../canvasPreviewUtils")
  })

  it("constructs its hover emitter through createHoverSampleEmitter", async () => {
    const emitterSpy = vi.fn()

    vi.doMock("../canvasPreviewUtils", async () => {
      const actual = await vi.importActual<typeof import("../canvasPreviewUtils")>("../canvasPreviewUtils")
      emitterSpy.mockImplementation(actual.createHoverSampleEmitter)
      return {
        ...actual,
        createHoverSampleEmitter: emitterSpy,
      }
    })

    const { default: CanvasPreviewSurface } = await import("../CanvasPreviewSurface")

    render(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
        onHoverSample={() => {}}
      />,
    )

    expect(emitterSpy).toHaveBeenCalledTimes(1)
  })
})
