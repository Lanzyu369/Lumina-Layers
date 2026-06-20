import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { translations } from "../../../i18n/translations"
import CanvasPreviewSurface, { type CanvasPreviewSurfaceReadyPayload } from "../CanvasPreviewSurface"

const OriginalImage = globalThis.Image
const OriginalResizeObserver = globalThis.ResizeObserver

type ResizeObserverCallbackType = ConstructorParameters<typeof ResizeObserver>[0]

let latestImage: TestImage | null = null
let createdImages: TestImage[] = []
let imageConstructCount = 0
let resizeObserverCallback: ResizeObserverCallbackType | null = null

class TestImage {
  onload: ((ev: Event) => unknown) | null = null
  onerror: ((ev: Event | string) => unknown) | null = null
  crossOrigin = ""
  naturalWidth = 100
  naturalHeight = 50
  complete = false
  private currentSrc = ""

  set src(value: string) {
    this.currentSrc = value
  }

  get src(): string {
    return this.currentSrc
  }

  dispatchLoad(): void {
    this.complete = true
    this.onload?.(new Event("load"))
  }

  dispatchError(): void {
    this.complete = false
    this.onerror?.(new Event("error"))
  }
}

function installCanvasContextMock(
  factory: () => CanvasRenderingContext2D,
): void {
  const getContextMock = function getContext(
    this: HTMLCanvasElement,
    contextId: string,
  ): CanvasRenderingContext2D | null {
    if (contextId === "2d") {
      return factory()
    }
    return null
  }

  vi
    .spyOn(HTMLCanvasElement.prototype, "getContext")
    .mockImplementation(getContextMock as unknown as typeof HTMLCanvasElement.prototype.getContext)
}

