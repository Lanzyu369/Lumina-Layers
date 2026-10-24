import * as THREE from "three";

const BED_TEXTURE_PIXELS_PER_MM = 2;
const BED_TEXTURE_RASTER_SCALE = 4;
const BED_TEXTURE_MAX_RASTER_EDGE_PX = 4096;
const BED_GRID_INSET_MM = 5;
const BED_FINE_GRID_STEP_MM = 10;
const BED_FINE_GRID_DASH_PX = 2;
const BED_FINE_GRID_GAP_PX = 8;
const BED_CORNER_BRANDING_INSET_MM = 12;
const BED_CORNER_BRANDING_BOTTOM_INSET_MM = 24;

export const BED_SURFACE_MARGIN_PX = 4;
export const BED_OUTER_RADIUS_MM = 8;
export const LUMINA_BED_MARK_URL = "./favicon.ico";

const LUMINA_MARK_ASPECT_RATIO = 310 / 424;
const BED_SURFACE_BORDER_WIDTH_PX = 2;

export interface BedTextureLayout {
  pixelsPerMm: number;
  gridInsetMm: number;
  fineGridDashPx: readonly number[];
  fineGridDashOffsetPx: {
    horizontal: number;
    vertical: number;
  };
  surface: {
    insetPx: number;
    outerRadiusPx: number;
    innerRadiusPx: number;
    borderWidthPx: number;
  };
  branding: {
    wordmark: string;
    dimensionLabel: string;
    baselinePx: number;
    dimensionBaselinePx: number;
    slicerLogoXpx: number;
    slicerLogoYpx: number;
    slicerLogoSizePx: number;
    watermarkXpx: number;
    watermarkYpx: number;
    watermarkWidthPx: number;
    watermarkHeightPx: number;
    wordmarkCenterPx: number;
    dimensionRightPx: number;
    fontSizePx: number;
  };
  gridBoundsPx: {
    left: number;
    top: number;
    right: number;
    bottom: number;
  };
}

export interface BedTextureRasterSize {
  rasterWidthPx: number;
  rasterHeightPx: number;
  rasterScale: number;
}

export interface BedTextureColors {
  bedBase: string;
  bedInner: string;
  bedFineGrid: string;
  bedBoldGrid: string;
  bedBorder: string;
  bedBrand: string;
}

export interface BedTextureSvgOptions {
  widthMm: number;
  heightMm: number;
  colors: BedTextureColors;
  gridVisible: boolean;
  luminaMarkDataUrl: string | null;
  slicerLogoDataUrl: string | null;
  slicerLogoAspectRatio: number;
}

export interface BedTextureLoadRequest {
  ready: Promise<THREE.Texture | null>;
  cancel: () => void;
}

/** Load one SVG bed texture without exposing it before its image is ready. */
export function createBedTextureRequest(
  options: BedTextureSvgOptions,
): BedTextureLoadRequest {
  const image = new Image();
  const texture = new THREE.Texture(image);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.magFilter = THREE.LinearFilter;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.generateMipmaps = true;
  texture.anisotropy = 4;

  let settled = false;
  let resolveReady!: (value: THREE.Texture | null) => void;
  const ready = new Promise<THREE.Texture | null>((resolve) => {
    resolveReady = resolve;
  });
  const cleanup = () => {
    image.removeEventListener("load", handleLoad);
    image.removeEventListener("error", handleError);
  };
  const finish = (value: THREE.Texture | null) => {
    if (settled) return;
    settled = true;
    cleanup();
    resolveReady(value);
  };
  const handleLoad = () => {
    texture.needsUpdate = true;
    finish(texture);
  };
  const handleError = () => {
    texture.dispose();
    finish(null);
  };

  image.addEventListener("load", handleLoad, { once: true });
  image.addEventListener("error", handleError, { once: true });
  const svg = buildBedTextureSvg(options);
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

  return {
    ready,
    cancel: () => {
      if (settled) return;
      texture.dispose();
      finish(null);
    },
  };
}

/** Keep the current material map until its complete replacement can be shown. */
export function stageBedTextureReplacement(
  material: THREE.MeshStandardMaterial,
  request: BedTextureLoadRequest,
  fallbackColor: string,
): () => void {
  let active = true;
  let committed = false;
  if (material.map === null) {
    material.color.set(fallbackColor);
  }

  void request.ready.then((nextTexture) => {
    if (nextTexture === null) return;
    if (!active) {
      nextTexture.dispose();
      return;
    }

    committed = true;
    const previousTexture = material.map;
    material.map = nextTexture;
    material.color.set(0xffffff);
    material.needsUpdate = true;
    if (previousTexture && previousTexture !== nextTexture) {
      previousTexture.dispose();
    }
  });

  return () => {
    active = false;
    if (!committed) {
      request.cancel();
    }
  };
}

