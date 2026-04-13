import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import ColorPreview2D from '../components/sections/ColorPreview2D';
import { DEFAULT_STATE, useConverterStore } from '../stores/converter';

vi.mock('../i18n/context', () => ({
  useI18n: () => ({ t: (key: string) => key, lang: 'zh' as const }),
}));

class MockResizeObserver {
  private readonly callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe(target: Element) {
    this.callback(
      [
        {
          target,
          contentRect: {
            width: 400,
            height: 300,
            x: 0,
            y: 0,
            top: 0,
            left: 0,
            right: 400,
            bottom: 300,
            toJSON: () => ({}),
          } as DOMRectReadOnly,
        } as ResizeObserverEntry,
      ],
      this as unknown as ResizeObserver,
    );
  }

  unobserve() {}

  disconnect() {}
}

function createCanvasContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  return {
    canvas,
    drawImage: vi.fn(),
    getImageData: vi.fn(() => ({
      data: new Uint8ClampedArray([17, 34, 51, 255]),
    })),
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    setTransform: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    imageSmoothingEnabled: false,
    strokeStyle: '',
    lineWidth: 1,
  } as unknown as CanvasRenderingContext2D;
}

describe('ColorPreview2D hover inspector', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('ResizeObserver', MockResizeObserver);
    const getContextMock = function getContext(
      this: HTMLCanvasElement,
      contextId: string,
    ): RenderingContext | null {
      if (contextId === '2d') {
        return createCanvasContext(this);
      }
      return null;
    };
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
      getContextMock as unknown as typeof HTMLCanvasElement.prototype.getContext,
    );

    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'current',
      sessionId: 'session-main-2d',
      preview_width_mm: 80,
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
      colorContours: {},
      regionData: null,
      selectedRegions: [],
      selectedColors: new Set<string>(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('shows and hides the main 2D hover inspector without leaving stale overlay nodes behind', async () => {
    render(<ColorPreview2D />);

    const container = screen.getByTestId('color-preview-2d-container');
    const image = screen.getByAltText('converter_preview_2d_alt');

    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 100 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 100 });
    Object.defineProperty(container, 'getBoundingClientRect', {
      configurable: true,
      value: () =>
        ({
          width: 400,
          height: 300,
          left: 0,
          top: 0,
          right: 400,
          bottom: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect,
    });

    act(() => {
      fireEvent.load(image);
    });

    act(() => {
      fireEvent.pointerMove(container, { clientX: 120, clientY: 150 });
      vi.advanceTimersByTime(220);
    });

    expect(screen.getByTestId('main-2d-hover-inspector')).toBeInTheDocument();
    expect(screen.getByText('viewer_hover_no_layer_data')).toBeInTheDocument();

    act(() => {
      fireEvent.pointerLeave(container);
      vi.advanceTimersByTime(1600);
    });

    expect(screen.queryByTestId('main-2d-hover-inspector')).not.toBeInTheDocument();
  });

  it('does not render the hover inspector when both hover tools are disabled', () => {
    render(<ColorPreview2D showMagnifier={false} showLayerDetails={false} />);

    const container = screen.getByTestId('color-preview-2d-container');
    const image = screen.getByAltText('converter_preview_2d_alt');

    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 100 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 100 });
    Object.defineProperty(container, 'getBoundingClientRect', {
      configurable: true,
      value: () =>
        ({
          width: 400,
          height: 300,
          left: 0,
          top: 0,
          right: 400,
          bottom: 300,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect,
    });

    act(() => {
      fireEvent.load(image);
      fireEvent.pointerMove(container, { clientX: 120, clientY: 150 });
      vi.advanceTimersByTime(220);
    });

    expect(screen.queryByTestId('main-2d-hover-inspector')).not.toBeInTheDocument();
  });
});
