import { describe, expect, it } from "vitest";
import {
  computeOutlinePreviewHeight,
  extractHexFromMeshName,
} from "../components/InteractiveModelViewer";

describe("extractHexFromMeshName", () => {
  it('extracts hex from "color_ff0000"', () => {
    expect(extractHexFromMeshName("color_ff0000")).toBe("ff0000");
  });

  it('extracts hex from "color_00ff00"', () => {
    expect(extractHexFromMeshName("color_00ff00")).toBe("00ff00");
  });

  it('extracts hex from "color_AABBCC" preserving case', () => {
    expect(extractHexFromMeshName("color_AABBCC")).toBe("AABBCC");
  });

  it("extracts hex from color_ prefix with 6 chars", () => {
    expect(extractHexFromMeshName("color_000000")).toBe("000000");
    expect(extractHexFromMeshName("color_ffffff")).toBe("ffffff");
  });
});

describe("computeOutlinePreviewHeight", () => {
  it("uses live single-sided spacer thickness for fridge-magnet outline preview", () => {
    expect(
      computeOutlinePreviewHeight(3.44, "Single-sided", false, {}, 12),
    ).toBeCloseTo(3.84, 5);
  });

  it("keeps double-sided color layers in the outline preview height", () => {
    expect(
      computeOutlinePreviewHeight(1.2, "Double-sided", false, {}, 12),
    ).toBeCloseTo(2.0, 5);
  });

  it("uses the tallest relief color height when relief preview is enabled", () => {
    expect(
      computeOutlinePreviewHeight(1.2, "Single-sided", true, { ff0000: 2.5, "00ff00": 1.5 }, 12),
    ).toBeCloseTo(3.7, 5);
  });
});
