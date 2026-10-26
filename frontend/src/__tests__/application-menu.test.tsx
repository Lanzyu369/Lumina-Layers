  it.each(['export', 'about'] as const)('dispatches the current %s handler only while registered', command => {
      useApplicationMenuCommand(command, handler, enabled),
    act(() => bridge.listeners.forEach(listener => listener(command)));
    act(() => bridge.listeners.forEach(listener => listener(command)));
    act(() => bridge.listeners.forEach(listener => listener(command)));
