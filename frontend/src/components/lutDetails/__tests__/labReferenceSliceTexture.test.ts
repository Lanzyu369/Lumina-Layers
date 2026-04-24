import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";

import { REFERENCE_SLICE_TEXTURE_RESOLUTION } from "../labPointCloud3DConfig";
import {
  getOrCreateReferenceSliceData,
  getReferenceSliceKey,
  getReferenceSliceWindowLightnesses,
  trimReferenceSliceCache,
  upsertReferenceSliceTexture,
} from "../labReferenceSliceTexture";

describe("labReferenceSliceTexture", () => {
  it("reuses cached slice data for repeated lightness requests and trims far-away layers", () => {
    const cache = new Map<number, Uint8Array>();
    const buildData = vi.fn((lightness: number) => new Uint8Array([Math.round(lightness * 10)]));

    const first = getOrCreateReferenceSliceData(cache, 60, buildData);
    const second = getOrCreateReferenceSliceData(cache, 60, buildData);

    expect(second).toBe(first);
    expect(buildData).toHaveBeenCalledTimes(1);

    for (const lightness of getReferenceSliceWindowLightnesses(60)) {
      getOrCreateReferenceSliceData(cache, lightness, buildData);
    }
    trimReferenceSliceCache(cache, 60);
    expect(cache.size).toBe(33);

    for (const lightness of getReferenceSliceWindowLightnesses(80)) {
      getOrCreateReferenceSliceData(cache, lightness, buildData);
    }
    trimReferenceSliceCache(cache, 80);
    expect(cache.has(getReferenceSliceKey(60))).toBe(false);
  });

  it("reuses the same DataTexture instance and swaps in the new slice data", () => {
    const firstData = new Uint8Array(REFERENCE_SLICE_TEXTURE_RESOLUTION * REFERENCE_SLICE_TEXTURE_RESOLUTION * 4);
    const secondData = new Uint8Array(REFERENCE_SLICE_TEXTURE_RESOLUTION * REFERENCE_SLICE_TEXTURE_RESOLUTION * 4);

    const texture = upsertReferenceSliceTexture(null, firstData);
    const initialVersion = texture.version;
    const updated = upsertReferenceSliceTexture(texture, secondData);

    expect(texture).toBeInstanceOf(THREE.DataTexture);
    expect(updated).toBe(texture);
    expect(updated.image.data).toBe(secondData);
    expect(updated.image.width).toBe(REFERENCE_SLICE_TEXTURE_RESOLUTION);
    expect(updated.image.height).toBe(REFERENCE_SLICE_TEXTURE_RESOLUTION);
    expect(updated.version).toBeGreaterThan(initialVersion);

    updated.dispose();
  });
});
