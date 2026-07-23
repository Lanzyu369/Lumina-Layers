import * as THREE from "three";
import type { ModelSurfacePlacement } from "../../stores/converter";

export type Numeric2 = [number, number];

export interface ArtworkPlacementDragUpdateInput {
  tool: "move" | "rotate" | "scale";
  center: Numeric2;
  startPoint: Numeric2;
  currentPoint: Numeric2;
  startPlacement: ModelSurfacePlacement;
  surfaceBounds?: {
    min: Numeric2;
    max: Numeric2;
  };
  artworkSizeMm?: {
    width: number;
    height: number;
  };
  snapThresholdMm?: number;
}

interface ArtworkCoverSizeInput {
  sourceWidth: number;
  sourceHeight: number;
  availableWidth: number;
  availableHeight: number;
  scale: number;
}

interface ArtworkCoverSizeMmInput {
  sourceWidth: number;
  sourceHeight: number;
  availableWidthMm: number;
  availableHeightMm: number;
  scale: number;
}

interface ArtworkPlacementSizeInput extends ArtworkCoverSizeInput {
  mode: ModelSurfacePlacement["mode"];
  rotationDeg: number;
}

interface ArtworkPlacementSizeMmInput extends ArtworkCoverSizeMmInput {
  mode: ModelSurfacePlacement["mode"];
  rotationDeg: number;
}

interface ArtworkCanvasTransformInput {
  widthPx: number;
  heightPx: number;
  pixelsPerMm: number;
  placement: ModelSurfacePlacement;
}

export interface ArtworkCanvasTransform {
  pivotX: number;
  pivotY: number;
  offsetX: number;
  offsetY: number;
  drawCenterX: number;
  drawCenterY: number;
  rotationRadians: number;
}

export interface SurfaceArtworkPreviewBudget {
  viewportLongestSidePx?: number;
  devicePixelRatio?: number;
  maxTextureSize?: number;
  maxTexturePixels?: number;
}

const ARTWORK_EDGE_SNAP_SURFACE_RATIO = 0.012;
const ARTWORK_EDGE_SNAP_MIN_MM = 0.8;
const ARTWORK_EDGE_SNAP_MAX_MM = 3;
const SURFACE_PREVIEW_OFFSET_MIN_MM = 0.18;
const SURFACE_PREVIEW_OFFSET_MAX_MM = 0.8;
const SURFACE_PREVIEW_OFFSET_RATIO = 0.002;
const SURFACE_ARTWORK_TEXTURE_DEFAULT_LONGEST_PX = 2048;
const SURFACE_ARTWORK_TEXTURE_VIEWPORT_SCALE = 1.5;
const SURFACE_ARTWORK_TEXTURE_DEFAULT_MAX_SIZE = 4096;
const SURFACE_ARTWORK_TEXTURE_DEFAULT_MAX_PIXELS =
  SURFACE_ARTWORK_TEXTURE_DEFAULT_MAX_SIZE * SURFACE_ARTWORK_TEXTURE_DEFAULT_MAX_SIZE;
const SURFACE_ARTWORK_TEXTURE_MIN_PX = 32;
const SURFACE_ARTWORK_TEXTURE_MAX_PIXELS_PER_MM = 10;

export function getSurfaceCenterLocal(surface: {
  boundsMin: Numeric2;
  boundsMax: Numeric2;
}): Numeric2 {
  return [
    (surface.boundsMin[0] + surface.boundsMax[0]) / 2,
    (surface.boundsMin[1] + surface.boundsMax[1]) / 2,
  ];
}

function normalizeArtworkOffsetZero(value: number): number {
  return Math.abs(value) <= 1e-9 ? 0 : value;
}

function getArtworkEdgeSnapThresholdMm(bounds: {
  min: Numeric2;
  max: Numeric2;
}): number {
  const width = Math.max(0, bounds.max[0] - bounds.min[0]);
  const height = Math.max(0, bounds.max[1] - bounds.min[1]);
  return THREE.MathUtils.clamp(
    Math.max(width, height) * ARTWORK_EDGE_SNAP_SURFACE_RATIO,
    ARTWORK_EDGE_SNAP_MIN_MM,
    ARTWORK_EDGE_SNAP_MAX_MM,
  );
}

function snapArtworkOffsetAxis(
  value: number,
  targets: number[],
  thresholdMm: number,
): number {
  let snapped = value;
  let nearestDistance = thresholdMm;
  for (const target of targets) {
    const distance = Math.abs(value - target);
    if (distance <= nearestDistance) {
      snapped = target;
      nearestDistance = distance;
    }
  }
  return normalizeArtworkOffsetZero(snapped);
}

