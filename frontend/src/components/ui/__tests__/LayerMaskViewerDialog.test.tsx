import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import LayerMaskViewerDialog from "../LayerMaskViewerDialog"

let capturedCanvasPreviewSurfaceProps: Record<string, unknown> | null = null

vi.mock("../../../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}))

vi.mock("../CanvasPreviewSurface", () => ({
  default: (props: Record<string, unknown>) => {
    capturedCanvasPreviewSurfaceProps = props
    return (
      <canvas
        data-testid="layer-mask-canvas-preview"
        role="img"
        aria-label={String(props.alt ?? "")}
        data-src={String(props.src ?? "")}
      />
    )
  },
}))

describe("LayerMaskViewerDialog", () => {
  beforeEach(() => {
    capturedCanvasPreviewSurfaceProps = null
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it("renders the active layer inside a canvas preview surface", () => {
    render(
      <LayerMaskViewerDialog
        open
        layers={[
          { layer_index: 0, name: "Layer 1", url: "/api/files/layer-1.png" },
          { layer_index: 1, name: "Layer 2", url: "/api/files/layer-2.png" },
        ]}
        activeIndex={0}
        onChangeIndex={vi.fn()}
        onClose={vi.fn()}
      />,
    )

    const previewSurface = screen.getByTestId("layer-mask-canvas-preview")
    expect(previewSurface.tagName).toBe("CANVAS")
    expect(previewSurface).toHaveAttribute("data-src", "/api/files/layer-1.png")

    const dialog = screen.getByTestId("layer-mask-viewer-dialog")
    expect(dialog.querySelector("img")).toBeNull()
  })

  it("shows the magnifier inspector after hover and redraws when the preview buffer becomes available", async () => {
    vi.useFakeTimers()

    const drawImage = vi.fn()
    const magnifierContext = {
      clearRect: vi.fn(),
      drawImage,
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      canvas: { width: 152, height: 152 },
      set imageSmoothingEnabled(_value: boolean) {},
      set strokeStyle(_value: string) {},
      set lineWidth(_value: number) {},
    } as unknown as CanvasRenderingContext2D

    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      ((contextId: string) => (contextId === "2d" ? magnifierContext : null)) as typeof HTMLCanvasElement.prototype.getContext,
    )

    render(
      <LayerMaskViewerDialog
        open
        layers={[{ layer_index: 0, name: "Layer 1", url: "/api/files/layer-1.png" }]}
        activeIndex={0}
        onChangeIndex={vi.fn()}
        onClose={vi.fn()}
      />,
    )

    const hoverHandler = capturedCanvasPreviewSurfaceProps?.onHoverSample as
      | ((sample: {
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
        } | null) => void)
      | undefined
    const surfaceReadyHandler = capturedCanvasPreviewSurfaceProps?.onSurfaceReady as
      | ((payload: {
          image: HTMLImageElement
          previewBuffer: {
            width: number
            height: number
            context: CanvasRenderingContext2D
          } | null
        } | null) => void)
      | undefined

    expect(hoverHandler).toBeTypeOf("function")
    expect(surfaceReadyHandler).toBeTypeOf("function")

    act(() => {
      hoverHandler?.({
        containerX: 96,
        containerY: 72,
        containerWidth: 320,
        containerHeight: 220,
        containerLeft: 40,
        containerTop: 60,
        pixelX: 200,
        pixelY: 120,
        naturalWidth: 600,
        naturalHeight: 400,
      })
      vi.advanceTimersByTime(180)
    })

    expect(screen.getByTestId("layer-mask-hover-inspector")).toBeInTheDocument()
    expect(drawImage).not.toHaveBeenCalled()

    const previewBufferContext = {
      getImageData: vi.fn(() => ({ data: new Uint8ClampedArray([12, 34, 56, 255]) })),
      canvas: document.createElement("canvas"),
    } as unknown as CanvasRenderingContext2D

    act(() => {
      surfaceReadyHandler?.({
        image: document.createElement("img"),
        previewBuffer: {
          width: 600,
          height: 400,
          context: previewBufferContext,
        },
      })
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(drawImage.mock.calls.some((call) => call.length >= 9)).toBe(true)
    expect(screen.getByText("#0C2238")).toBeInTheDocument()
  })

  it("closes when the overlay is clicked", () => {
    const onClose = vi.fn()

    render(
      <LayerMaskViewerDialog
        open
        layers={[{ layer_index: 0, name: "Layer 1", url: "/api/files/layer-1.png" }]}
        activeIndex={0}
        onChangeIndex={vi.fn()}
        onClose={onClose}
      />,
    )

    fireEvent.click(screen.getByTestId("layer-mask-viewer-overlay"))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("supports Esc and arrow keys for navigation", () => {
    const onClose = vi.fn()
    const onChangeIndex = vi.fn()

    render(
      <LayerMaskViewerDialog
        open
        layers={[
          { layer_index: 0, name: "Layer 1", url: "/api/files/layer-1.png" },
          { layer_index: 1, name: "Layer 2", url: "/api/files/layer-2.png" },
          { layer_index: 2, name: "Layer 3", url: "/api/files/layer-3.png" },
        ]}
        activeIndex={1}
        onChangeIndex={onChangeIndex}
        onClose={onClose}
      />,
    )

    fireEvent.keyDown(document, { key: "ArrowRight" })
    expect(onChangeIndex).toHaveBeenLastCalledWith(2)

    fireEvent.keyDown(document, { key: "ArrowLeft" })
    expect(onChangeIndex).toHaveBeenLastCalledWith(0)

    fireEvent.keyDown(document, { key: "Escape" })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
