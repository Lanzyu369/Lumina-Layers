import { describe, expect, it } from "vitest";
import { bindOrbitWheelZoom, wheelZoomDelta } from "../wheelZoom";

describe("wheel normalization", () => {
  it("converts units and ignores invalid input", () => {
    expect(wheelZoomDelta(-2, 1)).toBe(-32);
    expect(wheelZoomDelta(-1, 2, 600)).toBe(-100);
    expect(wheelZoomDelta(NaN)).toBe(0);
  });

  it("scales the native OrbitControls handler once per event and restores its speed", () => {
    const element = document.createElement("div");
    const controls = { zoomSpeed: 2 };
    const speeds: number[] = [];
    const anchors: number[] = [];
    element.addEventListener("wheel", (event) => {
      speeds.push(controls.zoomSpeed);
      anchors.push(event.clientX);
    });
    const cleanup = bindOrbitWheelZoom(element, controls);
    for (let i = 0; i < 20; i++) {
      const event = new WheelEvent("wheel", { deltaY: -5, clientX: 42, cancelable: true });
      element.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
      expect(controls.zoomSpeed).toBe(2);
    }
    expect(speeds).toHaveLength(20);
    expect(speeds.reduce((sum, speed) => sum + speed, 0)).toBeCloseTo(2);
    expect(anchors.every((x) => x === 42)).toBe(true);
    element.dispatchEvent(new WheelEvent("wheel", { deltaY: 0, deltaX: 20 }));
    expect(speeds).toHaveLength(20);
    element.dispatchEvent(new WheelEvent("wheel", { deltaY: -10000 }));
    expect(speeds.at(-1)).toBe(2);
    cleanup();
    element.dispatchEvent(new WheelEvent("wheel", { deltaY: -1 }));
    expect(speeds.at(-1)).toBe(2);
  });
});
