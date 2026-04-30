import { describe, expect, it } from "vitest";
import * as fc from "fast-check";
import { getObjectFitRect } from "../utils/lutCoordUtils";

const positiveDimension = fc.integer({ min: 1, max: 2000 });

describe("Feature: extractor-preview-object-fit, Property: 渲染区域边界不变量", () => {
  it("渲染区域完全包含在元素边界内", () => {
    fc.assert(
      fc.property(
        positiveDimension,
        positiveDimension,
        positiveDimension,
        positiveDimension,
        (naturalWidth, naturalHeight, clientWidth, clientHeight) => {
          const rendered = getObjectFitRect(
            naturalWidth,
            naturalHeight,
            clientWidth,
            clientHeight,
          );

          expect(rendered.offsetX).toBeGreaterThanOrEqual(0);
          expect(rendered.offsetY).toBeGreaterThanOrEqual(0);
          expect(rendered.offsetX + rendered.width).toBeLessThanOrEqual(clientWidth);
          expect(rendered.offsetY + rendered.height).toBeLessThanOrEqual(clientHeight);
        },
      ),
      { numRuns: 200 },
    );
  });
});
