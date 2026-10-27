import { describe, expect, it } from "vitest";
import { buildReferenceGridImageSvg, buildReferenceImageSvg } from "../lutDetails/referenceImage";

describe("referenceImage", () => {
  it("builds a smooth reference background instead of a crisp-edge dot grid", () => {
    const svg = buildReferenceImageSvg(
      [
        { x: -1, y: -1, hex_color: "#ff0000" },
        { x: 1, y: -1, hex_color: "#00ff00" },
        { x: -1, y: 1, hex_color: "#0000ff" },
        { x: 1, y: 1, hex_color: "#ffffff" },
      ],
      {
        minX: -1,
        maxX: 1,
        minY: -1,
        maxY: 1,
      },
      64,
    );

    expect(svg).not.toContain('shape-rendering="crispEdges"');
    expect(svg).toContain("<filter");
    expect(svg).toContain("<circle");
  });

  it("caps blur strength for dense reference backgrounds so colors stay legible", () => {
    const steps = Array.from({ length: 17 }, (_, index) => Math.round((index / 16) * 255));
    const points = [];
    for (const r of steps) {
      for (const g of steps) {
        for (const b of steps) {
          points.push({
            x: r - b,
            y: g - ((r + b) * 0.5),
            hex_color: `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`,
          });
        }
      }
    }

    const svg = buildReferenceImageSvg(
      points,
      {
        minX: -255,
        maxX: 255,
        minY: -255,
        maxY: 255,
      },
      240,
    );

    const deviations = Array.from(svg.matchAll(/stdDeviation="([0-9.]+)"/g), (match) => Number(match[1]));
    expect(Math.max(...deviations)).toBeLessThanOrEqual(4);
    expect(Math.min(...deviations)).toBeLessThanOrEqual(2.5);
  });

  it("keeps dense reference circles compact enough to avoid soft color bleeding", () => {
    const steps = Array.from({ length: 17 }, (_, index) => Math.round((index / 16) * 255));
    const points = [];
    for (const r of steps) {
      for (const g of steps) {
        for (const b of steps) {
          points.push({
            x: r - b,
            y: g - ((r + b) * 0.5),
            hex_color: `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`,
          });
        }
      }
    }

    const svg = buildReferenceImageSvg(
      points,
      {
        minX: -255,
        maxX: 255,
        minY: -255,
        maxY: 255,
      },
      240,
    );

    const radii = Array.from(svg.matchAll(/ r="([0-9.]+)"/g), (match) => Number(match[1]));
    expect(Math.max(...radii)).toBeLessThanOrEqual(6.2);
  });

  it("builds hue-style grid reference backgrounds as rect-only SVGs with the expected viewport", () => {
    const svg = buildReferenceGridImageSvg(
      {
        minX: 0,
        maxX: 360,
        minY: 0,
        maxY: 100,
      },
      {
        viewSize: 480,
        columns: 120,
        rows: 120,
        backgroundFill: "#0f172a",
        backgroundOpacity: 0.22,
        colorAt: (x, y) => ({
          fill: x > 180 ? "#ff0000" : "#00ff00",
          opacity: y > 50 ? 0.8 : 0.4,
        }),
      },
    );

    const rectCount = svg.match(/<rect /g)?.length ?? 0;
    const circleCount = svg.match(/<circle /g)?.length ?? 0;
    expect(svg).toContain('viewBox="0 0 480 480"');
    expect(rectCount).toBeGreaterThan(1000);
    expect(circleCount).toBe(0);
    expect(svg).toContain("#ff0000");
    expect(svg).toContain("#00ff00");
  });
});
