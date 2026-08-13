/**
 * 选区画笔笔迹草稿的绘制工具。
 * Brush-draft stroke drawing for the selection paint tool.
 *
 * 用法见 drawBrushStrokes。
 * See drawBrushStrokes.
 */

export const BRUSH_STROKE_COLOR = '#f472b6';
export const BRUSH_STROKE_OPACITY = 0.38;

export interface BrushPoint {
  x: number;
  y: number;
}

/**
 * 清空画布并把多笔路径画成同一个不透明粉色蒙版。
 * 透明度不在这里逐笔计算，而由承载画布的 DOM 元素统一施加一次；因此同一笔
 * 自交、不同笔反复覆盖都只得到同一种不透明粉色，最终显示透明度始终一致。
 * Clears the canvas and renders every path into one opaque pink mask. Opacity
 * is applied once by the canvas DOM element, so self-intersections and overlap
 * between strokes never accumulate alpha.
 */
export function drawBrushStrokes(
  context: CanvasRenderingContext2D,
  strokes: readonly (readonly BrushPoint[])[],
  currentStroke: readonly BrushPoint[],
  diameterPx: number,
): void {
  const { width, height } = context.canvas;
  context.clearRect(0, 0, width, height);
  const all = currentStroke.length > 0 ? [...strokes, currentStroke] : strokes;
  if (all.length === 0) return;
  context.save();
  context.globalAlpha = 1;
  context.globalCompositeOperation = 'source-over';
  context.strokeStyle = BRUSH_STROKE_COLOR;
  context.fillStyle = BRUSH_STROKE_COLOR;
  context.lineWidth = diameterPx;
  context.lineCap = 'round';
  context.lineJoin = 'round';

  // 所有多点笔画作为同一个 Path 的多个 subpath，一次 stroke；这样连抗锯齿
  // 边缘也只栅格化/复合一次。单点笔画同理合并成一个 fill Path。
  // All polylines become subpaths of one Path and are stroked once; singleton
  // discs are likewise filled once. Even anti-aliased overlap is composited once.
  let hasPolyline = false;
  context.beginPath();
  for (const points of all) {
    if (points.length < 2) continue;
    hasPolyline = true;
    context.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
      context.lineTo(points[i].x, points[i].y);
    }
  }
  if (hasPolyline) context.stroke();

  let hasSinglePoint = false;
  context.beginPath();
  for (const points of all) {
    if (points.length !== 1) continue;
    hasSinglePoint = true;
    context.moveTo(points[0].x + diameterPx / 2, points[0].y);
    context.arc(points[0].x, points[0].y, diameterPx / 2, 0, Math.PI * 2);
  }
  if (hasSinglePoint) context.fill();
  context.restore();
}
