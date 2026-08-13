import { describe, expect, it, vi } from 'vitest';
import {
  BRUSH_STROKE_COLOR,
  BRUSH_STROKE_OPACITY,
  drawBrushStrokes,
} from './brushDraftComposite';

describe('drawBrushStrokes', () => {
  it('renders every overlapping stroke into one opaque mask', () => {
    const context = {
      canvas: { width: 100, height: 100 },
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      strokeStyle: '',
      fillStyle: '',
      lineWidth: 0,
      lineCap: 'butt',
      lineJoin: 'miter',
    } as unknown as CanvasRenderingContext2D;

    const crossing = [
      [{ x: 10, y: 50 }, { x: 90, y: 50 }],
      [{ x: 50, y: 10 }, { x: 50, y: 90 }],
      [{ x: 10, y: 10 }, { x: 90, y: 90 }],
    ];

    drawBrushStrokes(context, crossing, [], 20);

    expect(context.clearRect).toHaveBeenCalledWith(0, 0, 100, 100);
    expect(context.strokeStyle).toBe(BRUSH_STROKE_COLOR);
    expect(context.fillStyle).toBe(BRUSH_STROKE_COLOR);
    expect(BRUSH_STROKE_COLOR).toBe('#f472b6');
    expect(BRUSH_STROKE_OPACITY).toBe(0.38);
    expect(context.stroke).toHaveBeenCalledTimes(1);
    expect(context.fill).not.toHaveBeenCalled();
  });
});
