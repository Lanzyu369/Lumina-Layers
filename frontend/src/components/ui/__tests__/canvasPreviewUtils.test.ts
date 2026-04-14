import { afterEach, describe, expect, it, vi } from "vitest"

import {
  createCanvasPreviewBuffer,
  createHoverSampleEmitter,
  drawCanvasPreviewFrame,
  mapPointerToCanvasPreviewHoverSample,
  resolveCanvasPreviewImageRect,
  type CanvasPreviewHoverSample,
} from "../canvasPreviewUtils"

describe("canvasPreviewUtils", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("resolves a fitted image rect centered within the container", () => {
    expect(
      resolveCanvasPreviewImageRect(
        { width: 400, height: 200 },
        { width: 100, height: 100 },
      ),
    ).toEqual({
      x: 100,
      y: 0,
      width: 200,
      height: 200,
    })
  })

  it("maps pointer coordinates to preview hover samples with pan and zoom applied", () => {
    expect(
      mapPointerToCanvasPreviewHoverSample({
        clientX: 240,
        clientY: 120,
        containerRect: {
          left: 10,
          top: 20,
          width: 400,
          height: 200,
        },
        imageRect: {
          x: 100,
          y: 0,
          width: 200,
          height: 200,
        },
        naturalWidth: 100,
        naturalHeight: 100,
        scale: 2,
        translate: { x: 20, y: 10 },
      }),
    ).toEqual({
      containerX: 230,
      containerY: 100,
      containerWidth: 400,
      containerHeight: 200,
      containerLeft: 10,
      containerTop: 20,
      pixelX: 2,
      pixelY: 22,
      naturalWidth: 100,
      naturalHeight: 100,
    })
  })

  it("returns null when the pointer is outside the rendered image", () => {
    expect(
      mapPointerToCanvasPreviewHoverSample({
        clientX: 30,
        clientY: 60,
        containerRect: {
          left: 10,
          top: 20,
          width: 400,
          height: 200,
        },
        imageRect: {
          x: 100,
          y: 0,
          width: 200,
          height: 200,
        },
        naturalWidth: 100,
        naturalHeight: 100,
        scale: 1,
        translate: { x: 0, y: 0 },
      }),
    ).toBeNull()
  })

  it("builds a preview buffer from the loaded image", () => {
    const drawImage = vi.fn()
    const getContext = vi.fn(() => ({ drawImage }))
    const originalCreateElement = document.createElement.bind(document)
    vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string) => {
        if (tagName === "canvas") {
          return {
            width: 0,
            height: 0,
            getContext,
          } as unknown as HTMLCanvasElement
        }
        return originalCreateElement(tagName)
      })

    const image = new Image()
    Object.defineProperty(image, "naturalWidth", { configurable: true, value: 64 })
    Object.defineProperty(image, "naturalHeight", { configurable: true, value: 32 })

    const buffer = createCanvasPreviewBuffer(image)

    expect(buffer).not.toBeNull()
    expect(buffer).toMatchObject({ width: 64, height: 32 })
    expect(getContext).toHaveBeenCalledWith("2d", { willReadFrequently: true })
    expect(drawImage).toHaveBeenCalledWith(image, 0, 0)
  })

  it("draws the loaded preview onto a visible canvas surface", () => {
    const clearRect = vi.fn()
    const save = vi.fn()
    const restore = vi.fn()
    const setTransform = vi.fn()
    const translate = vi.fn()
    const scale = vi.fn()
    const drawImage = vi.fn()
    const canvas = { width: 0, height: 0, style: {} } as HTMLCanvasElement
    const image = new Image()

    drawCanvasPreviewFrame({
      canvas,
      context: {
        clearRect,
        save,
        restore,
        setTransform,
        translate,
        scale,
        drawImage,
      } as unknown as CanvasRenderingContext2D,
      image,
      containerSize: { width: 200, height: 100 },
      imageRect: { x: 25, y: 10, width: 150, height: 80 },
      translate: { x: 12, y: 8 },
      scale: 1.5,
      devicePixelRatio: 2,
    })

    expect(canvas.width).toBe(400)
    expect(canvas.height).toBe(200)
    expect(setTransform).toHaveBeenCalledWith(2, 0, 0, 2, 0, 0)
    expect(clearRect).toHaveBeenCalledWith(0, 0, 200, 100)
    expect(save).toHaveBeenCalledTimes(1)
    expect(translate).toHaveBeenCalledWith(12, 8)
    expect(scale).toHaveBeenCalledWith(1.5, 1.5)
    expect(drawImage).toHaveBeenCalledWith(image, 25, 10, 150, 80)
    expect(restore).toHaveBeenCalledTimes(1)
  })

  it("disables image smoothing when crisp rendering is requested", () => {
    const clearRect = vi.fn()
    const save = vi.fn()
    const restore = vi.fn()
    const setTransform = vi.fn()
    const translate = vi.fn()
    const scale = vi.fn()
    const drawImage = vi.fn()
    const canvas = { width: 0, height: 0, style: {} } as HTMLCanvasElement
    const image = new Image()
    const context = {
      clearRect,
      save,
      restore,
      setTransform,
      translate,
      scale,
      drawImage,
      imageSmoothingEnabled: true,
    } as unknown as CanvasRenderingContext2D

    drawCanvasPreviewFrame({
      canvas,
      context,
      image,
      containerSize: { width: 200, height: 100 },
      imageRect: { x: 25, y: 10, width: 150, height: 80 },
      translate: { x: 12, y: 8 },
      scale: 1.5,
      renderingQuality: "crisp",
    })

    expect(context.imageSmoothingEnabled).toBe(false)
  })

  it("deduplicates hover sample emissions including null samples", () => {
    const emitted: Array<CanvasPreviewHoverSample | null> = []
    const emit = createHoverSampleEmitter((sample) => {
      emitted.push(sample)
    })

    const sample: CanvasPreviewHoverSample = {
      containerX: 12,
      containerY: 13,
      containerWidth: 200,
      containerHeight: 100,
      containerLeft: 20,
      containerTop: 30,
      pixelX: 5,
      pixelY: 6,
      naturalWidth: 40,
      naturalHeight: 50,
    }

    emit(sample)
    emit({ ...sample })
    emit(null)
    emit(null)

    expect(emitted).toEqual([sample, null])
  })

  it("emits a fresh hover sample when only the container bounds change", () => {
    const emitted: Array<CanvasPreviewHoverSample | null> = []
    const emit = createHoverSampleEmitter((sample) => {
      emitted.push(sample)
    })

    const sample: CanvasPreviewHoverSample = {
      containerX: 12,
      containerY: 13,
      containerWidth: 200,
      containerHeight: 100,
      containerLeft: 20,
      containerTop: 30,
      pixelX: 5,
      pixelY: 6,
      naturalWidth: 40,
      naturalHeight: 50,
    }

    emit(sample)
    emit({
      ...sample,
      containerWidth: 260,
      containerHeight: 140,
    })

    expect(emitted).toEqual([
      sample,
      {
        ...sample,
        containerWidth: 260,
        containerHeight: 140,
      },
    ])
  })
})
