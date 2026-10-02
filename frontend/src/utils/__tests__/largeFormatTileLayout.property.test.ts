import { describe, expect, it } from "vitest";
import fc from "fast-check";
import {
  buildLargeFormatTileOverlayGeometry,
  resolveLargeFormatTileGrid,
} from "../largeFormatTileLayout";

const EPSILON = 1e-6;

const dimensionsArb = fc.record({
  totalWidthMm: fc.double({ min: 10, max: 3000, noNaN: true }),
  totalHeightMm: fc.double({ min: 10, max: 3000, noNaN: true }),
  tileWidthMm: fc.double({ min: 50, max: 500, noNaN: true }),
  tileHeightMm: fc.double({ min: 50, max: 500, noNaN: true }),
});

const boundsArb = fc
  .record({
    minX: fc.double({ min: -500, max: 500, noNaN: true }),
    minY: fc.double({ min: -500, max: 500, noNaN: true }),
    width: fc.double({ min: 1, max: 1000, noNaN: true }),
    height: fc.double({ min: 1, max: 1000, noNaN: true }),
  })
  .map(({ minX, minY, width, height }) => ({
    minX,
    maxX: minX + width,
    minY,
    maxY: minY + height,
  }));

describe("large-format tile layout properties", () => {
  it("covers the artwork exactly: full tiles plus a positive remainder", () => {
    fc.assert(
      fc.property(dimensionsArb, (d) => {
        const grid = resolveLargeFormatTileGrid(
          d.totalWidthMm,
          d.totalHeightMm,
          d.tileWidthMm,
          d.tileHeightMm,
        );
        expect(grid).not.toBeNull();
        expect(grid!.lastColumnWidthMm).toBeGreaterThan(0);
        expect(grid!.lastColumnWidthMm).toBeLessThanOrEqual(d.tileWidthMm + EPSILON);
        expect(grid!.lastRowHeightMm).toBeGreaterThan(0);
        expect(grid!.lastRowHeightMm).toBeLessThanOrEqual(d.tileHeightMm + EPSILON);
        expect(
          (grid!.cols - 1) * d.tileWidthMm + grid!.lastColumnWidthMm,
        ).toBeCloseTo(d.totalWidthMm);
        expect(grid!.total).toBe(grid!.cols * grid!.rows);
      }),
    );
  });

  it("keeps every outline point inside the scene bounds with one cut per boundary", () => {
    fc.assert(
      fc.property(dimensionsArb, boundsArb, (d, bounds) => {
        const grid = resolveLargeFormatTileGrid(
          d.totalWidthMm,
          d.totalHeightMm,
          d.tileWidthMm,
          d.tileHeightMm,
        )!;
        const geometry = buildLargeFormatTileOverlayGeometry(
          bounds,
          d.totalWidthMm,
          d.totalHeightMm,
          d.tileWidthMm,
          d.tileHeightMm,
        );
        expect(geometry).not.toBeNull();
        expect(geometry!.segments).toHaveLength(
          2 * (4 + (grid.cols - 1) + (grid.rows - 1)),
        );
        const tolX = EPSILON * Math.max(1, Math.abs(bounds.maxX));
        const tolY = EPSILON * Math.max(1, Math.abs(bounds.maxY));
        for (const [x, y] of [
          ...geometry!.segments,
          ...geometry!.labels.map((a) => [a.x, a.y] as [number, number]),
        ]) {
          expect(x).toBeGreaterThanOrEqual(bounds.minX - tolX);
          expect(x).toBeLessThanOrEqual(bounds.maxX + tolX);
          expect(y).toBeGreaterThanOrEqual(bounds.minY - tolY);
          expect(y).toBeLessThanOrEqual(bounds.maxY + tolY);
        }
        if (geometry!.labels.length > 0) {
          expect(geometry!.labels).toHaveLength(grid.total);
          expect(new Set(geometry!.labels.map((a) => a.label)).size).toBe(grid.total);
        }
      }),
    );
  });
});
