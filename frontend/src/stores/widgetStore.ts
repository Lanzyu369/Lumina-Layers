/**
 * Widget layout store for the floating widget workspace.
 * 浮动 Widget 工作区布局状态管理。
 *
 * Manages widget positions, collapse states, snap edges, and stack ordering.
 * Uses Zustand persist middleware to save layout to localStorage.
 * 管理 Widget 位置、折叠状态、吸附边缘和堆叠排序。
 * 使用 Zustand persist middleware 将布局持久化到 localStorage。
 */

import { create } from "zustand";
import { persist, subscribeWithSelector } from "zustand/middleware";
import { EXPANDED_HEIGHT } from "../utils/widgetUtils";
import type {
  WidgetId,
  WidgetLayoutState,
  WidgetStore,
  WidgetConfig,
  TabId,
  ConverterSubTabId,
} from "../types/widget";

// ===== TAB → Widget 映射 =====

export const TAB_WIDGET_MAP: Record<TabId, WidgetId[]> = {
  converter: [
    "basic-settings",
    "advanced-settings",
    "relief-settings",
    "outline-settings",
    "cloisonne-settings",
    "coating-settings",
    "keychain-loop",
    "fridge-magnet-settings",
    "puzzle-settings",
    "action-bar",
  ],
  // Material/LUT tabs are rendered as full-page panels (in the MLS frontend),
  // not as dock widgets, so they own no WidgetId entries here.
  // 耗材/LUT 标签在 MLS 前端以整页面板渲染，非可停靠 widget，故无 WidgetId。
  calibration: [],
  extractor: [],
  "gradient-card-generate": [],
  "gradient-card-extract": [],
  "material-library": [],
  "material-recipe": [],
  "lut-manager": [],
  "lut-details": [],
  "lut-compare": [],
  "five-color": [],
  vectorizer: [],
  settings: [],
};

// ===== Main-app renderable tabs =====
// The main converter app (port :5174) only renders these three tabs; every
// other TabId belongs to the standalone Material-LUT Studio (MLS) frontend
// (port :5180), which reuses this same store as its router. Because the
// persist migration/rehydrate logic below is shared by BOTH entries, it must
// stay permissive (it cannot coerce MLS tabs away, or MLS would lose its
// last-tab persistence on every reload). Each app instead coerces a foreign
// ``activeTab`` to its own default at its boundary: MLS does it in MlsApp,
// the main app does it via :func:`isMainRenderableTab` in App.tsx.
// 主转换器应用（:5174）只渲染这三个标签；其余 TabId 属于独立的 MLS 前端
// （:5180），后者复用同一个 store 作为路由。由于下方的持久化迁移/水合逻辑被两个
// 入口共享，它必须保持宽松（不能把 MLS 标签清掉，否则 MLS 每次刷新都会丢失上次
// 标签）。两个应用各自在边界把外来的 ``activeTab`` 归位到自己的默认值：MLS 在
// MlsApp 处理，主应用通过 App.tsx 中的 :func:`isMainRenderableTab` 处理。
export const MAIN_RENDERABLE_TABS: ReadonlySet<TabId> = new Set<TabId>([
  "converter",
  "vectorizer",
  "settings",
]);

/**
 * Whether a tab has renderable content in the main converter app.
 * 判断某标签在主转换器应用中是否有可渲染内容。
 *
 * A persisted ``activeTab`` pointing at an MLS-only material/LUT tab (e.g.
 * ``calibration``/``lut-manager`` from before the MLS decouple) has no content
 * branch in App.tsx, so the user would land on an empty workspace. The main
 * app calls this to coerce such tabs back to ``converter``.
 * 持久化的 ``activeTab`` 若指向 MLS 专用的耗材/LUT 标签（如解耦前遗留的
 * ``calibration``/``lut-manager``），在 App.tsx 中没有对应内容分支，用户会落到空
 * 工作区。主应用据此把这类标签归位到 ``converter``。
 */
export function isMainRenderableTab(tab: TabId): boolean {
  return MAIN_RENDERABLE_TABS.has(tab);
}

// ===== Converter sub-tab → Widget 映射 =====
// 核心设置：只有基础设置、操作栏、高级设置 3 个面板，专注于 3MF 生成所需的主要参数。
// 颜色调整：dock 中不显示任何 widget；改由 Color2DOverlay 全屏接管。
// 高级功能：可访问全部 10 个 widget，承载所有进阶可选功能。
export const CONVERTER_SUB_TAB_WIDGET_MAP: Record<ConverterSubTabId, readonly WidgetId[]> = {
  core: ["basic-settings", "action-bar", "advanced-settings"],
  color: [],
  advanced: [
    "basic-settings",
    "advanced-settings",
    "relief-settings",
    "outline-settings",
    "cloisonne-settings",
    "coating-settings",
    "keychain-loop",
    "fridge-magnet-settings",
    "puzzle-settings",
    "action-bar",
  ],
};

