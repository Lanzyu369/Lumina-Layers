import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FiveColorCanvas from "../components/FiveColorCanvas";

class MockResizeObserver {
  observe = vi.fn();
  disconnect = vi.fn();
}

function createCanvasContext() {
  const gradient = {
    addColorStop: vi.fn(),
  };
  return {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    quadraticCurveTo: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    clearRect: vi.fn(),
    setTransform: vi.fn(),
    translate: vi.fn(),
    arc: vi.fn(),
    fillText: vi.fn(),
    measureText: vi.fn(() => ({ width: 120 })),
    createLinearGradient: vi.fn(() => gradient),
    createRadialGradient: vi.fn(() => gradient),
    set fillStyle(_value: string | CanvasGradient) {},
    set strokeStyle(_value: string | CanvasGradient) {},
    set globalAlpha(_value: number) {},
    set shadowColor(_value: string) {},
    set shadowBlur(_value: number) {},
    set shadowOffsetX(_value: number) {},
    set shadowOffsetY(_value: number) {},
    set font(_value: string) {},
    set textAlign(_value: CanvasTextAlign) {},
    set textBaseline(_value: CanvasTextBaseline) {},
    set lineWidth(_value: number) {},
    set lineCap(_value: CanvasLineCap) {},
  } as unknown as CanvasRenderingContext2D & {
    fillText: ReturnType<typeof vi.fn>;
  };
}

describe("FiveColorCanvas", () => {
  let context: ReturnType<typeof createCanvasContext>;

  beforeEach(() => {
    context = createCanvasContext();
    vi.stubGlobal("ResizeObserver", MockResizeObserver);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      ((contextId: string) =>
        contextId === "2d" ? context : null) as typeof HTMLCanvasElement.prototype.getContext,
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("redraws empty stack placeholders when the requested layer count changes", async () => {
    const stableSlices: [] = [];
    const { rerender } = render(
      <FiveColorCanvas
        slices={stableSlices}
        resultHex={null}
        isLoading={false}
        layerCount={5}
      />,
    );

    await waitFor(() => {
      expect(context.fillText).toHaveBeenCalledWith(
        "5",
        expect.any(Number),
        expect.any(Number),
      );
    });
    context.fillText.mockClear();

    rerender(
      <FiveColorCanvas
        slices={stableSlices}
        resultHex={null}
        isLoading={false}
        layerCount={6}
      />,
    );

    await waitFor(() => {
      expect(context.fillText).toHaveBeenCalledWith(
        "6",
        expect.any(Number),
        expect.any(Number),
      );
    });
  });
});
