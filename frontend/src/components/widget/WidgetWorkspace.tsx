/**
 * Widget workspace container with DnD context and snap guides.
 * Widget 工作区容器，包含拖拽上下文和吸附引导线。
 *
 * Wraps all widgets in a DndContext from @dnd-kit/core, handles drag lifecycle,
 * computes snap on drag end, and manages z-index layering for Three.js coexistence.
 * 使用 @dnd-kit/core 的 DndContext 包裹所有 Widget，处理拖拽生命周期，
 * 在拖拽结束时计算吸附，并管理 z-index 分层以与 Three.js 共存。
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type {
  DragStartEvent,
  DragMoveEvent,
  DragEndEvent,
} from '@dnd-kit/core';
import { AnimatePresence, motion } from 'framer-motion';
import { WIDGET_TRANSITION } from './widgetMotion';
import { useWidgetStore, WIDGET_REGISTRY, CONVERTER_SUB_TAB_WIDGET_MAP } from '../../stores/widgetStore';
import { useSettingsStore } from '../../stores/settingsStore';
import { computeSnap, computeStackPositions, resolveResponsiveWidgetWidth, resolveWidgetHeight, WIDGET_WIDTH, COLLAPSED_HEIGHT, STACK_GAP, WIDGET_PANEL_RADIUS } from '../../utils/widgetUtils';
import { WidgetPanel } from './WidgetPanel';
import { SnapGuides } from './SnapGuides';
import BasicSettingsWidgetContent from './BasicSettingsWidgetContent';
import ModelSurfaceSettingsWidgetContent from './ModelSurfaceSettingsWidgetContent';
import AdvancedSettingsWidgetContent from './AdvancedSettingsWidgetContent';
import ReliefSettingsWidgetContent from './ReliefSettingsWidgetContent';
import OutlineSettingsWidgetContent from './OutlineSettingsWidgetContent';
import CloisonneSettingsWidgetContent from './CloisonneSettingsWidgetContent';
import CoatingSettingsWidgetContent from './CoatingSettingsWidgetContent';
import KeychainLoopWidgetContent from './KeychainLoopWidgetContent';
import FridgeMagnetSettingsWidgetContent from './FridgeMagnetSettingsWidgetContent';
import PuzzleSettingsWidgetContent from './PuzzleSettingsWidgetContent';
import ActionBarWidgetContent from './ActionBarWidgetContent';
import CalibrationWidgetContent from './CalibrationWidgetContent';
import ExtractorWidgetContent from './ExtractorWidgetContent';
import LutManagerWidgetContent from './LutManagerWidgetContent';
import FiveColorWidgetContent from './FiveColorWidgetContent';
import Color2DOverlay from './Color2DOverlay';
import { ConverterDropIntentBanner, useConverterDropRouting } from '../../hooks/useConverterDropRouting';
import { useConverterDataInit } from '../../hooks/useConverterDataInit';
import { useWorkspaceMode } from '../../hooks/useWorkspaceMode';
import { useI18n } from '../../i18n/context';
import type { WidgetId } from '../../types/widget';
import type { ReactNode, ComponentType } from 'react';
import { useShallow } from 'zustand/react/shallow';

/**
 * Map from WidgetId to its content component.
 * WidgetId 到内容组件的映射。
 */
const WIDGET_CONTENT_MAP: Record<WidgetId, ComponentType> = {
  'basic-settings': BasicSettingsWidgetContent,
  'model-surface-settings': ModelSurfaceSettingsWidgetContent,
  'advanced-settings': AdvancedSettingsWidgetContent,
  'relief-settings': ReliefSettingsWidgetContent,
  'outline-settings': OutlineSettingsWidgetContent,
  'cloisonne-settings': CloisonneSettingsWidgetContent,
  'coating-settings': CoatingSettingsWidgetContent,
  'keychain-loop': KeychainLoopWidgetContent,
  'fridge-magnet-settings': FridgeMagnetSettingsWidgetContent,
  'puzzle-settings': PuzzleSettingsWidgetContent,
  'action-bar': ActionBarWidgetContent,
  'calibration': CalibrationWidgetContent,
  'extractor': ExtractorWidgetContent,
  'lut-manager': LutManagerWidgetContent,
  'five-color': FiveColorWidgetContent,
};

