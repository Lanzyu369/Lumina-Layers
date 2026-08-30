import * as THREE from "three";

export interface CoatingPreviewLayer {
  zMin: number;
  zMax: number;
}

export interface ArtworkCellSamples {
  solidMask: Uint8Array;
  colorsSrgb: Uint8Array;
}

const ARTWORK_MASK_SUPERSAMPLE = 4;

function finiteNonNegative(value: number, fallback = 0): number {
  return Number.isFinite(value) ? Math.max(0, value) : fallback;
}

function roundMillimetres(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}

function roundHalfToEven(value: number): number {
  const lower = Math.floor(value);
  const fraction = value - lower;
  if (Math.abs(fraction - 0.5) <= 1e-9) {
    return lower % 2 === 0 ? lower : lower + 1;
  }
  return Math.round(value);
}

/** Match Python's print-layer quantization for a positive coating request. */
export function quantizeCoatingHeightMm(
  coatingHeightMm: number,
  layerHeightMm: number,
): number {
  const requested = finiteNonNegative(coatingHeightMm);
  if (requested <= 0) return 0;
  const layerHeight = Number.isFinite(layerHeightMm) && layerHeightMm > 0
    ? layerHeightMm
    : 0.08;
  const layerCount = Math.max(1, roundHalfToEven(requested / layerHeight));
  return roundMillimetres(layerCount * layerHeight);
}

/** Map lightweight grayscale samples to the same physical height range as print. */
export function mapHeightmapGrayscaleToHeights(
  grayscale: Uint8Array,
  minimumHeightMm: number,
  maximumHeightMm: number,
): Float32Array {
  const minimum = finiteNonNegative(minimumHeightMm);
  const maximum = Math.max(minimum, finiteNonNegative(maximumHeightMm, minimum));
  const span = maximum - minimum;
  const heights = new Float32Array(grayscale.length);
  for (let index = 0; index < grayscale.length; index += 1) {
    heights[index] = minimum + ((grayscale[index] ?? 0) / 255) * span;
  }
  return heights;
}

/**
 * Downsample artwork into conservative occupancy cells and representative sRGB colours.
 * 将图稿超采样为保守占用格与代表性 sRGB 颜色，避免细线漏检或透明边缘变黑。
 */
export function sampleArtworkCells(
  image: CanvasImageSource,
  cellWidth: number,
  cellHeight: number,
  alphaThreshold: number,
): ArtworkCellSamples | null {
  const width = Math.max(1, Math.trunc(cellWidth));
  const height = Math.max(1, Math.trunc(cellHeight));
  const canvas = document.createElement("canvas");
  canvas.width = width * ARTWORK_MASK_SUPERSAMPLE;
  canvas.height = height * ARTWORK_MASK_SUPERSAMPLE;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return null;

  try {
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const rgba = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const solidMask = new Uint8Array(width * height);
    const colorsSrgb = new Uint8Array(width * height * 3);
    const threshold = Math.min(255, Math.max(0, Math.trunc(alphaThreshold)));
    for (let row = 0; row < height; row += 1) {
      for (let column = 0; column < width; column += 1) {
        let bestAlpha = -1;
        let bestOffset = 0;
        for (let sampleRow = 0; sampleRow < ARTWORK_MASK_SUPERSAMPLE; sampleRow += 1) {
          for (
            let sampleColumn = 0;
            sampleColumn < ARTWORK_MASK_SUPERSAMPLE;
            sampleColumn += 1
          ) {
            const sourceX = column * ARTWORK_MASK_SUPERSAMPLE + sampleColumn;
            const sourceY = row * ARTWORK_MASK_SUPERSAMPLE + sampleRow;
            const sourceOffset = (sourceY * canvas.width + sourceX) * 4;
            const alpha = rgba[sourceOffset + 3] ?? 0;
            if (alpha > bestAlpha) {
              bestAlpha = alpha;
              bestOffset = sourceOffset;
            }
          }
        }
        const cellIndex = row * width + column;
        if (bestAlpha < threshold) continue;
        solidMask[cellIndex] = 1;
        const colorOffset = cellIndex * 3;
        colorsSrgb[colorOffset] = rgba[bestOffset] ?? 0;
        colorsSrgb[colorOffset + 1] = rgba[bestOffset + 1] ?? 0;
        colorsSrgb[colorOffset + 2] = rgba[bestOffset + 2] ?? 0;
      }
    }
    return { solidMask, colorsSrgb };
  } catch {
    return null;
  }
}

