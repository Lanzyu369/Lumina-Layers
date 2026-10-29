import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PaletteEntry, ReplacementHistoryResponse, SelectionDocumentResponse } from '../api/types';
import ColorPreview2D from '../components/sections/ColorPreview2D';
import LutColorGrid from '../components/sections/LutColorGrid';
import MaterialColorPicker from '../components/sections/MaterialColorPicker';
import { buildLayerImagesSourceKey, DEFAULT_STATE, useConverterStore } from '../stores/converter';
import { useEyedropperStore } from '../stores/eyedropperStore';

const sourceColorPickMock = vi.hoisted(() => vi.fn());
const selectionApiMocks = vi.hoisted(() => ({
  getEditorSelection: vi.fn(),
  mutateEditorSelection: vi.fn(),
  replacementHistory: vi.fn(),
}));

vi.mock('../api/converter', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/converter')>()),
  sourceColorPick: sourceColorPickMock,
  ...selectionApiMocks,
}));

vi.mock('../i18n/context', () => ({
  useI18n: () => ({ t: (key: string) => key, lang: 'zh' as const }),
}));

const ORIGINAL_STORE_ACTIONS = {
  setSelectedColor: useConverterStore.getState().setSelectedColor,
  toggleColorInSelection: useConverterStore.getState().toggleColorInSelection,
  detectRegion: useConverterStore.getState().detectRegion,
  detectAndAccumulateRegion: useConverterStore.getState().detectAndAccumulateRegion,
  removeRegionFromSelection: useConverterStore.getState().removeRegionFromSelection,
  clearSelection: useConverterStore.getState().clearSelection,
  applySelectionMutation: useConverterStore.getState().applySelectionMutation,
  hydrateSelectionDocument: useConverterStore.getState().hydrateSelectionDocument,
  undoColorRemap: useConverterStore.getState().undoColorRemap,
  fetchLayerImages: useConverterStore.getState().fetchLayerImages,
};

const OriginalImage = globalThis.Image;
let sharedGetImageDataMock: ReturnType<typeof vi.fn>;
let selectionFixtureSession = 0;
const finishPendingRequests: Array<() => void> = [];

function deferredResponse<T>(fallback: T) {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, fail) => { resolve = accept; reject = fail; });
  finishPendingRequests.push(() => resolve(fallback));
  return { promise, resolve, reject };
}

type SelectionFixtureBlock = 'a' | 'b' | 'c';
const SELECTION_FIXTURE_BLOCKS = {
  a: { x: 8, hex: '#111111', label: 1 },
  b: { x: 10, hex: '#222222', label: 2 },
  c: { x: 30, hex: '#111111', label: 3 },
} as const;

function selectionFixtureDocument(
  revision: number, blocks: SelectionFixtureBlock[],
  extra: Partial<SelectionDocumentResponse> = {},
): SelectionDocumentResponse {
  const contours = blocks.includes('a') && blocks.includes('b')
    ? [[[8, 80], [12, 80], [12, 78], [8, 78]]]
    : blocks.filter((block) => block !== 'c').map((block) => {
        const { x } = SELECTION_FIXTURE_BLOCKS[block];
        return [[x, 80], [x + 2, 80], [x + 2, 78], [x, 78]];
      });
  if (blocks.includes('c')) contours.push([[30, 80], [32, 80], [32, 78], [30, 78]]);
  return {
    selection_revision: revision, content_revision: 10,
    selected_pixel_count: blocks.length * 4, selected_component_count: blocks.length,
    selected_color_hexes: [...new Set(blocks.map((block) => SELECTION_FIXTURE_BLOCKS[block].hex))],
    region_ids: blocks.length ? [`__editor_selection__:${revision}`] : [],
    components: blocks.map((block) => {
      const { x, hex, label } = SELECTION_FIXTURE_BLOCKS[block];
      return { label, region_id: `visible-${block}`, color_hex: hex, pixel_count: 4,
        bbox: [x, 20, 2, 2], anchor: [x, 20] };
    }),
    contours, can_undo: revision > 0, can_redo: false,
    ...extra,
  };
}

function outlineBounds(): number[][] {
  const path = screen.queryByTestId('selection-marching-ants-white')?.getAttribute('d') ?? '';
  return (path.match(/M[^Z]*Z/g) ?? []).map((polygon) => {
    const points = [...polygon.matchAll(/[ML]\s+([-\d.e+]+)\s+([-\d.e+]+)/gi)]
      .map((match) => [Number(match[1]), Number(match[2])]);
    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }).sort((left, right) => left[0] - right[0]);
}

function renderSelectionFixture(document = selectionFixtureDocument(0, [])): HTMLElement {
  const data = new Uint8ClampedArray(100 * 100 * 4);
  for (const [block, { x }] of Object.entries(SELECTION_FIXTURE_BLOCKS)) {
    const channel = block === 'b' ? 34 : 17;
    for (const y of [20, 21]) {
      for (const column of [x, x + 1]) {
        data.set([channel, channel, channel, 255], (y * 100 + column) * 4);
      }
    }
  }
  sharedGetImageDataMock.mockReturnValue({ data });
  selectionApiMocks.getEditorSelection.mockResolvedValue(document);
  useConverterStore.setState({
    ...DEFAULT_STATE, ...ORIGINAL_STORE_ACTIONS,
    previewBaseImageUrl: '/preview.png', previewImageUrl: '/preview.png',
    previewPixelWidth: 100, previewPixelHeight: 100, preview_width_mm: 100,
    sessionId: `selection-visual-${++selectionFixtureSession}`,
    selectionMode: 'multi-select', selectionTool: 'point', selectionDocument: document,
    historyCanUndo: document.can_undo, historyCanRedo: document.can_redo,
    fetchLayerImages: vi.fn(async () => {}),
  });
  render(<ColorPreview2D />);
  const container = screen.getByTestId('color-preview-2d-container');
  mockPreviewRect(container);
  flushPendingImages('/preview.png');
  return container;
}

function clickSelectionBlock(container: HTMLElement, block: SelectionFixtureBlock): void {
  const { x } = SELECTION_FIXTURE_BLOCKS[block];
  fireEvent.click(container, { clientX: 50 + (x + 0.5) * 3, clientY: 61.5 });
}

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
  const context = {
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
    arc: vi.fn(),
    closePath: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    getImageData: sharedGetImageDataMock,
    imageSmoothingEnabled: true,
    strokeStyle: '',
    lineWidth: 1,
    lineJoin: '',
    lineCap: '',
  } as unknown as CanvasRenderingContext2D;
  return context;
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