/**
 * Resolve the SVG raster target while keeping all artwork in logical bed pixels.
 * 计算 SVG 纹理栅格尺寸，同时保持热床图案的逻辑尺寸不变。
 */
export function computeBedTextureRasterSize(
  widthMm: number,
  heightMm: number,
): BedTextureRasterSize {
  const logicalWidthPx = widthMm * BED_TEXTURE_PIXELS_PER_MM;
  const logicalHeightPx = heightMm * BED_TEXTURE_PIXELS_PER_MM;
  const desiredLongestEdgePx =
    Math.max(logicalWidthPx, logicalHeightPx) * BED_TEXTURE_RASTER_SCALE;
  const capFactor = Math.min(
    1,
    BED_TEXTURE_MAX_RASTER_EDGE_PX / desiredLongestEdgePx,
  );
  const rasterScale = BED_TEXTURE_RASTER_SCALE * capFactor;

  return {
    rasterWidthPx: Math.max(
      1,
      Math.round(logicalWidthPx * rasterScale),
    ),
    rasterHeightPx: Math.max(
      1,
      Math.round(logicalHeightPx * rasterScale),
    ),
    rasterScale,
  };
}

/**
 * Resolve the texture-space bounds for a near-edge printable grid.
 * 计算贴近热床边缘的可打印网格纹理范围。
 */
export function computeBedTextureLayout(
  widthMm: number,
  heightMm: number,
): BedTextureLayout {
  const insetPx = BED_GRID_INSET_MM * BED_TEXTURE_PIXELS_PER_MM;
  const textureWidthPx = widthMm * BED_TEXTURE_PIXELS_PER_MM;
  const textureHeightPx = heightMm * BED_TEXTURE_PIXELS_PER_MM;
  const outerRadiusPx = Math.min(
    BED_OUTER_RADIUS_MM * BED_TEXTURE_PIXELS_PER_MM,
    textureWidthPx / 2,
    textureHeightPx / 2,
  );
  const shorterTextureEdgePx = Math.min(textureWidthPx, textureHeightPx);
  const cornerBrandingInsetPx =
    BED_CORNER_BRANDING_INSET_MM * BED_TEXTURE_PIXELS_PER_MM;
  const cornerBrandingBottomInsetPx =
    BED_CORNER_BRANDING_BOTTOM_INSET_MM * BED_TEXTURE_PIXELS_PER_MM;
  const fontSizePx = Math.max(
    10,
    Math.round(shorterTextureEdgePx * 0.019),
  );
  const slicerLogoSizePx = Math.min(
    22,
    Math.max(12, Math.round(shorterTextureEdgePx * 0.042)),
  );
  const watermarkHeightPx = slicerLogoSizePx;
  const watermarkWidthPx = Math.round(
    watermarkHeightPx * LUMINA_MARK_ASPECT_RATIO,
  );
  const brandingBaselinePx =
    textureHeightPx - cornerBrandingBottomInsetPx - slicerLogoSizePx / 2 + fontSizePx * 0.35;
  const wordmarkCenterPx = cornerBrandingInsetPx + watermarkWidthPx + 8 + fontSizePx * 1.65;
  const fineGridDashPeriodPx =
    BED_FINE_GRID_DASH_PX + BED_FINE_GRID_GAP_PX;
  const fineGridClearJunctionPhasePx =
    BED_FINE_GRID_DASH_PX + BED_FINE_GRID_GAP_PX / 2;
  const resolveFineGridDashOffsetPx = (
    axisCenterPx: number,
    pathStartPx: number,
  ) => {
    const phasePx =
      ((axisCenterPx - pathStartPx) % fineGridDashPeriodPx +
        fineGridDashPeriodPx) %
      fineGridDashPeriodPx;
    return (
      (fineGridClearJunctionPhasePx - phasePx + fineGridDashPeriodPx) %
      fineGridDashPeriodPx
    );
  };

  return {
    pixelsPerMm: BED_TEXTURE_PIXELS_PER_MM,
    gridInsetMm: BED_GRID_INSET_MM,
    fineGridDashPx: [BED_FINE_GRID_DASH_PX, BED_FINE_GRID_GAP_PX],
    fineGridDashOffsetPx: {
      horizontal: resolveFineGridDashOffsetPx(
        textureWidthPx / 2,
        insetPx,
      ),
      vertical: resolveFineGridDashOffsetPx(
        textureHeightPx / 2,
        insetPx,
      ),
    },
    surface: {
      insetPx: BED_SURFACE_MARGIN_PX,
      outerRadiusPx,
      innerRadiusPx: Math.max(0, outerRadiusPx - BED_SURFACE_MARGIN_PX),
      borderWidthPx: BED_SURFACE_BORDER_WIDTH_PX,
    },
    branding: {
      dimensionLabel: `${widthMm} × ${heightMm} mm`,
      baselinePx: brandingBaselinePx,
      dimensionBaselinePx:
        brandingBaselinePx,
      slicerLogoXpx: textureWidthPx - cornerBrandingInsetPx - slicerLogoSizePx,
      slicerLogoYpx:
        textureHeightPx -
        cornerBrandingBottomInsetPx -
        slicerLogoSizePx,
      slicerLogoSizePx,
      watermarkXpx: cornerBrandingInsetPx,
      watermarkYpx: textureHeightPx - cornerBrandingBottomInsetPx - watermarkHeightPx,
      watermarkWidthPx,
      watermarkHeightPx,
      wordmarkCenterPx,
      dimensionRightPx: textureWidthPx - cornerBrandingInsetPx - slicerLogoSizePx - 12,
      fontSizePx,
    },
    gridBoundsPx: {
      left: insetPx,
      top: insetPx,
      right: textureWidthPx - insetPx,
      bottom: textureHeightPx - insetPx,
    },
  };
}

