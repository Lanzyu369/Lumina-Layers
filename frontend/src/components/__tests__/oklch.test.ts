import { describe, expect, it } from "vitest";
import { rgbToOklch } from "../lutDetails/oklch";

describe("oklch utilities", () => {
  it("treats neutral gray as nearly zero saturation", () => {
    const gray = rgbToOklch(128, 128, 128);
    expect(gray.c).toBeLessThan(0.01);
  });

  it("models yellow as perceptually lighter than blue", () => {
    const yellow = rgbToOklch(255, 255, 0);
    const blue = rgbToOklch(0, 0, 255);
    expect(yellow.l).toBeGreaterThan(blue.l);
  });
});
