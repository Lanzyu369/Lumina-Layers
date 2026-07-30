import { useEffect, useMemo, useRef, type PointerEvent } from "react";

import { cx } from "../../../components/ui/panelPrimitives";
import type { BeadRenderResult } from "./renderer";
import type { BeadProject } from "./types";

interface BeadMatrixViewport {
  centerCellIndex: number;
  radius: number;
}

interface BeadMatrixCanvasProps {
  project: BeadProject;
  ariaLabel: string;
  renderResult?: BeadRenderResult | null;
  showGrid?: boolean;
  selectedCellIndex?: number | null;
  onPickCell?(cellIndex: number): void;
  viewport?: BeadMatrixViewport;
  className?: string;
}

interface MatrixBounds {
  startRow: number;
  endRow: number;
  startColumn: number;
  endColumn: number;
}

function resolveBounds(
  project: BeadProject,
  viewport: BeadMatrixViewport | undefined,
): MatrixBounds {
  if (!viewport) {
    return {
      startRow: 0,
      endRow: project.rows,
      startColumn: 0,
      endColumn: project.columns,
    };
  }
  const row = Math.floor(
    viewport.centerCellIndex / project.columns,
  );
  const column =
    viewport.centerCellIndex % project.columns;
  return {
    startRow: Math.max(0, row - viewport.radius),
    endRow: Math.min(project.rows, row + viewport.radius + 1),
    startColumn: Math.max(0, column - viewport.radius),
    endColumn: Math.min(
      project.columns,
      column + viewport.radius + 1,
    ),
  };
}

function drawMatrix(
  context: CanvasRenderingContext2D,
  project: BeadProject,
  bounds: MatrixBounds,
  scale: number,
  showGrid: boolean,
  selectedCellIndex: number | null,
): void {
  for (let row = bounds.startRow; row < bounds.endRow; row += 1) {
    for (
      let column = bounds.startColumn;
      column < bounds.endColumn;
      column += 1
    ) {
      const cellIndex = row * project.columns + column;
      const cell = project.cells[cellIndex];
      const x = (column - bounds.startColumn) * scale;
      const y = (row - bounds.startRow) * scale;
      if (cell.kind === "color") {
        const color = project.palette[cell.paletteIndex];
        context.fillStyle = `rgb(${color[0]} ${color[1]} ${color[2]})`;
        context.fillRect(x, y, scale, scale);
      } else if (cell.kind === "transparent-support") {
        context.fillStyle = "rgba(14, 165, 233, 0.18)";
        context.fillRect(x, y, scale, scale);
        context.strokeStyle = "rgba(14, 165, 233, 0.82)";
        context.lineWidth = Math.max(1, scale / 12);
        context.beginPath();
        context.moveTo(x + scale * 0.2, y + scale * 0.2);
        context.lineTo(x + scale * 0.8, y + scale * 0.8);
        context.moveTo(x + scale * 0.8, y + scale * 0.2);
        context.lineTo(x + scale * 0.2, y + scale * 0.8);
        context.stroke();
      }
      if (showGrid) {
        context.strokeStyle = "rgba(100, 116, 139, 0.42)";
        context.lineWidth = 1;
        context.strokeRect(x + 0.5, y + 0.5, scale - 1, scale - 1);
      }
      if (cellIndex === selectedCellIndex) {
        context.strokeStyle = "rgb(37 99 235)";
        context.lineWidth = Math.max(2, scale / 8);
        context.strokeRect(
          x + context.lineWidth / 2,
          y + context.lineWidth / 2,
          scale - context.lineWidth,
          scale - context.lineWidth,
        );
      }
    }
  }
}

function drawPressure(
  context: CanvasRenderingContext2D,
  result: BeadRenderResult,
  bounds: MatrixBounds,
): void {
  const imageData = context.createImageData(
    result.width,
    result.height,
  );
  imageData.data.set(result.data);
  context.putImageData(
    imageData,
    -bounds.startColumn * result.pixelsPerCell,
    -bounds.startRow * result.pixelsPerCell,
  );
}

export function BeadMatrixCanvas({
  project,
  ariaLabel,
  renderResult = null,
  showGrid = true,
  selectedCellIndex = null,
  onPickCell,
  viewport,
  className,
}: BeadMatrixCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const draggingRef = useRef(false);
  const lastPickedCellRef = useRef<number | null>(null);
  const bounds = useMemo(
    () => resolveBounds(project, viewport),
    [project, viewport],
  );
  const matrixScale = viewport ? 32 : 12;
  const scale = renderResult?.pixelsPerCell ?? matrixScale;
  const visibleRows = bounds.endRow - bounds.startRow;
  const visibleColumns =
    bounds.endColumn - bounds.startColumn;

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) {
      return;
    }
    canvas.width = visibleColumns * scale;
    canvas.height = visibleRows * scale;
    context.imageSmoothingEnabled = false;
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (renderResult) {
      drawPressure(context, renderResult, bounds);
    } else {
      drawMatrix(
        context,
        project,
        bounds,
        matrixScale,
        showGrid,
        selectedCellIndex,
      );
    }
  }, [
    bounds,
    matrixScale,
    project,
    renderResult,
    scale,
    selectedCellIndex,
    showGrid,
    visibleColumns,
    visibleRows,
  ]);

  const cellIndexAtPointer = (
    event: PointerEvent<HTMLCanvasElement>,
  ): number | null => {
    if (!onPickCell) {
      return null;
    }
    const rectangle =
      event.currentTarget.getBoundingClientRect();
    if (
      rectangle.width <= 0 ||
      rectangle.height <= 0 ||
      event.clientX < rectangle.left ||
      event.clientY < rectangle.top ||
      event.clientX >= rectangle.right ||
      event.clientY >= rectangle.bottom
    ) {
      return null;
    }
    const localColumn = Math.floor(
      ((event.clientX - rectangle.left) / rectangle.width) *
        visibleColumns,
    );
    const localRow = Math.floor(
      ((event.clientY - rectangle.top) / rectangle.height) *
        visibleRows,
    );
    const row = bounds.startRow + localRow;
    const column = bounds.startColumn + localColumn;
    if (
      row < 0 ||
      column < 0 ||
      row >= project.rows ||
      column >= project.columns
    ) {
      return null;
    }
    return row * project.columns + column;
  };

  const pickAtPointer = (
    event: PointerEvent<HTMLCanvasElement>,
  ) => {
    const cellIndex = cellIndexAtPointer(event);
    if (
      cellIndex === null ||
      cellIndex === lastPickedCellRef.current
    ) {
      return;
    }
    lastPickedCellRef.current = cellIndex;
    onPickCell?.(cellIndex);
  };

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={ariaLabel}
      onPointerDown={(event) => {
        if (!onPickCell) {
          return;
        }
        draggingRef.current = true;
        lastPickedCellRef.current = null;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        pickAtPointer(event);
      }}
      onPointerMove={(event) => {
        if (draggingRef.current) {
          pickAtPointer(event);
        }
      }}
      onPointerUp={(event) => {
        draggingRef.current = false;
        lastPickedCellRef.current = null;
        event.currentTarget.releasePointerCapture?.(event.pointerId);
      }}
      onPointerCancel={() => {
        draggingRef.current = false;
        lastPickedCellRef.current = null;
      }}
      className={cx(
        "block h-auto max-h-[68vh] max-w-full rounded-[22px] border border-slate-200/80 bg-slate-100 shadow-[var(--shadow-control)] [image-rendering:pixelated] dark:border-slate-700/80 dark:bg-slate-950",
        onPickCell && "cursor-crosshair touch-none",
        className,
      )}
    />
  );
}
