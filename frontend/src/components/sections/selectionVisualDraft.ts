import type { SelectionDocument, SelectionMutationInput } from '../../stores/converter/types';
import type { PreviewCanvasBuffer } from '../ui/previewHoverInspectorUtils';
import { detectLocalRegionContours, traceBoundaryPolygons } from './localRegionDetect';

type OutlineTarget = { hex: string; polygons: number[][][] };
type CompactRegion = {
  bbox: [number, number, number, number];
  mask: Uint8Array;
  hex: string;
  polygons: number[][][];
  contourWidth: number;
  bytes: number;
};
type BufferCache = {
  image: ImageData;
  regions: CompactRegion[];
  regionBytes: number;
  baseline?: { document: SelectionDocument; contourWidth: number; mask: Uint8Array };
};

const bufferCaches = new WeakMap<PreviewCanvasBuffer, BufferCache>();
const MAX_CACHED_REGIONS = 32;
const MAX_REGION_CACHE_BYTES = 16 * 1024 * 1024;

function getBufferCache(buffer: PreviewCanvasBuffer): BufferCache | null {
  const existing = bufferCaches.get(buffer);
  if (existing) return existing;
  try {
    const image = buffer.context.getImageData(0, 0, buffer.width, buffer.height);
    if (image.data.length < buffer.width * buffer.height * 4) return null;
    const cache: BufferCache = { image, regions: [], regionBytes: 0 };
    bufferCaches.set(buffer, cache);
    return cache;
  } catch {
    return null;
  }
}

/** Restore only a display mask from exact pixel-edge contours, including holes. */
function rasterizeContours(
  contours: number[][][], width: number, height: number, contourWidth: number,
): Uint8Array {
  const mask = new Uint8Array(width * height);
  const intersections: number[][] = Array.from({ length: height }, () => []);
  const scale = width / contourWidth;
  for (const polygon of contours) {
    if (polygon.length < 3) continue;
    for (let index = 0; index < polygon.length; index += 1) {
      const a = polygon[index];
      const b = polygon[(index + 1) % polygon.length];
      const ax = a[0] * scale;
      const ay = height - a[1] * scale;
      const bx = b[0] * scale;
      const by = height - b[1] * scale;
      if (![ax, ay, bx, by].every(Number.isFinite) || ay === by) continue;
      const start = Math.max(0, Math.ceil(Math.min(ay, by) - 0.5));
      const end = Math.min(height, Math.ceil(Math.max(ay, by) - 0.5));
      for (let y = start; y < end; y += 1) {
        intersections[y].push(ax + ((y + 0.5 - ay) * (bx - ax)) / (by - ay));
      }
    }
  }
  for (let y = 0; y < height; y += 1) {
    const row = intersections[y].sort((a, b) => a - b);
    for (let index = 0; index + 1 < row.length; index += 2) {
      const start = Math.max(0, Math.ceil(row[index] - 0.5));
      const end = Math.min(width, Math.ceil(row[index + 1] - 0.5));
      if (start < end) mask.fill(1, y * width + start, y * width + end);
    }
  }
  return mask;
}

