import { describe, expect, it } from "vitest";
import { createPreviewSpace } from "../utils/previewSpace";

describe("PreviewSpace", () => {
  const bounds = {
    minX: 2,
    maxX: 12,
    minY: -8,
    maxY: 2,
    maxZ: 3,
  };

  it("scales asset bounds around their centre", () => {
    const space = createPreviewSpace(bounds, 2, 3);

    expect(space.displayBounds).toEqual({
      minX: -3,
      maxX: 17,
      minY: -18,
      maxY: 12,
      maxZ: 3,
    });
    expect(space.assetGroupPosition).toEqual({ x: -7, y: 6 });
  });

  it("round-trips points and deltas under non-uniform scale", () => {
    const space = createPreviewSpace(bounds, 2, 3);

    expect(space.toDisplayPoint({ x: 10, y: -6 })).toEqual({ x: 13, y: -12 });
    expect(space.toAssetPoint({ x: 13, y: -12 })).toEqual({ x: 10, y: -6 });
    expect(space.displayDeltaToAsset({ x: 8, y: -9 })).toEqual({ x: 4, y: -3 });
  });

  it("sanitizes invalid scales without producing invalid scene coordinates", () => {
    const space = createPreviewSpace(bounds, Number.NaN, 0);

    expect(space.scaleX).toBe(1);
    expect(space.scaleY).toBe(1);
    expect(space.displayBounds).toEqual(bounds);
  });
});
