import type { FridgeMagnetItem } from "../api/types";
import { normalizeFridgeMagnetItem } from "../constants/fridgeMagnets";
import type { PreviewSpaceBounds } from "./previewSpace";

// Callers resolve bounds in centred model millimetres before laying out magnets.
function clampValue(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function getDefaultFridgeMagnetCount(
  bounds: PreviewSpaceBounds,
): number {
  const width = Math.max(bounds.maxX - bounds.minX, 0);
  const height = Math.max(bounds.maxY - bounds.minY, 0);
  const area = width * height;

  if (area <= 5000) {
    return 1;
  }
  if (area <= 15000) {
    return 2;
  }
  return 4;
}

const FRIDGE_MAGNET_LAYOUT_GAP_MM = 1;

function buildFridgeMagnetLayoutRatios(count: number): Array<[number, number]> {
  if (count <= 1) {
    return [[0.5, 0.5]];
  }
  if (count === 2) {
    return [
      [0.3, 0.5],
      [0.7, 0.5],
    ];
  }
  if (count === 3) {
    return [
      [0.3, 0.35],
      [0.7, 0.35],
      [0.5, 0.72],
    ];
  }
  if (count === 4) {
    return [
      [0.3, 0.3],
      [0.7, 0.3],
      [0.3, 0.7],
      [0.7, 0.7],
    ];
  }

  const cols = Math.ceil(Math.sqrt(count));
  const rows = Math.ceil(count / cols);
  const marginX = 0.18;
  const marginY = 0.18;
  const usableWidth = 1 - marginX * 2;
  const usableHeight = 1 - marginY * 2;
  const ratios: Array<[number, number]> = [];

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      if (ratios.length >= count) {
        break;
      }
      const xRatio =
        cols === 1 ? 0.5 : marginX + (usableWidth * col) / (cols - 1);
      const yRatio =
        rows === 1 ? 0.5 : marginY + (usableHeight * row) / (rows - 1);
      ratios.push([xRatio, yRatio]);
    }
  }

  return ratios;
}

export function buildSuggestedFridgeMagnetCenters(
  bounds: PreviewSpaceBounds,
  count: number,
): Array<{ x: number; y: number }> {
  const boundsCenterX = (bounds.minX + bounds.maxX) / 2;
  const boundsCenterY = (bounds.minY + bounds.maxY) / 2;
  const interpolate = (min: number, max: number, ratio: number) =>
    min + (max - min) * ratio;

  return buildFridgeMagnetLayoutRatios(Math.max(1, count)).map(
    ([xRatio, yRatio]) => ({
      x: interpolate(bounds.minX, bounds.maxX, xRatio) - boundsCenterX,
      y: interpolate(bounds.minY, bounds.maxY, yRatio) - boundsCenterY,
    }),
  );
}

function getFridgeMagnetLayoutSize(magnet: FridgeMagnetItem): {
  width: number;
  height: number;
} {
  if (magnet.shape === "round") {
    const diameter = magnet.diameter_mm ?? 0;
    return { width: diameter, height: diameter };
  }

  return {
    width: magnet.width_mm ?? 0,
    height: magnet.height_mm ?? 0,
  };
}

function clampFridgeMagnetLayoutCenter(
  center: { x: number; y: number },
  magnet: FridgeMagnetItem,
  bounds: PreviewSpaceBounds,
): { x: number; y: number } {
  const { width, height } = getFridgeMagnetLayoutSize(magnet);
  const halfWidth = width / 2;
  const halfHeight = height / 2;
  const boundsCenterX = (bounds.minX + bounds.maxX) / 2;
  const boundsCenterY = (bounds.minY + bounds.maxY) / 2;
  const clampAxis = (value: number, min: number, max: number) =>
    min > max ? (min + max) / 2 : clampValue(value, min, max);

  return {
    x: clampAxis(
      center.x,
      bounds.minX - boundsCenterX + halfWidth,
      bounds.maxX - boundsCenterX - halfWidth,
    ),
    y: clampAxis(
      center.y,
      bounds.minY - boundsCenterY + halfHeight,
      bounds.maxY - boundsCenterY - halfHeight,
    ),
  };
}

