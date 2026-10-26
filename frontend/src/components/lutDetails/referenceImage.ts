export interface ReferencePoint {
  x: number;
  y: number;
  hex_color: string | null;
  rgb?: readonly [number, number, number];
}

export interface ReferenceBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export interface ReferenceGridCell {
  fill: string;
  opacity?: number;
}

export interface ReferenceGridOptions {
  columns?: number;
  rows?: number;
  viewSize?: number;
  backgroundFill?: string;
  backgroundOpacity?: number;
  cellBleed?: number;
  colorAt: (x: number, y: number) => ReferenceGridCell | null;
}

interface RgbSum {
  r: number;
  g: number;
  b: number;
  count: number;
}

function hexToRgb(hex: string | null): { r: number; g: number; b: number } {
  const normalized = (hex ?? "#000000").replace("#", "");
  return {
    r: parseInt(normalized.slice(0, 2), 16) || 0,
    g: parseInt(normalized.slice(2, 4), 16) || 0,
    b: parseInt(normalized.slice(4, 6), 16) || 0,
  };
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

function mapPointToGrid(
  point: ReferencePoint,
  bounds: ReferenceBounds,
  gridSize: number,
): { x: number; y: number } {
  const spanX = bounds.maxX - bounds.minX || 1;
  const spanY = bounds.maxY - bounds.minY || 1;
  return {
    x: ((point.x - bounds.minX) / spanX) * gridSize,
    y: (1 - ((point.y - bounds.minY) / spanY)) * gridSize,
  };
}

function getSplatRadius(pointCount: number, gridSize: number): number {
  const density = Math.max(2, Math.round(Math.cbrt(pointCount)));
  return Math.max(3, gridSize / (density * 2.8));
}

function getFocusBlurDeviation(radius: number): number {
  return Math.max(1.1, radius * 0.28);
}

function getSpreadBlurDeviation(radius: number): number {
  return Math.max(1.6, radius * 0.42);
}

export function buildReferenceImageSvg(
  points: ReferencePoint[],
  bounds: ReferenceBounds,
  gridSize = 192,
): string {
  if (points.length === 0) {
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${gridSize} ${gridSize}"></svg>`;
  }

  const focusRadius = getSplatRadius(points.length, gridSize);
  const spreadRadius = focusRadius * 1.22;
  const blurDeviation = getFocusBlurDeviation(focusRadius);
  const spreadBlurDeviation = getSpreadBlurDeviation(spreadRadius);
  const circles: string[] = [];
  const spreadCircles: string[] = [];
  let avg: RgbSum = { r: 0, g: 0, b: 0, count: 0 };

  for (const point of points) {
    const { x, y } = mapPointToGrid(point, bounds, gridSize);
    const [r, g, b] = point.rgb ?? (() => {
      const rgb = hexToRgb(point.hex_color);
      return [rgb.r, rgb.g, rgb.b] as const;
    })();
    const color = point.hex_color ?? rgbToHex(r, g, b);
    circles.push(
      `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${focusRadius.toFixed(2)}" fill="${color}" fill-opacity="0.84" />`,
    );
    spreadCircles.push(
      `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${spreadRadius.toFixed(2)}" fill="${color}" fill-opacity="0.14" />`,
    );
    avg = {
      r: avg.r + r,
      g: avg.g + g,
      b: avg.b + b,
      count: avg.count + 1,
    };
  }

  const baseColor = rgbToHex(
    Math.round(avg.r / avg.count),
    Math.round(avg.g / avg.count),
    Math.round(avg.b / avg.count),
  );

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${gridSize} ${gridSize}">`,
    "<defs>",
    `<filter id="reference-spread" x="-28%" y="-28%" width="156%" height="156%" color-interpolation-filters="sRGB">`,
    `<feGaussianBlur stdDeviation="${spreadBlurDeviation.toFixed(2)}" />`,
    "</filter>",
    `<filter id="reference-focus" x="-20%" y="-20%" width="140%" height="140%" color-interpolation-filters="sRGB">`,
    `<feGaussianBlur stdDeviation="${blurDeviation.toFixed(2)}" />`,
    "</filter>",
    "</defs>",
    `<rect x="0" y="0" width="${gridSize}" height="${gridSize}" fill="${baseColor}" fill-opacity="0.18" />`,
    `<g filter="url(#reference-spread)">${spreadCircles.join("")}</g>`,
    `<g filter="url(#reference-focus)">${circles.join("")}</g>`,
    "</svg>",
  ].join("");
}

export function buildReferenceImageDataUri(
  points: ReferencePoint[],
  bounds: ReferenceBounds,
  gridSize = 192,
): string {
  return `data:image/svg+xml;utf8,${encodeURIComponent(buildReferenceImageSvg(points, bounds, gridSize))}`;
}

function svgToImageHref(svg: string): string {
  if (typeof Blob !== "undefined" && typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
    return URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  }
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export function buildReferenceImageHref(
  points: ReferencePoint[],
  bounds: ReferenceBounds,
  gridSize = 192,
): string {
  return svgToImageHref(buildReferenceImageSvg(points, bounds, gridSize));
}

export function buildReferenceGridImageSvg(
  bounds: ReferenceBounds,
  {
    columns = 160,
    rows = 160,
    viewSize = 480,
    backgroundFill = "#000000",
    backgroundOpacity = 0,
    cellBleed = 0,
    colorAt,
  }: ReferenceGridOptions,
): string {
  const rects: string[] = [];
  const cellWidth = viewSize / columns;
  const cellHeight = viewSize / rows;
  const spanX = bounds.maxX - bounds.minX || 1;
  const spanY = bounds.maxY - bounds.minY || 1;

  for (let row = 0; row < rows; row += 1) {
    const yDomain = bounds.maxY - (((row + 0.5) / rows) * spanY);
    const y = row * cellHeight;
    for (let column = 0; column < columns; column += 1) {
      const xDomain = bounds.minX + (((column + 0.5) / columns) * spanX);
      const x = column * cellWidth;
      const cell = colorAt(xDomain, yDomain);
      if (!cell) {
        continue;
      }
      rects.push(
        `<rect x="${(x - cellBleed).toFixed(2)}" y="${(y - cellBleed).toFixed(2)}" width="${(cellWidth + (cellBleed * 2)).toFixed(2)}" height="${(cellHeight + (cellBleed * 2)).toFixed(2)}" fill="${cell.fill}"${cell.opacity !== undefined ? ` fill-opacity="${cell.opacity.toFixed(3)}"` : ""} />`,
      );
    }
  }

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${viewSize} ${viewSize}">`,
    `<rect x="0" y="0" width="${viewSize}" height="${viewSize}" fill="${backgroundFill}"${backgroundOpacity > 0 ? ` fill-opacity="${backgroundOpacity.toFixed(3)}"` : ""} />`,
    ...rects,
    "</svg>",
  ].join("");
}

export function buildReferenceGridImageDataUri(
  bounds: ReferenceBounds,
  options: ReferenceGridOptions,
): string {
  return `data:image/svg+xml;utf8,${encodeURIComponent(buildReferenceGridImageSvg(bounds, options))}`;
}

export function buildReferenceGridImageHref(
  bounds: ReferenceBounds,
  options: ReferenceGridOptions,
): string {
  return svgToImageHref(buildReferenceGridImageSvg(bounds, options));
}
