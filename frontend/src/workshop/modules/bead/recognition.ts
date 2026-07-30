import type { WorkshopRaster } from "../../types";
import {
  MAX_BEAD_GRID_SIZE,
  type BeadCell,
  type BeadConfidenceIssue,
  type BeadConfidenceReason,
  type BeadGridGeometry,
  type BeadInputMode,
  type BeadOrientation,
  type GridSuggestion,
  type PatternClassification,
  type RecognitionRequest,
  type RecognitionResult,
  type RgbColor,
} from "./types";

const GRID_DARK_LUMINANCE = 80;
const HOLE_DARK_LUMINANCE = 70;
const COLOR_CHANGE_THRESHOLD_SQUARED = 20 * 20;
const PALETTE_MERGE_THRESHOLD_SQUARED = 12 * 12;

interface PixelSample {
  color: RgbColor;
  alpha: number;
  x: number;
  y: number;
}

interface CellSample {
  color: RgbColor;
  variance: number;
  dominantRatio: number;
  structureRatio: number;
  centreDark: boolean;
}

interface LineDetection {
  positions: number[];
  spacing: number;
  consistency: number;
}

interface HoleComponent {
  centreX: number;
  centreY: number;
  width: number;
  height: number;
  area: number;
}

function fail(message: string): never {
  throw new Error(message);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function validateRaster(source: WorkshopRaster): void {
  if (
    !Number.isInteger(source.width) ||
    !Number.isInteger(source.height) ||
    source.width <= 0 ||
    source.height <= 0 ||
    source.data.length !== source.width * source.height * 4
  ) {
    fail("Raster dimensions do not match RGBA data.");
  }
}

function pixelOffset(source: WorkshopRaster, x: number, y: number): number {
  return (y * source.width + x) * 4;
}

function readPixel(
  source: WorkshopRaster,
  x: number,
  y: number,
): PixelSample {
  const safeX = clamp(Math.trunc(x), 0, source.width - 1);
  const safeY = clamp(Math.trunc(y), 0, source.height - 1);
  const offset = pixelOffset(source, safeX, safeY);
  return {
    color: [
      source.data[offset],
      source.data[offset + 1],
      source.data[offset + 2],
    ],
    alpha: source.data[offset + 3],
    x: safeX,
    y: safeY,
  };
}

function luminance(color: RgbColor): number {
  return color[0] * 0.299 + color[1] * 0.587 + color[2] * 0.114;
}

function colorDistanceSquared(
  left: RgbColor,
  right: RgbColor,
): number {
  const red = left[0] - right[0];
  const green = left[1] - right[1];
  const blue = left[2] - right[2];
  return red * red + green * green + blue * blue;
}

function pixelDifferenceSquared(
  left: PixelSample,
  right: PixelSample,
): number {
  const alpha = left.alpha - right.alpha;
  return colorDistanceSquared(left.color, right.color) + alpha * alpha;
}

function median(values: readonly number[]): number {
  if (values.length === 0) {
    return 0;
  }
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

function medianColor(samples: readonly PixelSample[]): RgbColor {
  if (samples.length === 0) {
    return [0, 0, 0];
  }
  return [
    Math.round(median(samples.map((sample) => sample.color[0]))),
    Math.round(median(samples.map((sample) => sample.color[1]))),
    Math.round(median(samples.map((sample) => sample.color[2]))),
  ];
}

function dominantColor(samples: readonly PixelSample[]): {
  color: RgbColor;
  ratio: number;
} {
  if (samples.length === 0) {
    return { color: [0, 0, 0], ratio: 0 };
  }
  const counts = new Map<string, { count: number; color: RgbColor }>();
  for (const sample of samples) {
    const key = sample.color.join(",");
    const existing = counts.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      counts.set(key, { count: 1, color: [...sample.color] as RgbColor });
    }
  }
  const winner = [...counts.values()].sort(
    (left, right) =>
      right.count - left.count ||
      left.color[0] - right.color[0] ||
      left.color[1] - right.color[1] ||
      left.color[2] - right.color[2],
  )[0];
  if (!winner) {
    return { color: medianColor(samples), ratio: 0 };
  }
  return {
    color: winner.color,
    ratio: winner.count / samples.length,
  };
}

function groupConsecutive(positions: readonly number[]): number[] {
  if (positions.length === 0) {
    return [];
  }
  const groups: number[][] = [[positions[0]]];
  for (let index = 1; index < positions.length; index += 1) {
    const current = positions[index];
    const group = groups[groups.length - 1];
    if (current === group[group.length - 1] + 1) {
      group.push(current);
    } else {
      groups.push([current]);
    }
  }
  return groups.map((group) => group[0]);
}

function lineConsistency(positions: readonly number[]): {
  spacing: number;
  consistency: number;
} {
  if (positions.length < 2) {
    return { spacing: 0, consistency: 0 };
  }
  const gaps = positions
    .slice(1)
    .map((position, index) => position - positions[index]);
  const spacing = median(gaps);
  if (spacing <= 0) {
    return { spacing: 0, consistency: 0 };
  }
  const meanError =
    gaps.reduce((sum, gap) => sum + Math.abs(gap - spacing), 0) /
    gaps.length;
  return {
    spacing,
    consistency: clamp(1 - meanError / spacing, 0, 1),
  };
}

function detectDarkLines(
  source: WorkshopRaster,
  axis: "x" | "y",
): LineDetection {
  const length = axis === "x" ? source.width : source.height;
  const crossLength = axis === "x" ? source.height : source.width;
  const darkPositions: number[] = [];
  for (let coordinate = 0; coordinate < length; coordinate += 1) {
    let dark = 0;
    for (let cross = 0; cross < crossLength; cross += 1) {
      const pixel =
        axis === "x"
          ? readPixel(source, coordinate, cross)
          : readPixel(source, cross, coordinate);
      if (
        pixel.alpha >= 128 &&
        luminance(pixel.color) <= GRID_DARK_LUMINANCE
      ) {
        dark += 1;
      }
    }
    if (dark / crossLength >= 0.58) {
      darkPositions.push(coordinate);
    }
  }
  const positions = groupConsecutive(darkPositions);
  const { spacing, consistency } = lineConsistency(positions);
  return { positions, spacing, consistency };
}

function numberedGridSuggestion(source: WorkshopRaster): GridSuggestion {
  const vertical = detectDarkLines(source, "x");
  const horizontal = detectDarkLines(source, "y");
  const columns = clamp(vertical.positions.length - 1, 1, MAX_BEAD_GRID_SIZE);
  const rows = clamp(horizontal.positions.length - 1, 1, MAX_BEAD_GRID_SIZE);
  const cellWidth =
    vertical.spacing > 0 ? vertical.spacing : source.width / columns;
  const cellHeight =
    horizontal.spacing > 0 ? horizontal.spacing : source.height / rows;
  const confidence =
    vertical.positions.length >= 2 && horizontal.positions.length >= 2
      ? (vertical.consistency + horizontal.consistency) / 2
      : 0;
  return {
    rows,
    columns,
    geometry: {
      originX: vertical.positions[0] ?? 0,
      originY: horizontal.positions[0] ?? 0,
      cellWidth,
      cellHeight,
    },
    confidence,
    validSquareGrid:
      Math.abs(cellWidth - cellHeight) / Math.max(cellWidth, cellHeight) <=
      0.08,
  };
}

function greatestCommonDivisor(left: number, right: number): number {
  let a = Math.abs(Math.round(left));
  let b = Math.abs(Math.round(right));
  while (b !== 0) {
    const remainder = a % b;
    a = b;
    b = remainder;
  }
  return a;
}

function boundaryPositions(
  source: WorkshopRaster,
  axis: "x" | "y",
): number[] {
  const length = axis === "x" ? source.width : source.height;
  const crossLength = axis === "x" ? source.height : source.width;
  const positions: number[] = [];
  for (let coordinate = 1; coordinate < length; coordinate += 1) {
    let changed = 0;
    for (let cross = 0; cross < crossLength; cross += 1) {
      const before =
        axis === "x"
          ? readPixel(source, coordinate - 1, cross)
          : readPixel(source, cross, coordinate - 1);
      const after =
        axis === "x"
          ? readPixel(source, coordinate, cross)
          : readPixel(source, cross, coordinate);
      if (pixelDifferenceSquared(before, after) > COLOR_CHANGE_THRESHOLD_SQUARED) {
        changed += 1;
      }
    }
    if (changed / crossLength >= 0.22) {
      positions.push(coordinate);
    }
  }
  return groupConsecutive(positions);
}

function inferredBlockSize(
  dimension: number,
  boundaries: readonly number[],
): number {
  if (boundaries.length === 0) {
    return dimension;
  }
  const divisor = boundaries.reduce(
    (current, boundary) =>
      greatestCommonDivisor(current, boundary),
    dimension,
  );
  return divisor >= 4 ? divisor : dimension;
}

function hardPixelSuggestion(source: WorkshopRaster): GridSuggestion {
  const verticalBoundaries = boundaryPositions(source, "x");
  const horizontalBoundaries = boundaryPositions(source, "y");
  const cellWidth = inferredBlockSize(source.width, verticalBoundaries);
  const cellHeight = inferredBlockSize(source.height, horizontalBoundaries);
  const columns = clamp(
    Math.round(source.width / cellWidth),
    1,
    MAX_BEAD_GRID_SIZE,
  );
  const rows = clamp(
    Math.round(source.height / cellHeight),
    1,
    MAX_BEAD_GRID_SIZE,
  );
  const detectedBoundaryCount =
    verticalBoundaries.length + horizontalBoundaries.length;
  const expectedBoundaryCount = Math.max(1, columns + rows - 2);
  return {
    rows,
    columns,
    geometry: { originX: 0, originY: 0, cellWidth, cellHeight },
    confidence:
      detectedBoundaryCount === 0
        ? 0.15
        : clamp(detectedBoundaryCount / expectedBoundaryCount, 0.4, 1),
    validSquareGrid:
      Math.abs(cellWidth - cellHeight) / Math.max(cellWidth, cellHeight) <=
      0.08,
  };
}

function darkHoleComponents(source: WorkshopRaster): HoleComponent[] {
  const visited = new Uint8Array(source.width * source.height);
  const components: HoleComponent[] = [];
  const maximumArea = source.width * source.height * 0.08;

  for (let startY = 0; startY < source.height; startY += 1) {
    for (let startX = 0; startX < source.width; startX += 1) {
      const startIndex = startY * source.width + startX;
      if (visited[startIndex]) {
        continue;
      }
      const start = readPixel(source, startX, startY);
      if (
        start.alpha < 128 ||
        luminance(start.color) > HOLE_DARK_LUMINANCE
      ) {
        visited[startIndex] = 1;
        continue;
      }

      const queue: number[] = [startIndex];
      visited[startIndex] = 1;
      let cursor = 0;
      let area = 0;
      let sumX = 0;
      let sumY = 0;
      let minX = startX;
      let maxX = startX;
      let minY = startY;
      let maxY = startY;
      let touchesEdge = false;
      while (cursor < queue.length) {
        const index = queue[cursor];
        cursor += 1;
        const y = Math.floor(index / source.width);
        const x = index % source.width;
        area += 1;
        sumX += x + 0.5;
        sumY += y + 0.5;
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
        touchesEdge ||= x === 0 || y === 0 || x === source.width - 1 || y === source.height - 1;

        const neighbours = [
          [x - 1, y],
          [x + 1, y],
          [x, y - 1],
          [x, y + 1],
        ] as const;
        for (const [nextX, nextY] of neighbours) {
          if (
            nextX < 0 ||
            nextY < 0 ||
            nextX >= source.width ||
            nextY >= source.height
          ) {
            continue;
          }
          const nextIndex = nextY * source.width + nextX;
          if (visited[nextIndex]) {
            continue;
          }
          const next = readPixel(source, nextX, nextY);
          if (
            next.alpha >= 128 &&
            luminance(next.color) <= HOLE_DARK_LUMINANCE
          ) {
            visited[nextIndex] = 1;
            queue.push(nextIndex);
          }
        }
      }

      const width = maxX - minX + 1;
      const height = maxY - minY + 1;
      const fillRatio = area / (width * height);
      if (
        !touchesEdge &&
        area >= 8 &&
        area <= maximumArea &&
        fillRatio >= 0.55 &&
        Math.abs(width - height) / Math.max(width, height) <= 0.35
      ) {
        components.push({
          centreX: sumX / area,
          centreY: sumY / area,
          width,
          height,
          area,
        });
      }
    }
  }
  return components;
}

function clusterCoordinates(values: readonly number[]): number[] {
  const sorted = [...values].sort((left, right) => left - right);
  const groups: number[][] = [];
  for (const value of sorted) {
    const current = groups[groups.length - 1];
    if (!current || Math.abs(value - median(current)) > 3) {
      groups.push([value]);
    } else {
      current.push(value);
    }
  }
  return groups.map((group) => median(group));
}

function ringGridSuggestion(source: WorkshopRaster): GridSuggestion {
  const components = darkHoleComponents(source);
  const xCentres = clusterCoordinates(
    components.map((component) => component.centreX),
  );
  const yCentres = clusterCoordinates(
    components.map((component) => component.centreY),
  );
  const xSpacing = lineConsistency(xCentres);
  const ySpacing = lineConsistency(yCentres);
  const columns = clamp(xCentres.length || 1, 1, MAX_BEAD_GRID_SIZE);
  const rows = clamp(yCentres.length || 1, 1, MAX_BEAD_GRID_SIZE);
  const cellWidth =
    xSpacing.spacing > 0 ? xSpacing.spacing : source.width / columns;
  const cellHeight =
    ySpacing.spacing > 0 ? ySpacing.spacing : source.height / rows;
  const possibleCells = rows * columns;
  const occupancy = possibleCells > 0 ? components.length / possibleCells : 0;
  const confidence =
    components.length >= 2
      ? clamp(
          occupancy *
            ((xSpacing.consistency || 1) + (ySpacing.consistency || 1)) /
            2,
          0,
          1,
        )
      : 0;

  return {
    rows,
    columns,
    geometry: {
      originX: clamp(
        (xCentres[0] ?? cellWidth / 2) - cellWidth / 2,
        0,
        source.width,
      ),
      originY: clamp(
        (yCentres[0] ?? cellHeight / 2) - cellHeight / 2,
        0,
        source.height,
      ),
      cellWidth,
      cellHeight,
    },
    confidence,
    validSquareGrid:
      Math.abs(cellWidth - cellHeight) / Math.max(cellWidth, cellHeight) <=
      0.08,
  };
}

export function cropRaster(
  source: WorkshopRaster,
  crop: { x: number; y: number; width: number; height: number },
): WorkshopRaster {
  validateRaster(source);
  if (
    !Number.isInteger(crop.x) ||
    !Number.isInteger(crop.y) ||
    !Number.isInteger(crop.width) ||
    !Number.isInteger(crop.height) ||
    crop.x < 0 ||
    crop.y < 0 ||
    crop.width <= 0 ||
    crop.height <= 0 ||
    crop.x + crop.width > source.width ||
    crop.y + crop.height > source.height
  ) {
    return fail("Crop rectangle is outside the source raster.");
  }
  const data = new Uint8ClampedArray(crop.width * crop.height * 4);
  for (let row = 0; row < crop.height; row += 1) {
    const sourceStart =
      ((crop.y + row) * source.width + crop.x) * 4;
    const targetStart = row * crop.width * 4;
    data.set(
      source.data.subarray(
        sourceStart,
        sourceStart + crop.width * 4,
      ),
      targetStart,
    );
  }
  return { width: crop.width, height: crop.height, data };
}

export function suggestGrid(
  source: WorkshopRaster,
  mode: BeadInputMode,
): GridSuggestion {
  validateRaster(source);
  if (mode === "numbered-grid") {
    return numberedGridSuggestion(source);
  }
  if (mode === "ring-preview") {
    return ringGridSuggestion(source);
  }
  return hardPixelSuggestion(source);
}

function hardPixelScore(
  source: WorkshopRaster,
  suggestion: GridSuggestion,
): number {
  if (suggestion.rows === 1 && suggestion.columns === 1) {
    return 0.15;
  }
  const samples: PixelSample[] = [];
  const geometry = suggestion.geometry;
  for (let row = 0; row < suggestion.rows; row += 1) {
    for (let column = 0; column < suggestion.columns; column += 1) {
      const centreX = geometry.originX + (column + 0.5) * geometry.cellWidth;
      const centreY = geometry.originY + (row + 0.5) * geometry.cellHeight;
      samples.push(readPixel(source, centreX, centreY));
    }
  }
  let interiorError = 0;
  let checks = 0;
  for (let row = 0; row < suggestion.rows; row += 1) {
    for (let column = 0; column < suggestion.columns; column += 1) {
      const centre = samples[row * suggestion.columns + column];
      for (const [offsetX, offsetY] of [
        [-0.2, 0],
        [0.2, 0],
        [0, -0.2],
        [0, 0.2],
      ] as const) {
        const pixel = readPixel(
          source,
          geometry.originX +
            (column + 0.5 + offsetX) * geometry.cellWidth,
          geometry.originY +
            (row + 0.5 + offsetY) * geometry.cellHeight,
        );
        interiorError += pixelDifferenceSquared(centre, pixel);
        checks += 1;
      }
    }
  }
  const normalizedError = checks > 0 ? interiorError / checks : 0;
  const uniformity = 1 - clamp(normalizedError / 3_000, 0, 1);
  return clamp(0.5 + uniformity * 0.42, 0, 0.92);
}

export function classifyPattern(
  source: WorkshopRaster,
): PatternClassification {
  validateRaster(source);
  const numbered = numberedGridSuggestion(source);
  const hardPixel = hardPixelSuggestion(source);
  const rings = ringGridSuggestion(source);
  const scores: Record<BeadInputMode, number> = {
    "numbered-grid":
      numbered.rows > 1 && numbered.columns > 1
        ? clamp(0.82 + numbered.confidence * 0.17, 0, 0.99)
        : 0,
    "hard-pixel": hardPixelScore(source, hardPixel),
    "ring-preview":
      rings.rows > 1 && rings.columns > 1
        ? clamp(0.72 + rings.confidence * 0.25, 0, 0.97)
        : 0,
  };
  const ranked = (Object.entries(scores) as Array<[BeadInputMode, number]>)
    .sort((left, right) => right[1] - left[1]);
  const [first, second] = ranked;
  if (!first || first[1] < 0.45 || first[1] - (second?.[1] ?? 0) < 0.08) {
    return {
      mode: "ambiguous",
      confidence: first?.[1] ?? 0,
      scores,
    };
  }
  return { mode: first[0], confidence: first[1], scores };
}

function cellBounds(
  geometry: BeadGridGeometry,
  row: number,
  column: number,
  source: WorkshopRaster,
): { left: number; top: number; right: number; bottom: number } {
  return {
    left: clamp(
      Math.floor(geometry.originX + column * geometry.cellWidth),
      0,
      source.width,
    ),
    top: clamp(
      Math.floor(geometry.originY + row * geometry.cellHeight),
      0,
      source.height,
    ),
    right: clamp(
      Math.ceil(geometry.originX + (column + 1) * geometry.cellWidth),
      0,
      source.width,
    ),
    bottom: clamp(
      Math.ceil(geometry.originY + (row + 1) * geometry.cellHeight),
      0,
      source.height,
    ),
  };
}

function rectangularSamples(
  source: WorkshopRaster,
  bounds: ReturnType<typeof cellBounds>,
  insetFraction: number,
): PixelSample[] {
  const width = Math.max(0, bounds.right - bounds.left);
  const height = Math.max(0, bounds.bottom - bounds.top);
  const left = clamp(
    Math.ceil(bounds.left + width * insetFraction),
    0,
    source.width,
  );
  const right = clamp(
    Math.floor(bounds.right - width * insetFraction),
    left + 1,
    source.width,
  );
  const top = clamp(
    Math.ceil(bounds.top + height * insetFraction),
    0,
    source.height,
  );
  const bottom = clamp(
    Math.floor(bounds.bottom - height * insetFraction),
    top + 1,
    source.height,
  );
  const samples: PixelSample[] = [];
  for (let y = top; y < bottom; y += 1) {
    for (let x = left; x < right; x += 1) {
      samples.push(readPixel(source, x, y));
    }
  }
  return samples;
}

function localGradientSquared(
  source: WorkshopRaster,
  sample: PixelSample,
): number {
  const neighbours = [
    readPixel(source, sample.x - 1, sample.y),
    readPixel(source, sample.x + 1, sample.y),
    readPixel(source, sample.x, sample.y - 1),
    readPixel(source, sample.x, sample.y + 1),
  ];
  return Math.max(
    ...neighbours.map((neighbour) =>
      pixelDifferenceSquared(sample, neighbour),
    ),
  );
}

function summarizeSamples(
  samples: readonly PixelSample[],
  colorCandidates = samples,
): Omit<CellSample, "centreDark"> {
  const dominant = dominantColor(
    colorCandidates.length > 0 ? colorCandidates : samples,
  );
  const color =
    dominant.ratio >= 0.08 ? dominant.color : medianColor(colorCandidates);
  const variance =
    samples.length > 0
      ? samples.reduce(
          (sum, sample) =>
            sum + colorDistanceSquared(sample.color, color),
          0,
        ) / samples.length
      : 0;
  const structureRatio =
    samples.length > 0
      ? samples.filter(
          (sample) =>
            colorDistanceSquared(sample.color, color) >
              COLOR_CHANGE_THRESHOLD_SQUARED ||
            sample.alpha < 128,
        ).length / samples.length
      : 0;
  return {
    color,
    variance,
    dominantRatio: dominant.ratio,
    structureRatio,
  };
}

function sampleNumberedCell(
  source: WorkshopRaster,
  bounds: ReturnType<typeof cellBounds>,
): CellSample {
  const samples = rectangularSamples(source, bounds, 0.12);
  const lowGradient = samples.filter(
    (sample) =>
      localGradientSquared(source, sample) <=
      COLOR_CHANGE_THRESHOLD_SQUARED,
  );
  return {
    ...summarizeSamples(samples, lowGradient),
    centreDark: false,
  };
}

function sampleHardPixelCell(
  source: WorkshopRaster,
  bounds: ReturnType<typeof cellBounds>,
): CellSample {
  const samples = rectangularSamples(source, bounds, 0.2);
  return {
    ...summarizeSamples(samples),
    centreDark: false,
  };
}

function sampleRingCell(
  source: WorkshopRaster,
  bounds: ReturnType<typeof cellBounds>,
): CellSample {
  const width = Math.max(1, bounds.right - bounds.left);
  const height = Math.max(1, bounds.bottom - bounds.top);
  const centreX = (bounds.left + bounds.right) / 2;
  const centreY = (bounds.top + bounds.bottom) / 2;
  const scale = Math.min(width, height);
  const annulus: PixelSample[] = [];
  const centre: PixelSample[] = [];
  for (let y = bounds.top; y < bounds.bottom; y += 1) {
    for (let x = bounds.left; x < bounds.right; x += 1) {
      const distance =
        Math.hypot(x + 0.5 - centreX, y + 0.5 - centreY) / scale;
      if (distance >= 0.22 && distance <= 0.43) {
        annulus.push(readPixel(source, x, y));
      }
      if (distance <= 0.18) {
        centre.push(readPixel(source, x, y));
      }
    }
  }
  const summary = summarizeSamples(annulus);
  const darkCentreRatio =
    centre.length > 0
      ? centre.filter(
          (sample) =>
            sample.alpha >= 128 &&
            luminance(sample.color) <= HOLE_DARK_LUMINANCE,
        ).length / centre.length
      : 0;
  return { ...summary, centreDark: darkCentreRatio >= 0.35 };
}

function sampleCell(
  source: WorkshopRaster,
  bounds: ReturnType<typeof cellBounds>,
  mode: BeadInputMode,
): CellSample {
  if (mode === "numbered-grid") {
    return sampleNumberedCell(source, bounds);
  }
  if (mode === "ring-preview") {
    return sampleRingCell(source, bounds);
  }
  return sampleHardPixelCell(source, bounds);
}

function paletteIndexFor(
  palette: RgbColor[],
  color: RgbColor,
): number {
  const existing = palette.findIndex(
    (candidate) =>
      colorDistanceSquared(candidate, color) <=
      PALETTE_MERGE_THRESHOLD_SQUARED,
  );
  if (existing >= 0) {
    return existing;
  }
  palette.push([...color] as RgbColor);
  return palette.length - 1;
}

function orientedPosition(
  row: number,
  column: number,
  rows: number,
  columns: number,
  orientation: BeadOrientation,
): { row: number; column: number; rows: number; columns: number } {
  const flippedRow = orientation.flipVertical ? rows - 1 - row : row;
  const flippedColumn = orientation.flipHorizontal
    ? columns - 1 - column
    : column;
  if (orientation.rotation === 90) {
    return {
      row: flippedColumn,
      column: rows - 1 - flippedRow,
      rows: columns,
      columns: rows,
    };
  }
  if (orientation.rotation === 180) {
    return {
      row: rows - 1 - flippedRow,
      column: columns - 1 - flippedColumn,
      rows,
      columns,
    };
  }
  if (orientation.rotation === 270) {
    return {
      row: columns - 1 - flippedColumn,
      column: flippedRow,
      rows: columns,
      columns: rows,
    };
  }
  return {
    row: flippedRow,
    column: flippedColumn,
    rows,
    columns,
  };
}

function orientRecognition(
  cells: BeadCell[],
  issues: BeadConfidenceIssue[],
  rows: number,
  columns: number,
  orientation: BeadOrientation,
): {
  cells: BeadCell[];
  issues: BeadConfidenceIssue[];
  rows: number;
  columns: number;
} {
  const first = orientedPosition(0, 0, rows, columns, orientation);
  const orientedCells: BeadCell[] = Array.from(
    { length: cells.length },
    () => ({ kind: "empty" }),
  );
  const indexMap = new Map<number, number>();
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const sourceIndex = row * columns + column;
      const target = orientedPosition(
        row,
        column,
        rows,
        columns,
        orientation,
      );
      const targetIndex = target.row * target.columns + target.column;
      orientedCells[targetIndex] = cells[sourceIndex];
      indexMap.set(sourceIndex, targetIndex);
    }
  }
  return {
    cells: orientedCells,
    issues: issues.map((issue) => ({
      ...issue,
      cellIndex: indexMap.get(issue.cellIndex) ?? issue.cellIndex,
    })),
    rows: first.rows,
    columns: first.columns,
  };
}

