import { describe, expect, it } from "vitest";
import {
  computePuzzleOverlayPlacement,
  computePuzzleOverlayTextureSize,
} from "../components/puzzleOverlay3DUtils";

describe("computePuzzleOverlayPlacement", () => {
  it("returns null when bounds are missing", () => {
    expect(
      computePuzzleOverlayPlacement(null, 1.2, false, {}, false, false, 0.4),
    ).toBeNull();
  });

  it("uses model bounds for overlay placement and keeps it above the model", () => {
    const placement = computePuzzleOverlayPlacement(
      {
        minX: -30,
        maxX: 30,
        minY: -20,
        maxY: 20,
        maxZ: 2.2,
      },
      1.2,
      true,
      { "ff0000": 1.8, "00ff00": 2.6 },
      true,
      true,
      0.5,
    );

    expect(placement).toMatchObject({
      centerX: 0,
      centerY: 0,
      width: 60,
      height: 40,
    });
    expect(placement?.z).toBeCloseTo(3.95, 6);
  });

  it("uses preview canvas bounds instead of cropped model bounds when present", () => {
    const placement = computePuzzleOverlayPlacement(
      {
        minX: -25.15,
        maxX: 25.15,
        minY: -25,
        maxY: 25,
        maxZ: 2.2,
      },
      1.2,
      false,
      {},
      false,
      false,
      0.5,
      {
        minX: -30.55,
        maxX: 29.45,
        minY: -30.1,
        maxY: 29.9,
        maxZ: 0,
      },
    );

    expect(placement?.centerX).toBeCloseTo(-0.55, 6);
    expect(placement?.centerY).toBeCloseTo(-0.1, 6);
    expect(placement?.width).toBeCloseTo(60, 6);
    expect(placement?.height).toBeCloseTo(60, 6);
  });
});

describe("computePuzzleOverlayTextureSize", () => {
  it("keeps small textures unchanged", () => {
    expect(computePuzzleOverlayTextureSize(640, 480, 1024)).toEqual({
      width: 640,
      height: 480,
    });
  });

  it("downscales large textures while preserving aspect ratio", () => {
    expect(computePuzzleOverlayTextureSize(4096, 2048, 1024)).toEqual({
      width: 1024,
      height: 512,
    });
  });
});
