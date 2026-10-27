import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { HTMLAttributes, ReactNode } from 'react';
import { DEFAULT_LAYOUT, useWidgetStore } from '../stores/widgetStore';
import { I18nProvider } from '../i18n/context';
import { COLLAPSED_HEIGHT } from '../utils/widgetUtils';

const animation = vi.hoisted(() => ({ complete: () => {} }));
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, animate: _animate, initial: _initial, transition: _transition, onAnimationComplete, ...props }:
      HTMLAttributes<HTMLDivElement> & { children: ReactNode; animate: unknown; initial: unknown; transition: unknown; onAnimationComplete: () => void }) => {
      animation.complete = onAnimationComplete;
      return <div {...props}>{children}</div>;
    },
  },
}));

import { WidgetPanel } from '../components/widget/WidgetPanel';

describe('WidgetPanel collapse lifecycle', () => {
  let naturalHeight = 240;

  beforeEach(() => {
    naturalHeight = 240;
    useWidgetStore.setState({
      widgets: structuredClone(DEFAULT_LAYOUT),
      isDragging: false,
      activeWidgetId: null,
    });
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.style.height === '0px' ? 0 : naturalHeight;
    });
  });

  afterEach(() => vi.restoreAllMocks());

  function renderPanel() {
    render(
      <I18nProvider>
        <WidgetPanel widgetId="basic-settings" titleKey="widget.basicSettings">
          <input aria-label="Draft" defaultValue="keep me" />
        </WidgetPanel>
      </I18nProvider>,
    );
    return screen.getByRole('textbox').parentElement!;
  }

  it('keeps content laid out through collapse, then hides it without losing the draft or cached height', () => {
    const content = renderPanel();
    expect(useWidgetStore.getState().widgets['basic-settings'].expandedHeight).toBe(COLLAPSED_HEIGHT + naturalHeight);

    act(() => useWidgetStore.getState().toggleCollapse('basic-settings'));
    expect(content.style.height).toBe('auto');
    expect(content.style.visibility).not.toBe('hidden');
    expect(content).toHaveAttribute('inert');

    act(() => animation.complete());
    expect(content.style.height).toBe('0px');
    expect(content.style.contentVisibility).toBe('hidden');
    expect(useWidgetStore.getState().widgets['basic-settings'].expandedHeight).toBe(COLLAPSED_HEIGHT + naturalHeight);

    naturalHeight = 360;
    act(() => useWidgetStore.getState().toggleCollapse('basic-settings'));
    expect(content.style.height).toBe('auto');
    expect(content).not.toHaveAttribute('inert');
    expect(screen.getByRole('textbox')).toHaveValue('keep me');
    expect(useWidgetStore.getState().widgets['basic-settings'].expandedHeight).toBe(COLLAPSED_HEIGHT + naturalHeight);
  });

  it('handles reversing a collapse before completion without hiding the reopened content', () => {
    const content = renderPanel();
    const header = screen.getByRole('button', { name: '图像导入和基础设置' });
    fireEvent.doubleClick(header);
    fireEvent.doubleClick(header);
    act(() => animation.complete());
    expect(content.style.height).toBe('auto');
    expect(content.style.visibility).not.toBe('hidden');
    expect(content).not.toHaveAttribute('inert');

    fireEvent.doubleClick(header);
    expect(content.style.height).toBe('auto');
    act(() => animation.complete());
    expect(content.style.height).toBe('0px');
  });
});
