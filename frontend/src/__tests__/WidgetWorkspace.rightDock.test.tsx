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

vi.mock('../components/widget/WidgetPanel', async () => {
  const { useWidgetStore: useStore } = await import('../stores/widgetStore');
  return {
    WidgetPanel: ({ widgetId, dockOffsetX = 0 }: { widgetId: WidgetId; dockOffsetX?: number }) => {
      const widget = useStore((s) => s.widgets[widgetId]);
      if (!widget.visible) return null;
      return (
        <div
          data-widget-id={widgetId}
          data-testid={`panel-${widgetId}`}
          data-local-left={widget.position.x - dockOffsetX}
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

function rightPanelLocalLeft(id: WidgetId): number {
  return Number(screen.getByTestId(`panel-${id}`).dataset.localLeft);
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

  it('keeps right-dock widgets at dock-local x=0 after a width change without window resize', async () => {
    render(<WidgetWorkspace />);

    await waitFor(() => {
      expect(rightPanelLocalLeft('action-bar')).toBe(0);
    });

    // A page scrollbar appears: the workspace shrinks, but no window resize fires.
    workspaceWidth = 1009;
    act(() => {
      fireAllResizeObservers();
    });

    await waitFor(() => {
      expect(rightPanelLocalLeft('action-bar')).toBe(0);
      expect(rightPanelLocalLeft('advanced-settings')).toBe(0);
    });
    // Give the debounced widget re-stack a chance to run, then re-check.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 80));
    });
    expect(rightPanelLocalLeft('action-bar')).toBe(0);
  });
});
