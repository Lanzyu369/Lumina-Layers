import * as THREE from "three";
import { BED_OUTER_RADIUS_MM } from "./bedPlatformTexture";

const MIN_VISIBLE_BED_THICKNESS_MM = 3.2;
const FALLBACK_BED_THICKNESS_MM = 2.6;

export interface BedPreviewCameraPose {
  position: readonly [number, number, number];
  target: readonly [number, number, number];
  fitDistance: number;
}

interface NativeBedGeometryLoader {
  load: (
    url: string,
    onLoad: (geometry: THREE.BufferGeometry) => void,
    onProgress?: (event: ProgressEvent<EventTarget>) => void,
    onError?: (error: unknown) => void,
  ) => void;
  parse: (bytes: ArrayBuffer) => THREE.BufferGeometry;
}

interface LoadNativeBedGeometrySourceOptions {
  desktopModelReader?: (
    deviceProfileId: string,
  ) => Promise<ArrayBuffer | Uint8Array | null>;
  deviceProfileId: string;
  loader: NativeBedGeometryLoader;
  modelUrl: string;
}

function copyToArrayBuffer(bytes: ArrayBuffer | Uint8Array): ArrayBuffer {
  if (bytes instanceof ArrayBuffer) return bytes;
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

/** Load STL geometry through the guarded desktop bridge or the browser URL. */
export async function loadNativeBedGeometrySource({
  desktopModelReader,
  deviceProfileId,
  loader,
  modelUrl,
}: LoadNativeBedGeometrySourceOptions): Promise<THREE.BufferGeometry | null> {
  if (desktopModelReader) {
    const bytes = await desktopModelReader(deviceProfileId);
    return bytes ? loader.parse(copyToArrayBuffer(bytes)) : null;
  }
  return new Promise((resolve, reject) => {
    loader.load(modelUrl, resolve, undefined, reject);
  });
}

/** Frame an empty plate from a restrained oblique angle that reveals its rim. */
export function computeBedPreviewCameraPose(
  widthMm: number,
  heightMm: number,
  fovDeg: number,
): BedPreviewCameraPose {
  const radius = (Math.hypot(widthMm, heightMm) / 2) * 1.04;
  const halfFovRadians = (fovDeg * Math.PI) / 360;
  const fitDistance = (radius / Math.sin(halfFovRadians)) * 1.2;
  return {
    position: [0, -fitDistance * 0.42, fitDistance * 0.91],
    fitDistance,
  };
}

/** Create an irregular plate outline with a rear locator tab. */
function createIrregularBedShape(
  widthMm: number,
  heightMm: number,
  radius: number = BED_OUTER_RADIUS_MM,
): THREE.Shape {
  const halfWidth = widthMm / 2;
  const halfHeight = heightMm / 2;
  const cornerRadius = Math.min(radius, halfWidth, halfHeight);
  const halfTabWidth = Math.min(28, widthMm * 0.14);
  const tabDepth = Math.min(11, heightMm * 0.06);

  const shape = new THREE.Shape();
  shape.moveTo(-halfWidth + cornerRadius, -halfHeight);
  shape.lineTo(halfWidth - cornerRadius, -halfHeight);
  shape.quadraticCurveTo(
    halfWidth,
    -halfHeight,
    halfWidth,
    -halfHeight + cornerRadius,
  );
  shape.lineTo(halfWidth, halfHeight - cornerRadius);
  shape.quadraticCurveTo(
    halfWidth,
    halfHeight,
    halfWidth - cornerRadius,
    halfHeight,
  );
  shape.lineTo(halfTabWidth, halfHeight);
  shape.lineTo(halfTabWidth, halfHeight + tabDepth - 2);
  shape.quadraticCurveTo(
    halfTabWidth,
    halfHeight + tabDepth,
    halfTabWidth - 2,
    halfHeight + tabDepth,
  );
  shape.lineTo(-halfTabWidth + 2, halfHeight + tabDepth);
  shape.quadraticCurveTo(
    -halfTabWidth,
    halfHeight + tabDepth,
    -halfTabWidth,
    halfHeight + tabDepth - 2,
  );
  shape.lineTo(-halfTabWidth, halfHeight);
  shape.lineTo(-halfWidth + cornerRadius, halfHeight);
  shape.quadraticCurveTo(
    -halfWidth,
    halfHeight,
    -halfWidth,
    halfHeight - cornerRadius,
  );
  shape.lineTo(-halfWidth, -halfHeight + cornerRadius);
  shape.quadraticCurveTo(
    -halfWidth,
    -halfHeight,
    -halfWidth + cornerRadius,
    -halfHeight,
  );

  return shape;
}

function centerGeometryAndMapTopUv(
  geometry: THREE.BufferGeometry,
  printableWidthMm: number,
  printableHeightMm: number,
): THREE.BufferGeometry {
  geometry.computeBoundingBox();
  let bounds = geometry.boundingBox;
  if (!bounds) return geometry;

  const size = new THREE.Vector3();
  bounds.getSize(size);
  if (size.x <= 0 || size.y <= 0) return geometry;

  const resolvePrintableCenter = (
    minimum: number,
    maximum: number,
    printableSize: number,
  ): number => {
    const halfSize = printableSize / 2;
    const tolerance = Math.max(0.5, printableSize * 0.01);
    const contains = (start: number, end: number) =>
      minimum <= start + tolerance && maximum >= end - tolerance;
    const containsCenteredArea = contains(-halfSize, halfSize);
    const containsPositiveArea = contains(0, printableSize);
    if (containsCenteredArea !== containsPositiveArea) {
      return containsCenteredArea ? 0 : halfSize;
    }
    return (minimum + maximum) / 2;
  };
  const printableCenterX = resolvePrintableCenter(
    bounds.min.x,
    bounds.max.x,
    printableWidthMm,
  );
  const printableCenterY = resolvePrintableCenter(
    bounds.min.y,
    bounds.max.y,
    printableHeightMm,
  );
  geometry.translate(
    -printableCenterX,
    -printableCenterY,
    -bounds.max.z,
  );
  geometry.computeBoundingBox();
  bounds = geometry.boundingBox;
  if (!bounds) return geometry;

  const position = geometry.getAttribute("position");
  const uv = new Float32Array(position.count * 2);
  const width = Math.max(Number.EPSILON, printableWidthMm);
  const height = Math.max(Number.EPSILON, printableHeightMm);
  for (let index = 0; index < position.count; index += 1) {
    uv[index * 2] = position.getX(index) / width + 0.5;
    uv[index * 2 + 1] = position.getY(index) / height + 0.5;
  }
  geometry.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  geometry.computeVertexNormals();
  return geometry;
}

/** Prepare a native slicer STL for Lumina's centered, top-facing scene. */
export function prepareNativeBedGeometry(
  source: THREE.BufferGeometry,
  printableWidthMm: number,
  printableHeightMm: number,
): THREE.BufferGeometry {
  const geometry = source.clone();
  geometry.computeBoundingBox();
  const initialBounds = geometry.boundingBox;
  if (!initialBounds) return geometry;

  const initialSize = new THREE.Vector3();
  initialBounds.getSize(initialSize);
  if (initialSize.x < initialSize.y && initialSize.x < initialSize.z) {
    geometry.rotateY(Math.PI / 2);
  } else if (initialSize.y < initialSize.x && initialSize.y < initialSize.z) {
    geometry.rotateX(Math.PI / 2);
  }

  geometry.computeBoundingBox();
  const orientedBounds = geometry.boundingBox;
  if (!orientedBounds) return geometry;
  const orientedSize = new THREE.Vector3();
  orientedBounds.getSize(orientedSize);
  if (
    orientedSize.z > Number.EPSILON &&
    orientedSize.z < MIN_VISIBLE_BED_THICKNESS_MM
  ) {
    geometry.scale(1, 1, MIN_VISIBLE_BED_THICKNESS_MM / orientedSize.z);
  }

  return centerGeometryAndMapTopUv(
    geometry,
    printableWidthMm,
    printableHeightMm,
  );
}

/** Create a dimensional irregular fallback when a registry STL is unavailable. */
export function createFallbackBedGeometry(
  widthMm: number,
  heightMm: number,
): THREE.BufferGeometry {
  const body = createIrregularBedShape(widthMm, heightMm);
  const geometry = new THREE.ExtrudeGeometry(body, {
    depth: FALLBACK_BED_THICKNESS_MM,
    bevelEnabled: true,
    bevelSegments: 2,
    bevelSize: 0.55,
    bevelThickness: 0.35,
    curveSegments: 16,
    steps: 1,
  });
  return centerGeometryAndMapTopUv(geometry, widthMm, heightMm);
}
