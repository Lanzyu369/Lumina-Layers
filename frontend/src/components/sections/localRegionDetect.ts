import type { PreviewCanvasBuffer } from '../ui/previewHoverInspectorUtils';
import { mapPixelToBufferCoordinate } from '../ui/previewHoverInspectorUtils';

/**
 * Client-side connected-component detection for instant click selection.
 * 前端本地连通块检测，用于点击瞬间立即给出精确选区。
 *
 * The backend ``/region-detect`` runs an authoritative connected-components
 * pass on ``matched_rgb``. For instant feedback we reproduce the exact same
 * result in the browser: flood-fill (4-connectivity, strict same-colour) from
 * the clicked pixel over the *un-highlighted* preview buffer, then trace the
 * component's pixel-grid boundary into world coordinates. Because the buffer
 * is the rendered ``matched_rgb`` before any highlight blend, the colour match
 * is identical to the backend's, so the optimistic outline is *accurate* — not
 * the "every same-coloured pixel across the canvas" approximation.
 * 后端 region-detect 在 matched_rgb 上跑权威连通块。为了即时反馈，我们在浏览器
 * 里复现同样的结果：以点击像素为种子做 4 连通严格同色 flood-fill，再把该连通块
 * 的像素网格边界转换为世界坐标轮廓。由于 buffer 是未高亮的 matched_rgb 渲染图，
 * 颜色判定与后端一致，因此乐观轮廓是**精确**的，而不是"全图同色"的近似。
 */

export interface LocalRegionResult {
  /** Bounding-box aligned world-space contour polygons (mm, y-up). */
  polygons: number[][][];
  /** Buffer-space pixel count of the component. */
  pixelCount: number;
  /** Buffer-space bounding box [x, y, w, h]. */
  bbox: [number, number, number, number];
  /** Exact component membership for optimistic union operations. */
  mask: Uint8Array;
  /** Seed colour sampled from the unhighlighted preview. */
  colorHex: string;
  /** Buffer-space seed coordinate. */
  anchor: [number, number];
}

interface FloodFillOptions {
  pixelX: number;
  pixelY: number;
  naturalWidth: number;
  naturalHeight: number;
  /** Physical preview width in mm used to map pixels → world coordinates. */
  previewWidthMm: number;
}

/**
 * Detect the connected component under the clicked pixel using a local
 * flood-fill, and return its boundary as world-space polygons.
 * 用本地 flood-fill 检测点击像素所在连通块，返回其世界坐标边界轮廓。
 *
 * Returns ``null`` when the buffer is unavailable, the click is out of range,
 * or the clicked pixel is transparent (background).
 * buffer 不可用、点击越界或点击在透明背景上时返回 ``null``。
 */
export function detectLocalRegionContours(
  previewBuffer: PreviewCanvasBuffer | null,
  options: FloodFillOptions,
  cachedImage?: ImageData,
): LocalRegionResult | null {
  if (!previewBuffer) return null;
  const { width, height, context } = previewBuffer;
  if (width <= 0 || height <= 0) return null;

  const { pixelX, pixelY, naturalWidth, naturalHeight, previewWidthMm } = options;
  const bx = mapPixelToBufferCoordinate(pixelX, naturalWidth, width);
  const by = mapPixelToBufferCoordinate(pixelY, naturalHeight, height);
  if (bx < 0 || by < 0 || bx >= width || by >= height) return null;

  let image: ImageData;
  try {
    image = cachedImage ?? context.getImageData(0, 0, width, height);
  } catch {
    return null;
  }
  const data = image.data;
  if (!data || data.length < width * height * 4) return null;

  const seedIndex = (by * width + bx) * 4;
  const seedAlpha = data[seedIndex + 3];
  if (seedAlpha === undefined || seedAlpha <= 8) return null; // transparent background
  const seedR = data[seedIndex];
  const seedG = data[seedIndex + 1];
  const seedB = data[seedIndex + 2];
  if (seedR === undefined || seedG === undefined || seedB === undefined) return null;

  // 4-connectivity BFS over strict same-colour, opaque pixels.
  // 4 连通 BFS：严格同色且不透明的像素。
  const visited = new Uint8Array(width * height);
  const stack = new Int32Array(width * height);
  let stackSize = 0;
  const seedPixel = by * width + bx;
  visited[seedPixel] = 1;
  stack[stackSize++] = seedPixel;

  let pixelCount = 0;
  let minX = bx;
  let maxX = bx;
  let minY = by;
  let maxY = by;

  while (stackSize > 0) {
    const current = stack[--stackSize];
    const cx = current % width;
    const cy = (current / width) | 0;
    pixelCount += 1;
    if (cx < minX) minX = cx;
    if (cx > maxX) maxX = cx;
    if (cy < minY) minY = cy;
    if (cy > maxY) maxY = cy;

    // neighbours: left, right, up, down
    // 邻居：左、右、上、下
    if (cx > 0) stackSize = pushNeighbour(current - 1);
    if (cx < width - 1) stackSize = pushNeighbour(current + 1);
    if (cy > 0) stackSize = pushNeighbour(current - width);
    if (cy < height - 1) stackSize = pushNeighbour(current + width);
  }

  function pushNeighbour(pixel: number): number {
    if (visited[pixel]) return stackSize;
    const offset = pixel * 4;
    if (
      data[offset + 3] > 8 &&
      data[offset] === seedR &&
      data[offset + 1] === seedG &&
      data[offset + 2] === seedB
    ) {
      visited[pixel] = 1;
      stack[stackSize] = pixel;
      return stackSize + 1;
    }
    return stackSize;
  }

  if (pixelCount === 0) return null;

  // Trace the pixel-grid boundary of the component (edges touching
  // background / outside), simplified to collinear-reduced polygons.
  // 沿像素网格追踪连通块边界（与背景/外部相邻的边），并做共线化简。
  const polygons = traceBoundaryPolygons(
    visited,
    width,
    height,
    minX,
    minY,
    maxX,
    maxY,
    previewWidthMm,
  );
  if (polygons.length === 0) return null;

  return {
    polygons,
    pixelCount,
    bbox: [minX, minY, maxX - minX + 1, maxY - minY + 1],
    mask: visited,
    colorHex: [seedR, seedG, seedB]
      .map((value) => value.toString(16).padStart(2, '0'))
      .join(''),
    anchor: [bx, by],
  };
}

