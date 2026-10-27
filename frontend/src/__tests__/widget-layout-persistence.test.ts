import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_LAYOUT, useWidgetStore } from '../stores/widgetStore';

describe('widget layout persistence', () => {
  beforeEach(() => {
    useWidgetStore.setState({ widgets: structuredClone(DEFAULT_LAYOUT) });
  });

  afterEach(() => vi.restoreAllMocks());

  it('does not serialize the layout again for unchanged measurements', () => {
    const write = vi.spyOn(localStorage, 'setItem');
    const state = useWidgetStore.getState();
    state.setWidgetPositions({});
    state.setWidgetPositions({ 'basic-settings': { ...state.widgets['basic-settings'].position } });
    state.setExpandedHeight('basic-settings', state.widgets['basic-settings'].expandedHeight);

    expect(write).not.toHaveBeenCalled();
    expect(useWidgetStore.getState()).toBe(state);
  });

  it('persists changed positions once and preserves other widgets', () => {
    const write = vi.spyOn(localStorage, 'setItem');
    const state = useWidgetStore.getState();
    const position = { x: 123, y: 456 };
    state.setWidgetPositions({
      'basic-settings': position,
      'action-bar': { ...state.widgets['action-bar'].position },
    });

    const widgets = useWidgetStore.getState().widgets;
    expect(widgets['basic-settings'].position).toEqual(position);
    expect(widgets['action-bar']).toBe(state.widgets['action-bar']);
    expect(state.widgets['basic-settings'].position).not.toEqual(position);
    expect(write).toHaveBeenCalledTimes(1);
    const saved = JSON.parse(localStorage.getItem('lumina-widget-layout')!);
    expect(saved.state.widgets['basic-settings'].position).toEqual(position);
  });

  it('persists a changed expanded height', () => {
    const write = vi.spyOn(localStorage, 'setItem');
    const height = DEFAULT_LAYOUT['basic-settings'].expandedHeight + 10;
    useWidgetStore.getState().setExpandedHeight('basic-settings', height);

    expect(write).toHaveBeenCalledTimes(1);
    const saved = JSON.parse(localStorage.getItem('lumina-widget-layout')!);
    expect(saved.state.widgets['basic-settings'].expandedHeight).toBe(height);
  });
});
