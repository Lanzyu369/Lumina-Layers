import { describe, expect, it, vi } from 'vitest';

import {
  detectLocalRegionContours,
} from '../components/sections/localRegionDetect';

function makeBuffer(colors: number[][][]) {
  const height = colors.length;
  const width = colors[0].length;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const [r, g, b, a = 255] = colors[y][x];
      const offset = (y * width + x) * 4;
      data.set([r, g, b, a], offset);
    }
  }
  return {
    width,
    height,
    context: {
      getImageData: vi.fn(() => ({ data })),
    } as unknown as CanvasRenderingContext2D,
  };
}

describe('localRegionDetect', () => {
  it('returns the exact four-connected component for immediate display', () => {
    const buffer = makeBuffer([
      [[255, 0, 0], [255, 0, 0], [0, 0, 255]],
      [[255, 0, 0], [255, 0, 0], [0, 0, 255]],
      [[0, 0, 0], [0, 0, 0], [255, 0, 0]],
    ]);

    const result = detectLocalRegionContours(buffer, {
      pixelX: 0,
      pixelY: 0,
      naturalWidth: 3,
      naturalHeight: 3,
      previewWidthMm: 3,
    });

    expect(result).not.toBeNull();
    expect(result?.pixelCount).toBe(4);
    expect(result?.colorHex).toBe('ff0000');
    expect(Array.from(result?.mask ?? [])).toEqual([
      1, 1, 0,
      1, 1, 0,
      0, 0, 0,
    ]);
    expect(result?.polygons).toHaveLength(1);
  });
});
