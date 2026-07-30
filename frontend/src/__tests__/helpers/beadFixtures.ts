import type { WorkshopRaster } from "../../workshop/types";
import type { RgbColor } from "../../workshop/modules/bead/types";

const OPAQUE = 255;

export function makeRaster(
  width: number,
  height: number,
  color: readonly [number, number, number, number] = [
    250,
    250,
    250,
    OPAQUE,
  ],
): WorkshopRaster {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let index = 0; index < width * height; index += 1) {
    const offset = index * 4;
    data[offset] = color[0];
    data[offset + 1] = color[1];
    data[offset + 2] = color[2];
    data[offset + 3] = color[3];
  }
  return { width, height, data };
}

export function setPixel(
  raster: WorkshopRaster,
  x: number,
  y: number,
  color: readonly [number, number, number, number],
): void {
  if (x < 0 || y < 0 || x >= raster.width || y >= raster.height) {
    return;
  }
  const offset = (y * raster.width + x) * 4;
  raster.data[offset] = color[0];
  raster.data[offset + 1] = color[1];
  raster.data[offset + 2] = color[2];
  raster.data[offset + 3] = color[3];
}

function fillRect(
  raster: WorkshopRaster,
  left: number,
  top: number,
  right: number,
  bottom: number,
  color: readonly [number, number, number, number],
): void {
  for (let y = top; y < bottom; y += 1) {
    for (let x = left; x < right; x += 1) {
      setPixel(raster, x, y, color);
    }
  }
}

function rgba(color: RgbColor, alpha = OPAQUE) {
  return [color[0], color[1], color[2], alpha] as const;
}

export interface NumberedGridFixtureOptions {
  rows: number;
  columns: number;
  gridLineWidth?: number;
  watermarkCells?: number[];
  whiteBeadCells?: number[];
}

export function makeNumberedGridFixture({
  rows,
  columns,
  gridLineWidth = 2,
  watermarkCells = [],
  whiteBeadCells = [],
}: NumberedGridFixtureOptions): WorkshopRaster {
  const stride = 18;
  const raster = makeRaster(
    columns * stride + gridLineWidth,
    rows * stride + gridLineWidth,
    [244, 244, 244, OPAQUE],
  );
  const grid = [35, 35, 35, OPAQUE] as const;
  const palette: RgbColor[] = [
    [230, 40, 50],
    [30, 110, 220],
    [245, 190, 35],
  ];

  for (let row = 0; row <= rows; row += 1) {
    fillRect(
      raster,
      0,
      row * stride,
      raster.width,
      row * stride + gridLineWidth,
      grid,
    );
  }
  for (let column = 0; column <= columns; column += 1) {
    fillRect(
      raster,
      column * stride,
      0,
      column * stride + gridLineWidth,
      raster.height,
      grid,
    );
  }

  for (let cellIndex = 1; cellIndex < rows * columns; cellIndex += 1) {
    const row = Math.floor(cellIndex / columns);
    const column = cellIndex % columns;
    const fill = whiteBeadCells.includes(cellIndex)
      ? ([255, 255, 255] as RgbColor)
      : palette[cellIndex % palette.length];
    const left = column * stride + gridLineWidth + 1;
    const top = row * stride + gridLineWidth + 1;
    const right = (column + 1) * stride - 1;
    const bottom = (row + 1) * stride - 1;
    fillRect(raster, left, top, right, bottom, rgba(fill));

    const centreX = Math.floor((left + right) / 2);
    const centreY = Math.floor((top + bottom) / 2);
    for (let delta = -2; delta <= 2; delta += 1) {
      setPixel(raster, centreX + delta, centreY, grid);
      setPixel(raster, centreX, centreY + delta, grid);
    }
  }

  for (const cellIndex of watermarkCells) {
    const row = Math.floor(cellIndex / columns);
    const column = cellIndex % columns;
    const left = column * stride + gridLineWidth + 2;
    const top = row * stride + gridLineWidth + 2;
    for (let delta = 0; delta < stride - 5; delta += 1) {
      setPixel(
        raster,
        left + delta,
        top + delta,
        delta % 2 === 0
          ? [170, 20, 190, OPAQUE]
          : [15, 15, 15, OPAQUE],
      );
    }
  }
  return raster;
}

export interface HardPixelFixtureOptions {
  rows: number;
  columns: number;
  scale?: number;
  cellWidth?: number;
  cellHeight?: number;
  cellColors?: Array<RgbColor | null>;
}

export function makeHardPixelFixture({
  rows,
  columns,
  scale = 16,
  cellWidth = scale,
  cellHeight = scale,
  cellColors,
}: HardPixelFixtureOptions): WorkshopRaster {
  const empty: RgbColor = [248, 248, 248];
  const defaults: RgbColor[] = [
    [220, 45, 55],
    [40, 120, 220],
    [245, 185, 30],
  ];
  const raster = makeRaster(
    columns * cellWidth,
    rows * cellHeight,
    rgba(empty),
  );
  for (let index = 0; index < rows * columns; index += 1) {
    const requested = cellColors?.[index];
    const color =
      requested === null
        ? empty
        : requested ?? (index === 0 ? empty : defaults[index % defaults.length]);
    const row = Math.floor(index / columns);
    const column = index % columns;
    fillRect(
      raster,
      column * cellWidth,
      row * cellHeight,
      (column + 1) * cellWidth,
      (row + 1) * cellHeight,
      rgba(color),
    );
  }
  return raster;
}

export interface RingFixtureOptions {
  rows: number;
  columns: number;
  holeRadius?: number;
  supportCellIndex?: number;
}

export function makeRingFixture({
  rows,
  columns,
  holeRadius = 4,
  supportCellIndex = 2,
}: RingFixtureOptions): WorkshopRaster {
  const scale = 24;
  const raster = makeRaster(
    columns * scale,
    rows * scale,
    [248, 248, 248, OPAQUE],
  );
  const colors: RgbColor[] = [
    [225, 55, 70],
    [45, 125, 225],
    [245, 190, 35],
  ];
  const support: RgbColor = [205, 226, 228];
  const hole = [25, 25, 25, OPAQUE] as const;

  for (let index = 1; index < rows * columns; index += 1) {
    const row = Math.floor(index / columns);
    const column = index % columns;
    const centreX = column * scale + scale / 2;
    const centreY = row * scale + scale / 2;
    const color =
      index === supportCellIndex
        ? support
        : colors[index % colors.length];
    for (let y = row * scale; y < (row + 1) * scale; y += 1) {
      for (let x = column * scale; x < (column + 1) * scale; x += 1) {
        const distance = Math.hypot(x + 0.5 - centreX, y + 0.5 - centreY);
        if (distance <= holeRadius) {
          setPixel(raster, x, y, hole);
        } else if (distance <= 10) {
          setPixel(raster, x, y, rgba(color));
        }
      }
    }
  }
  return raster;
}
