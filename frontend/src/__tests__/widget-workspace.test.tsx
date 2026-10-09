/**
 * Unit tests for Widget workspace components.
 * Widget 工作区组件单元测试。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { I18nProvider } from '../i18n/context';
import { WidgetHeader } from '../components/widget/WidgetHeader';
import { useWidgetStore, DEFAULT_LAYOUT, TAB_WIDGET_MAP, CONVERTER_SUB_TAB_WIDGET_MAP } from '../stores/widgetStore';
import { computeDockBottomInset, computeStackPositions, resolveResponsiveWidgetWidth, WIDGET_WIDTH } from '../utils/widgetUtils';

/** Render helper that wraps component in I18nProvider. */
function renderWithI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

describe('Widget Workspace Unit Tests', () => {
  describe('responsive widget sizing', () => {
    it('caps widget width at the default width on wide workspaces', () => {
      expect(resolveResponsiveWidgetWidth(2200)).toBe(WIDGET_WIDTH);
    });

    it('shrinks widget width on narrow workspaces while keeping a usable minimum', () => {
      const width = resolveResponsiveWidgetWidth(900);
      expect(width).toBeGreaterThanOrEqual(280);
      expect(width).toBeLessThan(WIDGET_WIDTH);
    });
  });
  beforeEach(() => {
    useWidgetStore.setState({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
    });
  });

  // ===== WidgetHeader ARIA 属性 =====
  describe('WidgetHeader ARIA attributes', () => {
    it('renders with correct ARIA role and attributes when expanded', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={false}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      expect(header).toBeInTheDocument();
      expect(header).toHaveAttribute('aria-expanded', 'true');
      expect(header).toHaveAttribute('aria-label');
      expect(header).toHaveAttribute('tabindex', '0');
    });

    it('sets aria-expanded to false when collapsed', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={true}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      expect(header).toHaveAttribute('aria-expanded', 'false');
    });
  });

  // ===== 键盘 Enter 触发折叠 =====
  describe('WidgetHeader keyboard interaction', () => {
    it('calls onToggleCollapse when Enter key is pressed', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={false}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      fireEvent.keyDown(header, { key: 'Enter' });
      expect(onToggle).toHaveBeenCalledTimes(1);
    });

    it('does not call onToggleCollapse for other keys', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={false}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      fireEvent.keyDown(header, { key: 'Space' });
      fireEvent.keyDown(header, { key: 'Escape' });
      expect(onToggle).not.toHaveBeenCalled();
    });
  });

  // ===== 双击触发折叠 =====
  describe('WidgetHeader double-click', () => {
    it('calls onToggleCollapse on double click', () => {
      const onToggle = vi.fn();
      renderWithI18n(
        <WidgetHeader
          widgetId="basic-settings"
          titleKey="widget.basicSettings"
          collapsed={false}
          onToggleCollapse={onToggle}
        />
      );

      const header = screen.getByRole('heading', { level: 2 });
      fireEvent.doubleClick(header);
      expect(onToggle).toHaveBeenCalledTimes(1);
    });
  });

  // ===== 默认布局加载 =====
  describe('Default layout loading', () => {
    it('loads default layout when store is reset', () => {
      const state = useWidgetStore.getState();
      expect(state.widgets['basic-settings'].visible).toBe(true);
      expect(state.widgets['basic-settings'].collapsed).toBe(false);
      expect(state.widgets['basic-settings'].snapEdge).toBe('left');
      expect(state.widgets['action-bar'].collapsed).toBe(false);
    });

    it('has all 15 widgets in default layout', () => {
      const state = useWidgetStore.getState();
      const widgetIds = Object.keys(state.widgets);
      expect(widgetIds).toHaveLength(15);
      expect(widgetIds).toContain('basic-settings');
      expect(widgetIds).toContain('model-surface-settings');
      expect(widgetIds).toContain('fridge-magnet-settings');
      expect(widgetIds).toContain('puzzle-settings');
      expect(widgetIds).toContain('action-bar');
      expect(widgetIds).toContain('calibration');
      expect(widgetIds).toContain('extractor');
      expect(widgetIds).toContain('lut-manager');
      expect(widgetIds).toContain('five-color');
      // palette-panel and lut-color-grid have been merged into ColorWorkstation
      expect(widgetIds).not.toContain('palette-panel');
      expect(widgetIds).not.toContain('lut-color-grid');
    });

    it('registers the model texture widget as visible by default and only under the advanced sub-tab', () => {
      const state = useWidgetStore.getState();
      const modelSurface = state.widgets['model-surface-settings'];
      expect(modelSurface.visible).toBe(true);
      expect(modelSurface.collapsed).toBe(false);
      expect(modelSurface.snapEdge).toBe('left');

      expect(TAB_WIDGET_MAP.converter).toContain('model-surface-settings');
      expect(CONVERTER_SUB_TAB_WIDGET_MAP.advanced).toContain('model-surface-settings');
      // Must stay absent from 核心设置: the panel lives in the Creative Center sub-tab.
      // 必须不出现在「核心设置」：该面板位于创意中心子页签。
      expect(CONVERTER_SUB_TAB_WIDGET_MAP.core).not.toContain('model-surface-settings');
    });

    it('orders model-surface-settings above basic-settings in every default-order source', () => {
      // Both left-dock widgets ship at stackOrder 0; computeStackPositions
      // breaks the tie with a stable sort over CONVERTER_SUB_TAB_WIDGET_MAP
      // iteration order. So DEFAULT_LAYOUT, TAB_WIDGET_MAP, the sub-tab map,
      // and (for DOM order) WIDGET_REGISTRY must all list model first.
      // 两个左坞 widget 默认同为 stackOrder 0；computeStackPositions 依靠
      // 稳定排序按映射遍历顺序决胜，因此各处顺序都必须把模型贴图排在前面。
      expect(DEFAULT_LAYOUT['model-surface-settings'].stackOrder).toBe(0);
      expect(DEFAULT_LAYOUT['basic-settings'].stackOrder).toBe(0);

      expect(
        Object.keys(DEFAULT_LAYOUT).indexOf('model-surface-settings'),
      ).toBeLessThan(Object.keys(DEFAULT_LAYOUT).indexOf('basic-settings'));
      expect(
        TAB_WIDGET_MAP.converter.indexOf('model-surface-settings'),
      ).toBeLessThan(TAB_WIDGET_MAP.converter.indexOf('basic-settings'));
      expect(
        CONVERTER_SUB_TAB_WIDGET_MAP.advanced.indexOf('model-surface-settings'),
      ).toBeLessThan(
        CONVERTER_SUB_TAB_WIDGET_MAP.advanced.indexOf('basic-settings'),
      );
    });

    it('stacks model-surface-settings above basic-settings on the left dock', () => {
      const state = useWidgetStore.getState();
      const leftWidgets = CONVERTER_SUB_TAB_WIDGET_MAP.advanced
        .map((id) => state.widgets[id])
        .filter((w) => w && w.snapEdge !== 'right' && w.visible);
      const positions = computeStackPositions(leftWidgets, 'left', 1600);

      expect(positions.get('model-surface-settings')!.y).toBeLessThan(
        positions.get('basic-settings')!.y,
      );
    });
  });

  // ===== 批量位置更新 =====
  describe('Widget store batched position updates', () => {
    it('updates multiple widget positions in one action', () => {
      const { setWidgetPositions } = useWidgetStore.getState();

      setWidgetPositions({
        'basic-settings': { x: 12, y: 24 },
        'action-bar': { x: 240, y: 360 },
      });

      const state = useWidgetStore.getState();
      expect(state.widgets['basic-settings'].position).toEqual({ x: 12, y: 24 });
      expect(state.widgets['action-bar'].position).toEqual({ x: 240, y: 360 });
    });

    it('keeps unrelated widget positions unchanged during batched updates', () => {
      const { widgets, setWidgetPositions } = useWidgetStore.getState();
      const originalActionBarPosition = widgets['action-bar'].position;

      setWidgetPositions({
        'basic-settings': { x: 64, y: 96 },
      });

      const state = useWidgetStore.getState();
      expect(state.widgets['action-bar'].position).toEqual(originalActionBarPosition);
      expect(state.widgets['basic-settings'].position).toEqual({ x: 64, y: 96 });
    });
  });

  describe('Dock avoidance geometry', () => {
    it('returns overlap height when workstation overlaps dock', () => {
      const inset = computeDockBottomInset(
        { top: 40, bottom: 640, left: 0, right: 366 },
        { top: 428, bottom: 640, left: 200, right: 1700 }
      );

      expect(inset).toBe(212);
    });

    it('returns visible overlap height when workstation is partially collapsed', () => {
      const inset = computeDockBottomInset(
        { top: 40, bottom: 640, left: 0, right: 366 },
        { top: 592, bottom: 772, left: 120, right: 1700 }
      );

      expect(inset).toBe(48);
    });

    it('returns zero when workstation does not horizontally overlap dock', () => {
      const inset = computeDockBottomInset(
        { top: 40, bottom: 640, left: 0, right: 366 },
        { top: 428, bottom: 640, left: 500, right: 1800 }
      );

      expect(inset).toBe(0);
    });

    it('returns zero when workstation only overlaps horizontally but not vertically', () => {
      const inset = computeDockBottomInset(
        { top: 40, bottom: 300, left: 0, right: 366 },
        { top: 420, bottom: 640, left: 200, right: 1700 }
      );

      expect(inset).toBe(0);
    });
  });
});