function snapArtworkOffsetToSurfaceEdges({
  offset,
  center,
  bounds,
  artworkSizeMm,
  thresholdMm,
}: {
  offset: Numeric2;
  center: Numeric2;
  bounds: {
    min: Numeric2;
    max: Numeric2;
  };
  artworkSizeMm: {
    width: number;
    height: number;
  };
  thresholdMm?: number;
}): Numeric2 {
  if (
    artworkSizeMm.width <= 0
    || artworkSizeMm.height <= 0
    || bounds.max[0] <= bounds.min[0]
    || bounds.max[1] <= bounds.min[1]
  ) {
    return offset;
  }

  const snapThreshold = thresholdMm ?? getArtworkEdgeSnapThresholdMm(bounds);
  const halfWidth = artworkSizeMm.width / 2;
  const halfHeight = artworkSizeMm.height / 2;
  const xTargets = [
    bounds.min[0] + halfWidth - center[0],
    bounds.max[0] - halfWidth - center[0],
  ];
  const yTargets = [
    bounds.min[1] + halfHeight - center[1],
    bounds.max[1] - halfHeight - center[1],
  ];

  return [
    snapArtworkOffsetAxis(offset[0], xTargets, snapThreshold),
    snapArtworkOffsetAxis(offset[1], yTargets, snapThreshold),
  ];
}

function getRotatedArtworkBoundsSize(
  artworkSizeMm: { width: number; height: number },
  rotationDeg: number,
): { width: number; height: number } {
  const rotationRadians = THREE.MathUtils.degToRad(
    Number.isFinite(rotationDeg) ? rotationDeg : 0,
  );
  const cosine = Math.abs(Math.cos(rotationRadians));
  const sine = Math.abs(Math.sin(rotationRadians));
  return {
    width: artworkSizeMm.width * cosine + artworkSizeMm.height * sine,
    height: artworkSizeMm.width * sine + artworkSizeMm.height * cosine,
  };
}

export function computeArtworkPlacementDragUpdate({
  tool,
  center,
  startPoint,
  currentPoint,
  startPlacement,
  surfaceBounds,
  artworkSizeMm,
  snapThresholdMm,
}: ArtworkPlacementDragUpdateInput): Partial<ModelSurfacePlacement> {
  if (tool === "move") {
    const nextOffset: Numeric2 = [
      startPlacement.offset_x_mm + currentPoint[0] - startPoint[0],
      startPlacement.offset_y_mm - (currentPoint[1] - startPoint[1]),
    ];
    const snappedOffset = surfaceBounds && artworkSizeMm
      ? snapArtworkOffsetToSurfaceEdges({
          offset: nextOffset,
          center,
          bounds: surfaceBounds,
          artworkSizeMm: getRotatedArtworkBoundsSize(
            artworkSizeMm,
            startPlacement.rotation_deg,
          ),
          thresholdMm: snapThresholdMm,
        })
      : nextOffset;
    return {
      offset_x_mm: snappedOffset[0],
      offset_y_mm: snappedOffset[1],
    };
  }

  if (tool === "rotate") {
    const startAngle = Math.atan2(
      startPoint[1] - center[1],
      startPoint[0] - center[0],
    );
    const currentAngle = Math.atan2(
      currentPoint[1] - center[1],
      currentPoint[0] - center[0],
    );
    return {
      rotation_deg:
        startPlacement.rotation_deg + THREE.MathUtils.radToDeg(currentAngle - startAngle),
    };
  }

  const placedCenterX = center[0] + startPlacement.offset_x_mm;
  const placedCenterY = center[1] + startPlacement.offset_y_mm;
  const startDistance = Math.hypot(
    startPoint[0] - placedCenterX,
    startPoint[1] - placedCenterY,
  );
  const currentDistance = Math.hypot(
    currentPoint[0] - placedCenterX,
    currentPoint[1] - placedCenterY,
  );
  if (startDistance <= 1e-6) {
    return {};
  }
  return {
    scale: THREE.MathUtils.clamp(
      startPlacement.scale * (currentDistance / startDistance),
      0.1,
      10,
    ),
  };
}

export function computeArtworkCanvasTransform({
  widthPx,
  heightPx,
  pixelsPerMm,
  placement,
}: ArtworkCanvasTransformInput): ArtworkCanvasTransform {
  const pivotX = widthPx / 2;
  const pivotY = heightPx / 2;
  const offsetX = placement.offset_x_mm * pixelsPerMm;
  const offsetY = -placement.offset_y_mm * pixelsPerMm;
  return {
    pivotX,
    pivotY,
    offsetX,
    offsetY,
    drawCenterX: pivotX + offsetX,
    drawCenterY: pivotY + offsetY,
    rotationRadians: THREE.MathUtils.degToRad(placement.rotation_deg),
  };
}

