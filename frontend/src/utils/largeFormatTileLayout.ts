/**
 * Large-format tile layout shared by the settings summary and the 3D outline.
 * 大画幅分块布局：供设置面板摘要与 3D 分块轮廓共同使用。
 *
 * Mirrors the backend split rules in `core/vector_large_format.py` and the
 * raster path in `api/routers/converter/generate.py`: tiles start at the
 * artwork's top-left corner, run row by row, and the last column/row keeps
 * the remainder. Labels follow the exported `R{row}C{col}` file suffix.
 * 与后端切分规则一致：从作品左上角开始按行切分，最后一列/行保留余量，
 * 标签与导出文件名后缀 `R{行}C{列}` 相同。
 */

/** Grid summary of a large-format split. (大画幅切分的网格摘要) */
export interface LargeFormatTileGrid {
  cols: number;
  rows: number;
  total: number;
  lastColumnWidthMm: number;
  lastRowHeightMm: number;
}

/** Axis-aligned rectangle in scene units (X right, Y up). (场景坐标下的矩形) */
export interface LargeFormatOverlayBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/** One tile label anchored at the tile center. (锚定在分块中心的标签) */
export interface LargeFormatTileLabelAnchor {
  label: string;
  x: number;
  y: number;
}

/** Scene-space outline geometry for the tile grid. (分块网格的场景轮廓几何) */
export interface LargeFormatTileOverlayGeometry {
  /** Flat [x, y] pairs; every two points form one line segment. */
  segments: Array<[number, number]>;
  /** Empty when the grid is too dense for readable labels. */
  labels: LargeFormatTileLabelAnchor[];
}

/** Grids denser than this per axis are skipped to keep the preview responsive. */
export const MAX_TILE_OVERLAY_CUTS_PER_AXIS = 256;
/** Labels are only drawn while the tile count stays readable. */
export const MAX_TILE_OVERLAY_LABELS = 64;