interface InsertPreviewState {
  edge: 'left' | 'right';
  lineY: number;
  upperId: WidgetId | null;
  lowerId: WidgetId | null;
}

interface WidgetWorkspaceProps {
  children?: ReactNode; // CenterCanvas (Three.js)
}

export function WidgetWorkspace({ children }: WidgetWorkspaceProps) {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const moveWidget = useWidgetStore((s) => s.moveWidget);
  const setWidgetPositions = useWidgetStore((s) => s.setWidgetPositions);
  const snapAndReorder = useWidgetStore((s) => s.snapAndReorder);
  const setDragging = useWidgetStore((s) => s.setDragging);
  const isDragging = useWidgetStore((s) => s.isDragging);
  const activeWidgetId = useWidgetStore((s) => s.activeWidgetId);
  const activeTab = useWidgetStore((s) => s.activeTab);
  const activeConverterSubTab = useWidgetStore((s) => s.activeConverterSubTab);
  const color2DOverlayOpen = useWidgetStore((s) => s.color2DOverlayOpen);

  // Always render converter widgets only; other tabs have their own
  // page-level rendering and do not use the widget dock system.
  // The Converter sub-tab (核心 / 高级) further narrows the visible widget set;
  // hidden widgets keep their persisted state but do not occupy dock space.
  // Converter 二级 sub-tab（核心 / 高级）进一步收窄可见 widget 集合；
  // 被收起的 widget 保留持久化状态但不占用 dock 空间。
  const converterWidgetIds = useMemo(
    () => CONVERTER_SUB_TAB_WIDGET_MAP[activeConverterSubTab] as readonly WidgetId[],
    [activeConverterSubTab],
  );
  const activeWidgetIds = converterWidgetIds;
  const activeRegistry = WIDGET_REGISTRY.filter((c) => converterWidgetIds.includes(c.id));
  // Defensive: drop ids with no store entry (stale same-version persisted
  // layout) instead of letting undefined flow into position/height math.
  // 防御：丢弃没有 store 条目的 id（同版本旧持久化布局），避免 undefined
  // 流入后续位置/高度计算导致崩溃。
  const activeWidgets = useWidgetStore(
    useShallow((s) =>
      activeWidgetIds
        .map((id) => s.widgets[id])
        .filter((w) => Boolean(w))
    )
  );

  // Initialize converter data (LUT list, bed sizes) on mount
  useConverterDataInit();

  // Global STL/OBJ vs image drop routing for the whole converter tab.
  // Mounted here (not inside panels) so it keeps working while any widget,
  // including the model texture panel, is toggled off/unmounted.
  // 整个转换页的全局 STL/OBJ 与图片拖放路由。挂在工作区层级（而非面板内），
  // 即使模型贴图等任一面板被关闭卸载，拖放导入依然可用。
  const { dropImportIntent } = useConverterDropRouting();

  const containerRef = useRef<HTMLDivElement>(null);
  const leftDockRef = useRef<HTMLDivElement>(null);
  const rightDockRef = useRef<HTMLDivElement>(null);
  const measuredHeightsRef = useRef(new Map<WidgetId, number>());
  const dragPositionRef = useRef<{ x: number; y: number } | null>(null);
  const dragSourceRef = useRef<{ edge: 'left' | 'right'; scrollTop: number } | null>(null);
  const insertPreviewRef = useRef<InsertPreviewState | null>(null);
  const isDraggingRef = useRef(false);
  const [containerWidth, setContainerWidth] = useState(0);
  const activeWidgetMap = useMemo(() => {
    const map = new Map(activeWidgets.map((widget) => [widget.id, widget]));
    return map;
  }, [activeWidgets]);
  const widgetWidth = useMemo(
    () => resolveResponsiveWidgetWidth(
      containerWidth || (typeof window !== 'undefined' ? window.innerWidth : WIDGET_WIDTH),
      workspace.mode
    ),
    [containerWidth, workspace.mode]
  );
  // Reserve the outer inset as well as the existing scrollbar clearance.
  const dockScrollWidth = widgetWidth + STACK_GAP + (workspace.isCompact ? 12 : 16);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  );

  const syncMeasuredHeights = useCallback(() => {
    const container = containerRef.current;
    if (!container) {
      measuredHeightsRef.current = new Map();
      return;
    }

    // Only measure widgets currently in the DOM. Hidden widgets (e.g. those
    // outside the active converter sub-tab) are skipped because their nodes
    // simply do not exist; previously cached heights remain valid for them.
    // 仅测量当前 DOM 中的 widget；sub-tab 隐藏的 widget 节点不存在，
    // 沨用之前缓存的高度即可。
    const nextHeights = new Map(measuredHeightsRef.current);
    for (const id of converterWidgetIds) {
      const el = container.querySelector(`[data-widget-id="${id}"]`) as HTMLElement | null;
      if (el) {
        nextHeights.set(id, el.offsetHeight);
      }
    }

    measuredHeightsRef.current = nextHeights;
  }, [converterWidgetIds]);

  // Responsive resize handler — clamp free widgets & recalculate stacks
  // Only processes widgets belonging to the current active tab to prevent
  // cross-tab stacking that pushes widgets off-screen.
  // Reads actual DOM heights for expanded widgets to avoid overlap.
  const recalculateStacks = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const { width } = container.getBoundingClientRect();
    const state = useWidgetStore.getState();
    // Only stack widgets that are actually rendered in the current sub-tab.
    // Using the full converter set would let hidden widgets push visible ones
    // off-screen via accumulated stackOrder offsets after a layout reset.
    // 仅在当前 sub-tab 可见集合上计算 stack；否则重置后隐藏 widget 的
    // stackOrder 会把可见 widget 顶到画面外。
    const currentTabIds = converterWidgetIds;
    const tabWidgets = currentTabIds
      .map((id) => state.widgets[id])
      .filter((w) => Boolean(w));

    // Force any free-floating widgets in current tab to snap to left edge
    tabWidgets
      .filter((w) => w.snapEdge === null && w.visible)
      .forEach((w) => {
        state.snapToEdge(w.id, 'left');
      });

    // Measure actual DOM heights for expanded widgets
    const measuredHeights = measuredHeightsRef.current;

    // Recalculate stack positions for snapped widgets in the active sub-tab.
    // Re-read state after potential snapToEdge calls.
    const updatedState = useWidgetStore.getState();
    const updatedTabWidgets = currentTabIds
      .map((id) => updatedState.widgets[id])
      .filter((w) => Boolean(w));
    const batchedPositions: Partial<Record<WidgetId, { x: number; y: number }>> = {};
    for (const edge of ['left', 'right'] as const) {
      const stackWidgets = updatedTabWidgets.filter((w) => w.snapEdge === edge && w.visible);
      if (stackWidgets.length > 0) {
        const positions = computeStackPositions(stackWidgets, edge, width, measuredHeights, widgetWidth);
        positions.forEach((pos, id) => {
          batchedPositions[id] = pos;
        });
      }
    }
    setWidgetPositions(batchedPositions);
  }, [setWidgetPositions, widgetWidth, converterWidgetIds]);

  // ResizeObserver to detect widget content height changes (e.g. checkbox
  // toggling extra options) and recalculate stack positions automatically.
  // Uses a debounce to avoid excessive recalculations during animations.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    const debouncedRecalc = () => {
      if (isDraggingRef.current) return;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => recalculateStacks(), 50);
    };

    const observeWidgets = () => {
      observer.disconnect();
      syncMeasuredHeights();
      const widgetEls = container.querySelectorAll('[data-widget-id]');
      widgetEls.forEach((el) => observer.observe(el));
    };

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const el = entry.target as HTMLElement;
        const id = el.dataset.widgetId as WidgetId | undefined;
        if (id) {
          measuredHeightsRef.current.set(id, el.offsetHeight);
        }
      }
      debouncedRecalc();
    });

    const mutationObs = new MutationObserver(() => {
      observeWidgets();
      debouncedRecalc();
    });
    // Only widget membership changes require rebuilding the observation list.
    // Content size changes are already covered by ResizeObserver; observing
    // the whole workspace also rescanned the docks when the 3D canvas changed.
    for (const dock of [leftDockRef.current, rightDockRef.current]) {
      if (dock?.firstElementChild) {
        mutationObs.observe(dock.firstElementChild, { childList: true });
      }
    }
    observeWidgets();

    return () => {
      observer.disconnect();
      mutationObs.disconnect();
      if (debounceTimer) clearTimeout(debounceTimer);
    };
  }, [recalculateStacks, activeTab, syncMeasuredHeights]);

  useEffect(() => {
    window.addEventListener('resize', recalculateStacks);
    window.addEventListener('widget-animation-complete', recalculateStacks);

    return () => {
      window.removeEventListener('resize', recalculateStacks);
      window.removeEventListener('widget-animation-complete', recalculateStacks);
    };
  }, [recalculateStacks]);

  // Commit sibling targets before paint so their movement starts with the
  // panel and dock height animations, including rapid direction reversals.
  const layoutKey = useWidgetStore(
    useCallback(
      (s: { widgets: Record<WidgetId, { collapsed: boolean; expandedHeight: number }> }) =>
        activeWidgetIds
          .map((id) => {
            // Treat a missing entry as collapsed/invisible instead of crashing.
            // 条目缺失时按折叠/不可见处理，避免崩溃。
            const widget = s.widgets[id];
            return `${id}:${widget?.collapsed ? 1 : 0}:${widget?.expandedHeight ?? 0}`;
          })
          .join(','),
      [activeWidgetIds]
    )
  );

  useLayoutEffect(() => {
    recalculateStacks();
  }, [layoutKey, activeTab, recalculateStacks]);

  // Auto-detect backdrop-filter support and disable blur if unsupported
  useEffect(() => {
    const supportsBlur = CSS.supports?.('backdrop-filter', 'blur(12px)') ?? false;
    if (!supportsBlur) {
      useSettingsStore.getState().setEnableBlur(false);
    }
  }, []);

  // Keep a live workspace width snapshot for right-dock local positioning.
  // The workspace can change width without a window resize (e.g. a page
  // scrollbar appears), so observe the container itself; otherwise the stale
  // snapshot shifts right-dock widgets and clips a strip of them.
  // 工作区宽度可能在窗口未 resize 时变化（如出现页面滚动条），因此直接观察容器，
  // 避免宽度快照过期导致右侧坞 widget 偏移并被裁掉一条。
  useEffect(() => {
    const container = containerRef.current;
    const updateWidth = () => {
      const width = container?.getBoundingClientRect().width ?? 0;
      setContainerWidth(width);
    };
    updateWidth();
    window.addEventListener('resize', updateWidth);
    const resizeObserver = container && typeof ResizeObserver !== 'undefined'
      ? new ResizeObserver(updateWidth)
      : null;
    if (container) resizeObserver?.observe(container);
    return () => {
      window.removeEventListener('resize', updateWidth);
      resizeObserver?.disconnect();
    };
  }, []);

  // Re-stack against the new width so widget positions match rightDockOffset.
  // 宽度变化后重新计算堆叠，使 widget 位置与 rightDockOffset 保持一致。
  useEffect(() => {
    if (containerWidth > 0) recalculateStacks();
  }, [containerWidth, recalculateStacks]);

  const leftRegistry = activeRegistry.filter((config) => activeWidgetMap.get(config.id)?.snapEdge !== 'right');
  const rightRegistry = activeRegistry.filter((config) => activeWidgetMap.get(config.id)?.snapEdge === 'right');

  const stackHeight = (edge: 'left' | 'right') => {
    const stackWidgets = activeWidgets
      .filter((w) => w.visible && (edge === 'left' ? w.snapEdge !== 'right' : w.snapEdge === 'right'))
      .sort((a, b) => a.stackOrder - b.stackOrder);
    if (stackWidgets.length === 0) return 0;
    return stackWidgets.reduce(
      (sum, w) => sum + resolveWidgetHeight(w, measuredHeightsRef.current) + STACK_GAP,
      STACK_GAP
    );
  };

  const leftStackHeight = stackHeight('left');
  const rightStackHeight = stackHeight('right');
  const rightDockOffset = Math.max(0, (containerWidth || window.innerWidth) - dockScrollWidth);

  // Whether the docks currently host visible widgets. Consumers (e.g.
  // floating action buttons over the 3D scene) read these CSS variables to
  // avoid being hidden behind dock widgets.
  // 当前左右侧坞是否承载可见 widget，用于让 3D 场景浮动按钮通过 CSS 变量避让。
  const hasVisibleLeftWidget = activeWidgets.some(
    (w) => w.visible && w.snapEdge !== 'right',
  );
  const hasVisibleRightWidget = activeWidgets.some(
    (w) => w.visible && w.snapEdge === 'right',
  );
  const leftDockWidthVar = hasVisibleLeftWidget ? `${dockScrollWidth}px` : '0px';
  const rightDockWidthVar = hasVisibleRightWidget ? `${dockScrollWidth}px` : '0px';

  const getDockScrollTop = useCallback((edge: 'left' | 'right') => {
    return edge === 'left'
      ? (leftDockRef.current?.scrollTop ?? 0)
      : (rightDockRef.current?.scrollTop ?? 0);
  }, []);

  const lockDockHorizontalScroll = useCallback((edge: 'left' | 'right') => {
    const dock = edge === 'left' ? leftDockRef.current : rightDockRef.current;
    if (dock && dock.scrollLeft !== 0) {
      dock.scrollLeft = 0;
    }
  }, []);

  const toEdgeContentY = useCallback(
    (globalDropY: number, targetEdge: 'left' | 'right') => {
      const sourceScrollTop = dragSourceRef.current?.scrollTop ?? 0;
      const targetScrollTop = getDockScrollTop(targetEdge);
      return Math.max(0, globalDropY - sourceScrollTop + targetScrollTop);
    },
    [getDockScrollTop]
  );

  const computeInsertion = useCallback(
    (draggedId: WidgetId, targetEdge: 'left' | 'right', contentDropY: number) => {
      const state = useWidgetStore.getState();
      // Only siblings currently visible in the active sub-tab participate in
      // insertion ordering; widgets hidden by sub-tab are inert.
      const currentTabIds = converterWidgetIds;
      const siblings = currentTabIds
        .map((wid) => state.widgets[wid])
        .filter((w) => Boolean(w))
        .filter((w) => w.snapEdge === targetEdge && w.visible && w.id !== draggedId)
        .sort((a, b) => a.stackOrder - b.stackOrder);

      const orderedIds: WidgetId[] = [];
      let inserted = false;
      let lineY = STACK_GAP / 2;
      let upperId: WidgetId | null = null;
      let lowerId: WidgetId | null = siblings[0]?.id ?? null;
      let prevId: WidgetId | null = null;
      let accY = STACK_GAP;

      for (const sibling of siblings) {
        const h = resolveWidgetHeight(sibling, measuredHeightsRef.current);
        const midpoint = accY + h / 2;

        if (!inserted && contentDropY < midpoint) {
          orderedIds.push(draggedId);
          inserted = true;
          upperId = prevId;
          lowerId = sibling.id;
          lineY = Math.max(0, accY - STACK_GAP / 2);
        }

        orderedIds.push(sibling.id);
        prevId = sibling.id;
        accY += h + STACK_GAP;
      }

      if (!inserted) {
        orderedIds.push(draggedId);
        upperId = prevId;
        lowerId = null;
        lineY = Math.max(0, accY - STACK_GAP / 2);
      }

      return { orderedIds, lineY, upperId, lowerId };
    },
    [converterWidgetIds]
  );

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const id = event.active.id as WidgetId;
      const widget = useWidgetStore.getState().widgets[id];
      const sourceEdge = widget?.snapEdge === 'right' ? 'right' : 'left';
      lockDockHorizontalScroll(sourceEdge);
      dragSourceRef.current = { edge: sourceEdge, scrollTop: getDockScrollTop(sourceEdge) };
      insertPreviewRef.current = null;
      isDraggingRef.current = true;
      setDragging(true, id);
    },
    [setDragging, getDockScrollTop, lockDockHorizontalScroll]
  );

  const handleDragMove = useCallback(
    (event: DragMoveEvent) => {
      const { active, delta } = event;
      const id = active.id as WidgetId;
      const widget = useWidgetStore.getState().widgets[id];
      if (widget) {
        lockDockHorizontalScroll('left');
        lockDockHorizontalScroll('right');
        const newX = widget.position.x + delta.x;
        const newY = widget.position.y + delta.y;
        dragPositionRef.current = { x: newX, y: newY };

        const width = containerRef.current?.getBoundingClientRect().width ?? containerWidth;
        const targetEdge = computeSnap(newX, newX + widgetWidth, width);
        const contentDropY = toEdgeContentY(newY, targetEdge);
        const insertion = computeInsertion(id, targetEdge, contentDropY);
        const visualLineY = Math.max(0, insertion.lineY - getDockScrollTop(targetEdge));
        const prev = insertPreviewRef.current;
        if (
          !prev ||
          prev.edge !== targetEdge ||
          prev.lineY !== visualLineY ||
          prev.upperId !== insertion.upperId ||
          prev.lowerId !== insertion.lowerId
        ) {
          insertPreviewRef.current = {
            edge: targetEdge,
            lineY: visualLineY,
            upperId: insertion.upperId,
            lowerId: insertion.lowerId,
          };
        }
      }
    },
    [containerWidth, widgetWidth, toEdgeContentY, computeInsertion, getDockScrollTop, lockDockHorizontalScroll]
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, delta } = event;
      const id = active.id as WidgetId;
      const state = useWidgetStore.getState();
      const widget = state.widgets[id];
      const container = containerRef.current;

      if (!widget || !container) {
        setDragging(false);
        dragPositionRef.current = null;
        return;
      }

      const containerRect = container.getBoundingClientRect();
      const newX = widget.position.x + delta.x;
      const newY = widget.position.y + delta.y;
      const widgetLeft = newX;
      const widgetRight = newX + widgetWidth;

      const targetEdge = computeSnap(widgetLeft, widgetRight, containerRect.width);
      const contentDropY = toEdgeContentY(newY, targetEdge);
      const insertion = computeInsertion(id, targetEdge, contentDropY);

      // First, move widget to the actual drop position (position + delta).
      // This gives framer-motion the correct starting point for the snap
      // animation. recalculateStacks (next frame) will update to the final
      // stacked position, producing a smooth visual transition.
      moveWidget(id, { x: newX, y: newY });
      snapAndReorder(id, targetEdge, insertion.orderedIds);

      // Reset isDraggingRef BEFORE scheduling recalculateStacks so the
      // ResizeObserver guard won't block the recalculation.
      isDraggingRef.current = false;
      requestAnimationFrame(() => recalculateStacks());

      setDragging(false);
      dragPositionRef.current = null;
      dragSourceRef.current = null;
      insertPreviewRef.current = null;
    },
    [moveWidget, snapAndReorder, setDragging, recalculateStacks, toEdgeContentY, computeInsertion, widgetWidth]
  );

  const handleDragCancel = useCallback(
    () => {
      isDraggingRef.current = false;
      setDragging(false);
      dragPositionRef.current = null;
      dragSourceRef.current = null;
      insertPreviewRef.current = null;
    },
    [setDragging]
  );

  return (
    <>
      <DndContext
        sensors={sensors}
        onDragStart={handleDragStart}
        onDragMove={handleDragMove}
        onDragEnd={handleDragEnd}
        onDragCancel={handleDragCancel}
      >
        <div
          ref={containerRef}
          className="relative w-full h-full overflow-hidden"
          style={{
            pointerEvents: isDragging ? 'all' : undefined,
            ['--lumina-left-dock-width' as string]: leftDockWidthVar,
            ['--lumina-right-dock-width' as string]: rightDockWidthVar,
          }}
        >
          {/* Center Canvas (Three.js / Extractor) — z-10 */}
          <div className="absolute inset-0 z-10 flex flex-col" style={{ pointerEvents: 'auto' }}>
            {children}
          </div>

          {/* Global drop intent banner — z-[80], fixed to viewport top */}
          <ConverterDropIntentBanner intent={dropImportIntent} />

          {/* 2D Color Overlay — z-[45], above docks, covers 3D scene */}
          <AnimatePresence>
            {color2DOverlayOpen && <Color2DOverlay />}
          </AnimatePresence>

          {/* Snap Guides — z-20 */}
          <SnapGuides
            isDragging={isDragging}
            dragPositionRef={dragPositionRef}
            insertPreviewRef={insertPreviewRef}
            containerRef={containerRef}
            containerWidth={containerWidth}
            widgetWidth={widgetWidth}
          />

          {/* Left Dock Layer — z-30 */}
          <motion.div
            ref={leftDockRef}
            initial={false}
            animate={{ height: leftStackHeight }}
            transition={{ height: WIDGET_TRANSITION }}
            className="dock-scrollbar dock-scrollbar-hover absolute top-0 left-0 z-30 max-h-full overflow-x-hidden overscroll-y-contain"
            onScroll={() => lockDockHorizontalScroll('left')}
            data-testid="left-dock"
            style={{
              width: dockScrollWidth,
              pointerEvents: 'auto',
              overflowX: 'hidden',
              overscrollBehaviorX: 'none',
            }}
          >
            <motion.div className="relative min-h-full" initial={false} animate={{ height: leftStackHeight }} transition={{ height: WIDGET_TRANSITION }}>
              {leftRegistry.map((config) => {
                const ContentComponent = WIDGET_CONTENT_MAP[config.id];
                return (
                  <WidgetPanel
                    key={config.id}
                    widgetId={config.id}
                    titleKey={config.titleKey}
                    dockOffsetX={0}
                    width={widgetWidth}
                  >
                    <ContentComponent />
                  </WidgetPanel>
                );
              })}
            </motion.div>
          </motion.div>

          {/* Right Dock Layer — z-30 */}
          <motion.div
            ref={rightDockRef}
            initial={false}
            animate={{ height: rightStackHeight }}
            transition={{ height: WIDGET_TRANSITION }}
            className="dock-scrollbar dock-scrollbar-hover absolute top-0 right-0 z-30 max-h-full overflow-x-hidden overscroll-y-contain"
            onScroll={() => lockDockHorizontalScroll('right')}
            data-testid="right-dock"
            style={{
              width: dockScrollWidth,
              pointerEvents: 'auto',
              overflowX: 'hidden',
              overscrollBehaviorX: 'none',
            }}
          >
            <motion.div className="relative min-h-full" initial={false} animate={{ height: rightStackHeight }} transition={{ height: WIDGET_TRANSITION }}>
              {rightRegistry.map((config) => {
                const ContentComponent = WIDGET_CONTENT_MAP[config.id];
                return (
                  <WidgetPanel
                    key={config.id}
                    widgetId={config.id}
                    titleKey={config.titleKey}
                    dockOffsetX={rightDockOffset}
                    width={widgetWidth}
                  >
                    <ContentComponent />
                  </WidgetPanel>
                );
              })}
            </motion.div>
          </motion.div>

          {/* DragOverlay — z-40 */}
          <DragOverlay>
            {activeWidgetId ? (
              <div
                className="panel-card z-40 opacity-90"
                style={{ width: widgetWidth, height: COLLAPSED_HEIGHT, borderRadius: WIDGET_PANEL_RADIUS }}
              >
                <div className="px-3 py-2 text-sm font-medium text-slate-600 dark:text-slate-300">
                  {t(WIDGET_REGISTRY.find((w) => w.id === activeWidgetId)?.titleKey ?? activeWidgetId)}
                </div>
              </div>
            ) : null}
          </DragOverlay>
        </div>
      </DndContext>
    </>
  );
}
