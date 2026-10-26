import * as THREE from "three";

import { REFERENCE_SLICE_TEXTURE_RESOLUTION } from "./labPointCloud3DConfig";
import { sampleReferenceSliceColor } from "./labReferenceSlice";

const REFERENCE_A_MIN = -120;
const REFERENCE_A_MAX = 120;
const REFERENCE_B_MIN = -120;
const REFERENCE_B_MAX = 120;
const REFERENCE_L_MIN = 0;
const REFERENCE_L_MAX = 100;
const REFERENCE_SLICE_LIGHTNESS_STEP = 0.5;
const REFERENCE_SLICE_CACHE_RADIUS = 16;
const REFERENCE_SLICE_CACHE_LIMIT = (REFERENCE_SLICE_CACHE_RADIUS * 2) + 1;

export type ReferenceSliceDataCache = Map<number, Uint8Array>;

function clampReferenceLightness(value: number): number {
  return Math.min(REFERENCE_L_MAX, Math.max(REFERENCE_L_MIN, value));
}

export function getReferenceSliceKey(lightness: number): number {
  return Math.round(clampReferenceLightness(lightness) / REFERENCE_SLICE_LIGHTNESS_STEP);
}

function lightnessFromKey(key: number): number {
  return Number((key * REFERENCE_SLICE_LIGHTNESS_STEP).toFixed(1));
}

export function buildReferenceSliceData(lightness: number): Uint8Array {
  const width = REFERENCE_SLICE_TEXTURE_RESOLUTION;
  const height = REFERENCE_SLICE_TEXTURE_RESOLUTION;
  const data = new Uint8Array(width * height * 4);
  const spanX = REFERENCE_A_MAX - REFERENCE_A_MIN;
  const spanZ = REFERENCE_B_MAX - REFERENCE_B_MIN;

  for (let row = 0; row < height; row += 1) {
    const b = REFERENCE_B_MAX - ((row / (height - 1)) * spanZ);
    for (let column = 0; column < width; column += 1) {
      const a = REFERENCE_A_MIN + ((column / (width - 1)) * spanX);
      const offset = ((row * width) + column) * 4;
      const sample = sampleReferenceSliceColor(lightness, a, b);
      data[offset] = sample.rgb[0];
      data[offset + 1] = sample.rgb[1];
      data[offset + 2] = sample.rgb[2];
      data[offset + 3] = sample.alpha;
    }
  }

  return data;
}

export function getOrCreateReferenceSliceData(
  cache: ReferenceSliceDataCache,
  lightness: number,
  buildData: (lightness: number) => Uint8Array = buildReferenceSliceData,
): Uint8Array {
  const key = getReferenceSliceKey(lightness);
  const cached = cache.get(key);
  if (cached) {
    return cached;
  }

  const data = buildData(lightnessFromKey(key));
  cache.set(key, data);
  return data;
}

export function getReferenceSliceWindowLightnesses(lightness: number): number[] {
  const centerKey = getReferenceSliceKey(lightness);
  const values = [lightnessFromKey(centerKey)];

  for (let offset = 1; offset <= REFERENCE_SLICE_CACHE_RADIUS; offset += 1) {
    const positiveKey = centerKey + offset;
    const negativeKey = centerKey - offset;

    if (positiveKey * REFERENCE_SLICE_LIGHTNESS_STEP <= REFERENCE_L_MAX) {
      values.push(lightnessFromKey(positiveKey));
    }
    if (negativeKey * REFERENCE_SLICE_LIGHTNESS_STEP >= REFERENCE_L_MIN) {
      values.push(lightnessFromKey(negativeKey));
    }
  }

  return values;
}

export function trimReferenceSliceCache(
  cache: ReferenceSliceDataCache,
  centerLightness: number,
): void {
  if (cache.size <= REFERENCE_SLICE_CACHE_LIMIT) {
    return;
  }

  const centerKey = getReferenceSliceKey(centerLightness);
  const keysToKeep = new Set(
    [...cache.keys()]
      .sort((left, right) => Math.abs(left - centerKey) - Math.abs(right - centerKey))
      .slice(0, REFERENCE_SLICE_CACHE_LIMIT),
  );

  for (const key of [...cache.keys()]) {
    if (!keysToKeep.has(key)) {
      cache.delete(key);
    }
  }
}

export function upsertReferenceSliceTexture(
  current: THREE.DataTexture | null,
  data: Uint8Array,
): THREE.DataTexture {
  if (!current) {
    const texture = new THREE.DataTexture(
      data,
      REFERENCE_SLICE_TEXTURE_RESOLUTION,
      REFERENCE_SLICE_TEXTURE_RESOLUTION,
      THREE.RGBAFormat,
    );
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.magFilter = THREE.LinearFilter;
    texture.minFilter = THREE.LinearFilter;
    texture.generateMipmaps = false;
    texture.needsUpdate = true;
    texture.flipY = false;
    return texture;
  }

  current.image.data = data;
  current.image.width = REFERENCE_SLICE_TEXTURE_RESOLUTION;
  current.image.height = REFERENCE_SLICE_TEXTURE_RESOLUTION;
  current.needsUpdate = true;
  return current;
}
