const DEFAULT_COLOR_LAYER_HEIGHT_MM = 0.4;
const OVERLAY_ELEVATION_MM = 0.15;
export const MAX_3D_OVERLAY_TEXTURE_SIZE_PX = 1024;

export interface PuzzleOverlayBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  maxZ: number;
}

export interface PuzzleOverlayPlacement {
  centerX: number;
  centerY: number;
  width: number;
  height: number;
  z: number;
}

export interface PuzzleOverlayTextureSize {
  width: number;
  height: number;
}

/**
 * Resolve the 3D placement for the puzzle overlay texture plane.
 * 计算拼图叠线纹理平面的 3D 摆放位置。
 */
export function computePuzzleOverlayPlacement(
  modelBounds: PuzzleOverlayBounds | null,
  spacerThick: number,
  enableRelief: boolean,
  colorHeightMap: Record<string, number>,
  enableOutline: boolean,
  enableCloisonne: boolean,
  wireHeightMm: number,
  previewCanvasBounds: PuzzleOverlayBounds | null = null,
): PuzzleOverlayPlacement | null {
  if (!modelBounds) {
    return null;
  }

  const overlayBounds = isValidPuzzleOverlayBounds(previewCanvasBounds)
    ? previewCanvasBounds
    : modelBounds;
  const width = overlayBounds.maxX - overlayBounds.minX;
  const height = overlayBounds.maxY - overlayBounds.minY;
  if (width <= 0 || height <= 0) {
    return null;
  }

  const reliefHeights = Object.values(colorHeightMap).filter(
    (value) => Number.isFinite(value) && value > 0,
  );
  const maxColorHeight = enableRelief
    ? Math.max(DEFAULT_COLOR_LAYER_HEIGHT_MM, ...reliefHeights)
    : DEFAULT_COLOR_LAYER_HEIGHT_MM;
  const colorTopZ = spacerThick + maxColorHeight;
  const cloisonneTopZ = enableCloisonne
    ? spacerThick + DEFAULT_COLOR_LAYER_HEIGHT_MM + Math.max(0, wireHeightMm)
    : colorTopZ;
  const outlineTopZ = enableOutline
    ? Math.max(modelBounds.maxZ, colorTopZ)
    : colorTopZ;

  return {
    centerX: (overlayBounds.minX + overlayBounds.maxX) / 2,
    centerY: (overlayBounds.minY + overlayBounds.maxY) / 2,
    width,
    height,
    z: Math.max(colorTopZ, cloisonneTopZ, outlineTopZ) + OVERLAY_ELEVATION_MM,
  };
}

function isValidPuzzleOverlayBounds(
  bounds: PuzzleOverlayBounds | null,
): bounds is PuzzleOverlayBounds {
  return Boolean(
    bounds
      && Number.isFinite(bounds.minX)
      && Number.isFinite(bounds.maxX)
      && Number.isFinite(bounds.minY)
      && Number.isFinite(bounds.maxY)
      && bounds.maxX > bounds.minX
      && bounds.maxY > bounds.minY,
  );
}

/**
 * Clamp an overlay texture to a preview-friendly size for interactive 3D usage.
 * 将叠线贴图限制到适合交互 3D 预览的尺寸。
 */
export function computePuzzleOverlayTextureSize(
  width: number,
  height: number,
  maxDimension: number = MAX_3D_OVERLAY_TEXTURE_SIZE_PX,
): PuzzleOverlayTextureSize {
  if (width <= 0 || height <= 0 || maxDimension <= 0) {
    return { width: Math.max(1, width), height: Math.max(1, height) };
  }

  const longestEdge = Math.max(width, height);
  if (longestEdge <= maxDimension) {
    return { width, height };
  }

  const scale = maxDimension / longestEdge;
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}
