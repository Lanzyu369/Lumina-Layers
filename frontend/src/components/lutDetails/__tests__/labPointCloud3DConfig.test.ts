import { describe, expect, it } from "vitest";
import {
  getHullEdgeMaterialProps,
  getHullFillMaterialProps,
  getReferenceSliceMaterialProps,
  REFERENCE_SLICE_OPACITY,
  REFERENCE_SLICE_TEXTURE_RESOLUTION,
} from "../labPointCloud3DConfig";

describe("labPointCloud3DConfig", () => {
  it("raises the reference-slice texture resolution so the plane looks less blocky", () => {
    expect(REFERENCE_SLICE_TEXTURE_RESOLUTION).toBe(512);
  });

  it("keeps the reference slice visible enough while discarding fully transparent invalid fragments", () => {
    expect(REFERENCE_SLICE_OPACITY).toBeCloseTo(0.8, 6);
    expect(getReferenceSliceMaterialProps().toneMapped).toBe(false);
    expect(getReferenceSliceMaterialProps().depthWrite).toBe(true);
    expect(getReferenceSliceMaterialProps().alphaTest).toBeGreaterThan(0);
  });

  it("prevents the hull fill and edges from writing depth over interior point colors", () => {
    expect(getHullFillMaterialProps().depthWrite).toBe(false);
    expect(getHullEdgeMaterialProps().depthWrite).toBe(false);
  });
});
