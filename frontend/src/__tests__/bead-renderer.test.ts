import { describe, expect, it } from "vitest";

import { createBeadProject } from "../workshop/modules/bead/project";
import {
  renderBeadProject,
  type BeadRenderResult,
} from "../workshop/modules/bead/renderer";
import type {
  BeadCell,
  RgbColor,
} from "../workshop/modules/bead/types";

const RED: RgbColor = [230, 40, 50];
const BLUE: RgbColor = [20, 120, 210];

function makeProject(
  rows: number,
  columns: number,
  cells: BeadCell[],
) {
  return createBeadProject({
    projectId: `${rows}x${columns}`,
    moduleVersion: "1.0.0",
    now: "2026-07-30T00:00:00.000Z",
    rows,
    columns,
    palette: [RED, BLUE],
    cells,
  });
}

function alphaAt(
  result: BeadRenderResult,
  x: number,
  y: number,
): number {
  return result.data[(y * result.width + x) * 4 + 3];
}

function rgbAt(
  result: BeadRenderResult,
  x: number,
  y: number,
): RgbColor {
  const offset = (y * result.width + x) * 4;
  return [
    result.data[offset],
    result.data[offset + 1],
    result.data[offset + 2],
  ];
}

function opaqueCount(
  result: BeadRenderResult,
  bounds = {
    left: 0,
    top: 0,
    right: result.width,
    bottom: result.height,
  },
): number {
  let count = 0;
  for (let y = bounds.top; y < bounds.bottom; y += 1) {
    for (let x = bounds.left; x < bounds.right; x += 1) {
      count += alphaAt(result, x, y) === 255 ? 1 : 0;
    }
  }
  return count;
}

describe("bead pressure renderer", () => {
  it("shrinks the centre hole and closes it only at terminal pressure", () => {
    const project = makeProject(1, 1, [
      { kind: "color", paletteIndex: 0 },
    ]);

    const light = renderBeadProject(project, {
      compression: 0,
      pixelsPerCell: 32,
    });
    const standard = renderBeadProject(project, {
      compression: 50,
      pixelsPerCell: 32,
    });
    const almostTight = renderBeadProject(project, {
      compression: 99,
      pixelsPerCell: 32,
    });
    const tight = renderBeadProject(project, {
      compression: 100,
      pixelsPerCell: 32,
    });

    expect(alphaAt(light, 16, 16)).toBe(0);
    expect(alphaAt(standard, 16, 16)).toBe(0);
    expect(alphaAt(almostTight, 16, 16)).toBe(0);
    expect(alphaAt(tight, 16, 16)).toBe(255);
    expect(opaqueCount(light)).toBeLessThan(opaqueCount(standard));
    expect(opaqueCount(standard)).toBeLessThan(opaqueCount(tight));
  });

  it("keeps the four-bead junction open before 100 and closes it at 100", () => {
    const project = makeProject(
      2,
      2,
      Array.from(
        { length: 4 },
        () => ({ kind: "color", paletteIndex: 0 }) as const,
      ),
    );

    const standard = renderBeadProject(project, {
      compression: 50,
      pixelsPerCell: 32,
    });
    const almostTight = renderBeadProject(project, {
      compression: 99,
      pixelsPerCell: 32,
    });
    const tight = renderBeadProject(project, {
      compression: 100,
      pixelsPerCell: 32,
    });

    expect(alphaAt(standard, 32, 32)).toBe(0);
    expect(alphaAt(almostTight, 32, 32)).toBe(0);
    expect(alphaAt(tight, 32, 32)).toBe(255);
  });

  it("has no seam for same colors and preserves exact boundaries for different colors", () => {
    const sameColor = renderBeadProject(
      makeProject(1, 2, [
        { kind: "color", paletteIndex: 0 },
        { kind: "color", paletteIndex: 0 },
      ]),
      { compression: 100, pixelsPerCell: 32 },
    );
    const differentColors = renderBeadProject(
      makeProject(1, 2, [
        { kind: "color", paletteIndex: 0 },
        { kind: "color", paletteIndex: 1 },
      ]),
      { compression: 100, pixelsPerCell: 32 },
    );

    for (let y = 0; y < sameColor.height; y += 1) {
      expect(alphaAt(sameColor, 31, y)).toBe(255);
      expect(alphaAt(sameColor, 32, y)).toBe(255);
    }
    expect(rgbAt(differentColors, 31, 16)).toEqual(RED);
    expect(rgbAt(differentColors, 32, 16)).toEqual(BLUE);
  });

  it("uses support cells in contact geometry but writes their owned area transparent", () => {
    const withEmpty = renderBeadProject(
      makeProject(1, 2, [
        { kind: "color", paletteIndex: 0 },
        { kind: "empty" },
      ]),
      { compression: 35, pixelsPerCell: 32 },
    );
    const withSupport = renderBeadProject(
      makeProject(1, 2, [
        { kind: "color", paletteIndex: 0 },
        { kind: "transparent-support" },
      ]),
      { compression: 35, pixelsPerCell: 32 },
    );
    const firstCell = { left: 0, top: 0, right: 32, bottom: 32 };

    expect(opaqueCount(withSupport, firstCell)).toBeGreaterThan(
      opaqueCount(withEmpty, firstCell),
    );
    for (let y = 0; y < 32; y += 1) {
      for (let x = 32; x < 64; x += 1) {
        expect(alphaAt(withSupport, x, y)).toBe(0);
      }
    }
  });

  it("writes only binary alpha and exact palette bytes", () => {
    const rendered = renderBeadProject(
      makeProject(2, 2, [
        { kind: "color", paletteIndex: 0 },
        { kind: "color", paletteIndex: 1 },
        { kind: "empty" },
        { kind: "transparent-support" },
      ]),
      { compression: 63, pixelsPerCell: 16 },
    );
    const allowed = new Set([RED.join(","), BLUE.join(",")]);

    for (let offset = 0; offset < rendered.data.length; offset += 4) {
      const alpha = rendered.data[offset + 3];
      expect([0, 255]).toContain(alpha);
      if (alpha === 0) {
        expect([...rendered.data.slice(offset, offset + 3)]).toEqual([
          0, 0, 0,
        ]);
      } else {
        expect(
          allowed.has(
            [
              rendered.data[offset],
              rendered.data[offset + 1],
              rendered.data[offset + 2],
            ].join(","),
          ),
        ).toBe(true);
      }
    }
  });
});
