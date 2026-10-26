import { describe, expect, it } from "vitest";
import { buildHueChromaPoints, buildHueLightnessPoints, buildHuePeakProfile } from "../LutDetailsPanel";
import { oklchToHexClamped, rgbToOklch } from "../lutDetails/oklch";

function hexToRgbTuple(hex: string): [number, number, number] {
  const normalized = hex.replace("#", "");
  return [
    parseInt(normalized.slice(0, 2), 16),
    parseInt(normalized.slice(2, 4), 16),
    parseInt(normalized.slice(4, 6), 16),
  ];
}

function interpolateHuePeak(
  profile: Array<{ hue: number; lightness: number; maxChroma: number }>,
  hue: number,
): { lightness: number; maxChroma: number } {
  const normalizedHue = ((hue % 360) + 360) % 360;
  const maxIndex = profile.length - 1;
  const scaledIndex = (normalizedHue / 360) * maxIndex;
  const leftIndex = Math.floor(scaledIndex);
  const rightIndex = Math.min(maxIndex, leftIndex + 1);
  const mix = scaledIndex - leftIndex;
  const left = profile[leftIndex];
  const right = profile[rightIndex];
  return {
    lightness: left.lightness + ((right.lightness - left.lightness) * mix),
    maxChroma: left.maxChroma + ((right.maxChroma - left.maxChroma) * mix),
  };
}

describe("LutDetailsPanel hue peak profile", () => {
  it("normalizes hue-lightness points per hue instead of using absolute perceptual lightness", () => {
    const darkHex = oklchToHexClamped({ l: 0.32, c: 0.18, h: 25 });
    const brightHex = oklchToHexClamped({ l: 0.82, c: 0.18, h: 25 });
    const darkPoint = {
      x: 0,
      y: 0,
      hex_color: darkHex,
      rgb: hexToRgbTuple(darkHex),
      label: "dark",
    };
    const brightPoint = {
      x: 0,
      y: 0,
      hex_color: brightHex,
      rgb: hexToRgbTuple(brightHex),
      label: "bright",
    };

    const [darkMapped, brightMapped] = buildHueLightnessPoints([darkPoint, brightPoint]);
    expect(darkMapped.y).toBeLessThan(brightMapped.y);

    const darkAbsolute = rgbToOklch(...darkPoint.rgb).l * 100;
    const brightAbsolute = rgbToOklch(...brightPoint.rgb).l * 100;

    expect(darkMapped.y).not.toBeCloseTo(darkAbsolute, 3);
    expect(brightMapped.y).not.toBeCloseTo(brightAbsolute, 3);
  });

  it("maps hue-saturation chart points through OKLCH coordinates", () => {
    const low = {
      x: 0,
      y: 0,
      hex_color: "#7fae87",
      rgb: [127, 174, 135] as [number, number, number],
      label: "green-low",
    };
    const high = {
      x: 0,
      y: 0,
      hex_color: "#00ff00",
      rgb: [0, 255, 0] as [number, number, number],
      label: "green-high",
    };

    const [lowMapped, highMapped] = buildHueChromaPoints([low, high]);
    const expectedLow = rgbToOklch(...low.rgb);
    const expectedHigh = rgbToOklch(...high.rgb);

    expect(lowMapped.x).toBeCloseTo(expectedLow.h, 6);
    expect(highMapped.x).toBeCloseTo(expectedHigh.h, 6);
    expect(highMapped.y).not.toBeCloseTo(expectedHigh.c, 6);
    expect(lowMapped.y).not.toBeCloseTo(expectedLow.c, 6);
    expect(lowMapped.y).toBeGreaterThanOrEqual(0);
    expect(highMapped.y).toBeLessThanOrEqual(100);
  });

  it("uses the hue-saturation backdrop reference color for plotted LUT points", () => {
    const pointHex = oklchToHexClamped({ l: 0.42, c: 0.18, h: 28 });
    const point = {
      x: 0,
      y: 0,
      hex_color: pointHex,
      rgb: hexToRgbTuple(pointHex),
      label: "orange-mid",
    };

    const [mapped] = buildHueChromaPoints([point]);
    const oklch = rgbToOklch(...point.rgb);
    const profile = buildHuePeakProfile(721, 0.35);
    const huePeak = interpolateHuePeak(profile, oklch.h);
    const relativeSaturation = Math.max(
      0,
      Math.min(100, (oklch.c / Math.max(huePeak.maxChroma, 0.0001)) * 100),
    );
    const expectedHex = oklchToHexClamped({
      l: huePeak.lightness / 100,
      c: (relativeSaturation / 100) * huePeak.maxChroma,
      h: oklch.h,
    });

    expect(expectedHex).not.toBe(pointHex);
    expect(mapped.hex_color).toBe(expectedHex);
  });

  it("omits low-chroma points from hue-based charts because their hue is undefined", () => {
    const neutral = {
      x: 0,
      y: 0,
      hex_color: "#ffffff",
      rgb: [255, 255, 255] as [number, number, number],
      label: "neutral",
    };
    const chromaticHex = oklchToHexClamped({ l: 0.64, c: 0.22, h: 22 });
    const chromatic = {
      x: 0,
      y: 0,
      hex_color: chromaticHex,
      rgb: hexToRgbTuple(chromaticHex),
      label: "chromatic",
    };

    const hueLightnessPoints = buildHueLightnessPoints([neutral, chromatic]);
    const hueChromaPoints = buildHueChromaPoints([neutral, chromatic]);

    expect(hueLightnessPoints).toHaveLength(1);
    expect(hueChromaPoints).toHaveLength(1);
    expect(hueLightnessPoints[0]?.label).toBe("chromatic");
    expect(hueChromaPoints[0]?.label).toBe("chromatic");
  });

  it("keeps the perceptual hue profile within a normalized 0-100 lightness range", () => {
    const profile = buildHuePeakProfile(181, 140);
    const lightnessValues = profile.map((entry) => entry.lightness);
    expect(Math.min(...lightnessValues)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...lightnessValues)).toBeLessThanOrEqual(100);
  });
});
