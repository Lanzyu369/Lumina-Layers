import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import * as THREE from "three";
import {
  dilateGrid,
  createRingMask,
  greedyRectMerge,
  extrudeRectangles,
  offsetContour,
} from "../components/OutlineFrame3D";

// ========== Generators ==========

function occupiedGridArb(): fc.Arbitrary<{
  grid: Uint8Array;
  gridW: number;
  gridH: number;
}> {
  return fc
    .record({
      gridW: fc.integer({ min: 5, max: 30 }),
      gridH: fc.integer({ min: 5, max: 30 }),
    })
    .chain(({ gridW, gridH }) =>
      fc
        .array(
          fc.record({
            x: fc.integer({ min: 1, max: gridW - 2 }),
            y: fc.integer({ min: 1, max: gridH - 2 }),
          }),
          { minLength: 3, maxLength: Math.min(50, gridW * gridH) },
        )
        .map((cells) => {
          const grid = new Uint8Array(gridW * gridH);
          for (const { x, y } of cells) {
            grid[y * gridW + x] = 1;
          }
          return { grid, gridW, gridH };
        }),
    );
}

const iterationsArb = fc.integer({ min: 1, max: 5 });

const outlineWidthArb = fc.double({
  min: 0.5, max: 10, noNaN: true, noDefaultInfinity: true,
});

const modelMaxZArb = fc.double({
  min: 0.1, max: 50, noNaN: true, noDefaultInfinity: true,
});

function convexPolygonArb(
  minVerts = 3, maxVerts = 20, minRadius = 1, maxRadius = 100,
): fc.Arbitrary<[number, number][]> {
  return fc
    .record({
      n: fc.integer({ min: minVerts, max: maxVerts }),
      cx: fc.double({ min: -50, max: 50, noNaN: true, noDefaultInfinity: true }),
      cy: fc.double({ min: -50, max: 50, noNaN: true, noDefaultInfinity: true }),
      radius: fc.double({ min: minRadius, max: maxRadius, noNaN: true, noDefaultInfinity: true }),
    })
    .map(({ n, cx, cy, radius }) => {
      const step = (2 * Math.PI) / n;
      const contour: [number, number][] = [];
      for (let i = 0; i < n; i++) {
        const angle = -i * step;
        contour.push([cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)]);
      }
      return contour;
    });
}

function bbox2D(contour: [number, number][]): {
  minX: number; maxX: number; minY: number; maxY: number;
} {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [x, y] of contour) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  return { minX, maxX, minY, maxY };
}

// ========== Property-Based Tests ==========

describe("OutlineFrame3D — Property-Based Tests", () => {
  /**
   * Property 1: 有效输入产生有效几何体
   * **Validates: Requirements 1.1**
   */
  it("Property 1: dilate+ring+merge+extrude pipeline produces valid geometry", () => {
    fc.assert(
      fc.property(occupiedGridArb(), iterationsArb, modelMaxZArb, ({ grid, gridW, gridH }, iterations, height) => {
        const pad = iterations + 1;
        const paddedW = gridW + 2 * pad;
        const paddedH = gridH + 2 * pad;
        const paddedGrid = new Uint8Array(paddedW * paddedH);
        for (let y = 0; y < gridH; y++) {
          for (let x = 0; x < gridW; x++) {
            if (grid[y * gridW + x] === 1) {
              paddedGrid[(y + pad) * paddedW + (x + pad)] = 1;
            }
          }
        }

        const dilated = dilateGrid(paddedGrid, paddedW, paddedH, iterations);
        const ring = createRingMask(dilated, paddedGrid, paddedW, paddedH);
        const rects = greedyRectMerge(ring, paddedW, paddedH);

        let ringCount = 0;
        for (let i = 0; i < ring.length; i++) if (ring[i] === 1) ringCount++;
        expect(ringCount).toBeGreaterThan(0);
        expect(rects.length).toBeGreaterThan(0);

        const geo = extrudeRectangles(rects, 0, 0, 1, height, pad);
        expect(geo).not.toBeNull();
        expect(geo).toBeInstanceOf(THREE.BufferGeometry);
        expect(geo!.getAttribute("position").count).toBeGreaterThan(0);
        expect(geo!.getIndex()).not.toBeNull();
        expect(geo!.getIndex()!.count).toBeGreaterThan(0);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * Property 2: 膨胀后的网格严格包含原始网格
   * **Validates: Requirements 2.1, 4.1**
   */
  it("Property 2: dilated grid strictly contains original grid", () => {
    fc.assert(
      fc.property(occupiedGridArb(), iterationsArb, ({ grid, gridW, gridH }, iterations) => {
        const dilated = dilateGrid(grid, gridW, gridH, iterations);

        let origCount = 0;
        let dilatedCount = 0;
        for (let i = 0; i < gridW * gridH; i++) {
          if (grid[i] === 1) {
            origCount++;
            expect(dilated[i]).toBe(1);
          }
          if (dilated[i] === 1) dilatedCount++;
        }
        expect(dilatedCount).toBeGreaterThan(origCount);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * Property 3: Z 轴高度正确性
   * **Validates: Requirements 3.3, 4.2**
   */
  it("Property 3: extruded geometry Z range spans from 0 to modelMaxZ", () => {
    fc.assert(
      fc.property(modelMaxZArb, (modelMaxZ) => {
        const rects: [number, number, number, number][] = [[0, 0, 2, 2]];
        const geo = extrudeRectangles(rects, 0, 0, 1, modelMaxZ, 0);
        expect(geo).not.toBeNull();

        const posAttr = geo!.getAttribute("position");
        let minZ = Infinity, maxZ = -Infinity;
        for (let i = 0; i < posAttr.count; i++) {
          const z = posAttr.getZ(i);
          if (z < minZ) minZ = z;
          if (z > maxZ) maxZ = z;
        }
        expect(minZ).toBeCloseTo(0, 3);
        expect(maxZ).toBeCloseTo(modelMaxZ, 3);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * Property 2 (legacy): 偏移轮廓包含原始轮廓
   * **Validates: Requirements 2.1, 4.1**
   */
  it("Property 2 (legacy): offset contour bounding box expands in each direction", () => {
    fc.assert(
      fc.property(convexPolygonArb(), outlineWidthArb, (contour, offset) => {
        const outer = offsetContour(contour, offset);
        const innerBB = bbox2D(contour);
        const outerBB = bbox2D(outer);

        expect(outerBB.minX).toBeLessThan(innerBB.minX);
        expect(outerBB.maxX).toBeGreaterThan(innerBB.maxX);
        expect(outerBB.minY).toBeLessThan(innerBB.minY);
        expect(outerBB.maxY).toBeGreaterThan(innerBB.maxY);
      }),
      { numRuns: 100 },
    );
  });
});
