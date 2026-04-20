import { describe, expect, it } from "vitest";
import * as fc from "fast-check";
import {
  hexToLab,
  hexToRgb,
  labToHex,
  labToRgb,
  rgbToLab,
} from "../colorUtils";

const hexByte = fc.integer({ min: 0, max: 255 });
const labTolerance = 2;
const inGamutLab = fc
  .tuple(hexByte, hexByte, hexByte)
  .map(([r, g, b]) => rgbToLab([r, g, b]))
  .filter(
    ([l, a, b]) =>
      l >= 0 && l <= 100 && a >= -80 && a <= 80 && b >= -80 && b <= 80,
  );

function maxChannelDelta(a: string, b: string): number {
  const rgbA = hexToRgb(a);
  const rgbB = hexToRgb(b);
  return Math.max(
    Math.abs(rgbA[0] - rgbB[0]),
    Math.abs(rgbA[1] - rgbB[1]),
    Math.abs(rgbA[2] - rgbB[2]),
  );
}

describe("sRGB ↔ Lab (D65)", () => {
  it("round-trips #RRGGBB through Lab with at most two channel levels of drift", () => {
    fc.assert(
      fc.property(hexByte, hexByte, hexByte, (r, g, b) => {
        const hex = `#${[r, g, b]
          .map((value) => value.toString(16).padStart(2, "0").toUpperCase())
          .join("")}`;

        const roundTrip = labToHex(hexToLab(hex));

        expect(maxChannelDelta(hex, roundTrip)).toBeLessThanOrEqual(2);
      }),
      { numRuns: 100 },
    );
  });

  it("round-trips reasonable Lab values through sRGB with small Lab drift", () => {
    fc.assert(
      fc.property(inGamutLab, (lab) => {
          const roundTrip = rgbToLab(labToRgb(lab));

          expect(Math.abs(roundTrip[0] - lab[0])).toBeLessThanOrEqual(
            labTolerance,
          );
          expect(Math.abs(roundTrip[1] - lab[1])).toBeLessThanOrEqual(
            labTolerance,
          );
          expect(Math.abs(roundTrip[2] - lab[2])).toBeLessThanOrEqual(
            labTolerance,
          );
      }),
      { numRuns: 100 },
    );
  });

  it("maps black and white to expected Lab endpoints", () => {
    const black = hexToLab("#000000");
    expect(Math.abs(black[0])).toBeLessThan(0.5);
    expect(Math.abs(black[1])).toBeLessThan(0.5);
    expect(Math.abs(black[2])).toBeLessThan(0.5);

    const white = hexToLab("#FFFFFF");
    expect(Math.abs(white[0] - 100)).toBeLessThan(0.5);
    expect(Math.abs(white[1])).toBeLessThan(1);
    expect(Math.abs(white[2])).toBeLessThan(1);
  });

  it("matches the D65 pure-red reference lightness", () => {
    const red = hexToLab("#FF0000");
    expect(red[0]).toBeGreaterThanOrEqual(51);
    expect(red[0]).toBeLessThanOrEqual(55);
  });
});
