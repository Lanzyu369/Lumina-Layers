/**
 * Widget panel component with drag, collapse animation, and frosted glass effect.
 * Widget 面板组件，支持拖拽、折叠动画和毛玻璃效果。
 *
 * Uses ResizeObserver on the content area to measure expanded height.
 * Content stays laid out until the collapse animation finishes, then is hidden
 * via height:0 + contentVisibility:hidden without unmounting children.
 * The outer motion.div animates its own height with overflow:hidden to clip,
 * so the content reveal is driven by a single animation source and stays in
 * sync with sibling position shifts (computed from cached expandedHeight).
 * 使用 ResizeObserver 在内容区域测量展开高度。
 * 收起动画结束后才隐藏内容，子组件始终保留在 DOM 中，避免重置表单状态。
 * 外层 motion.div 通过 height 动画 + overflow:hidden 裁剪来控制内容可见
 * 区域，展开效果由单一动画源驱动，与同级组件位置避让同步（使用缓存
 * 的 expandedHeight 计算位置，不依赖动画中间态的 DOM 高度）。
 */

import React, { Component, useCallback, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { motion } from 'framer-motion';
import { WidgetHeader } from './WidgetHeader';
import { WIDGET_TRANSITION } from './widgetMotion';
import { useWidgetStore } from '../../stores/widgetStore';
import { COLLAPSED_HEIGHT, WIDGET_PANEL_RADIUS, WIDGET_WIDTH } from '../../utils/widgetUtils';
import type { WidgetId } from '../../types/widget';
import { useI18n } from '../../i18n/context';

// ===== ErrorBoundary =====

interface ErrorBoundaryProps {
  children: ReactNode;
  widgetId: WidgetId;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class WidgetErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <WidgetErrorFallback onRetry={() => this.setState({ hasError: false })} />
      );
    }
    return this.props.children;
  }
}

function WidgetErrorFallback({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <div className="p-4 text-center text-sm text-red-500">
      <p>{t('widget_error')}</p>
      <button
        className="action-control mt-2 px-3 py-1 text-xs bg-red-100 dark:bg-red-900/30 rounded hover:bg-red-200"
        onClick={onRetry}
      >
        {t('widget_retry')}
      </button>
    </div>
  );
}

// ===== WidgetPanel =====

interface WidgetPanelProps {
  widgetId: WidgetId;
  titleKey: string;
  children: ReactNode;
  dockOffsetX?: number;
  width?: number;
}

/**
 * Per-property transition config for snappy widget animations.
 * 分属性过渡配置，实现快速响应的 Widget 动画。
 *
 * - left/top: fast ease-out tween for position shifts (被挤走时快速滑动)
 * - height: the same tween as the dock's clipping boundary
 */
const TRANSITION_CONFIG = {
  left: WIDGET_TRANSITION,
  top: WIDGET_TRANSITION,
  height: WIDGET_TRANSITION,
};