function isPositiveFinite(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

/**
 * Resolve the tile grid for a large-format request.
 * 计算大画幅请求的分块网格。
 *
 * Args:
 *     totalWidthMm: Artwork width in mm. (作品宽度，毫米)
 *     totalHeightMm: Artwork height in mm. (作品高度，毫米)
 *     tileWidthMm: Tile width in mm. (分块宽度，毫米)
 *     tileHeightMm: Tile height in mm. (分块高度，毫米)
 *
 * Returns:
 *     Grid summary, or null when any dimension is not finite and positive.
 *     网格摘要；任一尺寸非有限正数时返回 null。
 */
export function resolveLargeFormatTileGrid(
  totalWidthMm: number,
  totalHeightMm: number,
  tileWidthMm: number,
  tileHeightMm: number,
): LargeFormatTileGrid | null {
  if (
    !isPositiveFinite(totalWidthMm)
    || !isPositiveFinite(totalHeightMm)
    || !isPositiveFinite(tileWidthMm)
    || !isPositiveFinite(tileHeightMm)
  ) {
    return null;
  }
  return {
    cols,
    rows,
    total: cols * rows,
    lastColumnWidthMm: totalWidthMm - (cols - 1) * tileWidthMm,
    lastRowHeightMm: totalHeightMm - (rows - 1) * tileHeightMm,
  };
}

/**
 * Resolve the artwork height the backend will actually tile.
 * 解析后端大画幅切分时实际使用的作品高度。
 *
 * Large-format generation sends only the width; the backend derives the
 * height from the preview cache aspect ratio (`target_w` / `target_h`, which
 * the preview response exposes as the preview pixel size) and rounds it to
 * 4 decimals. The browser-side height can differ for SVGs, so prefer the
 * backend ratio whenever it is known.
 * 大画幅生成只提交宽度，后端按预览缓存比例推导高度并保留 4 位小数；
 * SVG 的浏览器比例可能与后端不同，因此已知后端比例时优先使用它。
 *
 * Args:
 *     targetWidthMm: Requested artwork width in mm. (请求的作品宽度，毫米)
 *     fallbackHeightMm: Browser-side height used when the ratio is unknown.
 *         比例未知时使用的前端高度。
 *     previewPixelWidth: Backend preview width (`target_w`). (后端预览宽度)
 *     previewPixelHeight: Backend preview height (`target_h`). (后端预览高度)
 *
 * Returns:
 *     Height in mm matching the backend split. (与后端切分一致的高度，毫米)
 */
export function resolveLargeFormatTotalHeightMm(
  targetWidthMm: number,
  fallbackHeightMm: number,
  previewPixelWidth: number | null | undefined,
  previewPixelHeight: number | null | undefined,
): number {
  if (
    !isPositiveFinite(targetWidthMm)
    || typeof previewPixelWidth !== "number"
    || typeof previewPixelHeight !== "number"
    || !isPositiveFinite(previewPixelWidth)
    || !isPositiveFinite(previewPixelHeight)
  ) {
    return fallbackHeightMm;
  }
  const derived = (targetWidthMm * previewPixelHeight) / previewPixelWidth;
  return Math.round(derived * 1e4) / 1e4;
}

/**
 * Format a 1-based tile label exactly like the exported file suffix.
 * 按导出文件名后缀格式生成从 1 开始的分块标签。
 */
export function formatLargeFormatTileLabel(row: number, col: number): string {
  return `R${row}C${col}`;
}

/**
 * Build scene-space cut lines and tile labels over the artwork canvas.
 * 在作品画布范围上生成场景坐标的切割线与分块标签。
 *
 * Args:
 *     bounds: Artwork canvas bounds in scene units; image top maps to maxY.
 *         作品画布在场景中的范围，图像顶部对应 maxY。
 *     totalWidthMm: Artwork width in mm. (作品宽度，毫米)
 *     totalHeightMm: Artwork height in mm. (作品高度，毫米)
 *     tileWidthMm: Tile width in mm. (分块宽度，毫米)
 *     tileHeightMm: Tile height in mm. (分块高度，毫米)
 *
 * Returns:
 *     Border plus internal cut segments and optional labels, or null when the
 *     inputs are invalid or the grid is too dense to draw.
 *     外框与内部切割线段及可选标签；输入无效或网格过密时返回 null。
 */
export function buildLargeFormatTileOverlayGeometry(
  bounds: LargeFormatOverlayBounds,
  totalWidthMm: number,
  totalHeightMm: number,
  tileWidthMm: number,
  tileHeightMm: number,
): LargeFormatTileOverlayGeometry | null {
  const grid = resolveLargeFormatTileGrid(
    totalWidthMm,
    totalHeightMm,
    tileWidthMm,
    tileHeightMm,
  );
  const sceneWidth = bounds.maxX - bounds.minX;
  const sceneHeight = bounds.maxY - bounds.minY;
  if (!grid || !isPositiveFinite(sceneWidth) || !isPositiveFinite(sceneHeight)) {
    return null;
  }
  if (
    grid.cols - 1 > MAX_TILE_OVERLAY_CUTS_PER_AXIS
    || grid.rows - 1 > MAX_TILE_OVERLAY_CUTS_PER_AXIS
  ) {
    return null;
  }

  const toSceneX = (mm: number) => bounds.minX + (Math.min(mm, totalWidthMm) / totalWidthMm) * sceneWidth;
  const toSceneY = (mm: number) => bounds.maxY - (Math.min(mm, totalHeightMm) / totalHeightMm) * sceneHeight;

  const { minX, maxX, minY, maxY } = bounds;
  const segments: Array<[number, number]> = [
    [minX, maxY], [maxX, maxY],
    [maxX, maxY], [maxX, minY],
    [maxX, minY], [minX, minY],
    [minX, minY], [minX, maxY],
  ];
  for (let col = 1; col < grid.cols; col += 1) {
    const x = toSceneX(col * tileWidthMm);
    segments.push([x, maxY], [x, minY]);
  }
  for (let row = 1; row < grid.rows; row += 1) {
    const y = toSceneY(row * tileHeightMm);
    segments.push([minX, y], [maxX, y]);
  }

  const labels: LargeFormatTileLabelAnchor[] = [];
  if (grid.total <= MAX_TILE_OVERLAY_LABELS) {
    for (let row = 0; row < grid.rows; row += 1) {
      const y = (toSceneY(row * tileHeightMm) + toSceneY((row + 1) * tileHeightMm)) / 2;
      for (let col = 0; col < grid.cols; col += 1) {
        const x = (toSceneX(col * tileWidthMm) + toSceneX((col + 1) * tileWidthMm)) / 2;
        labels.push({ label: formatLargeFormatTileLabel(row + 1, col + 1), x, y });
      }
    }
  }

  return { segments, labels };
}
