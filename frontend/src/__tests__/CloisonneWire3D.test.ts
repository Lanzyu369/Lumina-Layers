import { StrictMode, createElement } from "react";
import { act, render } from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import * as THREE from "three";
import {
  default as CloisonneWire3D,
  WIRE_COLOR,
  WIRE_METALNESS,
  WIRE_ROUGHNESS,
  detectColorEdges,
  rasterizeColorMeshesToGrid,
  resetCloisonneWireGeometryDisposeForTests,
  selectVisibleCloisonneColorMeshes,
} from "../components/CloisonneWire3D";
import { materializePositionAttributeForGeometryBake } from "../utils/threeQuantizedGeometry";

// ========== Helpers ==========

/**
 * Create a flat rectangular mesh with a top face at z=topZ and bottom at z=0.
 * Used to simulate a ColorMesh from a GLB model.
 * 创建一个顶面在 z=topZ、底面在 z=0 的矩形网格，模拟 GLB 模型中的 ColorMesh。
 */
function createRectMesh(
  x: number, y: number, w: number, h: number, topZ: number = 1.0,
): THREE.Mesh {
  const positions = new Float32Array([
    // Bottom face (z = 0)
    x,     y,     0,
    x + w, y,     0,
    x + w, y + h, 0,
    x,     y + h, 0,
    // Top face (z = topZ)
    x,     y,     topZ,
    x + w, y,     topZ,
    x + w, y + h, topZ,
    x,     y + h, topZ,
  ]);
  const indices = new Uint16Array([
    0, 2, 1,  0, 3, 2,
    4, 5, 6,  4, 6, 7,
    0, 1, 5,  0, 5, 4,
    2, 3, 7,  2, 7, 6,
    0, 4, 7,  0, 7, 3,
    1, 2, 6,  1, 6, 5,
  ]);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  return new THREE.Mesh(geometry);
}

function createBakedQuantizedRectMesh(
  x: number,
  y: number,
  w: number,
  h: number,
  topZ: number = 1.0,
): THREE.Mesh {
  const max = 65535;
  const positions = new Uint16Array([
    0, 0, 0,
    max, 0, 0,
    max, max, 0,
    0, max, 0,
    0, 0, max,
    max, 0, max,
    max, max, max,
    0, max, max,
  ]);
  const indices = new Uint16Array([
    0, 2, 1,  0, 3, 2,
    4, 5, 6,  4, 6, 7,
    0, 1, 5,  0, 5, 4,
    2, 3, 7,  2, 7, 6,
    0, 4, 7,  0, 7, 3,
    1, 2, 6,  1, 6, 5,
  ]);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3, true));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  const mesh = new THREE.Mesh(geometry);
  mesh.position.set(x, y, 0);
  mesh.scale.set(w, h, topZ);
  mesh.updateWorldMatrix(true, false);
  materializePositionAttributeForGeometryBake(geometry);
  geometry.applyMatrix4(mesh.matrixWorld);
  mesh.position.set(0, 0, 0);
  mesh.scale.set(1, 1, 1);
  mesh.updateMatrixWorld(true);
  return mesh;
}

function createBackingPlateMesh(): THREE.Mesh {
  return new THREE.Mesh(new THREE.BoxGeometry(8, 4, 1));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  resetCloisonneWireGeometryDisposeForTests();
});

// ========== Unit Tests ==========

