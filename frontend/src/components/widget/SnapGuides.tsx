/**
 * Snap guide lines rendered during widget drag near screen edges.
 * Uses RAF polling of refs to avoid re-renders from parent state changes.
 * 拖拽 Widget 接近屏幕边缘时渲染的吸附引导线。
 * 通过 RAF 轮询 ref 避免父组件 state 变化导致的重渲染。
 */

import { useEffect, useState } from 'react';
import type { RefObject } from 'react';
import { SNAP_THRESHOLD, WIDGET_PANEL_RADIUS } from '../../utils/widgetUtils';
import type { WidgetId } from '../../types/widget';

interface InsertPreviewState {
  edge: 'left' | 'right';
  lineY: number;
  upperId: WidgetId | null;
  lowerId: WidgetId | null;
}

interface HighlightBounds {
  top: number;
  height: number;
}

interface GuideOverlayState {
  effectiveWidth: number;
  nearLeft: boolean;
  nearRight: boolean;
  insertPreview: InsertPreviewState | null;
  upperHighlight: HighlightBounds | null;
  lowerHighlight: HighlightBounds | null;
}

interface SnapGuidesProps {
  isDragging: boolean;
  dragPositionRef: RefObject<{ x: number; y: number } | null>;
  insertPreviewRef: RefObject<InsertPreviewState | null>;
  containerRef: RefObject<HTMLDivElement | null>;
  containerWidth: number;
  widgetWidth: number;
}

const BOUNDS_REFRESH_INTERVAL = 10;
const INSERT_LINE_HEIGHT = 6;
const INSERT_LINE_INSET = 8;

const EMPTY_OVERLAY_STATE: GuideOverlayState = {
  effectiveWidth: 0,
  nearLeft: false,
  nearRight: false,
  insertPreview: null,
  upperHighlight: null,
  lowerHighlight: null,
};

export function resolvePreviewLineLeft(
  edge: 'left' | 'right' | undefined,
  effectiveWidth: number,
  widgetWidth: number
): number {
  return edge === 'right'
    ? Math.max(0, effectiveWidth - widgetWidth)
    : 0;
}

function getWidgetBounds(
  container: HTMLDivElement,
  widgetId: WidgetId
): { top: number; height: number } | null {
  const selector = `[data-widget-id="${widgetId}"]`;
  const widgetEl = container.querySelector(selector) as HTMLElement | null;
  if (!widgetEl) return null;

  const containerRect = container.getBoundingClientRect();
  const widgetRect = widgetEl.getBoundingClientRect();
  return {
    top: widgetRect.top - containerRect.top,
    height: widgetRect.height,
  };
}

function isSameBounds(
  prev: HighlightBounds | null,
  next: HighlightBounds | null
): boolean {
  if (prev === next) return true;
  if (!prev || !next) return false;
  return prev.top === next.top && prev.height === next.height;
}

function isSamePreview(
  prev: InsertPreviewState | null,
  next: InsertPreviewState | null
): boolean {
  if (prev === next) return true;
  if (!prev || !next) return false;
  return (
    prev.edge === next.edge &&
    prev.lineY === next.lineY &&
    prev.upperId === next.upperId &&
    prev.lowerId === next.lowerId
  );
}

function isSameOverlayState(prev: GuideOverlayState, next: GuideOverlayState): boolean {
  return (
    prev.effectiveWidth === next.effectiveWidth &&
    prev.nearLeft === next.nearLeft &&
    prev.nearRight === next.nearRight &&
    isSameBounds(prev.upperHighlight, next.upperHighlight) &&
    isSameBounds(prev.lowerHighlight, next.lowerHighlight) &&
    isSamePreview(prev.insertPreview, next.insertPreview)
  );
}