/**
 * Return grid-line positions mirrored around the physical center of one axis.
 * 返回围绕热床单轴物理中心成对镜像的网格线位置。
 */
export function computeCenteredGridLinePositions(
  lengthMm: number,
  insetMm: number,
  stepMm: number,
  pixelsPerMm: number,
): number[] {
  const lengthPx = lengthMm * pixelsPerMm;
  const insetPx = insetMm * pixelsPerMm;
  const stepPx = stepMm * pixelsPerMm;
  if (
    !Number.isFinite(lengthPx) ||
    !Number.isFinite(insetPx) ||
    !Number.isFinite(stepPx) ||
    lengthPx <= 0 ||
    stepPx <= 0 ||
    insetPx < 0 ||
    insetPx * 2 >= lengthPx
  ) {
    return [];
  }

  const centerPx = lengthPx / 2;
  const minimumPx = insetPx;
  const maximumPx = lengthPx - insetPx;
  const leftLines: number[] = [];
  const rightLines: number[] = [];

  for (let offsetPx = stepPx; ; offsetPx += stepPx) {
    const leftPx = centerPx - offsetPx;
    const rightPx = centerPx + offsetPx;
    if (leftPx < minimumPx && rightPx > maximumPx) break;
    if (leftPx >= minimumPx) leftLines.push(leftPx);
    if (rightPx <= maximumPx) rightLines.push(rightPx);
  }

  return [...leftLines.reverse(), centerPx, ...rightLines];
}