describe("CloisonneWire3D — Unit Tests", () => {
  describe("geometry lifecycle", () => {
    it("does not dispose the active geometry during StrictMode mount replay", () => {
      vi.useFakeTimers();
      const colorMeshes = [
        createRectMesh(0, 0, 4, 4),
        createRectMesh(4, 0, 4, 4),
      ];
      const backingPlateMesh = createBackingPlateMesh();
      const disposeSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
      const { unmount } = render(
        createElement(
          StrictMode,
          null,
          createElement(CloisonneWire3D, {
            enabled: true,
            wireWidthMm: 1,
            wireHeightMm: 0.6,
            colorMeshes,
            backingPlateMesh,
            spacerThick: 1.2,
          }),
        ),
      );

      act(() => {
        vi.runAllTimers();
      });

      expect(disposeSpy).not.toHaveBeenCalled();

      unmount();
      act(() => {
        vi.runAllTimers();
      });
    });

    it("disposes replaced geometry only after the deferred timer flushes", () => {
      vi.useFakeTimers();
      const colorMeshes = [
        createRectMesh(0, 0, 4, 4),
        createRectMesh(4, 0, 4, 4),
      ];
      const backingPlateMesh = createBackingPlateMesh();
      const disposeSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
      const { rerender, unmount } = render(
        createElement(CloisonneWire3D, {
          enabled: true,
          wireWidthMm: 1,
          wireHeightMm: 0.6,
          colorMeshes,
          backingPlateMesh,
          spacerThick: 1.2,
        }),
      );

      rerender(
        createElement(CloisonneWire3D, {
          enabled: true,
          wireWidthMm: 2,
          wireHeightMm: 0.6,
          colorMeshes,
          backingPlateMesh,
          spacerThick: 1.2,
        }),
      );

      expect(disposeSpy).not.toHaveBeenCalled();

      act(() => {
        vi.runAllTimers();
      });

      expect(disposeSpy).toHaveBeenCalledTimes(1);

      unmount();
      act(() => {
        vi.runAllTimers();
      });
    });
  });

  // ---- Gold color constant ----

  describe("gold color constant", () => {
    it("WIRE_COLOR equals 0xDAA520 (#DAA520)", () => {
      expect(WIRE_COLOR).toBe(0xdaa520);
    });

    it("WIRE_COLOR converts to correct RGB components", () => {
      const r = (WIRE_COLOR >> 16) & 0xff;
      const g = (WIRE_COLOR >> 8) & 0xff;
      const b = WIRE_COLOR & 0xff;
      expect(r).toBe(0xda); // 218
      expect(g).toBe(0xa5); // 165
      expect(b).toBe(0x20); // 32
    });
  });

  // ---- MeshStandardMaterial configuration ----

  describe("MeshStandardMaterial configuration", () => {
    it("WIRE_METALNESS equals 0.6", () => {
      expect(WIRE_METALNESS).toBe(0.6);
    });

    it("WIRE_ROUGHNESS equals 0.3", () => {
      expect(WIRE_ROUGHNESS).toBe(0.3);
    });
  });

  // ---- Empty colorMeshes returns null ----

  describe("empty colorMeshes", () => {
    it("rasterizeColorMeshesToGrid with empty array returns all -1 grid", () => {
      const gridW = 5, gridH = 5;
      const grid = rasterizeColorMeshesToGrid([], 1.0, 0, 0, gridW, gridH);
      // All pixels should be -1 (no meshes to rasterize)
      for (let i = 0; i < grid.length; i++) {
        expect(grid[i]).toBe(-1);
      }
    });

    it("detectColorEdges on all-empty grid returns all-zero edge mask", () => {
      const gridW = 5, gridH = 5;
      const colorGrid = new Int16Array(gridW * gridH);
      colorGrid.fill(-1);
      const edges = detectColorEdges(colorGrid, gridW, gridH);
      for (let i = 0; i < edges.length; i++) {
        expect(edges[i]).toBe(0);
      }
    });
  });

  describe("material archive layer filtering", () => {
    it("uses only the visible top material layer for cloisonne boundaries", () => {
      const top = createRectMesh(0, 0, 4, 4);
      top.name = "color_ff0000_m000_l000";
      const hidden = createRectMesh(4, 0, 4, 4);
      hidden.name = "color_0000ff_m001_l001";
      const selected = selectVisibleCloisonneColorMeshes([top, hidden]);
      expect(selected).toEqual([top]);
    });

    it("keeps legacy color meshes unchanged", () => {
      const red = createRectMesh(0, 0, 4, 4);
      red.name = "color_ff0000";
      const blue = createRectMesh(4, 0, 4, 4);
      blue.name = "color_0000ff";
      const meshes = [red, blue];
      expect(selectVisibleCloisonneColorMeshes(meshes)).toBe(meshes);
    });
  });

  // ---- Single-color model (no edges) returns null ----

  describe("single-color model (no edges)", () => {
    it("detectColorEdges on uniform color grid produces zero edges", () => {
      // A 5x5 grid entirely filled with color index 0
      const gridW = 5, gridH = 5;
      const colorGrid = new Int16Array(gridW * gridH);
      colorGrid.fill(0);
      const edges = detectColorEdges(colorGrid, gridW, gridH);

      // With the updated logic, out-of-bounds and -1 neighbors don't trigger edges.
      // A uniform grid has no different solid neighbors → zero edges everywhere.
      for (let y = 0; y < gridH; y++) {
        for (let x = 0; x < gridW; x++) {
          expect(edges[y * gridW + x]).toBe(0);
        }
      }
    });

    it("single mesh rasterized produces uniform color grid with zero edges", () => {
      // Create a single mesh covering a 4x4 area
      const mesh = createRectMesh(0, 0, 4, 4);
      const cellSize = 1.0;
      const gridW = 4, gridH = 4;
      const grid = rasterizeColorMeshesToGrid([mesh], cellSize, 0, 0, gridW, gridH);

      // All covered pixels should have color index 0
      const coveredPixels = Array.from(grid).filter((v) => v >= 0);
      const uniqueColors = new Set(coveredPixels);
      expect(uniqueColors.size).toBeLessThanOrEqual(1);

      // With updated edge detection, single-color model produces zero edges
      // (out-of-bounds and -1 neighbors don't trigger edges)
      const edges = detectColorEdges(grid, gridW, gridH);
      for (let i = 0; i < edges.length; i++) {
        expect(edges[i]).toBe(0);
      }
    });

    it("rasterizes baked quantized GLB color meshes using millimetre coordinates", () => {
      const mesh = createBakedQuantizedRectMesh(2, 3, 4, 2, 0.4);
      mesh.name = "color_ff0000_chunk001";
      const posAttr = mesh.geometry.getAttribute("position") as THREE.BufferAttribute;
      expect(posAttr.array).toBeInstanceOf(Float32Array);
      expect(posAttr.normalized).toBe(false);

      const grid = rasterizeColorMeshesToGrid([mesh], 1.0, 2, 3, 4, 2);

      const coveredPixels = Array.from(grid).filter((value) => value >= 0);
      expect(coveredPixels.length).toBeGreaterThan(0);
      expect(new Set(coveredPixels)).toEqual(new Set([0]));
      const edges = detectColorEdges(grid, 4, 2);
      for (let i = 0; i < edges.length; i++) {
        expect(edges[i]).toBe(0);
      }
    });

    it("chunked meshes with the same color name do not create false internal edges", () => {
      const leftChunk = createRectMesh(0, 0, 2, 2);
      leftChunk.name = "color_ff0000_chunk001";
      const rightChunk = createRectMesh(2, 0, 2, 2);
      rightChunk.name = "color_ff0000_chunk002";

      const grid = rasterizeColorMeshesToGrid(
        [leftChunk, rightChunk],
        1.0,
        0,
        0,
        4,
        2,
      );

      const coveredColors = new Set(Array.from(grid).filter((value) => value >= 0));
      expect(coveredColors.size).toBe(1);

      const edges = detectColorEdges(grid, 4, 2);
      for (let i = 0; i < edges.length; i++) {
        expect(edges[i]).toBe(0);
      }
    });
  });
});