export function layoutFridgeMagnetsByCenters(
  bounds: PreviewSpaceBounds,
  magnets: readonly FridgeMagnetItem[],
  initialCenters?: Array<{ x: number; y: number }>,
): FridgeMagnetItem[] {
  if (magnets.length === 0) {
    return [];
  }

  const fallbackCenter = { x: 0, y: 0 };
  const positioned = magnets.map((magnet, index) => ({
    ...magnet,
    ...clampFridgeMagnetLayoutCenter(
      initialCenters?.[index] ?? fallbackCenter,
      magnet,
      bounds,
    ),
  }));

  for (let iteration = 0; iteration < 48; iteration += 1) {
    let moved = false;

    for (let leftIndex = 0; leftIndex < positioned.length; leftIndex += 1) {
      for (
        let rightIndex = leftIndex + 1;
        rightIndex < positioned.length;
        rightIndex += 1
      ) {
        const left = positioned[leftIndex];
        const right = positioned[rightIndex];
        const leftSize = getFridgeMagnetLayoutSize(left);
        const rightSize = getFridgeMagnetLayoutSize(right);
        const minSeparationX =
          leftSize.width / 2 +
          rightSize.width / 2 +
          FRIDGE_MAGNET_LAYOUT_GAP_MM;
        const minSeparationY =
          leftSize.height / 2 +
          rightSize.height / 2 +
          FRIDGE_MAGNET_LAYOUT_GAP_MM;
        const deltaX = right.center_x_mm - left.center_x_mm;
        const deltaY = right.center_y_mm - left.center_y_mm;
        const overlapX = minSeparationX - Math.abs(deltaX);
        const overlapY = minSeparationY - Math.abs(deltaY);

        if (overlapX <= 0 || overlapY <= 0) {
          continue;
        }

        const leftRoomX = left.center_x_mm - (bounds.minX + leftSize.width / 2);
        const rightRoomX =
          bounds.maxX - rightSize.width / 2 - right.center_x_mm;
        const leftRoomY =
          left.center_y_mm - (bounds.minY + leftSize.height / 2);
        const rightRoomY =
          bounds.maxY - rightSize.height / 2 - right.center_y_mm;
        const roomX = Math.max(0, leftRoomX) + Math.max(0, rightRoomX);
        const roomY = Math.max(0, leftRoomY) + Math.max(0, rightRoomY);
        const separateOnX =
          roomX >= overlapX && (roomX >= roomY || roomY < overlapY);
        const directionX =
          deltaX === 0 ? (leftIndex % 2 === 0 ? -1 : 1) : Math.sign(deltaX);
        const directionY =
          deltaY === 0 ? (leftIndex % 2 === 0 ? -1 : 1) : Math.sign(deltaY);

        if (separateOnX) {
          const shift = overlapX / 2 + 0.01;
          left.center_x_mm -= directionX * shift;
          right.center_x_mm += directionX * shift;
        } else {
          const shift = overlapY / 2 + 0.01;
          left.center_y_mm -= directionY * shift;
          right.center_y_mm += directionY * shift;
        }

        const clampedLeft = clampFridgeMagnetLayoutCenter(
          { x: left.center_x_mm, y: left.center_y_mm },
          left,
          bounds,
        );
        const clampedRight = clampFridgeMagnetLayoutCenter(
          { x: right.center_x_mm, y: right.center_y_mm },
          right,
          bounds,
        );
        left.center_x_mm = clampedLeft.x;
        left.center_y_mm = clampedLeft.y;
        right.center_x_mm = clampedRight.x;
        right.center_y_mm = clampedRight.y;
        moved = true;
      }
    }

    if (!moved) {
      break;
    }
  }

  return positioned;
}

export function canonicalizeFridgeMagnets(
  bounds: PreviewSpaceBounds,
  magnets: readonly FridgeMagnetItem[],
  options?: { resolveCollisions?: boolean },
): FridgeMagnetItem[] {
  if (magnets.length === 0) {
    return [];
  }

  const normalizedMagnets = magnets.map(normalizeFridgeMagnetItem);
  const fallbackCenter = { x: 0, y: 0 };
  const sanitizedCenters = normalizedMagnets.map((magnet) => ({
    x: Number.isFinite(magnet.center_x_mm) ? magnet.center_x_mm : fallbackCenter.x,
    y: Number.isFinite(magnet.center_y_mm) ? magnet.center_y_mm : fallbackCenter.y,
  }));

  if (options?.resolveCollisions) {
    return layoutFridgeMagnetsByCenters(
      bounds,
      normalizedMagnets,
      sanitizedCenters,
    );
  }

  return normalizedMagnets.map((magnet, index) => {
    const center = clampFridgeMagnetLayoutCenter(
      sanitizedCenters[index],
      magnet,
      bounds,
    );

    return {
      ...magnet,
      center_x_mm: center.x,
      center_y_mm: center.y,
    };
  });
}

export function autoLayoutFridgeMagnets(
  bounds: PreviewSpaceBounds,
  magnets: readonly FridgeMagnetItem[],
): FridgeMagnetItem[] {
  const currentMagnets = magnets.map(normalizeFridgeMagnetItem);
  if (currentMagnets.length === 0) {
    return [];
  }

  const centers = buildSuggestedFridgeMagnetCenters(
    bounds,
    currentMagnets.length,
  );
  return layoutFridgeMagnetsByCenters(bounds, currentMagnets, centers);
}
