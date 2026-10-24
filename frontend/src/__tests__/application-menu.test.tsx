import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useApplicationMenuCommand, useApplicationMenuLanguage } from '../integrations/applicationMenu';
import { useSettingsStore } from '../stores/settingsStore';

const bridge = vi.hoisted(() => ({
  listeners: new Set<(command: string) => void>(),
  setApplicationMenuState: vi.fn(),
}));
vi.mock('../integrations/electron', () => ({
  electronAPI: {
    setApplicationMenuState: bridge.setApplicationMenuState,
    onApplicationMenuCommand: (listener: (command: string) => void) => {
      bridge.listeners.add(listener);
      return () => bridge.listeners.delete(listener);
    },
  },
}));

describe('desktop menu bridge', () => {
  beforeEach(() => { bridge.setApplicationMenuState.mockClear(); });
  it('uses the latest workflow handler and disables unavailable or unmounted actions', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender, unmount } = renderHook(({ handler, enabled }) =>
      useApplicationMenuCommand('export', handler, enabled),
    { initialProps: { handler: first, enabled: true } });
    act(() => bridge.listeners.forEach(listener => listener('export')));
    expect(first).toHaveBeenCalledTimes(1);
    rerender({ handler: second, enabled: true });
    act(() => bridge.listeners.forEach(listener => listener('export')));
    expect(second).toHaveBeenCalledTimes(1);
    rerender({ handler: second, enabled: false });
    act(() => bridge.listeners.forEach(listener => listener('export')));
    expect(second).toHaveBeenCalledTimes(1);
    expect(bridge.setApplicationMenuState).toHaveBeenLastCalledWith({ commands: {} });
    unmount();
    expect(bridge.listeners.size).toBe(0);
  });
  it('updates native labels when the application language changes', () => {
    useSettingsStore.setState({ language: 'zh' });
    const { unmount } = renderHook(useApplicationMenuLanguage);
    expect(bridge.setApplicationMenuState).toHaveBeenLastCalledWith({ labels: expect.objectContaining({ file: '文件' }) });
    act(() => useSettingsStore.setState({ language: 'en' }));
    expect(bridge.setApplicationMenuState).toHaveBeenLastCalledWith({ labels: expect.objectContaining({ file: 'File' }) });
    unmount();
  });
  it('dispatches activated import events only while the uploader is registered', () => {
    const open = vi.fn();
    const { unmount } = renderHook(() => useApplicationMenuCommand('import', open));
    act(() => window.dispatchEvent(new Event('lumina-menu-import')));
    expect(open).toHaveBeenCalledTimes(1);
    unmount();
    act(() => window.dispatchEvent(new Event('lumina-menu-import')));
    expect(open).toHaveBeenCalledTimes(1);
  });
});
