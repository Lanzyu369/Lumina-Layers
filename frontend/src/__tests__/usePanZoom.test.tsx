import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as fc from "fast-check";
import { usePanZoom } from "../hooks/usePanZoom";
import ZoomViewport from "../components/ui/ZoomViewport";

describe("preview wheel zoom", () => {
  it("keeps arbitrary zoom sequences finite and bounded", () => {
    fc.assert(fc.property(fc.array(fc.record({
      x: fc.integer({ min: -2000, max: 2000 }),
      y: fc.integer({ min: -2000, max: 2000 }),
      delta: fc.integer({ min: -1000, max: 1000 }),
    }), { maxLength: 50 }), (operations) => {
      const { result, unmount } = renderHook(() => usePanZoom());
      try {
        for (const op of operations) act(() => result.current.zoom(op.x, op.y, op.delta));
        expect(result.current.scale).toBeGreaterThanOrEqual(0.1);
        expect(result.current.scale).toBeLessThanOrEqual(20);
        expect(Number.isFinite(result.current.translate.x)).toBe(true);
        expect(Number.isFinite(result.current.translate.y)).toBe(true);
      } finally {
        unmount();
      }
    }), { numRuns: 100 });
  });
  it("keeps small deltas proportional, anchored and reversible", () => {
    const { result } = renderHook(() => usePanZoom());
    for (let i = 0; i < 20; i++) act(() => result.current.zoom(80, 40, -5));
    expect(result.current.scale).toBeCloseTo(1.1, 8);
    expect(result.current.translate.x).toBeCloseTo(-8, 8);
    expect(result.current.translate.y).toBeCloseTo(-4, 8);
    act(() => result.current.zoom(80, 40, 100));
    expect(result.current.scale).toBeCloseTo(1, 8);
    expect(result.current.translate.x).toBeCloseTo(0, 8);
    act(() => result.current.zoom(80, 40, 0));
    expect(result.current.scale).toBeCloseTo(1, 8);
  });

  it("normalizes wheel units and shares the transform between comparison panes", () => {
    function Comparison() {
      const state = usePanZoom();
      return <><ZoomViewport {...state} src="a.png" alt="before" /><ZoomViewport {...state} src="b.png" alt="after" /></>;
    }
    render(<Comparison />);
    const before = screen.getByAltText("before");
    const after = screen.getByAltText("after");
    fireEvent.wheel(before.parentElement!, { deltaY: -6.25, deltaMode: 1 });
    expect(before.style.transform).toContain("scale(1.1)");
    expect(after.style.transform).toBe(before.style.transform);
    const event = new WheelEvent("wheel", { deltaY: 100, bubbles: true, cancelable: true });
    act(() => after.parentElement!.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(true);
    expect(before.style.transform).toContain("scale(1)");
  });

  it("bounds large impulses and respects scale limits", () => {
    const { result } = renderHook(() => usePanZoom());
    act(() => result.current.zoom(0, 0, -100000));
    expect(result.current.scale).toBeCloseTo(1.1);
    for (let i = 0; i < 100; i++) act(() => result.current.zoom(0, 0, -100));
    expect(result.current.scale).toBe(20);
    for (let i = 0; i < 100; i++) act(() => result.current.zoom(0, 0, 100));
    expect(result.current.scale).toBe(0.1);
  });
});