describe("CanvasPreviewSurface", () => {
  beforeEach(() => {
    latestImage = null
    createdImages = []
    imageConstructCount = 0
    resizeObserverCallback = null
    globalThis.Image = class MockImage extends OriginalImage {
      constructor(...args: ConstructorParameters<typeof Image>) {
        super(...args)
        imageConstructCount += 1
        latestImage = new TestImage()
        createdImages.push(latestImage)
        return latestImage as unknown as HTMLImageElement
      }
    } as typeof Image

    globalThis.ResizeObserver = class MockResizeObserver {
      constructor(callback: ResizeObserverCallbackType) {
        resizeObserverCallback = callback
      }

      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    } as unknown as typeof ResizeObserver
  })

  afterEach(() => {
    vi.restoreAllMocks()
    globalThis.Image = OriginalImage
    globalThis.ResizeObserver = OriginalResizeObserver
  })

  it("renders a real canvas preview surface and paints the loaded image onto it", () => {
    const readyPayloads: Array<CanvasPreviewSurfaceReadyPayload | null> = []
    const hoverSamples: Array<unknown> = []
    const drawImage = vi.fn()
    const clearRect = vi.fn()
    const save = vi.fn()
    const restore = vi.fn()
    const setTransform = vi.fn()
    const translate = vi.fn()
    const scale = vi.fn()
    installCanvasContextMock(() => ({
      clearRect,
      save,
      restore,
      setTransform,
      translate,
      scale,
      drawImage,
    } as unknown as CanvasRenderingContext2D))

    render(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
        resetLabel="Reset"
        overlay={<div data-testid="overlay">overlay</div>}
        floatingOverlay={<div data-testid="floating-overlay">floating</div>}
        onSurfaceReady={(payload) => readyPayloads.push(payload)}
        onHoverSample={(sample) => hoverSamples.push(sample)}
      />,
    )

    const surface = screen.getByTestId("canvas-preview-surface")
    const canvas = screen.getByRole("img", { name: "Preview" })

    Object.defineProperty(surface, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 10,
        top: 20,
        width: 200,
        height: 100,
        right: 210,
        bottom: 120,
        x: 10,
        y: 20,
        toJSON: () => ({}),
      }),
    })

    expect(canvas.tagName).toBe("CANVAS")
    expect(surface.querySelector("img")).toBeNull()

    act(() => {
      latestImage?.dispatchLoad()
    })

    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 110, clientY: 70 })
    fireEvent.pointerLeave(surface, { pointerId: 1 })

    expect(screen.getByTestId("overlay")).toBeInTheDocument()
    expect(screen.getByTestId("floating-overlay")).toBeInTheDocument()
    expect(readyPayloads[0]).toBeNull()
    expect(readyPayloads[1]).toMatchObject({
      image: latestImage,
      previewBuffer: { width: 100, height: 50 },
    })
    expect(drawImage.mock.calls.some((call) => (
      call[0] === latestImage && call.length === 5
    ))).toBe(true)
    expect(hoverSamples[0]).toBeNull()
    expect(hoverSamples[1]).toEqual({
      containerX: 100,
      containerY: 50,
      containerWidth: 200,
      containerHeight: 100,
      containerLeft: 10,
      containerTop: 20,
      pixelX: 50,
      pixelY: 25,
      naturalWidth: 100,
      naturalHeight: 50,
    })
    expect(hoverSamples[2]).toBeNull()
  })

  it("styles the shared reset button with theme-safe tokens instead of raw black and white classes", () => {
    installCanvasContextMock(() => ({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D))

    render(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
        resetLabel="Reset"
      />,
    )

    const resetButton = screen.getByRole("button", { name: "Reset" })
    const inlineStyle = resetButton.getAttribute("style") ?? ""

    expect(resetButton.className).not.toContain("bg-black")
    expect(resetButton.className).not.toContain("text-white")
    expect(inlineStyle).toContain("border-color: var(--surface-outline)")
    expect(inlineStyle).toContain(
      "background: color-mix(in srgb, var(--surface-panel-strong) 88%, transparent)",
    )
    expect(inlineStyle).toContain("color: var(--surface-text-muted)")
  })

  it("keeps default rendering quality for shared consumers unless crisp is requested", () => {
    const contexts: Array<{ imageSmoothingEnabled: boolean }> = []
    installCanvasContextMock(() => {
      const context = {
        clearRect: vi.fn(),
        save: vi.fn(),
        restore: vi.fn(),
        setTransform: vi.fn(),
        translate: vi.fn(),
        scale: vi.fn(),
        drawImage: vi.fn(),
        imageSmoothingEnabled: true,
      } as unknown as CanvasRenderingContext2D & { imageSmoothingEnabled: boolean }
      contexts.push(context)
      return context
    })

    const { rerender } = render(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
      />,
    )

    const surface = screen.getByTestId("canvas-preview-surface")
    Object.defineProperty(surface, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 10,
        top: 20,
        width: 200,
        height: 100,
        right: 210,
        bottom: 120,
        x: 10,
        y: 20,
        toJSON: () => ({}),
      }),
    })

    act(() => {
      latestImage?.dispatchLoad()
    })

    expect(contexts[0]?.imageSmoothingEnabled).toBe(true)

    rerender(
      <CanvasPreviewSurface
        src="/preview-crisp.png"
        alt="Preview"
        renderingQuality="crisp"
      />,
    )

    act(() => {
      latestImage?.dispatchLoad()
    })

    expect(contexts.at(-1)?.imageSmoothingEnabled).toBe(false)
  })

  it("does not change scale when wheel zoom is disabled", () => {
    const scaleChanges: number[] = []
    installCanvasContextMock(() => ({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D))

    render(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
        wheelZoomEnabled={false}
        onScaleChange={(scale) => scaleChanges.push(scale)}
      />,
    )

    const surface = screen.getByTestId("canvas-preview-surface")

    act(() => {
      latestImage?.dispatchLoad()
    })

    fireEvent.wheel(surface, { deltaY: -120, clientX: 60, clientY: 40 })

    expect(scaleChanges).toEqual([1])
  })

  it("calls preventDefault on wheel so the page does not scroll while zooming", () => {
    // Regression: React's synthetic `onWheel` is passive, so
    // `event.preventDefault()` inside a React handler is a no-op and the
    // page scrolls while the user zooms the preview. The component must
    // attach a native non-passive `wheel` listener.
    // 回归测试：React 合成 `onWheel` 是 passive 注册，React 回调里 `preventDefault`
    // 无效，用户缩放时页面会一起滚动。组件必须注册原生非 passive 的 `wheel` 监听器。
    installCanvasContextMock(() => ({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D))

    render(<CanvasPreviewSurface src="/preview.png" alt="Preview" />)

    const surface = screen.getByTestId("canvas-preview-surface")

    act(() => {
      latestImage?.dispatchLoad()
    })

    const wheelEvent = new WheelEvent("wheel", {
      deltaY: -120,
      clientX: 60,
      clientY: 40,
      bubbles: true,
      cancelable: true,
    })
    const dispatched = surface.dispatchEvent(wheelEvent)

    // `dispatchEvent` returns false when any listener called preventDefault
    // on a cancelable event.
    expect(dispatched).toBe(false)
    expect(wheelEvent.defaultPrevented).toBe(true)
  })

  it("does not prevent default when wheel zoom is disabled", () => {
    // Guard: if the consumer opts out of wheel zoom, the component must
    // leave the native wheel event alone so the page can scroll normally.
    // 守护：消费方关闭滚轮缩放时，组件必须放行原生 wheel 事件，页面正常滚动。
    installCanvasContextMock(() => ({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D))

    render(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
        wheelZoomEnabled={false}
      />,
    )

    const surface = screen.getByTestId("canvas-preview-surface")

    act(() => {
      latestImage?.dispatchLoad()
    })

    const wheelEvent = new WheelEvent("wheel", {
      deltaY: -120,
      clientX: 60,
      clientY: 40,
      bubbles: true,
      cancelable: true,
    })
    surface.dispatchEvent(wheelEvent)

    expect(wheelEvent.defaultPrevented).toBe(false)
  })

  it("does not reload or reset lifecycle state when callback identities change but src is stable", () => {
    const readyPayloads: Array<CanvasPreviewSurfaceReadyPayload | null> = []
    const hoverSamples: Array<unknown> = []

    installCanvasContextMock(() => ({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D))

    const { rerender } = render(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
        onSurfaceReady={(payload) => readyPayloads.push(payload)}
        onHoverSample={(sample) => hoverSamples.push(sample)}
      />,
    )

    act(() => {
      latestImage?.dispatchLoad()
    })

    rerender(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
        onSurfaceReady={(payload) => readyPayloads.push(payload)}
        onHoverSample={(sample) => hoverSamples.push(sample)}
      />,
    )

    expect(imageConstructCount).toBe(1)
    expect(readyPayloads).toHaveLength(2)
    expect(readyPayloads[0]).toBeNull()
    expect(readyPayloads[1]).toMatchObject({
      image: latestImage,
      previewBuffer: { width: 100, height: 50 },
    })
    expect(hoverSamples).toEqual([null])
  })

  it("recomputes hover anchor geometry after a resize observer update", () => {
    const hoverSamples: Array<unknown> = []
    installCanvasContextMock(() => ({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D))

    render(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
        onHoverSample={(sample) => hoverSamples.push(sample)}
      />,
    )

    const surface = screen.getByTestId("canvas-preview-surface")
    let rect = {
      left: 10,
      top: 20,
      width: 200,
      height: 100,
      right: 210,
      bottom: 120,
      x: 10,
      y: 20,
      toJSON: () => ({}),
    }

    Object.defineProperty(surface, "getBoundingClientRect", {
      configurable: true,
      value: () => rect,
    })

    act(() => {
      latestImage?.dispatchLoad()
    })

    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 110, clientY: 70 })

    rect = {
      left: 30,
      top: 50,
      width: 240,
      height: 120,
      right: 270,
      bottom: 170,
      x: 30,
      y: 50,
      toJSON: () => ({}),
    }

    act(() => {
      resizeObserverCallback?.([], {} as ResizeObserver)
    })

    expect(hoverSamples[0]).toBeNull()
    expect(hoverSamples[1]).toEqual({
      containerX: 100,
      containerY: 50,
      containerWidth: 200,
      containerHeight: 100,
      containerLeft: 10,
      containerTop: 20,
      pixelX: 50,
      pixelY: 25,
      naturalWidth: 100,
      naturalHeight: 50,
    })
    expect(hoverSamples[2]).toEqual({
      containerX: 80,
      containerY: 20,
      containerWidth: 240,
      containerHeight: 120,
      containerLeft: 30,
      containerTop: 50,
      pixelX: 33,
      pixelY: 8,
      naturalWidth: 100,
      naturalHeight: 50,
    })
  })

  it("emits a refreshed hover sample when resize changes only the container bounds", () => {
    const hoverSamples: Array<unknown> = []
    installCanvasContextMock(() => ({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D))

    render(
      <CanvasPreviewSurface
        src="/preview.png"
        alt="Preview"
        onHoverSample={(sample) => hoverSamples.push(sample)}
      />,
    )

    const surface = screen.getByTestId("canvas-preview-surface")
    let rect = {
      left: 10,
      top: 20,
      width: 220,
      height: 100,
      right: 230,
      bottom: 120,
      x: 10,
      y: 20,
      toJSON: () => ({}),
    }

    Object.defineProperty(surface, "getBoundingClientRect", {
      configurable: true,
      value: () => rect,
    })

    act(() => {
      latestImage?.dispatchLoad()
    })

    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 21, clientY: 21 })

    rect = {
      left: 10,
      top: 20,
      width: 260,
      height: 120,
      right: 270,
      bottom: 140,
      x: 10,
      y: 20,
      toJSON: () => ({}),
    }

    act(() => {
      resizeObserverCallback?.([], {} as ResizeObserver)
    })

    expect(hoverSamples).toEqual([
      null,
      {
        containerX: 11,
        containerY: 1,
        containerWidth: 220,
        containerHeight: 100,
        containerLeft: 10,
        containerTop: 20,
        pixelX: 0,
        pixelY: 0,
        naturalWidth: 100,
        naturalHeight: 50,
      },
      {
        containerX: 11,
        containerY: 1,
        containerWidth: 260,
        containerHeight: 120,
        containerLeft: 10,
        containerTop: 20,
        pixelX: 0,
        pixelY: 0,
        naturalWidth: 100,
        naturalHeight: 50,
      },
    ])
  })

  it("keeps the interactive measured surface sized to the full available area", () => {
    installCanvasContextMock(() => ({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D))

    render(
      <div className="h-80 w-96">
        <CanvasPreviewSurface
          src="/preview.png"
          alt="Preview"
          className="h-full w-full min-h-64 rounded-xl"
        />
      </div>,
    )

    const surface = screen.getByTestId("canvas-preview-surface")

    expect(surface).toHaveClass("h-full")
    expect(surface).toHaveClass("w-full")
    expect(surface).toHaveClass("min-h-64")
    expect(surface).toHaveClass("rounded-xl")
  })

  it("keeps the current preview painted until the replacement image finishes loading", () => {
    const readyPayloads: Array<CanvasPreviewSurfaceReadyPayload | null> = []
    const drawImage = vi.fn()
    const clearRect = vi.fn()
    const save = vi.fn()
    const restore = vi.fn()
    const setTransform = vi.fn()
    const translate = vi.fn()
    const scale = vi.fn()
    installCanvasContextMock(() => ({
      clearRect,
      save,
      restore,
      setTransform,
      translate,
      scale,
      drawImage,
    } as unknown as CanvasRenderingContext2D))

    const { rerender } = render(
      <CanvasPreviewSurface
        src="/preview-a.png"
        alt="Preview"
        onSurfaceReady={(payload) => readyPayloads.push(payload)}
      />,
    )

    const surface = screen.getByTestId("canvas-preview-surface")
    const canvas = screen.getByRole("img", { name: "Preview" }) as HTMLCanvasElement

    Object.defineProperty(surface, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 10,
        top: 20,
        width: 200,
        height: 100,
        right: 210,
        bottom: 120,
        x: 10,
        y: 20,
        toJSON: () => ({}),
      }),
    })

    act(() => {
      latestImage?.dispatchLoad()
    })

    const firstImage = createdImages[0]
    expect(canvas.width).toBe(200)
    expect(readyPayloads).toHaveLength(2)
    expect(readyPayloads[0]).toBeNull()
    expect(readyPayloads[1]).toMatchObject({
      image: firstImage,
      previewBuffer: { width: 100, height: 50 },
    })

    rerender(
      <CanvasPreviewSurface
        src="/preview-b.png"
        alt="Preview"
        onSurfaceReady={(payload) => readyPayloads.push(payload)}
      />,
    )

    expect(canvas.width).toBe(200)
    expect(readyPayloads).toHaveLength(2)
    expect(readyPayloads[1]).toMatchObject({
      image: firstImage,
      previewBuffer: { width: 100, height: 50 },
    })

    act(() => {
      latestImage?.dispatchLoad()
    })

    expect(readyPayloads).toHaveLength(3)
    expect(readyPayloads[2]).toMatchObject({
      image: createdImages[1],
      previewBuffer: { width: 100, height: 50 },
    })
  })

  it("clears the stale painted frame when a replacement image fails after an earlier successful load", () => {
    const readyPayloads: Array<CanvasPreviewSurfaceReadyPayload | null> = []
    installCanvasContextMock(() => ({
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      setTransform: vi.fn(),
      translate: vi.fn(),
      scale: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D))

    const { rerender } = render(
      <CanvasPreviewSurface
        src="/preview-a.png"
        alt="Preview"
        onSurfaceReady={(payload) => readyPayloads.push(payload)}
      />,
    )

    const surface = screen.getByTestId("canvas-preview-surface")
    const canvas = screen.getByRole("img", { name: "Preview" }) as HTMLCanvasElement

    Object.defineProperty(surface, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 10,
        top: 20,
        width: 200,
        height: 100,
        right: 210,
        bottom: 120,
        x: 10,
        y: 20,
        toJSON: () => ({}),
      }),
    })

    act(() => {
      latestImage?.dispatchLoad()
    })

    expect(canvas.width).toBe(200)
    expect(readyPayloads).toHaveLength(2)

    rerender(
      <CanvasPreviewSurface
        src="/preview-b.png"
        alt="Preview"
        onSurfaceReady={(payload) => readyPayloads.push(payload)}
      />,
    )

    expect(canvas.width).toBe(200)

    act(() => {
      latestImage?.dispatchError()
    })

    expect(screen.getByRole("alert")).toHaveTextContent(translations.canvas_preview_load_failed.zh)
    expect(canvas.width).toBe(0)
    expect(canvas.height).toBe(0)
    expect(readyPayloads).toHaveLength(3)
    expect(readyPayloads[2]).toBeNull()

    rerender(
      <CanvasPreviewSurface
        src="/preview-c.png"
        alt="Preview"
        onSurfaceReady={(payload) => readyPayloads.push(payload)}
      />,
    )

    expect(screen.queryByRole("alert")).toBeNull()

    act(() => {
      latestImage?.dispatchLoad()
    })

    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("uses pointer capture to preserve drag continuity", () => {
    const drawImage = vi.fn()
    const clearRect = vi.fn()
    const save = vi.fn()
    const restore = vi.fn()
    const setTransform = vi.fn()
    const translate = vi.fn()
    const scale = vi.fn()
    installCanvasContextMock(() => ({
      clearRect,
      save,
      restore,
      setTransform,
      translate,
      scale,
      drawImage,
    } as unknown as CanvasRenderingContext2D))

    render(<CanvasPreviewSurface src="/preview.png" alt="Preview" />)

    const surface = screen.getByTestId("canvas-preview-surface")
    const setPointerCapture = vi.fn()
    const releasePointerCapture = vi.fn()

    Object.defineProperty(surface, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 10,
        top: 20,
        width: 200,
        height: 100,
        right: 210,
        bottom: 120,
        x: 10,
        y: 20,
        toJSON: () => ({}),
      }),
    })
    Object.defineProperty(surface, "setPointerCapture", {
      configurable: true,
      value: setPointerCapture,
    })
    Object.defineProperty(surface, "releasePointerCapture", {
      configurable: true,
      value: releasePointerCapture,
    })

    act(() => {
      latestImage?.dispatchLoad()
    })

    fireEvent.pointerDown(surface, { pointerId: 7, clientX: 100, clientY: 60, button: 0 })
    fireEvent.pointerMove(surface, { pointerId: 7, clientX: 118, clientY: 74 })
    fireEvent.pointerUp(surface, { pointerId: 7, clientX: 118, clientY: 74 })

    expect(setPointerCapture).toHaveBeenCalledWith(7)
    expect(releasePointerCapture).toHaveBeenCalledWith(7)
    expect(translate).toHaveBeenCalledWith(18, 14)
  })
})