// ===== 默认布局 =====

export const DEFAULT_LAYOUT: Record<WidgetId, WidgetLayoutState> = {
  // --- Converter 页面 ---
  // 左侧：基础设置（展开）
  "basic-settings": {
    id: "basic-settings",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "left",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
  // 右侧：操作栏（展开）+ 其余 6 个（折叠）
  "action-bar": {
    id: "action-bar",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "right",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "keychain-loop": {
    id: "keychain-loop",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 1,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "fridge-magnet-settings": {
    id: "fridge-magnet-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 2,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "puzzle-settings": {
    id: "puzzle-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 3,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "coating-settings": {
    id: "coating-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 4,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "cloisonne-settings": {
    id: "cloisonne-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 5,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "outline-settings": {
    id: "outline-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 6,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "relief-settings": {
    id: "relief-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 7,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "advanced-settings": {
    id: "advanced-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 8,
    expandedHeight: EXPANDED_HEIGHT,
  },
};

// ===== Widget 注册表（静态配置，不含 component 字段）=====

export const WIDGET_REGISTRY: Omit<WidgetConfig, "component">[] = [
  // Converter 页面
  {
    id: "basic-settings",
    titleKey: "widget.basicSettings",
    icon: "settings",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "advanced-settings",
    titleKey: "widget.advancedSettings",
    icon: "sliders",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "relief-settings",
    titleKey: "widget.reliefSettings",
    icon: "layers",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "outline-settings",
    titleKey: "widget.outlineSettings",
    icon: "pen-tool",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "cloisonne-settings",
    titleKey: "widget.cloisonneSettings",
    icon: "hexagon",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "coating-settings",
    titleKey: "widget.coatingSettings",
    icon: "droplet",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "keychain-loop",
    titleKey: "widget.keychainLoop",
    icon: "link",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "fridge-magnet-settings",
    titleKey: "widget.fridgeMagnetSettings",
    icon: "circle",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "puzzle-settings",
    titleKey: "widget.puzzleSettings",
    icon: "grid",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "action-bar",
    titleKey: "widget.actionBar",
    icon: "play",
    defaultWidth: 350,
    minWidth: 300,
  },
];

// ===== Store =====

/**
 * Sanitize a persisted widget payload so it never references removed tabs or
 * widgets. Drops widget layouts whose id is no longer in DEFAULT_LAYOUT and
 * resets an ``activeTab`` that is no longer a valid TabId back to "converter".
 * 清洗持久化载荷，确保不引用已删除的标签/widget：丢弃 DEFAULT_LAYOUT 中已不存在
 * 的 widget 布局，并把失效的 ``activeTab`` 重置为 "converter"。
 */
function _sanitizePersistedState(persistedState: unknown): WidgetStore {
  const state =
    typeof persistedState === "object" && persistedState !== null
      ? (persistedState as { widgets?: Record<string, WidgetLayoutState>; activeTab?: TabId })
      : {};

  const validWidgetIds = new Set(Object.keys(DEFAULT_LAYOUT));
  const sourceWidgets = (state.widgets ?? {}) as Record<string, WidgetLayoutState>;
  const widgets: Record<string, WidgetLayoutState> = {};
  for (const [id, layout] of Object.entries(sourceWidgets)) {
    if (validWidgetIds.has(id)) {
      widgets[id] = layout;
    }
  }
  // Ensure every current widget exists (fill any missing from defaults).
  for (const id of Object.keys(DEFAULT_LAYOUT)) {
    if (!widgets[id]) {
      widgets[id] = { ...DEFAULT_LAYOUT[id as WidgetId] };
    }
  }

  const validTab = (Object.keys(TAB_WIDGET_MAP) as TabId[]).includes(
    state.activeTab as TabId,
  );

  return {
    ...(state as object),
    widgets,
    activeTab: validTab ? (state.activeTab as TabId) : "converter",
  } as WidgetStore;
}

export const useWidgetStore = create<WidgetStore>()(
  subscribeWithSelector(
    persist(
      (set) => ({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
      activeTab: "converter" as TabId,
      activeConverterSubTab: "core" as ConverterSubTabId,
      color2DOverlayOpen: false,
      canvasInteracting: false,

      /**
       * Set the active TAB page.
       * 设置当前激活的 TAB 页面。
       */
      setActiveTab: (tab: TabId) => {
        set({ activeTab: tab });
      },

      /**
       * Set the active Converter sub-tab.
       * Switching to 'color' opens the Color2DOverlay; leaving 'color' closes it.
       * Sub-tab and overlay state stay in lockstep so the overlay behaves like a
       * full-bleed page rather than a modal.
       *
       * 设置 Converter 页面下的二级 sub-tab。
       * 切到「颜色调整」即打开 2D 颜色覆盖层；离开「颜色调整」即关闭，
       * 让覆盖层像普通子页面一样进入/退出，而不是模态弹层。
       */
      setActiveConverterSubTab: (subTab: ConverterSubTabId) => {
        set({
          activeConverterSubTab: subTab,
          color2DOverlayOpen: subTab === "color",
        });
      },

      /**
       * Update widget position.
       * 更新 Widget 位置。
       */
      moveWidget: (id: WidgetId, position: { x: number; y: number }) => {
        set((state) => ({
          widgets: {
            ...state.widgets,
            [id]: { ...state.widgets[id], position },
          },
        }));
      },

      /**
       * Batch update widget positions in a single store commit.
       * 批量更新 Widget 位置，合并为一次 store 提交。
       */
      setWidgetPositions: (
        positions: Partial<Record<WidgetId, { x: number; y: number }>>,
      ) => {
        set((state) => {
          const entries = Object.entries(positions) as [
            WidgetId,
            { x: number; y: number },
          ][];
          if (entries.length === 0) return state;

          let changed = false;
          const widgets = { ...state.widgets };

          for (const [id, position] of entries) {
            const current = widgets[id];
            if (
              !current ||
              (current.position.x === position.x &&
                current.position.y === position.y)
            ) {
              continue;
            }
            widgets[id] = { ...current, position };
            changed = true;
          }

          return changed ? { widgets } : state;
        });
      },

      /**
       * Toggle widget collapsed state.
       * 切换 Widget 折叠状态。
       */
      toggleCollapse: (id: WidgetId) => {
        set((state) => ({
          widgets: {
            ...state.widgets,
            [id]: {
              ...state.widgets[id],
              collapsed: !state.widgets[id].collapsed,
            },
          },
        }));
      },

      /**
       * Toggle widget visibility.
       * 切换 Widget 可见性。
       */
      toggleVisible: (id: WidgetId) => {
        set((state) => ({
          widgets: {
            ...state.widgets,
            [id]: { ...state.widgets[id], visible: !state.widgets[id].visible },
          },
        }));
      },

      /**
       * Snap widget to a screen edge and assign next stack order.
       * 将 Widget 吸附到屏幕边缘并分配下一个堆叠顺序。
       *
       * Only considers widgets belonging to the same TAB when computing maxOrder,
       * preventing cross-tab stackOrder inflation that pushes widgets off-screen.
       * 仅考虑同一 TAB 页的 Widget 计算 maxOrder，防止跨 TAB 堆叠顺序膨胀导致 Widget 超出屏幕。
       */
      snapToEdge: (id: WidgetId, edge: "left" | "right") => {
        set((state) => {
          // Find which tab this widget belongs to
          const ownerTab = (Object.keys(TAB_WIDGET_MAP) as TabId[]).find(
            (tab) => TAB_WIDGET_MAP[tab].includes(id),
          );
          const tabWidgetIds = ownerTab ? TAB_WIDGET_MAP[ownerTab] : [];

          // Only consider widgets from the same tab for maxOrder calculation
          const maxOrder = Object.values(state.widgets)
            .filter(
              (w) =>
                w.snapEdge === edge &&
                w.id !== id &&
                tabWidgetIds.includes(w.id),
            )
            .reduce((max, w) => Math.max(max, w.stackOrder), -1);

          return {
            widgets: {
              ...state.widgets,
              [id]: {
                ...state.widgets[id],
                snapEdge: edge,
                stackOrder: maxOrder + 1,
              },
            },
          };
        });
      },

      /**
       * Detach widget from edge, making it free-floating.
       * 将 Widget 从边缘脱离，恢复为自由浮动。
       */
      detachFromEdge: (id: WidgetId) => {
        set((state) => ({
          widgets: {
            ...state.widgets,
            [id]: { ...state.widgets[id], snapEdge: null, stackOrder: -1 },
          },
        }));
      },

      /**
       * Set dragging state and active widget.
       * 设置拖拽状态和活动 Widget。
       */
      setDragging: (isDragging: boolean, activeId?: WidgetId) => {
        set({ isDragging, activeWidgetId: activeId ?? null });
      },

      /**
       * Update the pre-measured expanded height for a widget.
       * 更新 Widget 预测量的展开高度。
       */
      setExpandedHeight: (id: WidgetId, height: number) => {
        set((state) => {
          // Only update if height actually changed to avoid unnecessary re-renders
          if (state.widgets[id].expandedHeight === height) return state;
          return {
            widgets: {
              ...state.widgets,
              [id]: { ...state.widgets[id], expandedHeight: height },
            },
          };
        });
      },

      /**
       * Auto-arrange all free-floating visible widgets to the left edge.
       * 将所有自由浮动的可见 Widget 自动收纳到左侧边缘。
       */
      autoArrange: () => {
        set((state) => {
          const updated = { ...state.widgets };
          const floatingVisible = Object.values(updated).filter(
            (w) => w.snapEdge === null && w.visible,
          );

          if (floatingVisible.length === 0) return state;

          const maxOrder = Object.values(updated)
            .filter((w) => w.snapEdge === "left")
            .reduce((max, w) => Math.max(max, w.stackOrder), -1);

          let nextOrder = maxOrder + 1;
          for (const widget of floatingVisible) {
            updated[widget.id] = {
              ...updated[widget.id],
              snapEdge: "left",
              stackOrder: nextOrder++,
            };
          }

          return { widgets: updated };
        });
      },

      /**
       * Reset all widgets to default layout, preserving measured expandedHeight.
       *
       * `expandedHeight` is a ResizeObserver-derived runtime measurement, not a
       * user-facing layout setting. If we reset it to the static default
       * (EXPANDED_HEIGHT = 400) the wrapper instantly clips taller widgets
       * (e.g. BasicSettings ≈ 650px) and the observer never re-fires until
       * the user manually toggles collapse — visible as a one-frame "snap and
       * shrink" right after Reset Layout.
       *
       * 重置 widget 布局，但保留已测得的 expandedHeight。
       * expandedHeight 是 ResizeObserver 在运行时测量得到的派生值，并非
       * 用户可配置的布局项；如果一并重置成静态默认 400，wrapper 会瞬间
       * 把基础设置（~650px）等内容裁短，且 observer 不会再触发，必须
       * 手动收起/展开才能恢复——用户可见的「按下重置就被裁短」即此。
       */
      resetLayout: () => {
        set((state) => {
          const widgets = {} as Record<WidgetId, WidgetLayoutState>;
          (Object.keys(DEFAULT_LAYOUT) as WidgetId[]).forEach((id) => {
            const measured = state.widgets[id]?.expandedHeight;
            widgets[id] = {
              ...DEFAULT_LAYOUT[id],
              expandedHeight:
                typeof measured === "number" && measured > 0
                  ? measured
                  : DEFAULT_LAYOUT[id].expandedHeight,
            };
          });
          return {
            widgets,
            isDragging: false,
            activeWidgetId: null,
          };
        });
      },

      /**
       * Reorder widgets on a given edge based on ordered ID array.
       * 根据有序 ID 数组重新排列指定边缘上的 Widget。
       */
      reorderStack: (edge: "left" | "right", orderedIds: WidgetId[]) => {
        set((state) => {
          const updated = { ...state.widgets };
          orderedIds.forEach((id, index) => {
            if (updated[id] && updated[id].snapEdge === edge) {
              updated[id] = { ...updated[id], stackOrder: index };
            }
          });
          return { widgets: updated };
        });
      },

      /**
       * Atomically snap dragged widget and reorder target edge stack.
       * 原子化执行吸附与重排，避免中间态导致的错误动画。
       */
      snapAndReorder: (
        id: WidgetId,
        edge: "left" | "right",
        orderedIds: WidgetId[],
      ) => {
        set((state) => {
          const updated = { ...state.widgets };

          orderedIds.forEach((wid, index) => {
            if (!updated[wid]) return;
            updated[wid] = {
              ...updated[wid],
              snapEdge: edge,
              stackOrder: index,
            };
          });

          if (updated[id] && !orderedIds.includes(id)) {
            updated[id] = { ...updated[id], snapEdge: edge };
          }

          return { widgets: updated };
        });
      },

      /**
       * Open the 2D color overlay and switch the converter sub-tab to 'color'.
       * 打开 2D 颜色覆盖层，并把 converter 二级 sub-tab 切到「颜色调整」。
       */
      openColor2DOverlay: () => {
        set({ color2DOverlayOpen: true, activeConverterSubTab: "color" });
      },

      /**
       * Close the 2D color overlay. If the converter is currently sitting on
       * the 'color' sub-tab, fall back to 'core' so the user lands on a real
       * settings page rather than an empty dock.
       *
       * 关闭 2D 颜色覆盖层。如果 converter 当前位于「颜色调整」sub-tab，
       * 则自动回退到「核心设置」，避免用户看到一个空的工作区。
       */
      closeColor2DOverlay: () => {
        set((state) => ({
          color2DOverlayOpen: false,
          activeConverterSubTab:
            state.activeConverterSubTab === "color"
              ? "core"
              : state.activeConverterSubTab,
        }));
      },

      setCanvasInteracting: (interacting: boolean) => {
        set({ canvasInteracting: interacting });
      },
    }),
    {
      name: "lumina-widget-layout",
      version: 8,
      migrate: (persistedState, version) => {
        type PersistedWidgetState = {
          widgets?: Record<WidgetId, WidgetLayoutState>;
          activeTab?: TabId;
          colorWorkstationCollapsed?: boolean;
          color2DOverlayOpen?: boolean;
        };

        if (version < 3) {
          return { widgets: { ...DEFAULT_LAYOUT }, activeTab: "converter" };
        }
        if (version === 3 || version === 4 || version === 5 || version === 6) {
          const state =
            typeof persistedState === "object" && persistedState !== null
              ? (persistedState as PersistedWidgetState)
              : {};
          const widgets: Record<string, WidgetLayoutState> = {
            ...((state.widgets ?? {}) as Record<string, WidgetLayoutState>),
          };
          delete widgets["palette-panel"];
          delete widgets["lut-color-grid"];
          if (!widgets["fridge-magnet-settings"]) {
            widgets["fridge-magnet-settings"] = {
              ...DEFAULT_LAYOUT["fridge-magnet-settings"],
            };
          }
          if (!widgets["puzzle-settings"]) {
            widgets["puzzle-settings"] = {
              ...DEFAULT_LAYOUT["puzzle-settings"],
            };
          }
          // Recalculate stackOrder for converter widgets on both dock edges.
          const converterIds = TAB_WIDGET_MAP.converter;
          const reorderConverterEdge = (edge: "left" | "right") => {
            const edgeWidgets = converterIds
              .filter((id) => widgets[id]?.snapEdge === edge)
              .sort((a, b) => {
                const orderDiff =
                  (widgets[a]?.stackOrder ?? 0) - (widgets[b]?.stackOrder ?? 0);
                if (orderDiff !== 0) {
                  return orderDiff;
                }
                return converterIds.indexOf(a) - converterIds.indexOf(b);
              });

            edgeWidgets.forEach((id, index) => {
              if (widgets[id]) {
                widgets[id] = { ...widgets[id], stackOrder: index };
              }
            });
          };

          reorderConverterEdge("left");
          reorderConverterEdge("right");
          // Drop the deprecated `colorWorkstationCollapsed` field if it lingers in
          // the persisted payload; the entry has moved to a top-level secondary tab.
          // 颜色入口已迁移至顶部二级 tab，丢弃过时的折叠状态字段。
          const { colorWorkstationCollapsed: _drop, ...rest } = state;
          void _drop;
          return _sanitizePersistedState({ ...rest, widgets });
        }
        // v7 -> v8: Material/LUT tabs & widgets moved to the standalone MLS
        // service (Route B). Drop their persisted widget layouts and reset a
        // removed ``activeTab`` to "converter" so old localStorage never points
        // at a tab/widget that no longer exists (which crashed WidgetToggles).
        // v7 -> v8：耗材/LUT 标签与 widget 已迁移到独立 MLS 服务。丢弃它们的持久化
        // 布局，并把已删除的 ``activeTab`` 重置为 "converter"，避免旧 localStorage
        // 指向不存在的标签/widget（曾导致 WidgetToggles 崩溃白屏）。
        return _sanitizePersistedState(persistedState);
      },
      partialize: (state) => ({
        widgets: state.widgets,
        activeTab: state.activeTab,
      }),
      // Defensive guard for any payload (even at the current version) whose
      // activeTab/widgets reference removed entries: snap them back to valid
      // values on rehydrate so the UI never reads ``undefined``.
      // 二次防护：无论何种持久化载荷，重新水合时把失效的 activeTab/widgets 归位，
      // 确保 UI 不会读到 ``undefined``。
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        const validTab = (Object.keys(TAB_WIDGET_MAP) as TabId[]).includes(
          state.activeTab,
        );
        if (!validTab) {
          state.activeTab = "converter";
        }
      },
    },
    ),
  ),
);