export function computeArtworkCoverDrawSize({
  sourceWidth,
  sourceHeight,
  availableWidth,
  availableHeight,
  scale,
}: ArtworkCoverSizeInput): { width: number; height: number } {
  return computeArtworkPlacementDrawSize({
    sourceWidth,
    sourceHeight,
    availableWidth,
    availableHeight,
    scale,
    mode: "edge_to_edge",
    rotationDeg: 0,
  });
}

export function computeArtworkPlacementDrawSize({
  sourceWidth,
  sourceHeight,
  availableWidth,
  availableHeight,
  scale,
  mode,
  rotationDeg,
}: ArtworkPlacementSizeInput): { width: number; height: number } {
  if (
    sourceWidth <= 0
    || sourceHeight <= 0
    || availableWidth <= 0
    || availableHeight <= 0
  ) {
    return { width: 1, height: 1 };
  }
  const artworkScale = computeArtworkPlacementScale({
    sourceWidth,
    sourceHeight,
    availableWidth,
    availableHeight,
    scale,
    mode,
    rotationDeg,
  });
  const roundSize = mode === "inset" ? Math.floor : Math.ceil;
  return {
    width: Math.max(1, roundSize(sourceWidth * artworkScale)),
    height: Math.max(1, roundSize(sourceHeight * artworkScale)),
  };
}

export function computeSurfaceArtworkCanvasSize(
  widthMm: number,
  heightMm: number,
  budget: SurfaceArtworkPreviewBudget = {},
): { widthPx: number; heightPx: number; pixelsPerMm: number } {
  const safeWidth = Math.max(widthMm, 1);
  const safeHeight = Math.max(heightMm, 1);
  const longestSide = Math.max(safeWidth, safeHeight);
  const maxTextureSize = Math.max(
    SURFACE_ARTWORK_TEXTURE_MIN_PX,
    Math.floor(
      typeof budget.maxTextureSize === "number" && Number.isFinite(budget.maxTextureSize)
        ? budget.maxTextureSize
        : SURFACE_ARTWORK_TEXTURE_DEFAULT_MAX_SIZE,
    ),
  );
  const maxTexturePixels = Math.max(
    SURFACE_ARTWORK_TEXTURE_MIN_PX * SURFACE_ARTWORK_TEXTURE_MIN_PX,
    Math.min(
      maxTextureSize * maxTextureSize,
      Math.floor(
        typeof budget.maxTexturePixels === "number" && Number.isFinite(budget.maxTexturePixels)
          ? budget.maxTexturePixels
          : SURFACE_ARTWORK_TEXTURE_DEFAULT_MAX_PIXELS,
      ),
    ),
  );
  const viewportLongestSidePx =
    typeof budget.viewportLongestSidePx === "number"
    && Number.isFinite(budget.viewportLongestSidePx)
    && budget.viewportLongestSidePx > 0
      ? budget.viewportLongestSidePx
      : null;
  const devicePixelRatio =
    typeof budget.devicePixelRatio === "number"
    && Number.isFinite(budget.devicePixelRatio)
    && budget.devicePixelRatio > 0
      ? THREE.MathUtils.clamp(budget.devicePixelRatio, 1, 3)
      : 1;
  const desiredLongestSidePx = THREE.MathUtils.clamp(
    viewportLongestSidePx === null
      ? SURFACE_ARTWORK_TEXTURE_DEFAULT_LONGEST_PX
      : viewportLongestSidePx * devicePixelRatio * SURFACE_ARTWORK_TEXTURE_VIEWPORT_SCALE,
    SURFACE_ARTWORK_TEXTURE_MIN_PX,
    maxTextureSize,
  );
  const pixelsPerMm = THREE.MathUtils.clamp(
    desiredLongestSidePx / longestSide,
    0,
    SURFACE_ARTWORK_TEXTURE_MAX_PIXELS_PER_MM,
  );
  let widthPx = Math.max(SURFACE_ARTWORK_TEXTURE_MIN_PX, Math.round(safeWidth * pixelsPerMm));
  let heightPx = Math.max(SURFACE_ARTWORK_TEXTURE_MIN_PX, Math.round(safeHeight * pixelsPerMm));
  const previewPixels = widthPx * heightPx;
  if (previewPixels > maxTexturePixels) {
    const scale = Math.sqrt(maxTexturePixels / previewPixels);
    widthPx = Math.max(SURFACE_ARTWORK_TEXTURE_MIN_PX, Math.floor(widthPx * scale));
    heightPx = Math.max(SURFACE_ARTWORK_TEXTURE_MIN_PX, Math.floor(heightPx * scale));
  }
  return {
    widthPx,
    heightPx,
    pixelsPerMm: widthPx / safeWidth,
  };
}