function localRegion(
  buffer: PreviewCanvasBuffer, cache: BufferCache, x: number, y: number, contourWidth: number,
): CompactRegion | null {
  const index = cache.regions.findIndex(({ bbox: [left, top, width, height], mask }) =>
    x >= left && y >= top && x < left + width && y < top + height
      && mask[(y - top) * width + x - left] === 1,
  );
  if (index >= 0) {
    const [region] = cache.regions.splice(index, 1);
    cache.regions.push(region);
    return region;
  }
  const detected = detectLocalRegionContours(buffer, {
    pixelX: x, pixelY: y, naturalWidth: buffer.width, naturalHeight: buffer.height,
    previewWidthMm: contourWidth,
  }, cache.image);
  if (!detected) return null;
  const [left, top, width, height] = detected.bbox;
  const mask = new Uint8Array(width * height);
  for (let row = 0; row < height; row += 1) {
    const start = (top + row) * buffer.width + left;
    mask.set(detected.mask.subarray(start, start + width), row * width);
  }
  const region: CompactRegion = {
    bbox: detected.bbox, mask, hex: detected.colorHex, polygons: detected.polygons,
    contourWidth,
    bytes: mask.byteLength + detected.polygons.reduce((sum, polygon) => sum + polygon.length * 32 + 24, 0),
  };
  if (region.bytes <= MAX_REGION_CACHE_BYTES) {
    while (cache.regions.length >= MAX_CACHED_REGIONS
      || cache.regionBytes + region.bytes > MAX_REGION_CACHE_BYTES) {
      cache.regionBytes -= cache.regions.shift()!.bytes;
    }
    cache.regions.push(region);
    cache.regionBytes += region.bytes;
  }
  return region;
}

