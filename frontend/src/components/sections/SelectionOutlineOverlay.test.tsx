import { act, render, screen } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SelectionOutlineOverlay from './SelectionOutlineOverlay';

const gpu = vi.hoisted(() => ({
  create: vi.fn(), setGeometry: vi.fn(), draw: vi.fn(), dispose: vi.fn(), loseContext: vi.fn(),
}));
vi.mock('./selectionOutlineRenderer', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./selectionOutlineRenderer')>()),
  SelectionOutlineRenderer: { create: gpu.create },
}));

describe('SelectionOutlineOverlay GPU lifecycle', () => {
  let frames: Map<number, FrameRequestCallback>;
  const viewport = {
    containerSize: { width: 400, height: 300 }, naturalSize: { width: 100, height: 100 },
    imageRect: { x: 50, y: 0, width: 300, height: 300 },
    imageScreenRect: { x: 50, y: 0, width: 300, height: 300 },
    scale: 1, translate: { x: 0, y: 0 },
  };
  const props = {
    contours: [{ polygons: [[[0, 0], [20, 0], [20, 20]]] }],
    pixelWidth: 100, pixelHeight: 100, contourWidth: 100, viewport,
    fallback: <svg data-testid="fallback" />,
  };
  function nextFrame(time: number) {
    act(() => {
      const pending = Array.from(frames.values());
      frames.clear();
      pending.forEach((callback) => callback(time));
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
    frames = new Map();
    let nextId = 0;
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
      frames.set(++nextId, callback);
      return nextId;
    }));
    vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => frames.delete(id)));
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const getContext = (contextId: string) => contextId === 'webgl' ? {
      getExtension: () => ({ loseContext: gpu.loseContext }),
    } : null;
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
      getContext as unknown as typeof HTMLCanvasElement.prototype.getContext,
    );
    gpu.create.mockReturnValue(gpu);
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('keeps one geometry upload across viewport updates and stops the frame loop on unmount', async () => {
    const { rerender, unmount } = render(<SelectionOutlineOverlay {...props} />);
    expect(screen.queryByTestId('fallback')).not.toBeInTheDocument();
    expect(gpu.setGeometry).toHaveBeenCalledTimes(1);
    nextFrame(100);
    const moved = { ...viewport, imageScreenRect: { x: 20, y: 30, width: 600, height: 600 } };
    rerender(<SelectionOutlineOverlay {...props} viewport={moved} />);
    expect(gpu.draw).toHaveBeenLastCalledWith(moved.imageScreenRect, 100, 100, 400, 300,
      expect.any(Number), expect.any(Number), expect.any(Number));
    nextFrame(200);
    expect(gpu.draw).toHaveBeenLastCalledWith(moved.imageScreenRect, 100, 100, 400, 300,
      expect.any(Number), expect.any(Number), 200);
    expect(gpu.setGeometry).toHaveBeenCalledTimes(1);
    rerender(<SelectionOutlineOverlay {...props} contours={[{ polygons: [[[0, 0], [4, 0], [4, 4]]] }]} />);
    expect(gpu.setGeometry).toHaveBeenCalledTimes(2);
    unmount();
    expect(frames.size).toBe(0);
    expect(gpu.dispose).toHaveBeenCalledTimes(1);
    await act(async () => { await Promise.resolve(); });
    expect(gpu.loseContext).toHaveBeenCalledTimes(1);
  });

  it('keeps GPU rendering available when StrictMode replays the effects', async () => {
    const { unmount } = render(<StrictMode><SelectionOutlineOverlay {...props} /></StrictMode>);
    await act(async () => { await Promise.resolve(); });
    expect(gpu.create).toHaveBeenCalledTimes(2);
    expect(gpu.loseContext).not.toHaveBeenCalled();
    expect(screen.queryByTestId('fallback')).not.toBeInTheDocument();
    gpu.draw.mockClear();
    nextFrame(100);
    expect(gpu.draw).toHaveBeenCalledTimes(1);
    unmount();
    await act(async () => { await Promise.resolve(); });
    expect(gpu.loseContext).toHaveBeenCalledTimes(1);
  });

  it('restores the geometry after context loss while keeping the fallback visible during the loss', () => {
    render(<SelectionOutlineOverlay {...props} />);
    const canvas = screen.getByTestId('selection-outline-gpu');
    act(() => canvas.dispatchEvent(new Event('webglcontextlost', { cancelable: true })));
    expect(screen.getByTestId('fallback')).toBeInTheDocument();
    expect(frames.size).toBe(0);
    act(() => canvas.dispatchEvent(new Event('webglcontextrestored')));
    expect(screen.queryByTestId('fallback')).not.toBeInTheDocument();
    expect(gpu.setGeometry).toHaveBeenCalledTimes(2);
    gpu.draw.mockClear();
    nextFrame(300);
    expect(gpu.draw).toHaveBeenCalledTimes(1);
  });

  it('uses SVG when GPU initialization fails', () => {
    gpu.create.mockReturnValue(null);
    render(<SelectionOutlineOverlay {...props} />);
    expect(screen.getByTestId('fallback')).toBeInTheDocument();
    expect(frames.size).toBe(0);
  });

  it('releases the WebGL context on unmount even when shader initialization fails', async () => {
    gpu.create.mockReturnValue(null);
    const { unmount } = render(<SelectionOutlineOverlay {...props} />);
    expect(screen.getByTestId('fallback')).toBeInTheDocument();
    unmount();
    await act(async () => { await Promise.resolve(); });
    expect(gpu.loseContext).toHaveBeenCalledTimes(1);
  });

  it('recovers from an initially lost context without remounting the selection', () => {
    gpu.create.mockReturnValueOnce(null);
    render(<SelectionOutlineOverlay {...props} />);
    expect(screen.getByTestId('fallback')).toBeInTheDocument();
    const canvas = screen.getByTestId('selection-outline-gpu');
    const lost = new Event('webglcontextlost', { cancelable: true });
    act(() => canvas.dispatchEvent(lost));
    expect(lost.defaultPrevented).toBe(true);
    act(() => canvas.dispatchEvent(new Event('webglcontextrestored')));
    expect(screen.queryByTestId('fallback')).not.toBeInTheDocument();
    expect(gpu.setGeometry).toHaveBeenCalledTimes(1);
    nextFrame(300);
    expect(gpu.draw).toHaveBeenLastCalledWith(viewport.imageScreenRect, 100, 100, 400, 300,
      expect.any(Number), expect.any(Number), 300);
  });

  it.each([false, true])('keeps the outline moving with system reduced motion set to %s', (reduced) => {
    vi.mocked(window.matchMedia).mockReturnValue({ matches: reduced, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList);
    render(<SelectionOutlineOverlay {...props} />);
    nextFrame(250);
    expect(gpu.draw).toHaveBeenLastCalledWith(viewport.imageScreenRect, 100, 100, 400, 300,
      expect.any(Number), expect.any(Number), 250);
    nextFrame(500);
    expect(gpu.draw).toHaveBeenLastCalledWith(viewport.imageScreenRect, 100, 100, 400, 300,
      expect.any(Number), expect.any(Number), 500);
  });
});