export function computeSurfaceArtworkPreviewBudget(
  renderer?: {
    domElement?: { width?: number; height?: number } | null;
    capabilities?: { maxTextureSize?: number } | null;
  } | null,
): SurfaceArtworkPreviewBudget {
  const viewportLongestSidePx = Math.max(
    renderer?.domElement?.width ?? 0,
    renderer?.domElement?.height ?? 0,
  );
  const maxTextureSize = renderer?.capabilities?.maxTextureSize;
  return {
    viewportLongestSidePx: viewportLongestSidePx > 0 ? viewportLongestSidePx : undefined,
    devicePixelRatio:
      typeof window !== "undefined" && Number.isFinite(window.devicePixelRatio)
        ? window.devicePixelRatio
        : 1,
    maxTextureSize:
      typeof maxTextureSize === "number" && Number.isFinite(maxTextureSize)
        ? maxTextureSize
        : SURFACE_ARTWORK_TEXTURE_DEFAULT_MAX_SIZE,
    maxTexturePixels: SURFACE_ARTWORK_TEXTURE_DEFAULT_MAX_PIXELS,
  };
}

export function computeSurfacePreviewOffsetMm(widthMm: number, heightMm: number): number {
  const longestSide = Math.max(widthMm, heightMm, 1);
  return THREE.MathUtils.clamp(
    longestSide * SURFACE_PREVIEW_OFFSET_RATIO,
    SURFACE_PREVIEW_OFFSET_MIN_MM,
    SURFACE_PREVIEW_OFFSET_MAX_MM,
  );
}

export function computeArtworkCoverDrawSizeMm({
  sourceWidth,
  sourceHeight,
  availableWidthMm,
  availableHeightMm,
  scale,
}: ArtworkCoverSizeMmInput): { width: number; height: number } {
  return computeArtworkPlacementDrawSizeMm({
    sourceWidth,
    sourceHeight,
    availableWidthMm,
    availableHeightMm,
    scale,
    mode: "edge_to_edge",
    rotationDeg: 0,
  });
}

export function computeArtworkPlacementDrawSizeMm({
  sourceWidth,
  sourceHeight,
  availableWidthMm,
  availableHeightMm,
  scale,
  mode,
  rotationDeg,
}: ArtworkPlacementSizeMmInput): { width: number; height: number } {
  if (
    sourceWidth <= 0
    || sourceHeight <= 0
    || availableWidthMm <= 0
    || availableHeightMm <= 0
  ) {
    return { width: 1, height: 1 };
  }
  const artworkScale = computeArtworkPlacementScale({
    sourceWidth,
    sourceHeight,
    availableWidth: availableWidthMm,
    availableHeight: availableHeightMm,
    scale,
    mode,
    rotationDeg,
  });
  return {
    width: Math.max(0.001, sourceWidth * artworkScale),
    height: Math.max(0.001, sourceHeight * artworkScale),
  };
}

function computeArtworkPlacementScale({
  sourceWidth,
  sourceHeight,
  availableWidth,
  availableHeight,
  scale,
  mode,
  rotationDeg,
}: ArtworkPlacementSizeInput): number {
  const rotationRadians = THREE.MathUtils.degToRad(
    Number.isFinite(rotationDeg) ? rotationDeg : 0,
  );
  const cosine = Math.abs(Math.cos(rotationRadians));
  const sine = Math.abs(Math.sin(rotationRadians));
  let fitRatio: number;
  if (mode === "inset") {
    const rotatedSourceWidth = sourceWidth * cosine + sourceHeight * sine;
    const rotatedSourceHeight = sourceWidth * sine + sourceHeight * cosine;
    fitRatio = Math.min(
      availableWidth / rotatedSourceWidth,
      availableHeight / rotatedSourceHeight,
    );
  } else {
    const requiredLocalWidth =
      availableWidth * cosine + availableHeight * sine;
    const requiredLocalHeight =
      availableWidth * sine + availableHeight * cosine;
    fitRatio = Math.max(
      requiredLocalWidth / sourceWidth,
      requiredLocalHeight / sourceHeight,
    );
  }
  return fitRatio * Math.max(scale, 0.001);
}
