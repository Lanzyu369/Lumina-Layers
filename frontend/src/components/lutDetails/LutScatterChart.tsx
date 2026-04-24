import type { ReactNode } from "react";

export interface LutScatterPoint {
  x: number;
  y: number;
  hex_color: string | null;
  label?: string | null;
}

export interface LutScatterChartProps {
  title: string;
  description?: string;
  dataTestId: string;
  points: LutScatterPoint[];
  referenceImageHref?: string;
  fixedBounds?: { minX: number; maxX: number; minY: number; maxY: number };
  xLabel: string;
  yLabel: string;
  emptyMessage: string;
  hull?: Array<{ x: number; y: number }>;
  footer?: ReactNode;
  className?: string;
  showLabels?: boolean;
  plotShape?: "square" | "wide";
  headerAction?: ReactNode;
  squareViewportClassName?: string;
}

const LABEL_MAX_POINTS = 8;

function resolveChartLayout(
  plotShape: "square" | "wide",
  squareViewportClassName = "mx-auto block w-full max-w-[560px] aspect-square max-h-[560px]",
) {
  if (plotShape === "square") {
    const viewBoxWidth = 760;
    const viewBoxHeight = 760;
    const margin = { top: 28, right: 28, bottom: 68, left: 84 };
    const innerWidth = viewBoxWidth - margin.left - margin.right;
    const innerHeight = viewBoxHeight - margin.top - margin.bottom;
    const plotSize = Math.min(innerWidth, innerHeight);
    const plotLeft = margin.left + ((innerWidth - plotSize) / 2);
    const plotTop = margin.top + ((innerHeight - plotSize) / 2);
    return {
      viewBoxWidth,
      viewBoxHeight,
      plotLeft,
      plotTop,
      plotWidth: plotSize,
      plotHeight: plotSize,
      svgClassName: squareViewportClassName,
      yLabelX: 22,
    };
  }

  const viewBoxWidth = 960;
  const viewBoxHeight = 540;
  const margin = { top: 28, right: 28, bottom: 56, left: 72 };
  const innerWidth = viewBoxWidth - margin.left - margin.right;
  const innerHeight = viewBoxHeight - margin.top - margin.bottom;
  return {
    viewBoxWidth,
    viewBoxHeight,
    plotLeft: margin.left,
    plotTop: margin.top,
    plotWidth: innerWidth,
    plotHeight: innerHeight,
    svgClassName: "w-full aspect-[16/9] max-h-[540px]",
    yLabelX: 22,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function deriveBounds(points: Array<{ x: number; y: number }>) {
  if (points.length === 0) {
    return {
      minX: -1,
      maxX: 1,
      minY: -1,
      maxY: 1,
    };
  }

  let minX = points[0].x;
  let maxX = points[0].x;
  let minY = points[0].y;
  let maxY = points[0].y;

  for (const point of points) {
    minX = Math.min(minX, point.x);
    maxX = Math.max(maxX, point.x);
    minY = Math.min(minY, point.y);
    maxY = Math.max(maxY, point.y);
  }

  if (minX === maxX) {
    minX -= 1;
    maxX += 1;
  }
  if (minY === maxY) {
    minY -= 1;
    maxY += 1;
  }

  const xPad = (maxX - minX) * 0.08;
  const yPad = (maxY - minY) * 0.08;
  const paddedMinX = minX - xPad;
  const paddedMaxX = maxX + xPad;
  const paddedMinY = minY - yPad;
  const paddedMaxY = maxY + yPad;

  const xSpan = paddedMaxX - paddedMinX;
  const ySpan = paddedMaxY - paddedMinY;
  const span = Math.max(xSpan, ySpan);
  const centerX = (paddedMinX + paddedMaxX) / 2;
  const centerY = (paddedMinY + paddedMaxY) / 2;

  return {
    minX: centerX - span / 2,
    maxX: centerX + span / 2,
    minY: centerY - span / 2,
    maxY: centerY + span / 2,
  };
}

function buildScale(domainMin: number, domainMax: number, rangeMin: number, rangeMax: number) {
  const span = domainMax - domainMin || 1;
  return (value: number) => rangeMin + ((value - domainMin) / span) * (rangeMax - rangeMin);
}

function buildTicks(min: number, max: number, count = 5): number[] {
  if (count <= 1) {
    return [min];
  }
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, index) => min + index * step);
}

