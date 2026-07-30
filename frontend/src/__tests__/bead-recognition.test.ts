import { describe, expect, it } from "vitest";

import {
  classifyPattern,
  cropRaster,
  recognizeBeadPattern,
  suggestGrid,
} from "../workshop/modules/bead/recognition";
import type {
  RecognitionRequest,
} from "../workshop/modules/bead/types";
import {
  makeHardPixelFixture,
  makeNumberedGridFixture,
  makeRaster,
  makeRingFixture,
} from "./helpers/beadFixtures";

function requestFor(
  source: ReturnType<typeof makeRaster>,
  mode: RecognitionRequest["mode"],
  rows: number,
  columns: number,
  emptyCellIndex: number,
  transparentSupportSampleCellIndex: number | null = null,
): RecognitionRequest {
  const suggestion = suggestGrid(source, mode);
  return {
    source,
    mode,
    rows,
    columns,
    geometry: suggestion.geometry,
    emptySelection: { kind: "sample", cellIndex: emptyCellIndex },
    transparentSupportSampleCellIndex,
    orientation: {
      rotation: 0,
      flipHorizontal: false,
      flipVertical: false,
    },
  };
}

describe("bead recognition", () => {
  it("crops RGBA pixels without changing their exact values", () => {
    const source = makeHardPixelFixture({
      rows: 2,
      columns: 2,
      scale: 4,
    });

    const cropped = cropRaster(source, {
      x: 4,
      y: 0,
      width: 4,
      height: 4,
    });

    expect(cropped).toMatchObject({ width: 4, height: 4 });
    expect([...cropped.data.slice(0, 4)]).toEqual(
      [...source.data.slice(4 * 4, 4 * 4 + 4)],
    );
  });

  it("classifies clear numbered, hard-pixel, and ring-preview inputs", () => {
    const numbered = makeNumberedGridFixture({
      rows: 4,
      columns: 5,
      gridLineWidth: 2,
      watermarkCells: [7],
      whiteBeadCells: [1],
    });
    const hardPixel = makeHardPixelFixture({
      rows: 3,
      columns: 4,
      scale: 16,
    });
    const rings = makeRingFixture({
      rows: 3,
      columns: 3,
      holeRadius: 4,
    });

    expect(classifyPattern(numbered).mode).toBe("numbered-grid");
    expect(classifyPattern(hardPixel).mode).toBe("hard-pixel");
    expect(classifyPattern(rings).mode).toBe("ring-preview");
    expect(classifyPattern(makeRaster(40, 40)).mode).toBe("ambiguous");
  });

  it("suggests exact square-grid dimensions for all three digital modes", () => {
    const numbered = suggestGrid(
      makeNumberedGridFixture({ rows: 4, columns: 5 }),
      "numbered-grid",
    );
    const hardPixel = suggestGrid(
      makeHardPixelFixture({ rows: 3, columns: 4, scale: 16 }),
      "hard-pixel",
    );
    const rings = suggestGrid(
      makeRingFixture({ rows: 3, columns: 3 }),
      "ring-preview",
    );

    expect(numbered).toMatchObject({
      rows: 4,
      columns: 5,
      validSquareGrid: true,
    });
    expect(hardPixel).toMatchObject({
      rows: 3,
      columns: 4,
      validSquareGrid: true,
    });
    expect(rings).toMatchObject({
      rows: 3,
      columns: 3,
      validSquareGrid: true,
    });
  });

  it("marks a non-square hard-pixel calibration as unsupported", () => {
    const rectangularCells = makeHardPixelFixture({
      rows: 4,
      columns: 3,
      cellWidth: 16,
      cellHeight: 12,
    });

    const suggestion = suggestGrid(rectangularCells, "hard-pixel");

    expect(suggestion.validSquareGrid).toBe(false);
  });

  it("keeps a white numbered bead occupied and flags an overlay obstruction", () => {
    const source = makeNumberedGridFixture({
      rows: 4,
      columns: 5,
      watermarkCells: [7],
      whiteBeadCells: [1],
    });

    const result = recognizeBeadPattern(
      requestFor(source, "numbered-grid", 4, 5, 0),
    );

    expect(result.cells[0]).toEqual({ kind: "empty" });
    expect(result.cells[1]?.kind).toBe("color");
    const whiteCell = result.cells[1];
    expect(
      whiteCell?.kind === "color"
        ? result.palette[whiteCell.paletteIndex]
        : null,
    ).toEqual([255, 255, 255]);
    expect(result.confidenceIssues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          cellIndex: 7,
          reasons: expect.arrayContaining(["overlay-obstruction"]),
        }),
      ]),
    );
  });

  it("samples the robust inner color of a hard-pixel chart", () => {
    const source = makeHardPixelFixture({
      rows: 3,
      columns: 4,
      scale: 16,
    });

    const result = recognizeBeadPattern(
      requestFor(source, "hard-pixel", 3, 4, 0),
    );

    expect(result.cells[0]).toEqual({ kind: "empty" });
    expect(result.palette).toEqual(
      expect.arrayContaining([
        [40, 120, 220],
        [245, 185, 30],
        [220, 45, 55],
      ]),
    );
  });

  it("samples ring annuli and preserves a transparent support cell", () => {
    const source = makeRingFixture({
      rows: 3,
      columns: 3,
      supportCellIndex: 2,
    });

    const result = recognizeBeadPattern(
      requestFor(source, "ring-preview", 3, 3, 0, 2),
    );

    expect(result.cells[0]).toEqual({ kind: "empty" });
    expect(result.cells[2]).toEqual({ kind: "transparent-support" });
    expect(result.palette).not.toContainEqual([205, 226, 228]);
    expect(result.cells[1]?.kind).toBe("color");
  });
});