function normalizedHex(value: string | undefined): string | null {
  const hex = value?.replace(/^#/, '').toLowerCase();
  return hex && /^[0-9a-f]{6}$/.test(hex) ? hex : null;
}

function pointFromInput(input: SelectionMutationInput, width: number, height: number): [number, number] | null {
  const { x, y } = input;
  return x !== undefined && y !== undefined && Number.isInteger(x) && Number.isInteger(y)
    && x >= 0 && y >= 0 && x < width && y < height ? [x, y] : null;
}

/** Replay pending gestures for display only. Confirmed documents and history stay untouched. */
export function buildSelectionVisualDraft({ document, mutations, previewBuffer, previewWidthMm }: {
  document: SelectionDocument | null;
  mutations: readonly SelectionMutationInput[];
  previewBuffer: PreviewCanvasBuffer | null;
  previewWidthMm: number;
}): OutlineTarget[] | null {
  if (mutations.length === 0) return null;
  // A replacement/clear selection supersedes earlier pending gesture geometry.
  let start = 0;
  for (let index = 0; index < mutations.length; index += 1) {
    const mutation = mutations[index];
    if (mutation.operation === 'clear'
      || (mutation.operation === 'colors-set' && mutation.colorHexes !== undefined
        && mutation.colorHexes.every((color) => normalizedHex(color) !== null))) start = index;
  }
  const remaining = mutations.slice(start);
  const unsupportedIndex = remaining.findIndex(({ operation }) => ![
    'point-toggle', 'point-remove', 'same-color-toggle', 'same-color-remove', 'clear', 'colors-set',
  ].includes(operation));
  // Keep the predictable prefix visible while a later gesture needs the
  // server. Falling back here would undo an already displayed clear or click.
  const pending = unsupportedIndex < 0 ? remaining : remaining.slice(0, unsupportedIndex);
  if (pending.length === 0) return null;
  if (pending.every(({ operation }) => operation === 'clear')) return [];
  const knownEmptyPrefix = pending[0].operation === 'clear'
    || (pending[0].operation === 'colors-set' && pending[0].colorHexes?.length === 0);
  if (!previewBuffer || previewBuffer.width <= 0 || previewBuffer.height <= 0
    || !Number.isFinite(previewWidthMm) || previewWidthMm <= 0) return knownEmptyPrefix ? [] : null;
  const cache = getBufferCache(previewBuffer);
  if (!cache) return knownEmptyPrefix ? [] : null;
  const { width, height } = previewBuffer;
  const startsEmpty = pending[0].operation === 'clear' || pending[0].operation === 'colors-set';
  if (!startsEmpty && document && document.selected_pixel_count > 0 && document.contours.length === 0) return null;
  let mask: Uint8Array;
  if (document && !startsEmpty) {
    if (cache.baseline?.document !== document || cache.baseline.contourWidth !== previewWidthMm) {
      cache.baseline = {
        document, contourWidth: previewWidthMm,
        mask: rasterizeContours(document.contours, width, height, previewWidthMm),
      };
    }
    mask = cache.baseline.mask.slice();
  } else {
    mask = new Uint8Array(width * height);
  }
  let hex = normalizedHex(document?.selected_color_hexes.at(-1)) ?? 'ffffff';
  let targets: OutlineTarget[] = !startsEmpty && document?.contours.length
    ? [{ hex, polygons: document.contours }] : [];
  let needsTrace = false;
  let processed = 0;
  const finishProjection = (): OutlineTarget[] | null => {
    if (processed === 0) return null;
    if (!needsTrace) return targets;
    const polygons = traceBoundaryPolygons(mask, width, height, 0, 0, width - 1, height - 1, previewWidthMm);
    return polygons.length > 0 ? [{ hex, polygons }] : [];
  };

  for (const input of pending) {
    if (input.operation === 'clear') {
      mask.fill(0);
      targets = [];
      needsTrace = false;
      processed += 1;
      continue;
    }
    if (input.operation === 'point-toggle' || input.operation === 'point-remove') {
      const point = pointFromInput(input, width, height);
      if (!point) return finishProjection();
      const region = localRegion(previewBuffer, cache, point[0], point[1], previewWidthMm);
      if (!region) return finishProjection();
      const [left, top, regionWidth, regionHeight] = region.bbox;
      let allSelected = true;
      for (let y = 0; y < regionHeight && allSelected; y += 1) {
        for (let x = 0; x < regionWidth; x += 1) {
          if (region.mask[y * regionWidth + x] && !mask[(top + y) * width + left + x]) {
            allSelected = false;
            break;
          }
        }
      }
      const selected = input.operation === 'point-remove' || allSelected ? 0 : 1;
      for (let y = 0; y < regionHeight; y += 1) {
        for (let x = 0; x < regionWidth; x += 1) {
          if (region.mask[y * regionWidth + x]) mask[(top + y) * width + left + x] = selected;
        }
      }
      hex = region.hex;
      if (!selected) needsTrace = true;
      else if (!needsTrace) {
        const ratio = previewWidthMm / region.contourWidth;
        targets.push({ hex, polygons: ratio === 1 ? region.polygons
          : region.polygons.map((polygon) => polygon.map(([x, y]) => [x * ratio, y * ratio])) });
      }
      processed += 1;
      continue;
    }

    const colors = new Set<string>();
    if (input.operation === 'colors-set') {
      if (input.colorHexes === undefined) return finishProjection();
      for (const color of input.colorHexes) {
        const value = normalizedHex(color);
        if (!value) return finishProjection();
        colors.add(value);
      }
      mask.fill(0);
    } else {
      let color = normalizedHex(input.colorHex);
      if (!color) {
        const point = pointFromInput(input, width, height);
        if (!point) return finishProjection();
        const offset = (point[1] * width + point[0]) * 4;
        if (cache.image.data[offset + 3] <= 8) return finishProjection();
        color = Array.from(cache.image.data.subarray(offset, offset + 3))
          .map((value) => value.toString(16).padStart(2, '0')).join('');
      }
      colors.add(color);
    }
    const codes = new Set(Array.from(colors, (color) => parseInt(color, 16)));
    const data = cache.image.data;
    const matches = (pixel: number) => {
      const offset = pixel * 4;
      return data[offset + 3] > 8
        && codes.has((data[offset] << 16) | (data[offset + 1] << 8) | data[offset + 2]);
    };
    let allSelected = true;
    for (let pixel = 0; pixel < mask.length && allSelected; pixel += 1) {
      if (matches(pixel) && !mask[pixel]) allSelected = false;
    }
    const selected = input.operation === 'same-color-remove'
      || (input.operation === 'same-color-toggle' && allSelected) ? 0 : 1;
    for (let pixel = 0; pixel < mask.length; pixel += 1) {
      if (matches(pixel)) mask[pixel] = selected;
    }
    hex = Array.from(colors).at(-1) ?? hex;
    needsTrace = true;
    processed += 1;
  }
  return finishProjection();
}
