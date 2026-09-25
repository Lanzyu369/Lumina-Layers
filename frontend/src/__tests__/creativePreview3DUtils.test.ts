import { describe, expect, it } from "vitest";
import {
  computeCoatingPreviewLayers,
  mapHeightmapGrayscaleToHeights,
} from "../components/creativePreview3DUtils";

describe("mapHeightmapGrayscaleToHeights", () => {
  it("maps black through white to the requested lightweight relief range", () => {
    const heights = mapHeightmapGrayscaleToHeights(
      new Uint8Array([0, 128, 255]),
      0.08,
      3.0,
    );

    expect(Array.from(heights)).toEqual([
      expect.closeTo(0.08, 5),
      expect.closeTo(0.08 + (128 / 255) * 2.92, 5),
      expect.closeTo(3.0, 5),
    ]);
  });
});

describe("computeCoatingPreviewLayers", () => {
  it("places one coating below a single-sided model", () => {
    expect(computeCoatingPreviewLayers({
      coatingHeightMm: 0.08,
      layerHeightMm: 0.08,
      structureMode: "Single-sided",
      enableRelief: false,
      spacerThickMm: 1.2,
      visibleColorHeightMm: 0.4,
    })).toEqual([{ zMin: -0.08, zMax: 0 }]);
  });

  it("wraps both exposed faces of a double-sided model", () => {
    expect(computeCoatingPreviewLayers({
      coatingHeightMm: 0.08,
      layerHeightMm: 0.08,
      structureMode: "Double-sided",
      enableRelief: false,
      spacerThickMm: 1.2,
      visibleColorHeightMm: 0.4,
    })).toEqual([
      { zMin: -0.48, zMax: -0.4 },
      { zMin: 1.6, zMax: 1.68 },
    ]);
  });

  it("quantizes coating thickness to the same print layers as the backend", () => {
    expect(computeCoatingPreviewLayers({
      coatingHeightMm: 0.04,
      layerHeightMm: 0.08,
      structureMode: "Single-sided",
      enableRelief: false,
      spacerThickMm: 1.2,
      visibleColorHeightMm: 0.4,
    })).toEqual([{ zMin: -0.08, zMax: 0 }]);

    expect(computeCoatingPreviewLayers({
      coatingHeightMm: 0.12,
      layerHeightMm: 0.08,
      structureMode: "Single-sided",
      enableRelief: false,
      spacerThickMm: 1.2,
      visibleColorHeightMm: 0.4,
    })).toEqual([{ zMin: -0.16, zMax: 0 }]);
  });
});