function escapeSvgText(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function buildSvgGridLines(
  widthMm: number,
  heightMm: number,
  layout: BedTextureLayout,
  colors: BedTextureColors,
): string {
  const { left, top, right, bottom } = layout.gridBoundsPx;
  const fineVerticalLines = computeCenteredGridLinePositions(
    widthMm,
    layout.gridInsetMm,
    BED_FINE_GRID_STEP_MM,
    layout.pixelsPerMm,
  );
  const fineHorizontalLines = computeCenteredGridLinePositions(
    heightMm,
    layout.gridInsetMm,
    BED_FINE_GRID_STEP_MM,
    layout.pixelsPerMm,
  );
  const boldVerticalLines = computeCenteredGridLinePositions(
    widthMm,
    layout.gridInsetMm,
    50,
    layout.pixelsPerMm,
  );
  const boldHorizontalLines = computeCenteredGridLinePositions(
    heightMm,
    layout.gridInsetMm,
    50,
    layout.pixelsPerMm,
  );
  const verticalLine = (x: number) =>
    `<line x1="${x}" y1="${top}" x2="${x}" y2="${bottom}"/>`;
  const horizontalLine = (y: number) =>
    `<line x1="${left}" y1="${y}" x2="${right}" y2="${y}"/>`;

  return [
    `<g fill="none" stroke="${escapeSvgText(colors.bedFineGrid)}" stroke-width="1" stroke-linecap="round" stroke-dasharray="${layout.fineGridDashPx.join(" ")}">`,
    `<g stroke-dashoffset="${layout.fineGridDashOffsetPx.vertical}">`,
    ...fineVerticalLines.map(verticalLine),
    "</g>",
    `<g stroke-dashoffset="${layout.fineGridDashOffsetPx.horizontal}">`,
    ...fineHorizontalLines.map(horizontalLine),
    "</g>",
    "</g>",
    `<g fill="none" stroke="${escapeSvgText(colors.bedBoldGrid)}" stroke-width="2">`,
    ...boldVerticalLines.map(verticalLine),
    ...boldHorizontalLines.map(horizontalLine),
    "</g>",
  ].join("");
}

function buildSvgBranding(
  layout: BedTextureLayout,
  brandColor: string,
  luminaMarkDataUrl: string | null,
  slicerLogoDataUrl: string | null,
  slicerLogoAspectRatio: number,
): string {
  const branding = layout.branding;
  const elements: string[] = [];

  if (luminaMarkDataUrl) {
    elements.push(
      `<image href="${escapeSvgText(luminaMarkDataUrl)}" x="${branding.watermarkXpx}" y="${branding.watermarkYpx}" width="${branding.watermarkWidthPx}" height="${branding.watermarkHeightPx}" opacity="0.65"/>`,
    );
  }

  if (slicerLogoDataUrl) {
    const aspect =
      Number.isFinite(slicerLogoAspectRatio) && slicerLogoAspectRatio > 0
        ? slicerLogoAspectRatio
        : 1;
    const logoWidth =
      aspect >= 1
        ? branding.slicerLogoSizePx
        : branding.slicerLogoSizePx * aspect;
    const logoHeight =
      aspect >= 1
        ? branding.slicerLogoSizePx / aspect
        : branding.slicerLogoSizePx;
    elements.push(
      `<image href="${escapeSvgText(slicerLogoDataUrl)}" x="${branding.slicerLogoXpx}" y="${branding.slicerLogoYpx + (branding.slicerLogoSizePx - logoHeight) / 2}" width="${logoWidth}" height="${logoHeight}" opacity="0.55"/>`,
    );
  }

  const escapedBrandColor = escapeSvgText(brandColor);
  const textStyle = `fill="${escapedBrandColor}" opacity="0.72" font-family="MiSans,sans-serif" font-size="${branding.fontSizePx}" font-weight="500"`;
  elements.push(
    `<text x="${branding.wordmarkCenterPx}" y="${branding.baselinePx}" text-anchor="middle" ${textStyle}>${escapeSvgText(branding.wordmark)}</text>`,
    `<text x="${branding.dimensionRightPx}" y="${branding.dimensionBaselinePx}" text-anchor="end" ${textStyle}>${escapeSvgText(branding.dimensionLabel)}</text>`,
  );

  return elements.join("");
}

/**
 * Build scalable vector artwork for the print-bed surface.
 * 生成可缩放的热床表面矢量图案。
 */
export function buildBedTextureSvg({
  widthMm,
  heightMm,
  colors,
  gridVisible,
  luminaMarkDataUrl,
  slicerLogoDataUrl,
  slicerLogoAspectRatio,
}: BedTextureSvgOptions): string {
  const layout = computeBedTextureLayout(widthMm, heightMm);
  const raster = computeBedTextureRasterSize(widthMm, heightMm);
  const logicalWidthPx = widthMm * layout.pixelsPerMm;
  const logicalHeightPx = heightMm * layout.pixelsPerMm;
  const { insetPx, innerRadiusPx, borderWidthPx } = layout.surface;
  const innerWidthPx = logicalWidthPx - insetPx * 2;
  const innerHeightPx = logicalHeightPx - insetPx * 2;
  const grid = gridVisible
    ? buildSvgGridLines(widthMm, heightMm, layout, colors)
    : "";

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${raster.rasterWidthPx}" height="${raster.rasterHeightPx}" viewBox="0 0 ${logicalWidthPx} ${logicalHeightPx}" shape-rendering="geometricPrecision" text-rendering="geometricPrecision">`,
    `<rect width="${logicalWidthPx}" height="${logicalHeightPx}" fill="${escapeSvgText(colors.bedBase)}"/>`,
    `<rect x="${insetPx}" y="${insetPx}" width="${innerWidthPx}" height="${innerHeightPx}" rx="${innerRadiusPx}" fill="${escapeSvgText(colors.bedInner)}"/>`,
    `<defs><mask id="bed-grid-branding"><rect width="${logicalWidthPx}" height="${logicalHeightPx}" fill="white"/><rect x="${layout.gridBoundsPx.left}" y="${layout.branding.watermarkYpx - 8}" width="${layout.gridBoundsPx.right - layout.gridBoundsPx.left}" height="${layout.branding.watermarkHeightPx + 16}" fill="black"/></mask></defs>`,
    `<g mask="url(#bed-grid-branding)">${grid}</g>`,
    `<rect x="${insetPx}" y="${insetPx}" width="${innerWidthPx}" height="${innerHeightPx}" rx="${innerRadiusPx}" fill="none" stroke="${escapeSvgText(colors.bedBorder)}" stroke-width="${borderWidthPx}"/>`,
    buildSvgBranding(
      layout,
      colors.bedBrand,
      luminaMarkDataUrl,
      slicerLogoDataUrl,
      slicerLogoAspectRatio,
    ),
    "</svg>",
  ].join("");
}

/**
 * Map a centered bed-space Y coordinate to an upright texture V coordinate.
 * 将以热床中心为原点的 Y 坐标映射为正向纹理 V 坐标。
 */
export function mapBedUvY(yMm: number, heightMm: number): number {
  return (yMm + heightMm / 2) / heightMm;
}
