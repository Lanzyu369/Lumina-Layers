/**
 * Widget utility functions for the floating widget workspace.
 * 浮动 Widget 工作区工具函数。
 */

import type { WidgetId, WidgetLayoutState } from '../types/widget';
import type { WorkspaceMode } from '../types/workspace';

// ===== 常量 =====
/** Default widget width in pixels. (默认 Widget 宽度，单位像素) */
export const WIDGET_WIDTH = 350;
export const MIN_WIDGET_WIDTH = 280;

export function resolveResponsiveWidgetWidth(
  containerWidth: number,
  mode: WorkspaceMode = 'standard'
): number {
  if (containerWidth <= 0) return WIDGET_WIDTH;

  const modeMaxWidth = mode === 'compact' ? 320 : mode === 'wide' ? 360 : WIDGET_WIDTH;
  const modeMinWidth = mode === 'compact' ? 248 : MIN_WIDGET_WIDTH;
  const safeWidth = Math.max(240, containerWidth - 32);
  const proportionalWidth = Math.round(containerWidth * (mode === 'compact' ? 0.23 : 0.26));
  return Math.min(modeMaxWidth, safeWidth, Math.max(modeMinWidth, proportionalWidth));
}

/** Shared widget corner radius in pixels. Matches the Hierarchy v2 "card"
 *  step (16px) so the floating panel is the single card level and every
 *  control inside it (10px / 8px) stays one step below.
 *  Widget 统一圆角：与层级 v2 的“卡片”档（16px）一致，内部控件（10px / 8px）
 *  始终低一档。 */
export const WIDGET_PANEL_RADIUS = 16;

/** Collapsed widget height — header only. (折叠状态高度，仅标题栏) */
export const COLLAPSED_HEIGHT = 40;

/** Default expanded widget height. (默认展开状态高度) */
export const EXPANDED_HEIGHT = 400;

/** Snap zone threshold in pixels. (吸附区域阈值，单位像素) */
export const SNAP_THRESHOLD = 48;

/** Gap between stacked widgets in pixels. (堆叠 Widget 间距，单位像素) */
export const STACK_GAP = 8;

type RectBounds = Pick<DOMRectReadOnly, 'top' | 'bottom' | 'left' | 'right'>;

/**
 * Compute bottom inset for a dock when a bottom-fixed blocker overlaps it horizontally.
 * 当底部固定面板与侧边 Dock 在水平方向重叠时，计算需要避让的底部高度。
 *
 * Args:
 *   dockRect (HorizontalRect): Horizontal bounds of the dock. (Dock 的水平边界)
 *   blockerRect (BlockerRect): Horizontal bounds and height of the blocker. (遮挡面板的水平边界与高度)
 *
 * Returns:
 *   number: Bottom inset in pixels. Returns 0 when no overlap exists. (底部避让高度；无重叠时返回 0)
 */
export function computeDockBottomInset(
  dockRect: RectBounds,
  blockerRect: RectBounds
): number {
  const overlapWidth = Math.min(dockRect.right, blockerRect.right) - Math.max(dockRect.left, blockerRect.left);
  if (overlapWidth <= 0) return 0;

  const overlapHeight = Math.min(dockRect.bottom, blockerRect.bottom) - Math.max(dockRect.top, blockerRect.top);
  return overlapHeight > 0 ? Math.max(0, Math.ceil(overlapHeight)) : 0;
}

/**
 * Resolve the effective widget height for stack position calculations.
 * Always prefers the cached expandedHeight (target value set by the
 * WidgetPanel content ResizeObserver) over the live DOM measurement
 * from the Workspace ResizeObserver, because the DOM value reflects
 * the mid-animation height and would produce incorrect sibling offsets.
 * Falls back to measuredHeights only when expandedHeight has not been
 * set yet (e.g. initial mount before first measurement).
 * 解析 Widget 的有效高度，用于堆叠位置计算。
 * 始终优先使用缓存的 expandedHeight（由 WidgetPanel 内容区 ResizeObserver
 * 设置的目标值），而非 Workspace ResizeObserver 的实时 DOM 测量值，因为
 * DOM 值反映的是动画中间态高度，会导致同级组件偏移量不正确。
 * 仅在 expandedHeight 尚未设置时（如首次挂载未测量）回退到 measuredHeights。
 */
export function resolveWidgetHeight(
  widget: Pick<WidgetLayoutState, 'id' | 'collapsed' | 'expandedHeight'>,
  measuredHeights?: Map<WidgetId, number>
): number {
  if (widget.collapsed) {
    return COLLAPSED_HEIGHT;
  }
  if (widget.expandedHeight) {
    return widget.expandedHeight;
  }
  return measuredHeights?.get(widget.id) ?? EXPANDED_HEIGHT;
}

/** Select the nearest edge; an exact midpoint belongs to the left stack. */
export function computeSnap(
  widgetLeft: number,
  widgetRight: number,
  containerWidth: number
): 'left' | 'right' {
  const widgetCenter = (widgetLeft + widgetRight) / 2;
  return widgetCenter <= containerWidth / 2 ? 'left' : 'right';
}

/**
 * Compute stacked positions for widgets snapped to the same edge.
 * 计算吸附到同一边缘的 Widget 堆叠位置。
 *
 * Uses the pre-calculated expandedHeight from widget state for expanded widgets,
 * with optional DOM-measured heights as override for final accuracy.
 * 展开的 Widget 使用状态中预计算的 expandedHeight，
 * 可选的 DOM 测量高度作为最终精度覆盖。
 *
 * Args:
 *   stackWidgets (WidgetLayoutState[]): Widgets snapped to the target edge. (吸附到目标边缘的 Widget 列表)
 *   edge ('left' | 'right'): The edge to stack against. (堆叠的目标边缘)
 *   containerWidth (number): Container width in pixels. (容器宽度)
 *   measuredHeights (Map<WidgetId, number>): Optional actual DOM heights per widget. (可选的实际 DOM 高度映射)
 *
 * Returns:
 *   Map<WidgetId, { x: number; y: number }>: Computed positions keyed by widget ID. (按 Widget ID 索引的计算位置)
 */
export function computeStackPositions(
  stackWidgets: WidgetLayoutState[],
  edge: 'left' | 'right',
  containerWidth: number,
  measuredHeights?: Map<WidgetId, number>,
  widgetWidth: number = WIDGET_WIDTH
): Map<WidgetId, { x: number; y: number }> {
  const sorted = [...stackWidgets].sort((a, b) => a.stackOrder - b.stackOrder);
  const positions = new Map<WidgetId, { x: number; y: number }>();
  const x = edge === 'left' ? STACK_GAP : Math.max(0, containerWidth - widgetWidth - STACK_GAP);
  let currentY = STACK_GAP; // top padding

  for (const widget of sorted) {
    positions.set(widget.id, { x, y: currentY });
    currentY += resolveWidgetHeight(widget, measuredHeights) + STACK_GAP;
  }

  return positions;
}