export function recognizeBeadPattern(
  request: RecognitionRequest,
): RecognitionResult {
  validateRaster(request.source);
  if (
    !Number.isInteger(request.rows) ||
    !Number.isInteger(request.columns) ||
    request.rows < 1 ||
    request.columns < 1 ||
    request.rows > MAX_BEAD_GRID_SIZE ||
    request.columns > MAX_BEAD_GRID_SIZE
  ) {
    return fail("Recognition grid dimensions are invalid.");
  }

  const cellCount = request.rows * request.columns;
  const emptyIndex =
    request.emptySelection.kind === "sample"
      ? request.emptySelection.cellIndex
      : null;
  if (
    (emptyIndex !== null && (emptyIndex < 0 || emptyIndex >= cellCount)) ||
    (request.transparentSupportSampleCellIndex !== null &&
      (request.transparentSupportSampleCellIndex < 0 ||
        request.transparentSupportSampleCellIndex >= cellCount))
  ) {
    return fail("Calibration sample is outside the recognition grid.");
  }

  const samples: CellSample[] = [];
  for (let row = 0; row < request.rows; row += 1) {
    for (let column = 0; column < request.columns; column += 1) {
      samples.push(
        sampleCell(
          request.source,
          cellBounds(
            request.geometry,
            row,
            column,
            request.source,
          ),
          request.mode,
        ),
      );
    }
  }

  const emptyColor = emptyIndex === null ? null : samples[emptyIndex].color;
  const supportColor =
    request.transparentSupportSampleCellIndex === null
      ? null
      : samples[request.transparentSupportSampleCellIndex].color;
  const palette: RgbColor[] = [];
  const cells: BeadCell[] = [];
  const confidenceIssues: BeadConfidenceIssue[] = [];
  const squareError =
    Math.abs(
      request.geometry.cellWidth - request.geometry.cellHeight,
    ) /
    Math.max(request.geometry.cellWidth, request.geometry.cellHeight);

  for (let index = 0; index < samples.length; index += 1) {
    const sample = samples[index];
    const distanceFromEmpty =
      emptyColor === null
        ? Number.POSITIVE_INFINITY
        : colorDistanceSquared(sample.color, emptyColor);
    const occupied =
      emptyIndex === null ||
      index === request.transparentSupportSampleCellIndex ||
      distanceFromEmpty > COLOR_CHANGE_THRESHOLD_SQUARED ||
      (request.mode === "numbered-grid" &&
        sample.structureRatio >= 0.018) ||
      (request.mode === "ring-preview" && sample.centreDark);

    if (index === emptyIndex || !occupied) {
      cells.push({ kind: "empty" });
      continue;
    }
    if (index === request.transparentSupportSampleCellIndex) {
      cells.push({ kind: "transparent-support" });
    } else if (
      supportColor &&
      colorDistanceSquared(sample.color, supportColor) <=
        PALETTE_MERGE_THRESHOLD_SQUARED
    ) {
      cells.push({ kind: "transparent-support" });
    } else {
      cells.push({
        kind: "color",
        paletteIndex: paletteIndexFor(palette, sample.color),
      });
    }

    const reasons: BeadConfidenceReason[] = [];
    if (sample.variance > 4_000) {
      reasons.push("high-color-variance");
    }
    if (
      request.mode === "numbered-grid" &&
      (sample.structureRatio > 0.08 || sample.dominantRatio < 0.55)
    ) {
      reasons.push("overlay-obstruction");
    }
    if (
      emptyColor &&
      distanceFromEmpty <= COLOR_CHANGE_THRESHOLD_SQUARED
    ) {
      reasons.push("occupancy-color-conflict");
    }
    if (squareError > 0.12) {
      reasons.push("grid-misalignment");
    }
    if (reasons.length > 0) {
      confidenceIssues.push({
        cellIndex: index,
        confidence: clamp(1 - reasons.length * 0.2, 0.1, 0.95),
        reasons,
        resolved: false,
      });
    }
  }

  const oriented = orientRecognition(
    cells,
    confidenceIssues,
    request.rows,
    request.columns,
    request.orientation,
  );
  return {
    mode: request.mode,
    rows: oriented.rows,
    columns: oriented.columns,
    palette,
    cells: oriented.cells,
    confidenceIssues: oriented.issues,
  };
}
