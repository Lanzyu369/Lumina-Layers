import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PaletteEntry } from '../api/types';
import ColorPreview2D from '../components/sections/ColorPreview2D';
import { buildLayerImagesSourceKey, DEFAULT_STATE, useConverterStore } from '../stores/converter';

vi.mock('../i18n/context', () => ({
  useI18n: () => ({ t: (key: string) => key, lang: 'zh' as const }),
}));

const OriginalImage = globalThis.Image;

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

class TestImage {
  static instances: TestImage[] = [];

  onload: ((ev: Event) => unknown) | null = null;
  onerror: ((ev: Event | string) => unknown) | null = null;
  crossOrigin = '';
  naturalWidth = 100;
  naturalHeight = 100;
  width = 100;
  height = 100;
  complete = false;
  private currentSrc = '';

  constructor() {
    TestImage.instances.push(this);
  }

  set src(value: string) {
    this.currentSrc = value;
  }

  get src(): string {
    return this.currentSrc;
  }

  dispatchLoad(): void {
    this.complete = true;
    this.onload?.(new Event('load'));
  }
}

function createCanvasContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  return {
    canvas,
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    setTransform: vi.fn(),
    translate: vi.fn(),
    scale: vi.fn(),
    drawImage: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    getImageData: vi.fn((x: number, y: number) => {
      if (x === 10 && y === 20) {
        return { data: new Uint8ClampedArray([171, 205, 239, 255]) };
      }
      return { data: new Uint8ClampedArray([17, 34, 51, 255]) };
    }),
    imageSmoothingEnabled: true,
    strokeStyle: '',
    lineWidth: 1,
  } as unknown as CanvasRenderingContext2D;
}

function installCanvasContextMock(): void {
  const contextByCanvas = new WeakMap<HTMLCanvasElement, CanvasRenderingContext2D>();

  const getContextMock = function getContext(
    this: HTMLCanvasElement,
    contextId: string,
  ): CanvasRenderingContext2D | null {
    if (contextId === '2d') {
      const existingContext = contextByCanvas.get(this);
      if (existingContext) {
        return existingContext;
      }

      const context = createCanvasContext(this);
      contextByCanvas.set(this, context);
      return context;
    }
    return null;
  };

  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    getContextMock as unknown as typeof HTMLCanvasElement.prototype.getContext,
  );
}

function getVisiblePreviewContext(): CanvasRenderingContext2D | null {
  const canvas = screen.getByRole('img', { name: 'converter_preview_2d_alt' }) as HTMLCanvasElement;
  return canvas.getContext('2d');
}

function getPendingImages(src?: string): TestImage[] {
  return TestImage.instances.filter((image) => !image.complete && (src === undefined || image.src === src));
}

function dispatchImageLoads(images: TestImage[]): void {
  act(() => {
    for (const image of images) {
      image.dispatchLoad();
    }
  });
}

function flushPendingImages(src?: string): TestImage[] {
  const pendingImages = getPendingImages(src);
  dispatchImageLoads(pendingImages);
  return pendingImages;
}

