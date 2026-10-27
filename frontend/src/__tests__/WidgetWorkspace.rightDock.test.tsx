/**
 * Regression: right-dock widgets must stay aligned with the dock when the
 * workspace width changes without a window resize (e.g. a page scrollbar
 * appears after the model-surface overlay mounts).
 * 回归测试：工作区宽度在窗口未 resize 时变化（如出现页面滚动条），
 * 右侧坞 widget 仍需与坞对齐，不能被裁掉一条。
 */

import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WidgetId } from '../types/widget';
import { DEFAULT_LAYOUT, useWidgetStore } from '../stores/widgetStore';
import { COLLAPSED_HEIGHT, STACK_GAP } from '../utils/widgetUtils';

vi.mock('../components/widget/WidgetPanel', async () => {
  const { useWidgetStore: useStore } = await import('../stores/widgetStore');
  return {
    WidgetPanel: ({ widgetId, dockOffsetX = 0, width }: { widgetId: WidgetId; dockOffsetX?: number; width: number }) => {
      const widget = useStore((s) => s.widgets[widgetId]);
      if (!widget.visible) return null;
      return (
        <div
          data-widget-id={widgetId}
          data-testid={`panel-${widgetId}`}
          data-local-left={widget.position.x - dockOffsetX}
          data-width={width}
        />
      );
    },
  };
});
vi.mock('../components/widget/SnapGuides', () => ({ SnapGuides: () => null }));
vi.mock('../hooks/useConverterDataInit', () => ({ useConverterDataInit: () => {} }));
vi.mock('../components/widget/Color2DOverlay', () => ({ default: () => null }));
vi.mock('../components/widget/BasicSettingsWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/AdvancedSettingsWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/ReliefSettingsWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/OutlineSettingsWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/CloisonneSettingsWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/CoatingSettingsWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/KeychainLoopWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/FridgeMagnetSettingsWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/PuzzleSettingsWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/ActionBarWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/CalibrationWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/ExtractorWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/LutManagerWidgetContent', () => ({ default: () => null }));
vi.mock('../components/widget/FiveColorWidgetContent', () => ({ default: () => null }));

import { WidgetWorkspace } from '../components/widget/WidgetWorkspace';

type ObserverRecord = { callback: ResizeObserverCallback; targets: Element[] };

let workspaceWidth = 1024;
let observers: ObserverRecord[] = [];
const OriginalResizeObserver = globalThis.ResizeObserver;

class RecordingResizeObserver {
  private record: ObserverRecord;

  constructor(callback: ResizeObserverCallback) {
    this.record = { callback, targets: [] };
    observers.push(this.record);
  }

  observe(target: Element) {
    this.record.targets.push(target);
  }

  unobserve() {}

  disconnect() {
    this.record.targets = [];
  }
}

function fireAllResizeObservers() {
  for (const { callback, targets } of observers) {
    if (targets.length > 0) {
      callback([], {} as ResizeObserver);
    }
  }
}

function rightPanelOuterInset(id: WidgetId): number {
  const panel = screen.getByTestId(`panel-${id}`);
  const dockWidth = Number.parseFloat(screen.getByTestId('right-dock').style.width);
  return dockWidth - Number(panel.dataset.localLeft) - Number(panel.dataset.width);
}

describe('WidgetWorkspace right dock alignment', () => {
  beforeEach(() => {
    workspaceWidth = 1024;
    observers = [];
    globalThis.ResizeObserver = RecordingResizeObserver as unknown as typeof ResizeObserver;
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
      () =>
        ({
          left: 0,
          top: 0,
          width: workspaceWidth,
          height: 700,
          right: workspaceWidth,
          bottom: 700,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect,
    );
    useWidgetStore.setState({
      widgets: structuredClone(DEFAULT_LAYOUT),
      activeConverterSubTab: 'core',
      isDragging: false,
      activeWidgetId: null,
    });
  });

  afterEach(() => {
    globalThis.ResizeObserver = OriginalResizeObserver;
    vi.restoreAllMocks();
  });

  it('keeps both docks inset after a width change without window resize', async () => {
    render(<WidgetWorkspace />);

    await waitFor(() => {
      expect(rightPanelOuterInset('action-bar')).toBe(8);
      expect(Number(screen.getByTestId('panel-basic-settings').dataset.localLeft)).toBe(8);
    });

    // A page scrollbar appears: the workspace shrinks, but no window resize fires.
    workspaceWidth = 1009;
    act(() => {
      fireAllResizeObservers();
    });

    await waitFor(() => {
      expect(rightPanelOuterInset('action-bar')).toBe(8);
      expect(rightPanelOuterInset('advanced-settings')).toBe(8);
      expect(Number(screen.getByTestId('panel-basic-settings').dataset.localLeft)).toBe(8);
    });
    // Give the debounced widget re-stack a chance to run, then re-check.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 80));
    });
    expect(rightPanelOuterInset('action-bar')).toBe(8);
  });

  it('updates sibling targets in the collapse commit, including a rapid reversal', () => {
    render(<WidgetWorkspace />);

    act(() => useWidgetStore.getState().toggleCollapse('action-bar'));
    expect(useWidgetStore.getState().widgets['advanced-settings'].position.y)
      .toBe(STACK_GAP + COLLAPSED_HEIGHT + STACK_GAP);

    act(() => useWidgetStore.getState().toggleCollapse('action-bar'));
    expect(useWidgetStore.getState().widgets['advanced-settings'].position.y)
      .toBe(STACK_GAP + DEFAULT_LAYOUT['action-bar'].expandedHeight + STACK_GAP);
  });

  it('restacks after a widget is removed from and returned to a dock', async () => {
    render(<WidgetWorkspace />);

    act(() => useWidgetStore.getState().toggleVisible('action-bar'));
    await waitFor(() => {
      expect(screen.queryByTestId('panel-action-bar')).not.toBeInTheDocument();
      expect(useWidgetStore.getState().widgets['advanced-settings'].position.y).toBe(STACK_GAP);
    });

    act(() => useWidgetStore.getState().toggleVisible('action-bar'));
    await waitFor(() => {
      expect(screen.getByTestId('panel-action-bar')).toBeInTheDocument();
      expect(useWidgetStore.getState().widgets['advanced-settings'].position.y)
        .toBe(STACK_GAP + DEFAULT_LAYOUT['action-bar'].expandedHeight + STACK_GAP);
    });
  });

  it('uses the observed panel height when no expanded height is cached', async () => {
    useWidgetStore.getState().setExpandedHeight('action-bar', 0);
    render(<WidgetWorkspace />);
    const actionPanel = screen.getByTestId('panel-action-bar');
    Object.defineProperty(actionPanel, 'offsetHeight', { configurable: true, value: 640 });

    act(() => {
      const record = observers.find(({ targets }) => targets.includes(actionPanel))!;
      record.callback([{ target: actionPanel } as unknown as ResizeObserverEntry], {} as ResizeObserver);
    });

    await waitFor(() => {
      expect(useWidgetStore.getState().widgets['advanced-settings'].position.y)
        .toBe(STACK_GAP + 640 + STACK_GAP);
    });
  });
});