/**
 * Build a lightweight heightfield with walls along every visible artwork boundary.
 * 构建沿可见图稿边界（含孔洞）封边的轻量高度场，使浮雕侧视时不会悬空。
 */
export function buildHeightmapSurfaceGeometry({
  modelWidth,
  modelHeight,
  sampleWidth,
  sampleHeight,
  heights,
  skirtBaseHeightMm,
  solidCellMask,
  solidCellColorsSrgb,
}: {
  modelWidth: number;
  modelHeight: number;
  sampleWidth: number;
  sampleHeight: number;
  heights: Float32Array;
  skirtBaseHeightMm: number;
  solidCellMask?: Uint8Array;
  solidCellColorsSrgb?: Uint8Array;
}): THREE.BufferGeometry {
  const columns = Math.max(2, Math.trunc(sampleWidth));
  const rows = Math.max(2, Math.trunc(sampleHeight));
  const cellColumns = columns - 1;
  const cellRows = rows - 1;
  if (heights.length !== columns * rows) {
    throw new Error("Heightmap sample count does not match its grid dimensions");
  }
  if (solidCellMask && solidCellMask.length !== cellColumns * cellRows) {
    throw new Error("Artwork mask count does not match its heightmap cells");
  }
  if (
    solidCellColorsSrgb
    && solidCellColorsSrgb.length !== cellColumns * cellRows * 3
  ) {
    throw new Error("Artwork colour count does not match its heightmap cells");
  }

  const baseHeight = Number.isFinite(skirtBaseHeightMm)
    ? Math.max(0, skirtBaseHeightMm)
    : 0;
  const topGeometry = new THREE.PlaneGeometry(
    modelWidth,
    modelHeight,
    columns - 1,
    rows - 1,
  );
  const topPositions = topGeometry.getAttribute("position") as THREE.BufferAttribute;
  for (let index = 0; index < topPositions.count; index += 1) {
    const requestedHeight = heights[index];
    topPositions.setZ(
      index,
      Number.isFinite(requestedHeight)
        ? Math.max(baseHeight, requestedHeight)
        : baseHeight,
    );
  }

  const positions = Array.from(topPositions.array);
  const uvs = Array.from(topGeometry.getAttribute("uv").array);
  const colors = new Array(topPositions.count * 3).fill(1);
  const topIndices = Array.from(topGeometry.getIndex()?.array ?? []);
  const wallIndices: number[] = [];
  topGeometry.dispose();

  const isSolidCell = (row: number, column: number): boolean => (
    row >= 0
    && row < cellRows
    && column >= 0
    && column < cellColumns
    && (!solidCellMask || solidCellMask[row * cellColumns + column] !== 0)
  );

  const addSkirtSegment = (
    start: number,
    end: number,
    sampleU: number,
    sampleV: number,
    color: THREE.Color,
  ) => {
    const [startX, startY, startZ] = positions.slice(start * 3, start * 3 + 3);
    const [endX, endY, endZ] = positions.slice(end * 3, end * 3 + 3);
    const vertexStart = positions.length / 3;
    positions.push(
      startX, startY, startZ,
      endX, endY, endZ,
      startX, startY, baseHeight,
      endX, endY, baseHeight,
    );
    // Sample every wall vertex from the adjacent visible cell so the opaque
    // wall material keeps a representative edge colour.
    uvs.push(
      sampleU, sampleV,
      sampleU, sampleV,
      sampleU, sampleV,
      sampleU, sampleV,
    );
    colors.push(
      color.r, color.g, color.b,
      color.r, color.g, color.b,
      color.r, color.g, color.b,
      color.r, color.g, color.b,
    );
    wallIndices.push(
      vertexStart, vertexStart + 1, vertexStart + 2,
      vertexStart + 1, vertexStart + 3, vertexStart + 2,
    );
  };

  const wallColor = new THREE.Color(1, 1, 1);
  for (let row = 0; row < cellRows; row += 1) {
    for (let column = 0; column < cellColumns; column += 1) {
      if (!isSolidCell(row, column)) continue;
      const topLeft = row * columns + column;
      const topRight = topLeft + 1;
      const bottomLeft = topLeft + columns;
      const bottomRight = bottomLeft + 1;

      const sampleU = (column + 0.5) / cellColumns;
      const sampleV = 1 - (row + 0.5) / cellRows;
      const cellIndex = row * cellColumns + column;
      if (solidCellColorsSrgb) {
        const colorOffset = cellIndex * 3;
        wallColor.setRGB(
          (solidCellColorsSrgb[colorOffset] ?? 255) / 255,
          (solidCellColorsSrgb[colorOffset + 1] ?? 255) / 255,
          (solidCellColorsSrgb[colorOffset + 2] ?? 255) / 255,
          THREE.SRGBColorSpace,
        );
      } else {
        wallColor.setRGB(1, 1, 1);
      }
      if (!isSolidCell(row - 1, column)) {
        addSkirtSegment(topLeft, topRight, sampleU, sampleV, wallColor);
      }
      if (!isSolidCell(row, column + 1)) {
        addSkirtSegment(topRight, bottomRight, sampleU, sampleV, wallColor);
      }
      if (!isSolidCell(row + 1, column)) {
        addSkirtSegment(bottomRight, bottomLeft, sampleU, sampleV, wallColor);
      }
      if (!isSolidCell(row, column - 1)) {
        addSkirtSegment(bottomLeft, topLeft, sampleU, sampleV, wallColor);
      }
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geometry.setIndex([...topIndices, ...wallIndices]);
  if (topIndices.length > 0) {
    geometry.addGroup(0, topIndices.length, 0);
  }
  if (wallIndices.length > 0) {
    geometry.addGroup(topIndices.length, wallIndices.length, 1);
  }
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

/** Resolve the thin translucent layers shown around the lightweight model. */
export function computeCoatingPreviewLayers({
  coatingHeightMm,
  layerHeightMm,
  structureMode,
  enableRelief,
  spacerThickMm,
  visibleColorHeightMm,
}: {
  coatingHeightMm: number;
  layerHeightMm: number;
  structureMode: string;
  enableRelief: boolean;
  spacerThickMm: number;
  visibleColorHeightMm: number;
}): CoatingPreviewLayer[] {
  const coatingHeight = quantizeCoatingHeightMm(
    coatingHeightMm,
    layerHeightMm,
  );
  if (coatingHeight <= 0) return [];

  const colorHeight = finiteNonNegative(visibleColorHeightMm);
  const spacerHeight = finiteNonNegative(spacerThickMm);
  const doubleSided = structureMode.includes("Double") && !enableRelief;
  const lowerSurface = doubleSided ? -colorHeight : 0;
  const layers: CoatingPreviewLayer[] = [{
    zMin: roundMillimetres(lowerSurface - coatingHeight),
    zMax: roundMillimetres(lowerSurface),
  }];
  if (doubleSided) {
    const upperSurface = spacerHeight + colorHeight;
    layers.push({
      zMin: roundMillimetres(upperSurface),
      zMax: roundMillimetres(upperSurface + coatingHeight),
    });
  }
  return layers;
}
