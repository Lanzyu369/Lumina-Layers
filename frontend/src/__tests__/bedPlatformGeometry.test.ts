import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import {
  BED_SURFACE_MATERIAL_INDEX,
  createBedPlatformMesh,
  createFallbackBedGeometry,
  prepareNativeBedGeometry,
} from "../components/bedPlatformGeometry";
import { disposeMeshResources } from "../utils/threeDisposal";

function nativePlate(indexed: boolean, vertical: boolean = false): THREE.BufferGeometry {
  const box = new THREE.BoxGeometry(256, 256, 0.6);
  const source = indexed ? box : box.toNonIndexed();
  if (vertical) source.rotateX(Math.PI / 2);
  const geometry = prepareNativeBedGeometry(source, 256, 256);
  source.dispose();
  if (source !== box) box.dispose();
  return geometry;
}

describe("build plate surface materials", () => {
  it.each([
    ["indexed native plate", () => nativePlate(true)],
    ["non-indexed STL plate", () => nativePlate(false)],
    ["reoriented native plate", () => nativePlate(false, true)],
    ["fallback plate", () => createFallbackBedGeometry(256, 256)],
  ] as const)("shows artwork only from above on a %s", (_name, createGeometry) => {
    const geometry = createGeometry();
    const mesh = createBedPlatformMesh(geometry);
    const artwork = new THREE.Texture();
    mesh.material[BED_SURFACE_MATERIAL_INDEX].map = artwork;
    geometry.computeBoundingBox();
    const middleZ = (geometry.boundingBox!.min.z + geometry.boundingBox!.max.z) / 2;
    const visibleMaterials = (origin: THREE.Vector3, direction: THREE.Vector3) => {
      const hits = new THREE.Raycaster(origin, direction).intersectObject(mesh);
      expect(hits.length).toBeGreaterThan(0);
      return hits.map((hit) => mesh.material[hit.face!.materialIndex]);
    };

    const fromAbove = visibleMaterials(new THREE.Vector3(17, 23, 100), new THREE.Vector3(0, 0, -1));
    expect(fromAbove[0].map).toBe(artwork);

    const fromBelow = visibleMaterials(new THREE.Vector3(17, 23, -100), new THREE.Vector3(0, 0, 1));
    expect(fromBelow.every((material) => material.map === null)).toBe(true);

    const fromSide = visibleMaterials(new THREE.Vector3(500, 23, middleZ), new THREE.Vector3(-1, 0, 0));
    expect(fromSide.every((material) => material.map === null)).toBe(true);
    disposeMeshResources(mesh);
  });

  it("does not expose reversed artwork through a native plate without an underside", () => {
    const source = new THREE.PlaneGeometry(256, 256);
    const mesh = createBedPlatformMesh(prepareNativeBedGeometry(source, 256, 256));
    const hits = new THREE.Raycaster(new THREE.Vector3(17, 23, -100), new THREE.Vector3(0, 0, 1))
      .intersectObject(mesh);
    expect(hits).toHaveLength(0);
    source.dispose();
    disposeMeshResources(mesh);
  });

  it("releases both materials and the surface texture when the bed is removed", () => {
    const mesh = createBedPlatformMesh(createFallbackBedGeometry(256, 256));
    const texture = new THREE.Texture();
    mesh.material[BED_SURFACE_MATERIAL_INDEX].map = texture;
    const geometryDisposed = vi.fn();
    const textureDisposed = vi.fn();
    const materialsDisposed = mesh.material.map((material) => {
      const disposed = vi.fn();
      material.addEventListener("dispose", disposed);
      return disposed;
    });
    mesh.geometry.addEventListener("dispose", geometryDisposed);
    texture.addEventListener("dispose", textureDisposed);

    disposeMeshResources(mesh);

    expect(geometryDisposed).toHaveBeenCalledOnce();
    expect(textureDisposed).toHaveBeenCalledOnce();
    for (const disposed of materialsDisposed) expect(disposed).toHaveBeenCalledOnce();
  });
});
