import { describe, expect, it } from "vitest";

import { resolveCameraClippingPlanes } from "../utils/cameraDepthPrecision";

const DEPTH_BUFFER_LEVELS = 2 ** 24;
const MIN_MATERIAL_LAYER_MM = 0.08;

function estimatedDepthResolutionMm(distance: number, near: number): number {
  return (distance * distance) / (near * DEPTH_BUFFER_LEVELS);
}

describe("resolveCameraClippingPlanes", () => {
  it.each([10, 475, 2_000])(
    "keeps 0.08 mm material layers distinguishable at distance %d mm",
    (distance) => {
      const planes = resolveCameraClippingPlanes(distance);

      expect(planes.near).toBeGreaterThan(0);
      expect(planes.near).toBeLessThan(distance);
      expect(planes.far).toBeGreaterThan(distance);
      expect(
        estimatedDepthResolutionMm(distance, planes.near),
      ).toBeLessThan(MIN_MATERIAL_LAYER_MM / 4);
    },
  );

  it("falls back to safe finite clipping planes for an invalid distance", () => {
    expect(resolveCameraClippingPlanes(Number.NaN)).toEqual({
      near: 0.1,
      far: 2_500,
    });
  });
});
