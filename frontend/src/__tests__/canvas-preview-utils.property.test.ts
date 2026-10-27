import { describe, expect, it } from "vitest";
import * as fc from "fast-check";
import {
  clampCanvasPreviewScale,
  computeCanvasPreviewZoomTranslate,
} from "../components/ui/canvasPreviewUtils";

const arbFinite = fc.double({ min: -1e6, max: 1e6, noNaN: true });
const arbScale = fc.double({ min: 0.01, max: 100, noNaN: true });
const arbPoint = fc.record({ x: arbFinite, y: arbFinite });
const arbDeltaY = fc.double({ min: -5000, max: 5000, noNaN: true });

describe("Feature: canvas-preview-utils, Property 8: 缩放范围不变量", () => {
  it("clampCanvasPreviewScale always returns a value within [0.5, 5.0] for any input", () => {
    fc.assert(
      fc.property(arbFinite, (value) => {
        const result = clampCanvasPreviewScale(value);
        return result >= 0.5 && result <= 5.0;
      }),
      { numRuns: 100 },
    );
  });

  it("a sequence of wheel zoom operations keeps scale within [0.5, 5.0]", () => {
    fc.assert(
      fc.property(
        fc.array(arbDeltaY, { minLength: 1, maxLength: 50 }),
        (deltas) => {
          let scale = 1.0;
          for (const deltaY of deltas) {
            scale = clampCanvasPreviewScale(scale * (1 - deltaY * 0.001));
          }
          return scale >= 0.5 && scale <= 5.0;
        },
      ),
      { numRuns: 100 },
    );
  });
});

describe("Feature: canvas-preview-utils, Property 9: 鼠标锚点缩放不变量", () => {
  it("keeps the pointer-anchored preview coordinate stable after zoom translate is recomputed", () => {
    fc.assert(
      fc.property(arbPoint, arbPoint, arbScale, arbScale, (mousePos, oldTranslate, oldScale, rawNewScale) => {
        const newScale = clampCanvasPreviewScale(rawNewScale, 0.01, 100);
        const nextTranslate = computeCanvasPreviewZoomTranslate(
          mousePos,
          oldTranslate,
          oldScale,
          newScale,
        );
        const anchoredXBefore = (mousePos.x - oldTranslate.x) / oldScale;
        const anchoredYBefore = (mousePos.y - oldTranslate.y) / oldScale;
        const anchoredXAfter = (mousePos.x - nextTranslate.x) / newScale;
        const anchoredYAfter = (mousePos.y - nextTranslate.y) / newScale;
        const tolerance = 1e-6;
        return (
          Math.abs(anchoredXBefore - anchoredXAfter) < tolerance &&
          Math.abs(anchoredYBefore - anchoredYAfter) < tolerance
        );
      }),
      { numRuns: 100 },
    );
  });
});

describe("Feature: canvas-preview-utils, Property 10: 钳制幂等性", () => {
  it("clamping a value twice yields the same result as clamping it once", () => {
    fc.assert(
      fc.property(arbFinite, (value) => {
        const once = clampCanvasPreviewScale(value);
        const twice = clampCanvasPreviewScale(once);
        return once === twice;
      }),
      { numRuns: 100 },
    );
  });

  it("matches the explicit min and max bounds at the extremes", () => {
    expect(clampCanvasPreviewScale(-1e9)).toBe(0.5);
    expect(clampCanvasPreviewScale(1e9)).toBe(5.0);
  });
});
