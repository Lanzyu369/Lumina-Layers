import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { mapHeightmapGrayscaleToHeights } from "./creativePreview3DUtils";

const MAX_HEIGHTMAP_GRID_EDGE = 160;
const MIN_RELIEF_SURFACE_HEIGHT_MM = 0.08;
const SURFACE_Z_EPSILON_MM = 0.003;

interface HeightmapBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

interface HeightmapSurfaceResources {
  mesh: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshStandardMaterial>;
  artworkTexture: THREE.Texture;
}

export interface HeightmapReliefSurface3DProps {
  enabled: boolean;
  heightmapUrl: string | null;
  artworkUrl: string | null;
  modelBounds: HeightmapBounds | null;
  spacerThickMm: number;
  maximumHeightMm: number;
}

function disposeSurfaceResources(resources: HeightmapSurfaceResources | null): void {
  if (!resources) return;
  resources.mesh.geometry.dispose();
  resources.mesh.material.dispose();
  resources.artworkTexture.dispose();
}

function textureImageSize(image: CanvasImageSource): { width: number; height: number } | null {
  const candidate = image as { width?: number; height?: number };
  const width = Number(candidate.width);
  const height = Number(candidate.height);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null;
  }
  return { width: Math.round(width), height: Math.round(height) };
}

function readLightweightGrayscale(image: CanvasImageSource): {
  grayscale: Uint8Array;
  width: number;
  height: number;
} | null {
  const sourceSize = textureImageSize(image);
  if (!sourceSize) return null;
  const scale = Math.min(1, MAX_HEIGHTMAP_GRID_EDGE / Math.max(sourceSize.width, sourceSize.height));
  const width = Math.max(2, Math.round(sourceSize.width * scale));
  const height = Math.max(2, Math.round(sourceSize.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return null;
  try {
    context.drawImage(image, 0, 0, width, height);
    const rgba = context.getImageData(0, 0, width, height).data;
    const grayscale = new Uint8Array(width * height);
    for (let index = 0; index < grayscale.length; index += 1) {
      grayscale[index] = rgba[index * 4] ?? 0;
    }
    return { grayscale, width, height };
  } catch {
    return null;
  }
}

function buildSurfaceResources({
  heightmapTexture,
  artworkTexture,
  modelBounds,
  spacerThickMm,
  maximumHeightMm,
}: {
  heightmapTexture: THREE.Texture;
  artworkTexture: THREE.Texture;
  modelBounds: HeightmapBounds;
  spacerThickMm: number;
  maximumHeightMm: number;
}): HeightmapSurfaceResources | null {
  const image = heightmapTexture.image as CanvasImageSource | undefined;
  if (!image) return null;
  const samples = readLightweightGrayscale(image);
  if (!samples) return null;

  const modelWidth = modelBounds.maxX - modelBounds.minX;
  const modelHeight = modelBounds.maxY - modelBounds.minY;
  if (!Number.isFinite(modelWidth) || !Number.isFinite(modelHeight) || modelWidth <= 0 || modelHeight <= 0) {
    return null;
  }

  const geometry = new THREE.PlaneGeometry(
    modelWidth,
    modelHeight,
    samples.width - 1,
    samples.height - 1,
  );
  const heights = mapHeightmapGrayscaleToHeights(
    samples.grayscale,
    MIN_RELIEF_SURFACE_HEIGHT_MM,
    maximumHeightMm,
  );
  const positions = geometry.getAttribute("position") as THREE.BufferAttribute;
  if (positions.count !== heights.length) {
    geometry.dispose();
    return null;
  }
  for (let index = 0; index < positions.count; index += 1) {
    positions.setZ(index, heights[index] ?? MIN_RELIEF_SURFACE_HEIGHT_MM);
  }
  positions.needsUpdate = true;
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();

  artworkTexture.colorSpace = THREE.SRGBColorSpace;
  artworkTexture.generateMipmaps = false;
  artworkTexture.minFilter = THREE.LinearFilter;
  artworkTexture.magFilter = THREE.LinearFilter;
  artworkTexture.wrapS = THREE.ClampToEdgeWrapping;
  artworkTexture.wrapT = THREE.ClampToEdgeWrapping;
  artworkTexture.needsUpdate = true;
  const material = new THREE.MeshStandardMaterial({
    map: artworkTexture,
    alphaTest: 0.04,
    side: THREE.DoubleSide,
    roughness: 0.72,
    metalness: 0,
    toneMapped: true,
    polygonOffset: true,
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = "heightmap_relief_surface";
  mesh.position.set(
    (modelBounds.minX + modelBounds.maxX) / 2,
    (modelBounds.minY + modelBounds.maxY) / 2,
    Math.max(0, spacerThickMm) + SURFACE_Z_EPSILON_MM,
  );
  mesh.renderOrder = 40;
  return { mesh, artworkTexture };
}

/** Render a bounded, downsampled heightmap surface over the lightweight GLB. */
export default function HeightmapReliefSurface3D({
  enabled,
  heightmapUrl,
  artworkUrl,
  modelBounds,
  spacerThickMm,
  maximumHeightMm,
}: HeightmapReliefSurface3DProps) {
  const [resources, setResources] = useState<HeightmapSurfaceResources | null>(null);
  const resourcesRef = useRef<HeightmapSurfaceResources | null>(null);

  useEffect(() => {
    disposeSurfaceResources(resourcesRef.current);
    resourcesRef.current = null;
    setResources(null);
    if (!enabled || !heightmapUrl || !artworkUrl || !modelBounds) return;

    let active = true;
    let failed = false;
    let heightmapTexture: THREE.Texture | null = null;
    let artworkTexture: THREE.Texture | null = null;
    const disposePending = () => {
      heightmapTexture?.dispose();
      artworkTexture?.dispose();
      heightmapTexture = null;
      artworkTexture = null;
    };
    const maybeCommit = () => {
      if (failed || !heightmapTexture || !artworkTexture) return;
      const next = buildSurfaceResources({
        heightmapTexture,
        artworkTexture,
        modelBounds,
        spacerThickMm,
        maximumHeightMm,
      });
      heightmapTexture.dispose();
      heightmapTexture = null;
      if (!active || !next) {
        artworkTexture.dispose();
        artworkTexture = null;
        return;
      }
      resourcesRef.current = next;
      artworkTexture = null;
      setResources(next);
    };
    const fail = () => {
      failed = true;
      disposePending();
      if (active) setResources(null);
    };

    const loader = new THREE.TextureLoader();
    loader.load(
      heightmapUrl,
      (texture) => {
        if (!active || failed) {
          texture.dispose();
          return;
        }
        heightmapTexture = texture;
        maybeCommit();
      },
      undefined,
      fail,
    );
    loader.load(
      artworkUrl,
      (texture) => {
        if (!active || failed) {
          texture.dispose();
          return;
        }
        artworkTexture = texture;
        maybeCommit();
      },
      undefined,
      fail,
    );

    return () => {
      active = false;
      disposePending();
      if (resourcesRef.current) {
        disposeSurfaceResources(resourcesRef.current);
        resourcesRef.current = null;
      }
    };
  }, [artworkUrl, enabled, heightmapUrl, maximumHeightMm, modelBounds, spacerThickMm]);

  return resources ? <primitive object={resources.mesh} /> : null;
}