function mockPreviewRect(element: HTMLElement): void {
  Object.defineProperty(element, 'getBoundingClientRect', {
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
}

describe('ColorPreview2D hover inspector', () => {
  beforeEach(() => {
    TestImage.instances = [];
    vi.useFakeTimers();
    vi.stubGlobal('ResizeObserver', MockResizeObserver);
    globalThis.Image = class MockImage extends OriginalImage {
      constructor(...args: ConstructorParameters<typeof Image>) {
        super(...args);
        return new TestImage() as unknown as HTMLImageElement;
      }
    } as typeof Image;

    installCanvasContextMock();

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
    globalThis.Image = OriginalImage;
  });

  it('renders the shared canvas surface and preserves the hover inspector lifecycle', () => {
    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    const surface = screen.getByRole('img', { name: 'converter_preview_2d_alt' });

    mockPreviewRect(container);

    expect(surface.tagName).toBe('CANVAS');
    expect(container).toHaveClass('h-full');
    expect(container).toHaveClass('w-full');
    expect(container.querySelector('img')).toBeNull();

    act(() => {
      fireEvent.pointerMove(container, { pointerId: 1, clientX: 120, clientY: 150 });
      vi.advanceTimersByTime(220);
    });

    expect(screen.getByTestId('main-2d-hover-inspector')).toBeInTheDocument();
    expect(screen.getByText('viewer_hover_no_layer_data')).toBeInTheDocument();

    act(() => {
      fireEvent.pointerLeave(container, { pointerId: 1 });
      vi.advanceTimersByTime(1600);
    });

    expect(screen.queryByTestId('main-2d-hover-inspector')).not.toBeInTheDocument();
  });

  it('renders the workstation preview with crisp canvas sampling', () => {
    render(<ColorPreview2D />);

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    flushPendingImages('/preview.png');

    expect(getVisiblePreviewContext()?.imageSmoothingEnabled).toBe(false);
  });

  it('reuses the preview buffer for select-all clicks without creating a fresh canvas per click', async () => {
    const toggleColorInSelection = vi.fn();
    const setSelectedColor = vi.fn();
    let canvasCreateCount = 0;
    const originalCreateElement = document.createElement.bind(document);

    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName.toLowerCase() === 'canvas') {
        canvasCreateCount += 1;
      }
      return originalCreateElement(tagName);
    });

    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'select-all',
      palette: [{
        quantized_hex: 'ABCDEF',
        matched_hex: 'ABCDEF',
        pixel_count: 10,
        percentage: 100,
      } satisfies PaletteEntry],
      selectedColors: new Set<string>(),
      toggleColorInSelection,
      setSelectedColor,
      sessionId: 'session-main-2d',
      preview_width_mm: 80,
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
    });

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    const initialCanvasCreateCount = canvasCreateCount;

    act(() => {
      fireEvent.click(container, { clientX: 80, clientY: 60 });
    });

    expect(toggleColorInSelection).toHaveBeenCalledWith('ABCDEF');
    expect(setSelectedColor).toHaveBeenCalledWith('ABCDEF');
    expect(canvasCreateCount).toBe(initialCanvasCreateCount);
  });

  it('keeps SVG contour overlays aligned on top of the shared canvas preview surface', async () => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'current',
      selectedColor: 'AABBCC',
      regionData: {
        regionId: 'region-1',
        colorHex: '#AABBCC',
        pixelCount: 42,
        previewUrl: '/preview.png',
        contours: [
          [
            [0, 0],
            [20, 0],
            [20, 20],
          ],
        ],
        clickX: 10,
        clickY: 10,
      },
      colorContours: {},
      preview_width_mm: 100,
      sessionId: 'session-main-2d',
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
    });

    const { container } = render(<ColorPreview2D />);
    const surface = screen.getByTestId('color-preview-2d-container');

    mockPreviewRect(surface);

    flushPendingImages('/preview.png');

    const polygon = container.querySelector('polygon');
    expect(polygon).not.toBeNull();
    expect(polygon).toHaveAttribute('points', '0,100 20,100 20,80');
  });

  it('blocks hover and wheel interactions while replacePreviewLoading is active', () => {
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
      replacePreviewLoading: true,
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
    });

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    act(() => {
      fireEvent.pointerMove(container, { pointerId: 1, clientX: 120, clientY: 150 });
      fireEvent.wheel(container, { clientX: 120, clientY: 150, deltaY: -100 });
      vi.advanceTimersByTime(220);
    });

    expect(screen.queryByTestId('main-2d-hover-inspector')).not.toBeInTheDocument();
    expect(screen.queryByText('115%')).not.toBeInTheDocument();
  });

  it('does not keep the inspector visible after shift-click once the pointer leaves', () => {
    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    act(() => {
      fireEvent.pointerMove(container, { pointerId: 1, clientX: 120, clientY: 150 });
      vi.advanceTimersByTime(220);
    });

    expect(screen.getByText('(23, 50)')).toBeInTheDocument();

    act(() => {
      fireEvent.click(container, { clientX: 120, clientY: 150, shiftKey: true });
      fireEvent.pointerLeave(container, { pointerId: 1 });
      vi.advanceTimersByTime(1600);
    });

    expect(screen.queryByTestId('main-2d-hover-inspector')).not.toBeInTheDocument();
  });

  it('keeps regular clicks routed to the existing selection behavior', () => {
    const detectRegion = vi.fn();

    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'current',
      detectRegion,
      sessionId: 'session-main-2d',
      preview_width_mm: 80,
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
    });

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    act(() => {
      fireEvent.click(container, { clientX: 120, clientY: 150 });
    });

    expect(detectRegion).toHaveBeenCalledWith(23, 50);
  });

  it('releases layer hover data after hover leaves and the release delay expires', async () => {
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
      layerImages: [{ layer_index: 0, name: 'Layer 1', url: '/layer-1.png' }],
    });
    useConverterStore.setState({
      layerImagesSourceKey: buildLayerImagesSourceKey(useConverterStore.getState()),
    });

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    act(() => {
      fireEvent.pointerMove(container, { pointerId: 1, clientX: 120, clientY: 150 });
      vi.advanceTimersByTime(220);
    });

    flushPendingImages('/layer-1.png');
    await act(async () => {});

    expect(screen.queryByText('viewer_hover_no_layer_data')).not.toBeInTheDocument();

    act(() => {
      fireEvent.pointerLeave(container, { pointerId: 1 });
    });

    await act(async () => {
      vi.advanceTimersByTime(1600);
    });

    expect(screen.queryByTestId('main-2d-hover-inspector')).not.toBeInTheDocument();
  });

  it('does not switch layer-image source until the replacement preview is actually displayed', async () => {
    const fetchLayerImages = vi.fn(async () => {});

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
      fetchLayerImages,
      layerImagesLoading: false,
      layerImages: [{ layer_index: 0, name: 'Layer 1', url: '/layer-1.png' }],
      layerImagesSourceKey: buildLayerImagesSourceKey({
        ...DEFAULT_STATE,
        sessionId: 'session-main-2d',
        previewBaseImageUrl: '/preview.png',
        previewImageUrl: '/preview.png',
        previewGlbUrl: null,
      }),
    });

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    act(() => {
      fireEvent.pointerMove(container, { pointerId: 1, clientX: 120, clientY: 150 });
      vi.advanceTimersByTime(220);
    });
    fetchLayerImages.mockClear();

    act(() => {
      useConverterStore.setState({
        previewBaseImageUrl: '/preview-next.png',
        previewImageUrl: '/preview-next.png',
      });
    });

    expect(fetchLayerImages).not.toHaveBeenCalled();
  });

  it('does not switch layer-image source when previewGlbUrl changes before the displayed preview swaps', async () => {
    const fetchLayerImages = vi.fn(async () => {});

    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewGlbUrl: '/preview.glb',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'current',
      sessionId: 'session-main-2d',
      preview_width_mm: 80,
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages,
      layerImagesLoading: false,
      layerImages: [{ layer_index: 0, name: 'Layer 1', url: '/layer-1.png' }],
      layerImagesSourceKey: buildLayerImagesSourceKey({
        ...DEFAULT_STATE,
        sessionId: 'session-main-2d',
        previewBaseImageUrl: '/preview.png',
        previewImageUrl: '/preview.png',
        previewGlbUrl: '/preview.glb',
      }),
    });

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    act(() => {
      fireEvent.pointerMove(container, { pointerId: 1, clientX: 120, clientY: 150 });
      vi.advanceTimersByTime(220);
      useConverterStore.setState({
        previewBaseImageUrl: '/preview-next.png',
        previewImageUrl: '/preview-next.png',
        previewGlbUrl: '/preview-next.glb',
      });
    });
    fetchLayerImages.mockClear();

    expect(fetchLayerImages).not.toHaveBeenCalled();
  });
});
