import { describe, expect, it } from "vitest";

import { sampleReferenceSliceColor } from "../labReferenceSlice";

function srgbToLinear(channel: number): number {
  const normalized = channel / 255;
  if (normalized <= 0.04045) {
    return normalized / 12.92;
  }
  return ((normalized + 0.055) / 1.055) ** 2.4;
}

function rgbToLab(r: number, g: number, b: number): { l: number; a: number; b2: number } {
  const lr = srgbToLinear(r);
  const lg = srgbToLinear(g);
  const lb = srgbToLinear(b);

  const x = (lr * 0.4124564 + lg * 0.3575761 + lb * 0.1804375) / 0.95047;
  const y = (lr * 0.2126729 + lg * 0.7151522 + lb * 0.072175) / 1.0;
  const z = (lr * 0.0193339 + lg * 0.119192 + lb * 0.9503041) / 1.08883;

  const f = (value: number) =>
    value > 0.008856 ? Math.cbrt(value) : (7.787 * value) + (16 / 116);

  const fx = f(x);
  const fy = f(y);
  const fz = f(z);

  return {
    l: (116 * fy) - 16,
    a: 500 * (fx - fy),
    b2: 200 * (fy - fz),
  };
}

describe("labReferenceSlice", () => {
  it("hides out-of-gamut samples instead of painting clipped reference colors", () => {
    const sample = sampleReferenceSliceColor(60, 120, 20);

    expect(sample.inGamut).toBe(false);
    expect(sample.alpha).toBe(0);
  });

  it("keeps in-gamut samples fully opaque", () => {
    const sample = sampleReferenceSliceColor(60, 40, 20);

    expect(sample.inGamut).toBe(true);
    expect(sample.alpha).toBe(255);
    expect(sample.rgb[0]).toBeGreaterThan(sample.rgb[1]);
    expect(sample.rgb[1]).toBeGreaterThan(sample.rgb[2] - 8);
  });

  it("round-trips real rgb points so the reference plane matches plotted colors", () => {
    const lab = rgbToLab(255, 0, 0);
    const sample = sampleReferenceSliceColor(lab.l, lab.a, lab.b2);

    expect(sample.inGamut).toBe(true);
    expect(sample.alpha).toBe(255);
    expect(sample.rgb[0]).toBe(255);
    expect(sample.rgb[1]).toBe(0);
    expect(sample.rgb[2]).toBe(0);
  });
});
