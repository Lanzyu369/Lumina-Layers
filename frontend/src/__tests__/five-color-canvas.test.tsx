import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FiveColorCanvas from "../components/FiveColorCanvas";
import { I18nProvider } from "../i18n/context";
import { useSettingsStore } from "../stores/settingsStore";

vi.unmock("../i18n/context");

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
    useSettingsStore.setState({ language: "zh" });
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.each([false, true])("redraws localized labels after language changes (loading: %s)", async (isLoading) => {
    useSettingsStore.setState({ language: "zh" });
    render(
      <I18nProvider>
        <FiveColorCanvas
          slices={isLoading ? [{ hex: "#ffffff", name: "PLA" }] : []}
          resultHex={null}
          isLoading={isLoading}
        />
      </I18nProvider>,
    );

    for (const language of ["en", "zh", "en"] as const) {
      context.fillText.mockClear();
      act(() => useSettingsStore.getState().setLanguage(language));
      await waitFor(() => {
        const drawnText = context.fillText.mock.calls.map(([text]) => text);
        expect(drawnText).toContain(language === "en" ? "Viewing Face" : "观赏面");
        expect(drawnText).toContain(language === "en" ? "Bottom" : "底面");
        expect(drawnText).not.toContain(language === "en" ? "观赏面" : "Viewing Face");
        if (isLoading) {
          expect(drawnText).toContain(language === "en" ? "Querying..." : "查询中...");
        }
      });
    }
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