export const WidgetPanel = React.memo(function WidgetPanel({
  widgetId,
  titleKey,
  children,
  dockOffsetX = 0,
  width = WIDGET_WIDTH,
}: WidgetPanelProps) {
  const widget = useWidgetStore((s) => s.widgets[widgetId]);
  const toggleCollapse = useWidgetStore((s) => s.toggleCollapse);
  const setExpandedHeight = useWidgetStore((s) => s.setExpandedHeight);
  const isActiveDragWidget = useWidgetStore((s) => s.activeWidgetId === widgetId);
  const [contentHidden, setContentHidden] = useState(widget?.collapsed ?? true);

  // Content area ref — used by ResizeObserver to measure expanded height
  const contentRef = useRef<HTMLDivElement>(null);

  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: widgetId,
  });

  // Dispatch custom event when height animation completes so workspace
  // can do a final recalculation with accurate DOM heights.
  const handleAnimationComplete = useCallback(() => {
    setContentHidden(useWidgetStore.getState().widgets[widgetId]?.collapsed ?? true);
    window.dispatchEvent(new CustomEvent('widget-animation-complete'));
  }, [widgetId]);

  // Measure content height via ResizeObserver on the visible content area.
  // Restore and measure content before the first expanded frame. Never
  // overwrite its cached height with the collapsed/dragging content size.
  // Debounced to avoid rapid setExpandedHeight calls that cascade into
  // full workspace re-renders (each call creates a new widget object ref).
  useLayoutEffect(() => {
    const el = contentRef.current;
    if (!el || !widget?.visible || widget.collapsed || isActiveDragWidget) return;
    setContentHidden(false);

    let timer: ReturnType<typeof setTimeout> | null = null;
    const update = () => {
      const h = el.scrollHeight;
      if (h > 0) setExpandedHeight(widgetId, COLLAPSED_HEIGHT + h);
    };

    // Initial measurement (synchronous, no debounce)
    update();

    const observer = new ResizeObserver(() => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(update, 80);
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
      if (timer) clearTimeout(timer);
    };
  }, [widgetId, widget?.visible, widget?.collapsed, isActiveDragWidget, setExpandedHeight]);

  // Defensive: a missing store entry (stale same-version persisted layout)
  // is treated as invisible instead of crashing on property access.
  // 防御：store 条目缺失（同版本旧持久化布局）时按不可见处理，避免崩溃。
  if (!widget || !widget.visible) return null;

  const isBeingDragged = isActiveDragWidget && !!transform;
  const hideContent = isBeingDragged || (widget.collapsed && contentHidden);
  const targetHeight = isBeingDragged
    ? COLLAPSED_HEIGHT
    : (widget.collapsed ? COLLAPSED_HEIGHT : widget.expandedHeight);
  const localLeft = widget.position.x - dockOffsetX;

  // Always set left/top in style so framer-motion has a stable base.
  // During drag: dnd-kit transform is layered on top via CSS transform.
  // After drag: framer-motion animates left/top from current to target.
  //
  // IMPORTANT: We do NOT set left/top in style — framer-motion owns them
  // exclusively via `animate`. During drag we still feed the visual position
  // (base + delta) into animate so framer-motion tracks the value; this way,
  // when drag ends and the target switches to the stacked position, framer
  // interpolates smoothly from the drop point instead of jumping from 0.
  const style: React.CSSProperties = {
    position: 'absolute',
    width,
    borderRadius: WIDGET_PANEL_RADIUS,
    pointerEvents: isBeingDragged ? 'none' : 'auto',
    zIndex: isBeingDragged ? 50 : 30,
    overflow: 'hidden',
    contain: 'content',
    ...(isBeingDragged ? { opacity: 0 } : {}),
  };

  // During drag, include dnd transform in animate target so framer-motion
  // tracks the *visual* position (even while hidden). This avoids stale
  // motion values that can cause drop animation to start from dock top.
  const animateTarget = isBeingDragged
    ? {
        left: localLeft + (transform?.x ?? 0),
        top: widget.position.y + (transform?.y ?? 0),
        height: targetHeight,
      }
    : {
        left: localLeft,
        top: widget.position.y,
        height: targetHeight,
      };

  // During drag, use instant transitions for left/top so the widget
  // follows the cursor without lag. Normal transitions resume after drop.
  const transition = isBeingDragged
    ? {
        left: { duration: 0 },
        top: { duration: 0 },
        height: TRANSITION_CONFIG.height,
      }
    : TRANSITION_CONFIG;

  return (
      <motion.div
        ref={setNodeRef}
        initial={false}
        style={style}
        data-widget-id={widgetId}
        animate={animateTarget}
        transition={transition}
        onAnimationComplete={handleAnimationComplete}
        className="panel-card will-change-transform"
      >
        <WidgetHeader
          widgetId={widgetId}
          titleKey={titleKey}
          collapsed={widget.collapsed}
          onToggleCollapse={() => toggleCollapse(widgetId)}
          dragListeners={listeners}
          dragAttributes={attributes}
        />
        <div
          ref={contentRef}
          inert={widget.collapsed || isBeingDragged}
          onPointerDown={(e) => e.stopPropagation()}
          style={{
            height: hideContent ? 0 : 'auto',
            overflow: 'hidden',
            ...(hideContent
              ? { visibility: 'hidden' as const, contentVisibility: 'hidden' as const }
              : {}),
          }}
        >
          <WidgetErrorBoundary widgetId={widgetId}>
            {children}
          </WidgetErrorBoundary>
        </div>
      </motion.div>
  );
});
