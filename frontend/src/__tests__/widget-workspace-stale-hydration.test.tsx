/**
 * Regression: a stale SAME-version persisted widget layout (written before
 * ``model-surface-settings`` existed) must not crash the advanced converter
 * sub-tab.
 * 回归：同版本但缺少新增 widget 的旧持久化布局不得让「创意中心」子页签白屏。
 *
 * Seeds localStorage BEFORE importing the store module so hydration picks up
 * the stale payload (now migrated through the v8→v9 bump), renders the real
 * WidgetWorkspace (content panels mocked), switches to the advanced sub-tab,
 * and asserts the previously-missing panel appears ABOVE basic-settings.
 */

import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../hooks/useConverterDataInit', () => ({
  useConverterDataInit: () => {},
}));

vi.mock('../components/widget/Color2DOverlay', () => ({
  default: () => null,
}));

vi.mock('../components/widget/BasicSettingsWidgetContent', () => ({
  default: () => <div data-testid="w-content-basic-settings" />,
}));
vi.mock('../components/widget/ModelSurfaceSettingsWidgetContent', () => ({
  default: () => <div data-testid="w-content-model-surface-settings" />,
}));
vi.mock('../components/widget/AdvancedSettingsWidgetContent', () => ({
  default: () => <div data-testid="w-content-advanced-settings" />,
}));
vi.mock('../components/widget/ReliefSettingsWidgetContent', () => ({
  default: () => <div data-testid="w-content-relief-settings" />,
}));
vi.mock('../components/widget/OutlineSettingsWidgetContent', () => ({
  default: () => <div data-testid="w-content-outline-settings" />,
}));
vi.mock('../components/widget/CloisonneSettingsWidgetContent', () => ({
  default: () => <div data-testid="w-content-cloisonne-settings" />,
}));
vi.mock('../components/widget/CoatingSettingsWidgetContent', () => ({
  default: () => <div data-testid="w-content-coating-settings" />,
}));
vi.mock('../components/widget/KeychainLoopWidgetContent', () => ({
  default: () => <div data-testid="w-content-keychain-loop" />,
}));
vi.mock('../components/widget/FridgeMagnetSettingsWidgetContent', () => ({
  default: () => <div data-testid="w-content-fridge-magnet-settings" />,
}));
vi.mock('../components/widget/PuzzleSettingsWidgetContent', () => ({
  default: () => <div data-testid="w-content-puzzle-settings" />,
}));
vi.mock('../components/widget/ActionBarWidgetContent', () => ({
  default: () => <div data-testid="w-content-action-bar" />,
}));
vi.mock('../components/widget/CalibrationWidgetContent', () => ({
  default: () => <div data-testid="w-content-calibration" />,
}));
vi.mock('../components/widget/ExtractorWidgetContent', () => ({
  default: () => <div data-testid="w-content-extractor" />,
}));
vi.mock('../components/widget/LutManagerWidgetContent', () => ({
  default: () => <div data-testid="w-content-lut-manager" />,
}));
vi.mock('../components/widget/FiveColorWidgetContent', () => ({
  default: () => <div data-testid="w-content-five-color" />,
}));

/** Stale v8 payload written before model-surface-settings existed. */
function seedStaleV8Layout(): void {
  localStorage.setItem(
    'lumina-widget-layout',
    JSON.stringify({
      state: {
        widgets: {
          'cloisonne-settings': {
            id: 'cloisonne-settings',
            position: { x: 0, y: 0 },
            collapsed: false,
            visible: true,
            snapEdge: 'left',
            stackOrder: 1,
            expandedHeight: 420,
          },
          'basic-settings': {
            position: { x: 0, y: 0 },
            collapsed: false,
            visible: true,
            snapEdge: 'left',
            stackOrder: 0,
            expandedHeight: 655,
          },
          'action-bar': {
            position: { x: 900, y: 10 },
            collapsed: false,
            visible: true,
            snapEdge: 'right',
            stackOrder: 0,
            expandedHeight: 420,
          },
        },
        activeTab: 'converter',
      },
      version: 8,
    }),
  );
}

describe('WidgetWorkspace stale same-version layout regression', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  it('renders the advanced sub-tab and the backfilled model-surface panel', async () => {
    seedStaleV8Layout();

    const [{ WidgetWorkspace }, { useWidgetStore }] = await Promise.all([
      import('../components/widget/WidgetWorkspace'),
      import('../stores/widgetStore'),
    ]);
    await useWidgetStore.persist.rehydrate();

    render(<WidgetWorkspace />);

    expect(() => {
      act(() => {
        useWidgetStore.getState().setActiveConverterSubTab('advanced');
      });
    }).not.toThrow();

    // Render completed: both docks are present.
    expect(screen.getByTestId('left-dock')).toBeInTheDocument();
    expect(screen.getByTestId('right-dock')).toBeInTheDocument();

    // The previously-missing panel is rendered with its default visible state.
    expect(
      screen.getByTestId('w-content-model-surface-settings'),
    ).toBeInTheDocument();
    // Header title comes from translations (zh label in tests).
    expect(screen.getByText('模型贴图')).toBeInTheDocument();

    // Sibling advanced panels still render alongside it.
    expect(screen.getByTestId('w-content-basic-settings')).toBeInTheDocument();
    expect(screen.getByTestId('w-content-action-bar')).toBeInTheDocument();

    // Legacy layouts cannot expose the retired panel or its dock entry.
    expect(screen.queryByTestId('w-content-cloisonne-settings')).not.toBeInTheDocument();
    expect(screen.queryByText('掐丝珐琅设置')).not.toBeInTheDocument();

    // The backfilled panel takes the TOP of the left dock: DOM order inside
    // the left dock mirrors WIDGET_REGISTRY order (model before basic).
    // 补齐后的面板位于左坞顶部：左坞内 DOM 顺序镜像 WIDGET_REGISTRY 顺序
    // （模型贴图在基础设置之前）。
    const leftDockOrder = Array.from(
      screen.getByTestId('left-dock').querySelectorAll('[data-widget-id]'),
    ).map((el) => el.getAttribute('data-widget-id'));
    expect(leftDockOrder.indexOf('model-surface-settings')).toBeLessThan(
      leftDockOrder.indexOf('basic-settings'),
    );
  });
});
