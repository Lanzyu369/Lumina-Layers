import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PaletteEntry } from '../api/types';
import ColorPreview2D from '../components/sections/ColorPreview2D';
import { buildLayerImagesSourceKey, DEFAULT_STATE, useConverterStore } from '../stores/converter';

const sourceColorPickMock = vi.hoisted(() => vi.fn());

vi.mock('../api/converter', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/converter')>()),
  sourceColorPick: sourceColorPickMock,
}));

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
    sourceColorPickMock.mockReset();
    sourceColorPickMock.mockRejectedValue(new Error('source color pick unavailable'));

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

    await act(async () => {
      fireEvent.click(container, { clientX: 80, clientY: 60 });
    });

    expect(toggleColorInSelection).toHaveBeenCalledWith('ABCDEF');
    expect(setSelectedColor).toHaveBeenCalledWith('ABCDEF');
    expect(canvasCreateCount).toBe(initialCanvasCreateCount);
  });

  it('selects the original source palette color after the displayed preview has been replaced', async () => {
    let resolvePick: (value: { source_matched_hex: string; quantized_hex: string }) => void = () => {};
    sourceColorPickMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePick = resolve;
      }),
    );
    const toggleColorInSelection = vi.fn((hex: string) => {
      const previous = useConverterStore.getState().selectedColors;
      const next = new Set(previous);
      if (next.has(hex)) {
        next.delete(hex);
      } else {
        next.add(hex);
      }
      useConverterStore.setState({ selectedColors: next });
    });
    const setSelectedColor = vi.fn((hex: string | null) => {
      useConverterStore.setState({ selectedColor: hex });
    });

    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview-replaced.png',
      previewImageUrl: '/preview-replaced.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'select-all',
      palette: [
        {
          quantized_hex: 'A80000',
          matched_hex: 'AA0000',
          pixel_count: 10,
          percentage: 50,
        } satisfies PaletteEntry,
        {
          quantized_hex: '0000F0',
          matched_hex: '0000FF',
          pixel_count: 10,
          percentage: 50,
        } satisfies PaletteEntry,
      ],
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

    flushPendingImages('/preview-replaced.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);
    const context = getVisiblePreviewContext();
    const getImageDataMock = context?.getImageData as unknown as ReturnType<typeof vi.fn>;
    getImageDataMock.mockReturnValue({ data: new Uint8ClampedArray([0, 0, 255, 255]) });

    await act(async () => {
      fireEvent.click(container, { clientX: 120, clientY: 150 });
    });
    expect(sourceColorPickMock).toHaveBeenCalledWith('session-main-2d', 23, 50);

    await act(async () => {
      resolvePick({
        source_matched_hex: '#aa0000',
        quantized_hex: '#a80000',
      });
      await Promise.resolve();
    });

    expect(useConverterStore.getState().selectedColors).toEqual(new Set(['AA0000']));
    expect(useConverterStore.getState().selectedColors.has('0000FF')).toBe(false);
    expect(useConverterStore.getState().selectedColor).toBe('AA0000');
  });

  it('falls back to local preview sampling when source-color picking is unavailable', async () => {
    sourceColorPickMock.mockRejectedValueOnce(new Error('old session'));
    const toggleColorInSelection = vi.fn();
    const setSelectedColor = vi.fn();

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

    await act(async () => {
      fireEvent.click(container, { clientX: 80, clientY: 60 });
    });

    expect(sourceColorPickMock).toHaveBeenCalledWith('session-main-2d', 10, 20);
    expect(toggleColorInSelection).toHaveBeenCalledWith('ABCDEF');
    expect(setSelectedColor).toHaveBeenCalledWith('ABCDEF');
  });

  it('ignores stale source-color picks after leaving select-all mode', async () => {
    let resolvePick: (value: { source_matched_hex: string; quantized_hex: string }) => void = () => {};
    sourceColorPickMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePick = resolve;
      }),
    );

    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'select-all',
      palette: [{
        quantized_hex: 'A80000',
        matched_hex: 'AA0000',
        pixel_count: 10,
        percentage: 100,
      } satisfies PaletteEntry],
      selectedColors: new Set<string>(),
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

    await act(async () => {
      fireEvent.click(container, { clientX: 120, clientY: 150 });
    });
    expect(sourceColorPickMock).toHaveBeenCalledWith('session-main-2d', 23, 50);

    act(() => {
      useConverterStore.getState().setSelectionMode('current');
    });

    await act(async () => {
      resolvePick({
        source_matched_hex: '#aa0000',
        quantized_hex: '#a80000',
      });
    });

    expect(useConverterStore.getState().selectionMode).toBe('current');
    expect(useConverterStore.getState().selectedColors.size).toBe(0);
    expect(useConverterStore.getState().selectedColor).toBeNull();
  });

  it('suppresses SVG contour overlay and shows backend cyan image when selection came from a gradient region', async () => {
    // Regression: picking a region button in the Gradient Groups panel
    // previously left the frontend painting cyan outlines for *every*
    // pixel of the selected hexes across the whole canvas (because
    // ``colorContours`` is a whole-image structure), while simultaneously
    // keeping the preview anchored to the plain base image. The exact
    // cyan mask the backend produced (``previewImageUrl``) was never shown.
    // Users saw "the whole body lit cyan" instead of just the region.
    // This test pins both halves of the fix: region-scoped selection
    // (1) loads ``previewImageUrl`` instead of ``previewBaseImageUrl``
    // (2) renders no contour polygons (the mask is already baked into
    //     the backend image).
    // 回归：点击区域按钮时前端原本用全图 colorContours 绘制 cyan 轮廓，
    // 同时预览仍指向干净的 previewBaseImageUrl，后端精确 mask 图反而没
    // 被显示——于是"区域选中"看起来全身都亮。本测试锁定修复的两半：
    // 区域来源时应显示 previewImageUrl 并跳过 contour 绘制。
    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/base.png',
      previewImageUrl: '/cyan-region.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'select-all',
      selectedColor: null,
      selectedColors: new Set(['aabbcc', 'ddeeff']),
      colorContours: {
        aabbcc: [
          [
            [0, 0],
            [20, 0],
            [20, 20],
          ],
        ],
        ddeeff: [
          [
            [30, 30],
            [50, 30],
            [50, 50],
          ],
        ],
      },
      gradientSelection: { kind: 'region', groupIndex: 3, regionIndex: 1 },
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

    flushPendingImages('/cyan-region.png');

    // (1) Preloader must have requested the backend's precise cyan image,
    // not the stable base preview.
    const loadedSrcs = TestImage.instances.map((image) => image.src);
    expect(loadedSrcs).toContain('/cyan-region.png');

    // (2) No SVG contour polygons may be rendered: the cyan mask is
    // already baked into the loaded image, and ``colorContours`` would
    // otherwise outline pixels that are outside of the region.
    expect(container.querySelector('polygon')).toBeNull();
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

  it('shows the original image while Shift is held and releases it on keyup', () => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      imagePreviewUrl: '/original-upload.png',
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
    });

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const holdButton = screen.getByTestId('color-preview-2d-hold-original');
    expect(holdButton).not.toHaveAttribute('data-active');

    act(() => {
      fireEvent.keyDown(window, { key: 'Shift' });
    });
    expect(holdButton).toHaveAttribute('data-active', 'true');

    act(() => {
      fireEvent.keyUp(window, { key: 'Shift' });
    });
    expect(holdButton).not.toHaveAttribute('data-active');
  });

  it('does not trigger the Shift shortcut while typing in a text input', () => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      imagePreviewUrl: '/original-upload.png',
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
    });

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();

    const holdButton = screen.getByTestId('color-preview-2d-hold-original');

    act(() => {
      fireEvent.keyDown(input, { key: 'Shift' });
    });
    expect(holdButton).not.toHaveAttribute('data-active');

    input.remove();
  });

  it('releases the original view when the window loses focus mid-press', () => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      imagePreviewUrl: '/original-upload.png',
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
    });

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const holdButton = screen.getByTestId('color-preview-2d-hold-original');

    act(() => {
      fireEvent.keyDown(window, { key: 'Shift' });
    });
    expect(holdButton).toHaveAttribute('data-active', 'true');

    act(() => {
      fireEvent.blur(window);
    });
    expect(holdButton).not.toHaveAttribute('data-active');
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

  it('keeps the color-picking cursor after zooming the workstation preview', () => {
    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    act(() => {
      fireEvent.wheel(container, { clientX: 120, clientY: 150, deltaY: -100 });
    });

    expect(screen.getByText('115%')).toBeInTheDocument();
    expect(container).toHaveClass('cursor-crosshair');
    expect(container).not.toHaveClass('cursor-grab');
  });

  it('keeps left-click color selection active after zooming', () => {
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
      fireEvent.wheel(container, { clientX: 120, clientY: 150, deltaY: -100 });
      fireEvent.click(container, { clientX: 120, clientY: 150, button: 0 });
    });

    expect(detectRegion).toHaveBeenCalledWith(23, 50);
  });

  it('keeps right-button panning available after zooming', async () => {
    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);
    const setPointerCapture = vi.fn();
    const releasePointerCapture = vi.fn();
    Object.defineProperty(container, 'setPointerCapture', {
      configurable: true,
      value: setPointerCapture,
    });
    Object.defineProperty(container, 'releasePointerCapture', {
      configurable: true,
      value: releasePointerCapture,
    });

    act(() => {
      fireEvent.wheel(container, { clientX: 120, clientY: 150, deltaY: -100 });
    });

    act(() => {
      fireEvent.pointerDown(container, { pointerId: 3, button: 2, clientX: 120, clientY: 150 });
      fireEvent.pointerMove(container, { pointerId: 3, buttons: 2, clientX: 150, clientY: 170 });
      fireEvent.pointerUp(container, { pointerId: 3, button: 2, clientX: 150, clientY: 170 });
    });
    await act(async () => {});

    expect(setPointerCapture).toHaveBeenCalledWith(3);
    expect(releasePointerCapture).toHaveBeenCalledWith(3);
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
