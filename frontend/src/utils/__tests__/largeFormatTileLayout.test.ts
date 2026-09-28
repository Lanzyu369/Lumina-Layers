import { describe, expect, it } from "vitest";
import {
  buildLargeFormatTileOverlayGeometry,
  formatLargeFormatTileLabel,
  MAX_TILE_OVERLAY_CUTS_PER_AXIS,
  MAX_TILE_OVERLAY_LABELS,
  resolveLargeFormatTileGrid,
} from "../largeFormatTileLayout";

const SCENE_BOUNDS = { minX: -50, maxX: 50, minY: -30, maxY: 30 };

describe("resolveLargeFormatTileGrid", () => {
  it("matches the backend ceil-based split and keeps the remainder in the last tile", () => {
    expect(resolveLargeFormatTileGrid(600, 400, 250, 250)).toEqual({
      cols: 3,
      rows: 2,
      total: 6,
      lastColumnWidthMm: 100,
      lastRowHeightMm: 150,
    });
  });

  it("returns a single full tile when the artwork fits inside one tile", () => {
    expect(resolveLargeFormatTileGrid(120, 80, 250, 250)).toEqual({
      cols: 1,
      rows: 1,
      total: 1,
      lastColumnWidthMm: 120,
      lastRowHeightMm: 80,
    });
  });

  it("does not add an empty column when the width divides evenly", () => {
    const grid = resolveLargeFormatTileGrid(500, 250, 250, 250);
    expect(grid?.cols).toBe(2);
    expect(grid?.rows).toBe(1);
    expect(grid?.lastColumnWidthMm).toBe(250);
  });

  it.each([
    [0, 100, 250, 250],
    [100, Number.NaN, 250, 250],
    [100, 100, -1, 250],
    [100, 100, 250, Number.POSITIVE_INFINITY],
  ])("rejects invalid dimensions %#", (w, h, tw, th) => {
    expect(resolveLargeFormatTileGrid(w, h, tw, th)).toBeNull();
  });
});

describe("formatLargeFormatTileLabel", () => {
  it("uses the same R{row}C{col} suffix as exported 3MF files", () => {
    expect(formatLargeFormatTileLabel(1, 1)).toBe("R1C1");
    expect(formatLargeFormatTileLabel(2, 3)).toBe("R2C3");
  });
});

describe("buildLargeFormatTileOverlayGeometry", () => {
  it("places R1C1 at the top-left of the artwork and cuts at tile boundaries", () => {
    // 600 x 400 mm artwork, 250 mm tiles -> 3 x 2 grid.
    const geometry = buildLargeFormatTileOverlayGeometry(SCENE_BOUNDS, 600, 400, 250, 250);
    expect(geometry).not.toBeNull();

    // Border (4 segments) + 2 vertical cuts + 1 horizontal cut.
    expect(geometry!.segments).toHaveLength((4 + 2 + 1) * 2);

    // Vertical cut at 250 mm of 600 mm -> 250/600 of the 100-unit width.
    const firstVertical = geometry!.segments[8];
    expect(firstVertical[0]).toBeCloseTo(-50 + (250 / 600) * 100);
    expect(geometry!.segments[9][0]).toBeCloseTo(firstVertical[0]);

    // Horizontal cut 250 mm down from the image top (maxY).
    const horizontal = geometry!.segments[12];
    expect(horizontal[1]).toBeCloseTo(30 - (250 / 400) * 60);

    const labels = geometry!.labels.map((anchor) => anchor.label);
    expect(labels).toEqual(["R1C1", "R1C2", "R1C3", "R2C1", "R2C2", "R2C3"]);

    const r1c1 = geometry!.labels[0];
    expect(r1c1.x).toBeLessThan(0);
    expect(r1c1.y).toBeGreaterThan(0);
    const r2c3 = geometry!.labels[5];
    // Last column spans 500..600 mm, last row spans 250..400 mm.
    expect(r2c3.x).toBeCloseTo(-50 + (550 / 600) * 100);
    expect(r2c3.y).toBeCloseTo(30 - (325 / 400) * 60);
  });

  it("draws only the border for a single-tile artwork", () => {
    const geometry = buildLargeFormatTileOverlayGeometry(SCENE_BOUNDS, 100, 60, 250, 250);
    expect(geometry!.segments).toHaveLength(8);
    expect(geometry!.labels).toEqual([{ label: "R1C1", x: 0, y: 0 }]);
  });

  it("drops labels once the grid is too dense to read", () => {
    const perAxis = Math.ceil(Math.sqrt(MAX_TILE_OVERLAY_LABELS)) + 1;
    const geometry = buildLargeFormatTileOverlayGeometry(
      SCENE_BOUNDS,
      perAxis * 50,
      perAxis * 50,
      50,
      50,
    );
    expect(geometry).not.toBeNull();
    expect(geometry!.labels).toEqual([]);
    expect(geometry!.segments.length).toBeGreaterThan(8);
  });

  it("skips the overlay when the grid would be too dense to draw", () => {
    const tooWide = (MAX_TILE_OVERLAY_CUTS_PER_AXIS + 2) * 50;
    expect(
      buildLargeFormatTileOverlayGeometry(SCENE_BOUNDS, tooWide, 100, 50, 50),
    ).toBeNull();
  });

  it("returns null for empty scene bounds", () => {
    expect(
      buildLargeFormatTileOverlayGeometry(
        { minX: 0, maxX: 0, minY: 0, maxY: 10 },
        600,
        400,
        250,
        250,
      ),
    ).toBeNull();
  });
});
