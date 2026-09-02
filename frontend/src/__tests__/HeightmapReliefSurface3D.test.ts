import { afterEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import {
  buildHeightmapSurfaceGeometry,
  sampleArtworkCells,
} from "../components/creativePreview3DUtils";

afterEach(() => vi.restoreAllMocks());

function zValuesAt(
  geometry: THREE.BufferGeometry,
  x: number,
  y: number,
): number[] {
  const positions = geometry.getAttribute("position") as THREE.BufferAttribute;
  const values: number[] = [];
  for (let index = 0; index < positions.count; index += 1) {
    if (
      Math.abs(positions.getX(index) - x) < 1e-6
      && Math.abs(positions.getY(index) - y) < 1e-6
    ) {
      values.push(positions.getZ(index));
    }
  }
  return [...new Set(values.map((value) => Number(value.toFixed(6))))].sort(
    (left, right) => left - right,
  );
}

function referencedBottomVertices(
  geometry: THREE.BufferGeometry,
  baseHeight: number,
): Array<{ index: number; x: number; y: number; u: number; v: number }> {
  const positions = geometry.getAttribute("position") as THREE.BufferAttribute;
  const uvs = geometry.getAttribute("uv") as THREE.BufferAttribute;
  const index = geometry.getIndex();
  if (!index) return [];

  const referenced = new Set(Array.from(index.array));
  return [...referenced]
    .filter((vertexIndex) => Math.abs(positions.getZ(vertexIndex) - baseHeight) < 1e-6)
    .map((vertexIndex) => ({
      index: vertexIndex,
      x: positions.getX(vertexIndex),
      y: positions.getY(vertexIndex),
      u: uvs.getX(vertexIndex),
      v: uvs.getY(vertexIndex),
    }));
}

function wallTriangles(geometry: THREE.BufferGeometry): Array<{
  points: [THREE.Vector3, THREE.Vector3, THREE.Vector3];
  normal: THREE.Vector3;
}> {
  const positions = geometry.getAttribute("position") as THREE.BufferAttribute;
  const index = geometry.getIndex();
  const wallGroup = geometry.groups.find((group) => group.materialIndex === 1);
  if (!index || !wallGroup) return [];

  const triangles = [];
  for (
    let offset = wallGroup.start;
    offset < wallGroup.start + wallGroup.count;
    offset += 3
  ) {
    const points = [0, 1, 2].map((corner) => {
      const vertexIndex = index.getX(offset + corner);
      return new THREE.Vector3(
        positions.getX(vertexIndex),
        positions.getY(vertexIndex),
        positions.getZ(vertexIndex),
      );
    }) as [THREE.Vector3, THREE.Vector3, THREE.Vector3];
    const normal = new THREE.Vector3()
      .subVectors(points[1], points[0])
      .cross(new THREE.Vector3().subVectors(points[2], points[0]))
      .normalize();
    triangles.push({ points, normal });
  }
  return triangles;
}

function expectClosedWallEdge({
  triangles,
  axis,
  value,
  baseHeight,
  expectedNormal,
}: {
  triangles: ReturnType<typeof wallTriangles>;
  axis: "x" | "y";
  value: number;
  baseHeight: number;
  expectedNormal: THREE.Vector3;
}): void {
  const faces = triangles.filter(({ points }) => points.every(
    (point) => Math.abs(point[axis] - value) < 1e-6,
  ));
  expect(faces).toHaveLength(2);
  const bottomPositions = new Set<string>();
  for (const face of faces) {
    expect(face.points.some((point) => Math.abs(point.z - baseHeight) < 1e-6)).toBe(true);
    expect(face.points.some((point) => point.z > baseHeight + 1e-6)).toBe(true);
    expect(face.normal.dot(expectedNormal)).toBeGreaterThan(0.999);
    for (const point of face.points) {
      if (Math.abs(point.z - baseHeight) < 1e-6) {
        bottomPositions.add(`${point.x.toFixed(6)},${point.y.toFixed(6)}`);
      }
    }
  }
  expect(bottomPositions.size).toBe(2);
}

describe("buildHeightmapSurfaceGeometry", () => {
  it("detects thin artwork coverage and keeps colour from its most opaque sample", () => {
    const rgba = new Uint8ClampedArray(8 * 4 * 4);
    const visiblePixelOffset = (1 * 8 + 2) * 4;
    rgba.set([214, 73, 41, 180], visiblePixelOffset);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockImplementation((() => ({
        drawImage: vi.fn(),
        getImageData: vi.fn(() => ({ data: rgba })),
      })) as unknown as typeof HTMLCanvasElement.prototype.getContext);

    const samples = sampleArtworkCells(
      {} as CanvasImageSource,
      2,
      1,
      11,
    );

    expect(samples?.solidMask).toEqual(new Uint8Array([1, 0]));
    expect(samples?.colorsSrgb).toEqual(new Uint8Array([214, 73, 41, 0, 0, 0]));
  });

  it("keeps image rows aligned with world-space top and bottom", () => {
    const geometry = buildHeightmapSurfaceGeometry({
      modelWidth: 4,
      modelHeight: 2,
      sampleWidth: 2,
      sampleHeight: 2,
      heights: new Float32Array([0.25, 4, 1.5, 3]),
      skirtBaseHeightMm: 0.08,
    });

    expect(zValuesAt(geometry, -2, 1)).toContain(0.25);
    expect(zValuesAt(geometry, 2, 1)).toContain(4);
    expect(zValuesAt(geometry, -2, -1)).toContain(1.5);
    expect(zValuesAt(geometry, 2, -1)).toContain(3);
    geometry.dispose();
  });

  it("closes every perimeter edge down to the lightweight relief base", () => {
    const geometry = buildHeightmapSurfaceGeometry({
      modelWidth: 4,
      modelHeight: 2,
      sampleWidth: 2,
      sampleHeight: 2,
      heights: new Float32Array([0.25, 4, 1.5, 3]),
      skirtBaseHeightMm: 0.08,
    });

    expect(zValuesAt(geometry, -2, 1)).toContain(0.08);
    expect(zValuesAt(geometry, 2, 1)).toContain(0.08);
    expect(zValuesAt(geometry, -2, -1)).toContain(0.08);
    expect(zValuesAt(geometry, 2, -1)).toContain(0.08);
    expect(geometry.getIndex()?.count).toBe(30);
    const referencedBottom = referencedBottomVertices(geometry, 0.08);
    for (const [x, y] of [[-2, 1], [2, 1], [-2, -1], [2, -1]]) {
      expect(referencedBottom.some((vertex) => (
        Math.abs(vertex.x - x) < 1e-6 && Math.abs(vertex.y - y) < 1e-6
      ))).toBe(true);
    }
    const triangles = wallTriangles(geometry);
    expect(triangles).toHaveLength(8);
    expectClosedWallEdge({
      triangles, axis: "y", value: 1, baseHeight: 0.08,
      expectedNormal: new THREE.Vector3(0, 1, 0),
    });
    expectClosedWallEdge({
      triangles, axis: "x", value: 2, baseHeight: 0.08,
      expectedNormal: new THREE.Vector3(1, 0, 0),
    });
    expectClosedWallEdge({
      triangles, axis: "y", value: -1, baseHeight: 0.08,
      expectedNormal: new THREE.Vector3(0, -1, 0),
    });
    expectClosedWallEdge({
      triangles, axis: "x", value: -2, baseHeight: 0.08,
      expectedNormal: new THREE.Vector3(-1, 0, 0),
    });
    geometry.computeBoundingBox();
    expect(geometry.boundingBox?.min.z).toBeCloseTo(0.08, 5);
    geometry.dispose();
  });

  it("closes the visible artwork footprint instead of its transparent canvas", () => {
    const cellColors = new Uint8Array(9 * 3);
    cellColors.set([255, 64, 0], 4 * 3);
    const geometry = buildHeightmapSurfaceGeometry({
      modelWidth: 3,
      modelHeight: 3,
      sampleWidth: 4,
      sampleHeight: 4,
      heights: new Float32Array(16).fill(1),
      skirtBaseHeightMm: 0.08,
      // Transparent outer ring with a single visible cell in the middle.
      solidCellMask: new Uint8Array([
        0, 0, 0,
        0, 255, 0,
        0, 0, 0,
      ]),
      solidCellColorsSrgb: cellColors,
    });

    // The full top grid stays available for high-resolution artwork alphaTest;
    // the coarse mask controls only the four side walls.
    expect(geometry.getIndex()?.count).toBe(9 * 6 + 4 * 6);
    expect(geometry.groups).toEqual([
      { start: 0, count: 9 * 6, materialIndex: 0 },
      { start: 9 * 6, count: 4 * 6, materialIndex: 1 },
    ]);
    const referencedBottom = referencedBottomVertices(geometry, 0.08);
    expect(referencedBottom).toHaveLength(8);
    for (const vertex of referencedBottom) {
      expect(Math.abs(vertex.x)).toBeCloseTo(0.5, 6);
      expect(Math.abs(vertex.y)).toBeCloseTo(0.5, 6);
      // Side colours sample the adjacent visible artwork cell.
      expect(vertex.u).toBeCloseTo(0.5, 6);
      expect(vertex.v).toBeCloseTo(0.5, 6);
    }
    const colors = geometry.getAttribute("color") as THREE.BufferAttribute | undefined;
    expect(colors).toBeDefined();
    for (const vertex of referencedBottom) {
      expect(colors?.getX(vertex.index)).toBeCloseTo(1, 6);
      expect(colors?.getY(vertex.index)).toBeCloseTo(0.051269, 5);
      expect(colors?.getZ(vertex.index)).toBeCloseTo(0, 6);
    }
    geometry.dispose();
  });

  it("adds inward-facing walls around transparent holes", () => {
    const geometry = buildHeightmapSurfaceGeometry({
      modelWidth: 3,
      modelHeight: 3,
      sampleWidth: 4,
      sampleHeight: 4,
      heights: new Float32Array(16).fill(1),
      skirtBaseHeightMm: 0.08,
      solidCellMask: new Uint8Array([
        1, 1, 1,
        1, 0, 1,
        1, 1, 1,
      ]),
    });

    expect(geometry.groups).toEqual([
      { start: 0, count: 9 * 6, materialIndex: 0 },
      { start: 9 * 6, count: (12 + 4) * 6, materialIndex: 1 },
    ]);
    const referencedBottom = referencedBottomVertices(geometry, 0.08);
    for (const [x, y] of [[-0.5, 0.5], [0.5, 0.5], [-0.5, -0.5], [0.5, -0.5]]) {
      expect(referencedBottom.some((vertex) => (
        Math.abs(vertex.x - x) < 1e-6 && Math.abs(vertex.y - y) < 1e-6
      ))).toBe(true);
    }
    const triangles = wallTriangles(geometry);
    expectClosedWallEdge({
      triangles, axis: "y", value: 0.5, baseHeight: 0.08,
      expectedNormal: new THREE.Vector3(0, -1, 0),
    });
    expectClosedWallEdge({
      triangles, axis: "x", value: 0.5, baseHeight: 0.08,
      expectedNormal: new THREE.Vector3(-1, 0, 0),
    });
    expectClosedWallEdge({
      triangles, axis: "y", value: -0.5, baseHeight: 0.08,
      expectedNormal: new THREE.Vector3(0, 1, 0),
    });
    expectClosedWallEdge({
      triangles, axis: "x", value: -0.5, baseHeight: 0.08,
      expectedNormal: new THREE.Vector3(1, 0, 0),
    });
    geometry.dispose();
  });
});