export function traceBoundaryPolygons(
  filled: Uint8Array,
  width: number,
  height: number,
  minX: number,
  minY: number,
  maxX: number,
  maxY: number,
  previewWidthMm: number,
): number[][][] {
  const pixelScale = previewWidthMm / width;
  const boxWidth = maxX - minX + 1;
  const boxHeight = maxY - minY + 1;

  const isFilled = (x: number, y: number): boolean => {
    if (x < 0 || y < 0 || x >= width || y >= height) return false;
    return filled[y * width + x] === 1;
  };

  // Build directed edges around filled pixels (clockwise), keyed by start
  // point so we can chain them into loops. Points are in local box coords.
  // 围绕填充像素构建有向边（顺时针），按起点索引以便串成环。点为局部包围盒坐标。
  const edges = new Map<string, Array<[number, number]>>();
  const addEdge = (x1: number, y1: number, x2: number, y2: number) => {
    const key = `${x1},${y1}`;
    let list = edges.get(key);
    if (!list) {
      list = [];
      edges.set(key, list);
    }
    list.push([x2, y2]);
  };

  for (let y = minY; y <= maxY; y += 1) {
    for (let x = minX; x <= maxX; x += 1) {
      if (!isFilled(x, y)) continue;
      const lx = x - minX;
      const ly = y - minY;
      // top edge
      if (!isFilled(x, y - 1)) addEdge(lx, ly, lx + 1, ly);
      // right edge
      if (!isFilled(x + 1, y)) addEdge(lx + 1, ly, lx + 1, ly + 1);
      // bottom edge
      if (!isFilled(x, y + 1)) addEdge(lx + 1, ly + 1, lx, ly + 1);
      // left edge
      if (!isFilled(x - 1, y)) addEdge(lx, ly + 1, lx, ly);
    }
  }

  const loops: Array<Array<[number, number]>> = [];
  const guardLimit = boxWidth * boxHeight * 8 + 16;
  while (edges.size > 0) {
    const startKey = edges.keys().next().value as string;
    const [sx, sy] = startKey.split(',').map(Number);
    const start: [number, number] = [sx, sy];
    const loop: Array<[number, number]> = [start];
    let current = start;
    let guard = 0;
    for (;;) {
      const nextList = edges.get(`${current[0]},${current[1]}`);
      if (!nextList || nextList.length === 0) break;
      const next = nextList.pop() as [number, number];
      if (nextList.length === 0) edges.delete(`${current[0]},${current[1]}`);
      current = next;
      guard += 1;
      if (current[0] === start[0] && current[1] === start[1]) break;
      loop.push(current);
      if (guard > guardLimit) break;
    }
    const simplified = simplifyCollinear(loop);
    if (simplified.length >= 3) loops.push(simplified);
  }

  // Local box coords → world mm, y flipped.
  // 局部包围盒坐标 → 世界 mm，y 翻转。
  return loops.map((loop) =>
    loop.map(([lx, ly]) => [
      (minX + lx) * pixelScale,
      previewWidthMm * (height / width) - (minY + ly) * pixelScale,
    ]),
  );
}

function simplifyCollinear(
  loop: Array<[number, number]>,
): Array<[number, number]> {
  if (loop.length < 3) return loop;
  const dedup: Array<[number, number]> = [];
  for (const point of loop) {
    const last = dedup[dedup.length - 1];
    if (last && last[0] === point[0] && last[1] === point[1]) continue;
    dedup.push(point);
  }
  let changed = true;
  let points = dedup;
  while (changed && points.length >= 3) {
    changed = false;
    const next: Array<[number, number]> = [];
    const count = points.length;
    for (let i = 0; i < count; i += 1) {
      const prev = points[(i - 1 + count) % count];
      const curr = points[i];
      const following = points[(i + 1) % count];
      if (areCollinear(prev, curr, following)) {
        changed = true;
        continue;
      }
      next.push(curr);
    }
    points = next;
  }
  return points;
}

function areCollinear(
  a: [number, number],
  b: [number, number],
  c: [number, number],
): boolean {
  return (
    (b[0] - a[0]) * (c[1] - b[1]) === (b[1] - a[1]) * (c[0] - b[0])
  );
}