function paintBrushStroke(container: HTMLElement, pointerId: number, start: [number, number], end: [number, number]): void {
  act(() => {
    fireEvent.pointerDown(container, { button: 0, pointerId, clientX: start[0], clientY: start[1] });
    fireEvent.pointerMove(container, { button: 0, pointerId, clientX: end[0], clientY: end[1] });
    fireEvent.pointerUp(container, { button: 0, pointerId, clientX: end[0], clientY: end[1] });
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

    sharedGetImageDataMock = vi.fn((x: number, y: number) => {
      if (x === 10 && y === 20) {
        return { data: new Uint8ClampedArray([171, 205, 239, 255]) };
      }
      return { data: new Uint8ClampedArray([17, 34, 51, 255]) };
    });
    installCanvasContextMock();
    sourceColorPickMock.mockReset();
    sourceColorPickMock.mockRejectedValue(new Error('source color pick unavailable'));
    Object.values(selectionApiMocks).forEach((mock) => mock.mockReset());

    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
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

  afterEach(async () => {
    await act(async () => { finishPendingRequests.splice(0).forEach((finish) => finish()); });
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
    expect(screen.queryByRole('button', { name: 'zoom_reset' })).not.toBeInTheDocument();
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
      sessionId: null,
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

  it.each(['point', 'brush'] as const)(
    'eyedropper picks the clicked pixel colour without touching the selection (%s tool)',
    async (tool) => {
      const applySelectionMutation = vi.fn(async () => true);
      const toggleColorInSelection = vi.fn();
      useEyedropperStore.setState({ active: true, lastPick: null });
      useConverterStore.setState({
        ...DEFAULT_STATE,
        previewBaseImageUrl: '/preview.png',
        previewImageUrl: '/preview.png',
        previewPixelWidth: 100,
        previewPixelHeight: 100,
        selectionTool: tool,
        selectionMode: 'multi-select',
        applySelectionMutation,
        toggleColorInSelection,
        sessionId: 'session-eyedropper',
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

      expect(useEyedropperStore.getState().lastPick?.hex).toBe('#abcdef');
      expect(useEyedropperStore.getState().active).toBe(false);
      expect(applySelectionMutation).not.toHaveBeenCalled();
      expect(toggleColorInSelection).not.toHaveBeenCalled();
      expect(sourceColorPickMock).not.toHaveBeenCalled();
    },
  );

  it('optimistically sets the clicked palette colour in single-select mode before region detection returns', async () => {
    const detectRegion = vi.fn(
      () => new Promise<void>(() => {
        // Keep the request pending so the assertion proves the immediate path.
      }),
    );
    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'current',
      palette: [{
        quantized_hex: 'ABCDEF',
        matched_hex: 'ABCDEF',
        pixel_count: 10,
        percentage: 100,
      } satisfies PaletteEntry],
      selectedColor: null,
      sessionId: 'session-main-2d',
      preview_width_mm: 80,
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
      detectRegion,
    } as never);

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    await act(async () => {
      fireEvent.click(container, { clientX: 80, clientY: 60 });
      await Promise.resolve();
    });

    expect(detectRegion).toHaveBeenCalledWith(10, 20);
    expect(useConverterStore.getState().selectedColor).toBe('ABCDEF');
  });

  it('keeps click selection active immediately after the preview image load event', async () => {
    const detectRegion = vi.fn(
      () => new Promise<void>(() => {
        // Keep pending: this test only needs to prove the click is not dropped.
      }),
    );
    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
      previewBaseImageUrl: '/fresh-preview.png',
      previewImageUrl: '/fresh-preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'current',
      palette: [{
        quantized_hex: 'ABCDEF',
        matched_hex: 'ABCDEF',
        pixel_count: 10,
        percentage: 100,
      } satisfies PaletteEntry],
      selectedColor: null,
      sessionId: 'session-main-2d',
      preview_width_mm: 80,
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
      detectRegion,
    } as never);

    render(<ColorPreview2D />);

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);
    sharedGetImageDataMock.mockReturnValue({
      data: new Uint8ClampedArray([0xab, 0xcd, 0xef, 255]),
    });
    const freshPreviewImage = getPendingImages('/fresh-preview.png').at(-1);
    expect(freshPreviewImage).toBeDefined();

    act(() => {
      freshPreviewImage?.dispatchLoad();
      fireEvent.click(container, { clientX: 80, clientY: 60 });
    });

    expect(detectRegion).toHaveBeenCalledWith(10, 20);
    expect(useConverterStore.getState().selectedColor).toBe('ABCDEF');
  });

  it('shows adjacent point selections immediately and converges to the confirmed union without losing pending clicks', async () => {
    const initial = selectionFixtureDocument(0, []);
    const selectedA = selectionFixtureDocument(1, ['a']);
    const selectedAB = selectionFixtureDocument(2, ['a', 'b']);
    const first = deferredResponse(selectedA);
    const second = deferredResponse(selectedAB);
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const container = renderSelectionFixture(initial);

    clickSelectionBlock(container, 'a');
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    clickSelectionBlock(container, 'b');
    expect(outlineBounds()).toEqual([[8, 20, 10, 22], [10, 20, 12, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(initial);
    expect(useConverterStore.getState().historyCanUndo).toBe(false);
    expect(useConverterStore.getState().historyCanRedo).toBe(false);
    expect(useConverterStore.getState().pendingSelectionMutations).toHaveLength(2);
    await act(async () => { await Promise.resolve(); });
    expect(selectionApiMocks.mutateEditorSelection).toHaveBeenCalledOnce();

    await act(async () => { first.resolve(selectedA); });
    expect(useConverterStore.getState().selectionDocument).toBe(selectedA);
    expect(useConverterStore.getState().pendingSelectionMutations).toHaveLength(1);
    expect(outlineBounds()).toEqual([[8, 20, 10, 22], [10, 20, 12, 22]]);
    expect(selectionApiMocks.mutateEditorSelection).toHaveBeenCalledTimes(2);

    await act(async () => { second.resolve(selectedAB); });
    expect(outlineBounds()).toEqual([[8, 20, 12, 22]]);
    expect(screen.getByTestId('selection-marching-ants-white'))
      .toHaveAttribute('d', 'M 8 20 L 12 20 L 12 22 L 8 22 Z');
    expect(useConverterStore.getState().selectionDocument).toBe(selectedAB);
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
    expect(selectionApiMocks.mutateEditorSelection.mock.calls.map(([request]) => ({
      operation: request.operation, x: request.x, base: request.base_selection_revision,
    }))).toEqual([
      { operation: 'point-toggle', x: 8, base: 0 },
      { operation: 'point-toggle', x: 10, base: 1 },
    ]);
    expect(useConverterStore.getState().historyCanUndo).toBe(true);
  });

  it('keeps a rapid repeated point toggle visually empty as each server response arrives', async () => {
    const selectedA = selectionFixtureDocument(1, ['a']);
    const empty = selectionFixtureDocument(2, []);
    const first = deferredResponse(selectedA);
    const second = deferredResponse(empty);
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const container = renderSelectionFixture();

    clickSelectionBlock(container, 'a');
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    clickSelectionBlock(container, 'a');
    expect(outlineBounds()).toEqual([]);
    expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(0);
    await act(async () => { first.resolve(selectedA); });
    expect(outlineBounds()).toEqual([]);
    expect(useConverterStore.getState().selectionDocument).toBe(selectedA);
    await act(async () => { second.resolve(empty); });
    expect(outlineBounds()).toEqual([]);
    expect(useConverterStore.getState().selectionDocument).toBe(empty);
    expect(selectionApiMocks.mutateEditorSelection).toHaveBeenCalledTimes(2);
  });

  it('keeps only B visible through the confirmations of rapid A, B, A clicks', async () => {
    const documents = [
      selectionFixtureDocument(1, ['a']), selectionFixtureDocument(2, ['a', 'b']),
      selectionFixtureDocument(3, ['b']),
    ];
    const responses = documents.map((document) => deferredResponse(document));
    responses.forEach((response) => selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(response.promise));
    const container = renderSelectionFixture();

    clickSelectionBlock(container, 'a');
    clickSelectionBlock(container, 'b');
    clickSelectionBlock(container, 'a');
    expect(outlineBounds()).toEqual([[10, 20, 12, 22]]);
    expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(0);
    for (const [index, response] of responses.entries()) {
      await act(async () => { response.resolve(documents[index]); });
      expect(outlineBounds()).toEqual([[10, 20, 12, 22]]);
      expect(useConverterStore.getState().selectionDocument).toBe(documents[index]);
    }
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
    expect(selectionApiMocks.mutateEditorSelection.mock.calls.map(([request]) => request.base_selection_revision))
      .toEqual([0, 1, 2]);
  });

  it('drops a failed visual draft while preserving confirmed selection during reconciliation', async () => {
    const selectedA = selectionFixtureDocument(1, ['a']);
    const failedSelection = deferredResponse(selectionFixtureDocument(2, ['a', 'b']));
    const reconciliation = deferredResponse(selectedA);
    const container = renderSelectionFixture(selectedA);
    await act(async () => { await useConverterStore.getState().hydrateSelectionDocument(); });
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(failedSelection.promise);
    selectionApiMocks.getEditorSelection.mockReturnValueOnce(reconciliation.promise);

    clickSelectionBlock(container, 'b');
    expect(outlineBounds()).toEqual([[8, 20, 10, 22], [10, 20, 12, 22]]);
    await act(async () => { failedSelection.reject(new Error('selection request failed')); });
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(selectedA);
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
    expect(useConverterStore.getState().error).toBeTruthy();
    await act(async () => { reconciliation.resolve(selectedA); });
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(selectionApiMocks.mutateEditorSelection).toHaveBeenCalledOnce();
  });

  it('clears pending point outlines immediately and keeps them empty through queued confirmations', async () => {
    const selectedA = selectionFixtureDocument(1, ['a']);
    const empty = selectionFixtureDocument(2, []);
    const first = deferredResponse(selectedA);
    const clearResponse = deferredResponse(empty);
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(first.promise).mockReturnValueOnce(clearResponse.promise);
    const container = renderSelectionFixture();

    clickSelectionBlock(container, 'a');
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    let clear!: Promise<void>;
    act(() => { clear = useConverterStore.getState().clearSelection(); });
    expect(outlineBounds()).toEqual([]);
    expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(0);
    await act(async () => { first.resolve(selectedA); });
    expect(outlineBounds()).toEqual([]);
    expect(useConverterStore.getState().selectionDocument).toBe(selectedA);
    await act(async () => { clearResponse.resolve(empty); await clear; });
    expect(outlineBounds()).toEqual([]);
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
    expect(selectionApiMocks.mutateEditorSelection.mock.calls.map(([request]) => request.operation))
      .toEqual(['point-toggle', 'clear']);
    expect(useConverterStore.getState().historyCanUndo).toBe(true);
  });

  it('ignores old-session visual drafts and responses while preserving a new-session click', async () => {
    const oldSelectedA = selectionFixtureDocument(1, ['a']);
    const newSelectedB = selectionFixtureDocument(1, ['b']);
    const oldResponse = deferredResponse(oldSelectedA);
    const newResponse = deferredResponse(newSelectedB);
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(oldResponse.promise).mockReturnValueOnce(newResponse.promise);
    const container = renderSelectionFixture();
    const oldSession = useConverterStore.getState().sessionId;
    clickSelectionBlock(container, 'a');
    await act(async () => { await Promise.resolve(); });
    expect(selectionApiMocks.mutateEditorSelection).toHaveBeenCalledOnce();
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);

    const newEmpty = selectionFixtureDocument(0, []);
    act(() => useConverterStore.setState({
      sessionId: `selection-visual-${++selectionFixtureSession}`, selectionDocument: newEmpty,
    }));
    expect(outlineBounds()).toEqual([]);
    clickSelectionBlock(container, 'b');
    expect(outlineBounds()).toEqual([[10, 20, 12, 22]]);
    await act(async () => { oldResponse.resolve(oldSelectedA); });
    expect(outlineBounds()).toEqual([[10, 20, 12, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(newEmpty);
    await act(async () => { newResponse.resolve(newSelectedB); });
    expect(outlineBounds()).toEqual([[10, 20, 12, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(newSelectedB);
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
    expect(selectionApiMocks.mutateEditorSelection.mock.calls.map(([request]) => request.session_id))
      .toEqual([oldSession, useConverterStore.getState().sessionId]);
  });

  it('keeps the local point outline visible while the first authoritative document loads', async () => {
    const empty = selectionFixtureDocument(0, []);
    const selectedA = selectionFixtureDocument(1, ['a']);
    const hydration = deferredResponse(empty);
    const mutation = deferredResponse(selectedA);
    const container = renderSelectionFixture(empty);
    act(() => useConverterStore.setState({ selectionDocument: null }));
    selectionApiMocks.getEditorSelection.mockReturnValueOnce(hydration.promise);
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(mutation.promise);

    clickSelectionBlock(container, 'a');
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBeNull();
    await act(async () => { hydration.resolve(empty); });
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(empty);
    await act(async () => { mutation.resolve(selectedA); });
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(selectedA);
  });

  it('does not replay a pending point toggle over a concurrent hydration response that already includes it', async () => {
    const initial = selectionFixtureDocument(0, []);
    const selectedA = selectionFixtureDocument(1, ['a']);
    const earlyGet = deferredResponse(selectedA);
    const mutation = deferredResponse(selectedA);
    const container = renderSelectionFixture(initial);
    selectionApiMocks.getEditorSelection.mockReturnValueOnce(earlyGet.promise);
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(mutation.promise);
    let hydration!: Promise<void>;
    await act(async () => {
      hydration = useConverterStore.getState().hydrateSelectionDocument();
      await Promise.resolve();
    });
    expect(selectionApiMocks.getEditorSelection).toHaveBeenCalledOnce();

    clickSelectionBlock(container, 'a');
    await act(async () => { await Promise.resolve(); });
    expect(selectionApiMocks.mutateEditorSelection).toHaveBeenCalledOnce();
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    // The GET began first but observed the server after its point toggle.
    // Publishing it before retiring the pending toggle would deselect A twice.
    await act(async () => { earlyGet.resolve(selectedA); });
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(initial);
    expect(useConverterStore.getState().pendingSelectionMutations).toHaveLength(1);

    await act(async () => { mutation.resolve(selectedA); await hydration; });
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(selectedA);
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
    expect(selectionApiMocks.mutateEditorSelection).toHaveBeenCalledOnce();
  });

  it('waits for pending point selection before starting a public hydration request', async () => {
    const initial = selectionFixtureDocument(0, []);
    const selectedA = selectionFixtureDocument(1, ['a']);
    const mutation = deferredResponse(selectedA);
    const lateGet = deferredResponse(selectedA);
    const container = renderSelectionFixture(initial);
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(mutation.promise);
    selectionApiMocks.getEditorSelection.mockReturnValueOnce(lateGet.promise);

    clickSelectionBlock(container, 'a');
    let hydration!: Promise<void>;
    await act(async () => {
      hydration = useConverterStore.getState().hydrateSelectionDocument();
      await Promise.resolve();
    });
    expect(selectionApiMocks.getEditorSelection).not.toHaveBeenCalled();
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(initial);

    await act(async () => { mutation.resolve(selectedA); });
    expect(selectionApiMocks.getEditorSelection).toHaveBeenCalledOnce();
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(selectedA);
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
    await act(async () => { lateGet.resolve(selectedA); await hydration; });
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(useConverterStore.getState().selectionDocument).toBe(selectedA);
    expect(selectionApiMocks.mutateEditorSelection).toHaveBeenCalledOnce();
  });

  it('shows the restored outline after undoing a point selection that was still pending', async () => {
    const selectedA = selectionFixtureDocument(1, ['a']);
    const empty = selectionFixtureDocument(2, [], { can_undo: false, can_redo: true });
    const first = deferredResponse(selectedA);
    const historyResult: ReplacementHistoryResponse = {
      status: 'ok', action: 'undo', entry_kind: 'selection', message: 'ok',
      preview_url: '/preview.png', can_undo: false, can_redo: true,
      replacement_regions: [], recipe_overrides: [], recipe_override_count: 0,
      selection: empty,
    };
    const undoResponse = deferredResponse(historyResult);
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(first.promise);
    selectionApiMocks.replacementHistory.mockReturnValueOnce(undoResponse.promise);
    const container = renderSelectionFixture();

    clickSelectionBlock(container, 'a');
    let undo!: Promise<void>;
    act(() => { undo = useConverterStore.getState().undoColorRemap(); });
    await act(async () => { first.resolve(selectedA); });
    expect(outlineBounds()).toEqual([[8, 20, 10, 22]]);
    expect(selectionApiMocks.replacementHistory).toHaveBeenCalledOnce();
    await act(async () => { undoResponse.resolve(historyResult); await undo; });
    expect(outlineBounds()).toEqual([]);
    expect(useConverterStore.getState().selectionDocument).toBe(empty);
    expect(useConverterStore.getState().historyCanRedo).toBe(true);
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
  });

  it.each([
    ['point', true], ['same-color', true], ['point', false], ['same-color', false],
  ] as const)(
    'dispatches %s selection without a readable pixel buffer (document loaded: %s)', async (selectionTool, hasDocument) => {
      const applySelectionMutation = vi.fn(async () => true);
      sharedGetImageDataMock.mockImplementation(() => { throw new Error('pixel buffer unavailable'); });
      useConverterStore.setState({
        selectionMode: 'multi-select', selectionTool, applySelectionMutation,
        selectionDocument: hasDocument ? {
          selection_revision: 5, content_revision: 7,
          selected_pixel_count: 0, selected_component_count: 0,
          selected_color_hexes: [], region_ids: [], components: [], contours: [],
          can_undo: true, can_redo: false,
        } : null,
      });
      render(<ColorPreview2D />);
      flushPendingImages('/preview.png');
      const container = screen.getByTestId('color-preview-2d-container');
      mockPreviewRect(container);

      await act(async () => {
        fireEvent.click(container, { clientX: 80, clientY: 60 });
      });

      expect(applySelectionMutation).toHaveBeenCalledWith({
        operation: selectionTool === 'point' ? 'point-toggle' : 'same-color-toggle',
        x: 10, y: 20,
      });
      expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(hasDocument ? 5 : undefined);
    },
  );

  it('renders no stale legacy outline when the authoritative selection is empty', () => {
    useConverterStore.setState({
      selectionMode: 'multi-select',
      selectedRegions: [{
        regionId: 'stale-region', colorHex: '#111111', pixelCount: 4,
        clickX: 8, clickY: 20, previewUrl: '/preview.png',
        contours: [[[8, 80], [10, 80], [10, 78], [8, 78]]],
      }],
      selectionDocument: {
        selection_revision: 5, content_revision: 7,
        selected_pixel_count: 0, selected_component_count: 0,
        selected_color_hexes: [], region_ids: [], components: [], contours: [],
        can_undo: true, can_redo: false,
      },
    });
    render(<ColorPreview2D />);
    flushPendingImages('/preview.png');

    expect(screen.queryByTestId('selection-marching-ants-white')).toBeNull();
  });

  it.each([true, false])('submits separate brush strokes in one operation (document loaded: %s)', async (hasDocument) => {
    const applySelectionMutation = vi.fn(async () => true);
    useConverterStore.setState({
      selectionMode: 'multi-select', selectionTool: 'brush', brushSizePx: 12,
      applySelectionMutation,
      selectionDocument: hasDocument ? {
        selection_revision: 5, content_revision: 7,
        selected_pixel_count: 0, selected_component_count: 0,
        selected_color_hexes: [], region_ids: [], components: [], contours: [],
        can_undo: true, can_redo: false,
      } : null,
    });
    render(<ColorPreview2D />);
    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);
    flushPendingImages('/preview.png');

    paintBrushStroke(container, 31, [80, 60], [110, 60]);
    paintBrushStroke(container, 32, [230, 180], [260, 180]);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'selection_brush_apply' }));
    });

    expect(applySelectionMutation).toHaveBeenCalledExactlyOnceWith({
      operation: 'brush-add', brushRadius: 2,
      brushStrokes: [
        [{ x: 10, y: 20 }, { x: 20, y: 20 }],
        [{ x: 60, y: 60 }, { x: 70, y: 60 }],
      ],
    });
    expect(screen.queryByRole('button', { name: 'selection_brush_apply' })).toBeNull();
  });

  it('keeps failed brush drafts and preserves later strokes when an earlier submission succeeds', async () => {
    let resolveFirst: (succeeded: boolean) => void = () => {};
    let resolveSecond: (succeeded: boolean) => void = () => {};
    const applySelectionMutation = vi.fn(async () => true)
      .mockImplementationOnce(() => new Promise<boolean>((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise<boolean>((resolve) => { resolveSecond = resolve; }));
    useConverterStore.setState({
      selectionMode: 'multi-select', selectionTool: 'brush', brushSizePx: 12,
      applySelectionMutation, selectionDocument: null,
    });
    render(<ColorPreview2D />);
    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);
    flushPendingImages('/preview.png');

    paintBrushStroke(container, 41, [80, 60], [110, 60]);
    fireEvent.click(screen.getByRole('button', { name: 'selection_brush_apply' }));
    expect(screen.getByRole('button', { name: 'selection_brush_apply' })).toBeDisabled();
    paintBrushStroke(container, 42, [230, 180], [260, 180]);
    await act(async () => { resolveFirst(false); });
    expect(screen.getByRole('button', { name: 'selection_brush_apply' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'selection_brush_apply' }));
    expect(applySelectionMutation).toHaveBeenLastCalledWith({
      operation: 'brush-add', brushRadius: 2,
      brushStrokes: [
        [{ x: 10, y: 20 }, { x: 20, y: 20 }],
        [{ x: 60, y: 60 }, { x: 70, y: 60 }],
      ],
    });
    paintBrushStroke(container, 43, [140, 120], [170, 120]);
    await act(async () => { resolveSecond(true); });
    expect(screen.getByRole('button', { name: 'selection_brush_apply' })).toBeEnabled();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'selection_brush_apply' }));
    });

    expect(applySelectionMutation).toHaveBeenLastCalledWith({
      operation: 'brush-add', brushRadius: 2,
      brushStrokes: [[{ x: 30, y: 40 }, { x: 40, y: 40 }]],
    });
    expect(screen.queryByRole('button', { name: 'selection_brush_apply' })).toBeNull();
  });

  it.each(['lut', 'material'])('stages a target from %s while the first visible point selection is pending', async (picker) => {
    const response = deferredResponse(selectionFixtureDocument(1, ['a']));
    selectionApiMocks.mutateEditorSelection.mockReturnValueOnce(response.promise);
    const container = renderSelectionFixture();
    useConverterStore.setState({
      source_version: 'legacy',
      lutColors: [{ hex: '#ff0000', rgb: [255, 0, 0] }],
      lutColorsLutName: '', lutColorsLoading: false,
      selectedMaterialDirNames: ['red'], materialSuggestionsLoading: false,
      materialSuggestions: {
        status: 'ok', message: 'ok', source: 'cache', palette_hash: 'test',
        layer_count: 1, layer_height_mm: 0.08, substrate: 'white',
        target_hex: '#ff0000', target_rgb: [255, 0, 0],
        suggestions: [{ hex: '#ff0000', rgb: [255, 0, 0], delta_e: 0.1,
          recipe: [0], recipe_display: '[0]' }],
      },
    });
    render(picker === 'lut' ? <LutColorGrid /> : <MaterialColorPicker />);

    await act(async () => { clickSelectionBlock(container, 'a'); });
    expect(outlineBounds().length).toBeGreaterThan(0);
    expect(useConverterStore.getState().pendingSelectionMutations).toHaveLength(1);
    expect(useConverterStore.getState().selectionDocument?.selected_component_count).toBe(0);
    const target = screen.getByRole('button', {
      name: picker === 'lut' ? 'lut_grid_color_label' : 'material_picker_suggestion_tooltip',
    });
    fireEvent.click(target);
    expect(useConverterStore.getState().pendingReplacement).toMatchObject({
      targetHex: 'ff0000', mode: 'multi-select',
    });

    // A pending gesture from a previous image cannot enable a new empty session.
    act(() => { useConverterStore.setState({ sessionId: 'unrelated-session', pendingReplacement: null }); });
    fireEvent.click(target);
    expect(useConverterStore.getState().pendingReplacement).toBeNull();
  });

  it('preserves a later brush stroke size when an earlier submission succeeds', async () => {
    const response = deferredResponse(true);
    const applySelectionMutation = vi.fn(async () => true).mockReturnValueOnce(response.promise);
    useConverterStore.setState({
      selectionMode: 'multi-select', selectionTool: 'brush', brushSizePx: 12,
      applySelectionMutation, selectionDocument: null,
    });
    render(<ColorPreview2D />);
    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);
    flushPendingImages('/preview.png');

    paintBrushStroke(container, 51, [80, 60], [110, 60]);
    fireEvent.click(screen.getByRole('button', { name: 'selection_brush_apply' }));
    act(() => { useConverterStore.getState().setBrushSizePx(60); });
    paintBrushStroke(container, 52, [230, 180], [260, 180]);
    const context = (screen.getByTestId('selection-brush-draft') as HTMLCanvasElement).getContext('2d')!;
    expect(context.lineWidth).toBe(20);
    await act(async () => { response.resolve(true); });
    expect(context.lineWidth).toBe(20);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'selection_brush_apply' }));
    });
    expect(applySelectionMutation).toHaveBeenLastCalledWith({
      operation: 'brush-add', brushRadius: 10,
      brushStrokes: [[{ x: 60, y: 60 }, { x: 70, y: 60 }]],
    });
    expect(screen.queryByRole('button', { name: 'selection_brush_apply' })).toBeNull();
  });

  it('does not render same-colour contours while a single-select region detection is still pending', async () => {
    const detectRegion = vi.fn(
      () => new Promise<void>(() => {
        // Keep pending: the test verifies no whole-colour contour flashes
        // before the region-specific response arrives.
      }),
    );

    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      preview_width_mm: 80,
      selectionMode: 'current',
      palette: [{
        quantized_hex: 'ABCDEF',
        matched_hex: 'ABCDEF',
        pixel_count: 10,
        percentage: 100,
      } satisfies PaletteEntry],
      colorContours: {
        ABCDEF: [
          [
            [0, 0],
            [80, 0],
            [80, 80],
            [0, 80],
          ],
        ],
      },
      selectedColor: null,
      regionData: null,
      detectRegion,
      sessionId: 'session-main-2d',
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
    });

    const { container: rendered } = render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    act(() => {
      fireEvent.click(container, { clientX: 80, clientY: 60 });
    });

    expect(useConverterStore.getState().selectedColor).toBe('ABCDEF');
    expect(detectRegion).toHaveBeenCalledWith(10, 20);
    expect(rendered.querySelector('[data-testid="selection-contour-compat"]')).toBeNull();
    expect(rendered.querySelector('[data-testid="selection-marching-ants-white"]')).toBeNull();
    expect(rendered.querySelector('[data-testid="selection-marching-ants-black"]')).toBeNull();
  });

  it('immediately deselects the current region when the selected region is clicked again', async () => {
    const detectRegion = vi.fn();

    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/region-mask.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      preview_width_mm: 80,
      selectionMode: 'current',
      selectedColor: 'AABBCC',
      regionData: {
        regionId: 'region-1',
        colorHex: '#AABBCC',
        pixelCount: 42,
        previewUrl: '/region-mask.png',
        contours: [
          [
            [0, 0],
            [80, 0],
            [80, 80],
            [0, 80],
          ],
        ],
      },
      detectRegion,
      sessionId: null,
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
    sharedGetImageDataMock.mockReturnValue({
      data: new Uint8ClampedArray([0xaa, 0xbb, 0xcc, 255]),
    });

    act(() => {
      fireEvent.click(container, { clientX: 120, clientY: 150 });
    });

    expect(detectRegion).not.toHaveBeenCalled();
    expect(useConverterStore.getState().regionData).toBeNull();
    expect(useConverterStore.getState().selectedColor).toBeNull();
    expect(useConverterStore.getState().previewImageUrl).toBe('/preview.png');
  });

  it('can locally deselect a selected region when preview width metadata is missing', async () => {
    const detectRegion = vi.fn();

    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      preview_width_mm: null,
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
            [80, 0],
            [80, 80],
            [0, 80],
          ],
        ],
      },
      detectRegion,
      sessionId: null,
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
    sharedGetImageDataMock.mockReturnValue({
      data: new Uint8ClampedArray([0xaa, 0xbb, 0xcc, 255]),
    });

    act(() => {
      fireEvent.click(container, { clientX: 120, clientY: 150 });
    });

    expect(detectRegion).not.toHaveBeenCalled();
    expect(useConverterStore.getState().regionData).toBeNull();
  });

  it('does not treat a region bbox as a selected-shape fallback when contour hit-testing misses', async () => {
    const detectAndAccumulateRegion = vi.fn();

    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      preview_width_mm: 100,
      selectionMode: 'multi-select',
      selectedColor: 'AABBCC',
      selectedRegions: [
        {
          regionId: 'region-thin',
          colorHex: '#AABBCC',
          pixelCount: 10,
          previewUrl: '/region-thin.png',
          contours: [
            [
              [0, 0],
              [1, 0],
              [1, 1],
              [0, 1],
            ],
          ],
          bbox: [20, 45, 10, 10],
        },
      ],
      detectAndAccumulateRegion,
      sessionId: null,
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
    sharedGetImageDataMock.mockReturnValue({
      data: new Uint8ClampedArray([0xaa, 0xbb, 0xcc, 255]),
    });

    act(() => {
      fireEvent.click(container, { clientX: 120, clientY: 150 });
    });

    expect(detectAndAccumulateRegion).toHaveBeenCalledWith(
      expect.any(Number),
      expect.any(Number),
    );
    expect(useConverterStore.getState().selectedRegions.map((region) => region.regionId)).toEqual([
      'region-thin',
    ]);
  });

  it('immediately removes a clicked selected region in multi-select mode without waiting for detection', async () => {
    const detectAndAccumulateRegion = vi.fn();

    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      preview_width_mm: 80,
      selectionMode: 'multi-select',
      selectedColor: 'DDEEFF',
      selectedRegions: [
        {
          regionId: 'region-1',
          colorHex: '#AABBCC',
          pixelCount: 42,
          previewUrl: '/region-1.png',
          contours: [
            [
              [0, 0],
              [80, 0],
              [80, 80],
              [0, 80],
            ],
          ],
        },
        {
          regionId: 'region-2',
          colorHex: '#DDEEFF',
          pixelCount: 24,
          previewUrl: '/region-2.png',
          contours: [
            [
              [90, 0],
              [100, 0],
              [100, 10],
              [90, 10],
            ],
          ],
        },
      ],
      detectAndAccumulateRegion,
      sessionId: null,
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
    sharedGetImageDataMock.mockReturnValue({
      data: new Uint8ClampedArray([0xaa, 0xbb, 0xcc, 255]),
    });

    act(() => {
      fireEvent.click(container, { clientX: 120, clientY: 150 });
    });

    expect(detectAndAccumulateRegion).not.toHaveBeenCalled();
    expect(useConverterStore.getState().selectedRegions.map((region) => region.regionId)).toEqual([
      'region-2',
    ]);
    expect(useConverterStore.getState().selectedColor).toBe('DDEEFF');
    expect(useConverterStore.getState().previewImageUrl).toBe('/region-2.png');
  });

  it('does not remove an existing multi-select region when a different-colour click geometrically overlaps its contour', async () => {
    const detectAndAccumulateRegion = vi.fn();

    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      preview_width_mm: 80,
      selectionMode: 'multi-select',
      selectedColor: 'AABBCC',
      selectedRegions: [
        {
          regionId: 'region-1',
          colorHex: '#AABBCC',
          pixelCount: 42,
          previewUrl: '/region-1.png',
          contours: [
            [
              [0, 0],
              [80, 0],
              [80, 80],
              [0, 80],
            ],
          ],
        },
      ],
      detectAndAccumulateRegion,
      sessionId: null,
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
    sharedGetImageDataMock.mockReturnValue({
      data: new Uint8ClampedArray([0xdd, 0xee, 0xff, 255]),
    });

    act(() => {
      fireEvent.click(container, { clientX: 120, clientY: 150 });
    });

    expect(detectAndAccumulateRegion).toHaveBeenCalledWith(23, 50);
    expect(useConverterStore.getState().selectedRegions.map((region) => region.regionId)).toEqual([
      'region-1',
    ]);
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
    expect(container.querySelector('[data-testid="selection-marching-ants-overlay"]')).toBeNull();
    expect(container.querySelector('[data-testid="selection-contour-compat"]')).toBeNull();
    expect(container.querySelector('[data-testid="selection-marching-ants-white"]')).toBeNull();
    expect(container.querySelector('[data-testid="selection-marching-ants-black"]')).toBeNull();
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

    render(<ColorPreview2D />);
    const surface = screen.getByTestId('color-preview-2d-container');

    mockPreviewRect(surface);

    flushPendingImages('/preview.png');

    // Image-pixel geometry is projected through the fitted canvas rectangle.
    const whiteAnts = screen.getByTestId('selection-marching-ants-white');
    const blackAnts = screen.getByTestId('selection-marching-ants-black');
    expect(whiteAnts).toHaveAttribute('d', 'M 0 100 L 20 100 L 20 80 Z');
    expect(whiteAnts.parentElement).toHaveAttribute('transform', 'translate(50 0) scale(3 3)');
    expect(blackAnts).toHaveAttribute('d', whiteAnts.getAttribute('d'));
    expect(whiteAnts).toHaveAttribute('stroke', '#ffffff');
    expect(blackAnts).toHaveAttribute('stroke', '#1a1a1a');
    for (const path of [whiteAnts, blackAnts]) {
      expect(path).toHaveAttribute('stroke-width', '1');
      expect(path).toHaveAttribute('stroke-dasharray', '4 4');
      expect(path).toHaveAttribute('vector-effect', 'non-scaling-stroke');
    }
  });

  it('adds a frontend canvas pulse layer for blinking selection without replacing the real contour', async () => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'multi-select',
      selectedColor: '222222',
      selectionBlinkEnabled: true,
      selectedRegions: [
        {
          regionId: 'region-light',
          colorHex: '#eeeeee',
          pixelCount: 42,
          previewUrl: '/preview.png',
          contours: [
            [
              [0, 0],
              [20, 0],
              [20, 20],
            ],
          ],
        },
        {
          regionId: 'region-dark',
          colorHex: '#222222',
          pixelCount: 24,
          previewUrl: '/preview.png',
          contours: [
            [
              [30, 0],
              [50, 0],
              [50, 20],
            ],
          ],
        },
      ],
      colorContours: {},
      preview_width_mm: 100,
      sessionId: 'session-main-2d',
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
    });

    const { container, unmount } = render(<ColorPreview2D />);

    mockPreviewRect(screen.getByTestId('color-preview-2d-container'));
    flushPendingImages('/preview.png');

    expect(container.querySelector('[data-testid="selection-marching-ants-white"]')).not.toBeNull();
    const blinkCanvas = screen.getByTestId('selection-blink-canvas');
    expect(blinkCanvas).toBeInTheDocument();
    expect(blinkCanvas).toHaveStyle({ zIndex: '6' });

    unmount();
  });

  it('renders pixel-space region contours when preview width metadata is missing', async () => {
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
      },
      colorContours: {},
      preview_width_mm: null,
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

    const path = container.querySelector('[data-testid="selection-marching-ants-white"]');
    expect(path).toHaveAttribute('d', 'M 0 100 L 20 100 L 20 80 Z');
    expect(path?.parentElement).toHaveAttribute('transform', 'translate(50 0) scale(3 3)');
  });

  it('renders same-colour contours even when contour keys include a hash or different case', async () => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'select-all',
      selectedColor: null,
      selectedColors: new Set(['AABBCC']),
      colorContours: {
        '#aabbcc': [
          [
            [0, 0],
            [20, 0],
            [20, 20],
          ],
        ],
      },
      gradientSelection: null,
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

    const path = container.querySelector('[data-testid="selection-marching-ants-white"]');
    expect(path).toHaveAttribute('d', 'M 0 100 L 20 100 L 20 80 Z');
    expect(path?.parentElement).toHaveAttribute('transform', 'translate(50 0) scale(3 3)');
  });

  it.each(['same-color', 'regions', 'document'] as const)(
    'keeps thousands of %s contours cached while zooming and panning',
    (source) => {
      const polygons = Array.from({ length: 3000 }, (_, index) => {
        const x = index % 100;
        const y = Math.floor(index / 100);
        return [[x, y], [x + 0.5, y], [x + 0.5, y + 0.5]];
      });
      const mapPolygon = vi.spyOn(polygons[0], 'map');
      const selectionState = {
        selectionMode: 'select-all',
        selectedColor: '112233',
        selectedColors: new Set(['112233']),
        colorContours: { '112233': polygons },
        selectionBlinkEnabled: false,
      } as const;
      useConverterStore.setState(selectionState);
      if (source === 'regions') {
        useConverterStore.setState({
          selectionMode: 'multi-select',
          selectedRegions: polygons.map((polygon, index) => ({
            regionId: `region-${index}`, colorHex: '112233', pixelCount: 1,
            previewUrl: '/preview.png', contours: [polygon],
          })),
        });
      } else if (source === 'document') {
        useConverterStore.setState({
          selectionDocument: {
            selection_revision: 1, content_revision: 1,
            selected_pixel_count: 3000, selected_component_count: 3000,
            selected_color_hexes: ['#112233'], region_ids: [], components: [],
            contours: polygons, can_undo: false, can_redo: false,
          },
        });
      }
      render(<ColorPreview2D />);
      const surface = screen.getByTestId('color-preview-2d-container');
      mockPreviewRect(surface);
      flushPendingImages('/preview.png');

      const path = screen.getAllByTestId('selection-marching-ants-white')[0];
      const initialGeometry = path.getAttribute('d');
      const initialTransform = path.parentElement?.getAttribute('transform');
      mapPolygon.mockClear();

      fireEvent.wheel(surface, { deltaY: -100, clientX: 200, clientY: 150 });
      expect(path.parentElement?.getAttribute('transform')).not.toBe(initialTransform);
      const zoomTransform = path.parentElement?.getAttribute('transform');
      fireEvent.pointerDown(surface, { button: 2, pointerId: 1, clientX: 200, clientY: 150 });
      fireEvent.pointerMove(surface, { pointerId: 1, clientX: 220, clientY: 180 });
      fireEvent.pointerUp(surface, { button: 2, pointerId: 1, clientX: 220, clientY: 180 });

      expect(path.parentElement?.getAttribute('transform')).not.toBe(zoomTransform);
      expect(path).toHaveAttribute('d', initialGeometry);
      expect(mapPolygon).not.toHaveBeenCalled();
      expect(screen.getAllByTestId('selection-marching-ants-white')).toHaveLength(1);
      expect(screen.getAllByTestId('selection-marching-ants-black')).toHaveLength(1);
      expect(surface.querySelectorAll('polygon')).toHaveLength(0);
      expect(initialGeometry?.match(/ Z/g)).toHaveLength(3000);
    },
  );

  it('refreshes the cached union outline when selection or dimensions change and removes it on clear', () => {
    const selectionDocument = {
      selection_revision: 1, content_revision: 1,
      selected_pixel_count: 20, selected_component_count: 2,
      selected_color_hexes: ['#112233'], region_ids: [], components: [],
      contours: [
        [[0, 0], [20, 0], [20, 20]],
        [[30, 30], [40, 30], [40, 40]],
        [[50, 50], [60, 60]],
      ],
      can_undo: false, can_redo: false,
    };
    useConverterStore.setState({ selectionDocument, preview_width_mm: 100 });
    render(<ColorPreview2D />);
    mockPreviewRect(screen.getByTestId('color-preview-2d-container'));
    flushPendingImages('/preview.png');
    const path = screen.getByTestId('selection-marching-ants-white');
    expect(path).toHaveAttribute('d', 'M 0 100 L 20 100 L 20 80 Z M 30 70 L 40 70 L 40 60 Z');

    act(() => useConverterStore.setState({ preview_width_mm: 200 }));
    expect(path).toHaveAttribute('d', 'M 0 100 L 10 100 L 10 90 Z M 15 85 L 20 85 L 20 80 Z');
    act(() => useConverterStore.setState({
      selectionDocument: { ...selectionDocument, selection_revision: 2, contours: [[[0, 0], [4, 0], [4, 4]]] },
    }));
    expect(path).toHaveAttribute('d', 'M 0 100 L 2 100 L 2 98 Z');
    act(() => useConverterStore.setState({ selectionDocument: null }));
    expect(screen.queryByTestId('selection-marching-ants-overlay')).not.toBeInTheDocument();
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

  it('routes left-button pointerup to selection even when the browser click event is missing', () => {
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
      fireEvent.pointerDown(container, {
        button: 0,
        pointerId: 11,
        clientX: 120,
        clientY: 150,
      });
      fireEvent.pointerUp(container, {
        button: 0,
        pointerId: 11,
        clientX: 120,
        clientY: 150,
      });
    });

    expect(detectRegion).toHaveBeenCalledTimes(1);
    expect(detectRegion).toHaveBeenCalledWith(23, 50);
  });

  it('does not duplicate selection when pointerup is followed by a browser click', () => {
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
      fireEvent.pointerDown(container, {
        button: 0,
        pointerId: 12,
        clientX: 120,
        clientY: 150,
      });
      fireEvent.pointerUp(container, {
        button: 0,
        pointerId: 12,
        clientX: 120,
        clientY: 150,
      });
      fireEvent.click(container, { clientX: 120, clientY: 150, button: 0 });
    });

    expect(detectRegion).toHaveBeenCalledTimes(1);
  });

  it('routes consecutive multi-select pointerup clicks without requiring browser click events', () => {
    const applySelectionMutation = vi.fn(async () => true);

    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'multi-select',
      applySelectionMutation,
      selectedRegions: [],
      sessionId: 'session-main-2d',
      preview_width_mm: 80,
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
    } as never);

    render(<ColorPreview2D />);

    flushPendingImages('/preview.png');

    const container = screen.getByTestId('color-preview-2d-container');
    mockPreviewRect(container);

    act(() => {
      fireEvent.pointerDown(container, {
        button: 0,
        pointerId: 21,
        clientX: 120,
        clientY: 150,
      });
      fireEvent.pointerUp(container, {
        button: 0,
        pointerId: 21,
        clientX: 120,
        clientY: 150,
      });
      fireEvent.pointerDown(container, {
        button: 0,
        pointerId: 22,
        clientX: 200,
        clientY: 150,
      });
      fireEvent.pointerUp(container, {
        button: 0,
        pointerId: 22,
        clientX: 200,
        clientY: 150,
      });
    });

    expect(applySelectionMutation).toHaveBeenCalledTimes(2);
    expect(applySelectionMutation).toHaveBeenNthCalledWith(
      1,
      { operation: 'point-toggle', x: expect.any(Number), y: expect.any(Number) },
    );
    expect(applySelectionMutation).toHaveBeenNthCalledWith(
      2,
      { operation: 'point-toggle', x: expect.any(Number), y: expect.any(Number) },
    );
  });

  it('does not treat a moved left-button pointer gesture as a color selection click', () => {
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
      fireEvent.pointerDown(container, {
        button: 0,
        pointerId: 31,
        clientX: 120,
        clientY: 150,
      });
      fireEvent.pointerMove(container, {
        button: 0,
        pointerId: 31,
        clientX: 130,
        clientY: 150,
      });
      fireEvent.pointerUp(container, {
        button: 0,
        pointerId: 31,
        clientX: 130,
        clientY: 150,
      });
    });

    expect(detectRegion).not.toHaveBeenCalled();
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

  it('keeps left-click color selection active after a right-button pan gesture', () => {
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
    Object.defineProperty(container, 'setPointerCapture', {
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(container, 'releasePointerCapture', {
      configurable: true,
      value: vi.fn(),
    });

    act(() => {
      fireEvent.pointerDown(container, {
        button: 2,
        pointerId: 7,
        clientX: 120,
        clientY: 120,
      });
      fireEvent.pointerMove(container, {
        button: 2,
        pointerId: 7,
        clientX: 140,
        clientY: 140,
      });
      fireEvent.pointerUp(container, {
        button: 2,
        pointerId: 7,
        clientX: 140,
        clientY: 140,
      });
      fireEvent.pointerDown(container, {
        button: 0,
        pointerId: 8,
        clientX: 120,
        clientY: 150,
      });
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

  it('uses Space+left drag for panning without replacing ordinary left-click selection', () => {
    const detectRegion = vi.fn();
    useConverterStore.setState({ detectRegion });

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

    fireEvent.click(container, { button: 0, clientX: 120, clientY: 150 });
    expect(detectRegion).toHaveBeenCalledTimes(1);

    fireEvent.pointerEnter(container);
    const spaceDown = new KeyboardEvent('keydown', {
      bubbles: true,
      cancelable: true,
      code: 'Space',
      key: ' ',
    });
    act(() => {
      window.dispatchEvent(spaceDown);
    });
    expect(spaceDown.defaultPrevented).toBe(true);
    expect(container).toHaveAttribute('data-space-pan-active', 'true');

    fireEvent.pointerDown(container, {
      pointerId: 8,
      button: 0,
      clientX: 120,
      clientY: 150,
    });
    fireEvent.pointerMove(container, {
      pointerId: 8,
      buttons: 1,
      clientX: 155,
      clientY: 175,
    });

    const spaceUp = new KeyboardEvent('keyup', {
      bubbles: true,
      cancelable: true,
      code: 'Space',
      key: ' ',
    });
    act(() => {
      window.dispatchEvent(spaceUp);
    });
    expect(spaceUp.defaultPrevented).toBe(true);
    expect(releasePointerCapture).toHaveBeenCalledWith(8);
    expect(container).not.toHaveAttribute('data-space-pan-active');

    // The compatibility click from Space+left is consumed, then normal left
    // clicks immediately return to the existing color-selection path.
    fireEvent.click(container, { button: 0, clientX: 155, clientY: 175 });
    expect(detectRegion).toHaveBeenCalledTimes(1);
    fireEvent.click(container, { button: 0, clientX: 120, clientY: 150 });
    expect(detectRegion).toHaveBeenCalledTimes(2);
    expect(setPointerCapture).toHaveBeenCalledWith(8);
  });

  it('pans with the middle button, blocks auto-scroll, and clears cancelled drags', () => {
    const detectRegion = vi.fn();
    useConverterStore.setState({ detectRegion });

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

    const pointerDownAllowed = fireEvent.pointerDown(container, {
      pointerId: 9,
      button: 1,
      clientX: 120,
      clientY: 150,
    });
    fireEvent.pointerMove(container, {
      pointerId: 9,
      buttons: 4,
      clientX: 150,
      clientY: 170,
    });
    fireEvent.pointerCancel(container, { pointerId: 9, button: 1 });
    const auxClick = new MouseEvent('auxclick', {
      bubbles: true,
      cancelable: true,
      button: 1,
    });
    const auxClickAllowed = container.dispatchEvent(auxClick);

    expect(pointerDownAllowed).toBe(false);
    expect(auxClickAllowed).toBe(false);
    expect(setPointerCapture).toHaveBeenCalledWith(9);
    expect(releasePointerCapture).toHaveBeenCalledWith(9);

    fireEvent.pointerDown(container, {
      pointerId: 10,
      button: 1,
      clientX: 120,
      clientY: 150,
    });
    act(() => {
      window.dispatchEvent(new Event('blur'));
    });
    expect(releasePointerCapture).toHaveBeenCalledWith(10);

    fireEvent.click(container, { button: 0, clientX: 120, clientY: 150 });
    expect(detectRegion).toHaveBeenCalledTimes(1);
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

  it('restores the system cursor outside the image so the pointer never turns invisible', () => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      ...ORIGINAL_STORE_ACTIONS,
      previewBaseImageUrl: '/preview.png',
      previewImageUrl: '/preview.png',
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      selectionMode: 'region',
      selectionTool: 'brush',
      brushSizePx: 24,
      sessionId: 'session-main-2d',
      preview_width_mm: 80,
      bed_label: '256 x 256 mm',
      bedSizes: [],
      fetchLayerImages: vi.fn(async () => {}),
      layerImagesLoading: false,
      layerImages: [],
    });

    render(<ColorPreview2D />);

    const container = screen.getByTestId('color-preview-2d-container');
    // 必须在图片 load 之前 mock 尺寸：surface 在 mount 时测量容器，
    // load 后重渲染才携带有效的 viewport（screenSpaceOverlay 依赖它）。
    mockPreviewRect(container);

    flushPendingImages('/preview.png');

    // 未悬停：保持系统十字光标，不渲染指示圈。
    expect(container).toHaveClass('cursor-crosshair');
    expect(screen.queryByTestId('selection-brush-cursor')).not.toBeInTheDocument();

    // 图像内悬停：隐藏系统光标，指示圈接管（跟随指针）。
    act(() => {
      fireEvent.pointerMove(container, { pointerId: 1, clientX: 120, clientY: 150 });
    });

    expect(container).toHaveClass('cursor-none');
    const insideCursor = screen.getByTestId('selection-brush-cursor');
    expect(insideCursor.style.left).toBe('120px');
    expect(insideCursor.style.top).toBe('150px');

    // 移出图像（图像显示在容器 x∈[50,350]）：系统光标立刻恢复可见，
    // 指示圈退场——任何时刻都不会出现"光标隐身"。
    act(() => {
      fireEvent.pointerMove(container, { pointerId: 1, clientX: 20, clientY: 150 });
    });

    expect(container).toHaveClass('cursor-crosshair');
    expect(container).not.toHaveClass('cursor-none');
    expect(screen.queryByTestId('selection-brush-cursor')).not.toBeInTheDocument();
  });
});