function pointColor(point: LutScatterPoint): string {
  if (point.hex_color) {
    return point.hex_color;
  }
  return "rgb(148, 163, 184)";
}

export function getPointRadius(pointCount: number): number {
  if (pointCount >= 1500) return 1.2;
  if (pointCount >= 800) return 1.5;
  if (pointCount >= 250) return 2;
  if (pointCount >= 80) return 2.8;
  if (pointCount >= 20) return 3.8;
  return 4.8;
}

function getPointStrokeWidth(pointCount: number): number {
  if (pointCount >= 1500) return 0.45;
  if (pointCount >= 800) return 0.55;
  if (pointCount >= 250) return 0.7;
  return 0.9;
}

function buildPath(
  points: Array<{ x: number; y: number }>,
  scaleX: (value: number) => number,
  scaleY: (value: number) => number,
) {
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${scaleX(point.x).toFixed(2)} ${scaleY(point.y).toFixed(2)}`)
    .join(" ");
}

export function formatNumberRange(min: number, max: number, precision = 1): string {
  return `${min.toFixed(precision)} – ${max.toFixed(precision)}`;
}

export function LutScatterChart({
  title,
  description,
  dataTestId,
  points,
  referenceImageHref,
  fixedBounds,
  xLabel,
  yLabel,
  emptyMessage,
  hull,
  footer,
  className,
  showLabels = false,
  plotShape = "square",
  headerAction,
  squareViewportClassName,
}: LutScatterChartProps) {
  const layout = resolveChartLayout(plotShape, squareViewportClassName);
  const bounds = fixedBounds ?? deriveBounds([
    ...points,
    ...(hull ?? []),
  ]);
  const scaleX = buildScale(bounds.minX, bounds.maxX, layout.plotLeft, layout.plotLeft + layout.plotWidth);
  const scaleY = buildScale(bounds.minY, bounds.maxY, layout.plotTop + layout.plotHeight, layout.plotTop);
  const ticksX = buildTicks(bounds.minX, bounds.maxX);
  const ticksY = buildTicks(bounds.minY, bounds.maxY);
  const hullPath = hull && hull.length > 1 ? buildPath(hull, scaleX, scaleY) : "";
  const pointRadius = getPointRadius(points.length);
  const pointStrokeWidth = getPointStrokeWidth(points.length);
  const showPointLabels = showLabels && points.length <= LABEL_MAX_POINTS;

  return (
    <section className={className ?? "panel-section rounded-[28px] px-4 py-4 sm:px-5 sm:py-5"}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{title}</h3>
          {description && <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>}
        </div>
        {headerAction ? <div className="shrink-0">{headerAction}</div> : null}
      </div>

      <div className="overflow-hidden rounded-[24px] border border-slate-200/80 bg-slate-100/70 dark:border-slate-700/80 dark:bg-slate-900/50">
        <svg
          data-testid={dataTestId}
          data-plot-shape={plotShape}
          viewBox={`0 0 ${layout.viewBoxWidth} ${layout.viewBoxHeight}`}
          className={layout.svgClassName}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={title}
        >
          <defs>
            <linearGradient id={`${dataTestId}-grid`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(148, 163, 184, 0.12)" />
              <stop offset="100%" stopColor="rgba(148, 163, 184, 0.02)" />
            </linearGradient>
          </defs>

          <rect x="0" y="0" width={layout.viewBoxWidth} height={layout.viewBoxHeight} fill={`url(#${dataTestId}-grid)`} />

          {ticksX.map((tick) => {
            const x = scaleX(tick);
            return (
              <g key={`x-${tick}`}>
                <line
                  x1={x}
                  y1={layout.plotTop}
                  x2={x}
                  y2={layout.plotTop + layout.plotHeight}
                  stroke="rgba(148, 163, 184, 0.14)"
                  strokeWidth="1"
                />
                <text
                  x={x}
                  y={layout.plotTop + layout.plotHeight + 24}
                  textAnchor="middle"
                  className="fill-slate-500 text-[11px] dark:fill-slate-400"
                >
                  {tick.toFixed(1)}
                </text>
              </g>
            );
          })}

          {ticksY.map((tick) => {
            const y = scaleY(tick);
            return (
              <g key={`y-${tick}`}>
                <line
                  x1={layout.plotLeft}
                  y1={y}
                  x2={layout.plotLeft + layout.plotWidth}
                  y2={y}
                  stroke="rgba(148, 163, 184, 0.14)"
                  strokeWidth="1"
                />
                <text
                  x={layout.plotLeft - 10}
                  y={y + 4}
                  textAnchor="end"
                  className="fill-slate-500 text-[11px] dark:fill-slate-400"
                >
                  {tick.toFixed(1)}
                </text>
              </g>
            );
          })}

          <line
            x1={layout.plotLeft}
            y1={layout.plotTop + layout.plotHeight}
            x2={layout.plotLeft + layout.plotWidth}
            y2={layout.plotTop + layout.plotHeight}
            stroke="rgba(148, 163, 184, 0.45)"
            strokeWidth="1.25"
          />
          <line
            x1={layout.plotLeft}
            y1={layout.plotTop}
            x2={layout.plotLeft}
            y2={layout.plotTop + layout.plotHeight}
            stroke="rgba(148, 163, 184, 0.45)"
            strokeWidth="1.25"
          />

          {referenceImageHref && (
            <image
              data-layer="reference"
              href={referenceImageHref}
              x={layout.plotLeft}
              y={layout.plotTop}
              width={layout.plotWidth}
              height={layout.plotHeight}
              preserveAspectRatio={plotShape === "wide" ? "none" : "xMidYMid meet"}
              opacity="0.95"
            />
          )}

          {hullPath && (
            <path
              d={`${hullPath} Z`}
              fill="rgba(59, 130, 246, 0.08)"
              stroke="rgba(59, 130, 246, 0.72)"
              strokeWidth="1.4"
            />
          )}

          {points.map((point, index) => {
            const cx = clamp(scaleX(point.x), layout.plotLeft, layout.plotLeft + layout.plotWidth);
            const cy = clamp(scaleY(point.y), layout.plotTop, layout.plotTop + layout.plotHeight);
            const color = pointColor(point);
            return (
              <g key={`${point.x}-${point.y}-${index}`}>
                <circle
                  cx={cx}
                  cy={cy}
                  r={pointRadius}
                  fill={color}
                  fillOpacity={points.length >= 250 ? 0.82 : 0.94}
                  stroke="rgba(2, 6, 23, 0.78)"
                  strokeWidth={pointStrokeWidth}
                  vectorEffect="non-scaling-stroke"
                />
                <title>{point.label ?? `${point.x}, ${point.y}`}</title>
                {showPointLabels && point.label && (
                  <text
                    x={cx + pointRadius + 4}
                    y={cy - pointRadius - 4}
                    className="fill-slate-600 text-[11px] font-semibold dark:fill-slate-300"
                  >
                    {point.label}
                  </text>
                )}
              </g>
            );
          })}

          <text
            x={layout.plotLeft + (layout.plotWidth / 2)}
            y={layout.viewBoxHeight - 8}
            textAnchor="middle"
            className="fill-slate-500 text-[12px] font-medium dark:fill-slate-400"
          >
            {xLabel}
          </text>
          <text
            x={layout.yLabelX}
            y={layout.plotTop + (layout.plotHeight / 2)}
            textAnchor="middle"
            transform={`rotate(-90 ${layout.yLabelX} ${layout.plotTop + (layout.plotHeight / 2)})`}
            className="fill-slate-500 text-[12px] font-medium dark:fill-slate-400"
          >
            {yLabel}
          </text>

          {points.length === 0 && (
            <g>
              <rect x={layout.plotLeft} y={layout.plotTop} width={layout.plotWidth} height={layout.plotHeight} fill="transparent" />
              <text
                x={layout.plotLeft + (layout.plotWidth / 2)}
                y={layout.plotTop + (layout.plotHeight / 2)}
                textAnchor="middle"
                className="fill-slate-500 text-sm font-medium dark:fill-slate-400"
              >
                {emptyMessage}
              </text>
            </g>
          )}
        </svg>
      </div>

      {footer && <div className="mt-3 text-sm text-slate-500 dark:text-slate-400">{footer}</div>}
    </section>
  );
}