export function SnapGuides({
  isDragging,
  dragPositionRef,
  insertPreviewRef,
  containerRef,
  containerWidth,
  widgetWidth,
}: SnapGuidesProps) {
  const [overlayState, setOverlayState] = useState<GuideOverlayState>(EMPTY_OVERLAY_STATE);

  useEffect(() => {
    if (!isDragging) {
      setOverlayState((prev) => (isSameOverlayState(prev, EMPTY_OVERLAY_STATE) ? prev : EMPTY_OVERLAY_STATE));
      return;
    }

    let rafId = 0;
    let cachedPreviewKey = '';
    let cachedUpperBounds: HighlightBounds | null = null;
    let cachedLowerBounds: HighlightBounds | null = null;
    let framesSinceBoundsRefresh = BOUNDS_REFRESH_INTERVAL;

    const tick = () => {
      const pos = dragPositionRef.current;
      const container = containerRef.current;
      const effectiveWidth = containerWidth || container?.clientWidth || 0;
      const insertPreview = insertPreviewRef.current;

      if (!pos || !container || effectiveWidth <= 0) {
        setOverlayState((prev) => (isSameOverlayState(prev, EMPTY_OVERLAY_STATE) ? prev : EMPTY_OVERLAY_STATE));
        rafId = requestAnimationFrame(tick);
        return;
      }

      const nearLeft = pos.x < SNAP_THRESHOLD;
      const nearRight = effectiveWidth - (pos.x + widgetWidth) < SNAP_THRESHOLD;
      const previewKey = insertPreview
        ? `${insertPreview.edge}:${insertPreview.upperId ?? ''}:${insertPreview.lowerId ?? ''}`
        : '';

      if (!insertPreview) {
        cachedPreviewKey = '';
        cachedUpperBounds = null;
        cachedLowerBounds = null;
        framesSinceBoundsRefresh = BOUNDS_REFRESH_INTERVAL;
      } else if (
        previewKey !== cachedPreviewKey ||
        framesSinceBoundsRefresh >= BOUNDS_REFRESH_INTERVAL
      ) {
        cachedPreviewKey = previewKey;
        cachedUpperBounds = insertPreview.upperId
          ? getWidgetBounds(container, insertPreview.upperId)
          : null;
        cachedLowerBounds = insertPreview.lowerId
          ? getWidgetBounds(container, insertPreview.lowerId)
          : null;
        framesSinceBoundsRefresh = 0;
      } else {
        framesSinceBoundsRefresh += 1;
      }

      const nextState: GuideOverlayState = {
        effectiveWidth,
        nearLeft,
        nearRight,
        insertPreview: insertPreview ?? null,
        lowerHighlight: cachedLowerBounds,
        upperHighlight: cachedUpperBounds,
      };

      setOverlayState((prev) => (isSameOverlayState(prev, nextState) ? prev : nextState));
      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [isDragging, dragPositionRef, insertPreviewRef, containerRef, containerWidth, widgetWidth]);

  const { effectiveWidth, nearLeft, nearRight, insertPreview, lowerHighlight, upperHighlight } = overlayState;
  if (!nearLeft && !nearRight && !insertPreview && !lowerHighlight && !upperHighlight) {
    return null;
  }

  const previewLineLeft = resolvePreviewLineLeft(insertPreview?.edge, effectiveWidth, widgetWidth);

  const createEdgeHighlightStyle = (
    bounds: HighlightBounds,
    edge: 'top' | 'bottom'
  ) => ({
    top: Math.max(0, bounds.top),
    left: previewLineLeft,
    width: widgetWidth,
    height: bounds.height,
    borderRadius: WIDGET_PANEL_RADIUS,
    border: '1px solid var(--snap-guide-highlight-border)',
    background:
      edge === 'top'
        ? 'var(--snap-guide-highlight-top-bg)'
        : 'var(--snap-guide-highlight-bottom-bg)',
    boxShadow:
      edge === 'top'
        ? 'var(--snap-guide-highlight-top-shadow)'
        : 'var(--snap-guide-highlight-bottom-shadow)',
  });

  return (
    <div className="absolute inset-0 z-20 pointer-events-none">
      {nearLeft && (
        <div
          className="absolute left-0 top-0 bottom-0 w-0.5 bg-blue-400/60 shadow-[var(--snap-guide-edge-shadow)]"
        />
      )}
      {nearRight && (
        <div
          className="absolute right-0 top-0 bottom-0 w-0.5 bg-blue-400/60 shadow-[var(--snap-guide-edge-shadow)]"
        />
      )}
      {lowerHighlight && insertPreview && (
        <div
          className="absolute"
          style={createEdgeHighlightStyle(lowerHighlight, 'top')}
        />
      )}
      {upperHighlight && insertPreview && (
        <div
          className="absolute"
          style={createEdgeHighlightStyle(upperHighlight, 'bottom')}
        />
      )}
      {insertPreview && (
        <div
          className="absolute"
          style={{
            top: Math.max(0, insertPreview.lineY) - INSERT_LINE_HEIGHT / 2,
            left: previewLineLeft + INSERT_LINE_INSET,
            width: Math.max(0, widgetWidth - INSERT_LINE_INSET * 2),
            height: INSERT_LINE_HEIGHT,
            borderRadius: 999,
            background: 'var(--snap-guide-insert-line-bg)',
            boxShadow: 'var(--snap-guide-insert-line-shadow)',
          }}
        />
      )}
    </div>
  );
}
