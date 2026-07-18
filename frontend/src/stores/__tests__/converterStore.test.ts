import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useConverterStore } from '../../stores/converter';
import { DEFAULT_STATE } from '../../stores/converter';
import { ColorMode, ModelingMode, StructureMode } from '../../api/types';
import { uploadImagePreview } from '../../api/system';

vi.mock('../../api/system', () => ({
  uploadImagePreview: vi.fn(),
}));

const rawUnsupportedDetail =
  '当前环境暂不支持 RAW 图片，请先转换为 PNG/JPEG 后再上传。';

/**
 * Converter_Store 单元测试
 * Validates: Requirements 9.4, 2.4, 4.3, 4.5
 */

function resetStore(): void {
  useConverterStore.setState({
    source_version: 'legacy',
    lut_name: 'test-lut',
    nativeBrandGroups: [],
    nativeBrandGroupsLoading: false,
    selectedNativeBrandKey: '',
    selectedNativeDbNames: [],
    selectedColor: null,
    colorRemapMap: {},
    remapHistory: [],
    autoHeightMode: 'darker-higher',
    palette: [],
    previewGlbUrl: null,
  });
}

function resetConverterState(overrides?: Record<string, unknown>): void {
  useConverterStore.setState({
    ...DEFAULT_STATE,
    ...overrides,
  });
}

async function flushPromises(): Promise<void> {
  await Promise.resolve();
}

function expectMagnetsToNotOverlap(
  magnets: Array<{
    shape: 'round' | 'rect';
    diameter_mm: number | null;
    width_mm: number | null;
    height_mm: number | null;
    center_x_mm: number;
    center_y_mm: number;
  }>,
  gapMm: number = 1,
): void {
  const getSize = (magnet: (typeof magnets)[number]) => ({
    width: magnet.shape === 'round'
      ? magnet.diameter_mm ?? 0
      : magnet.width_mm ?? 0,
    height: magnet.shape === 'round'
      ? magnet.diameter_mm ?? 0
      : magnet.height_mm ?? 0,
  });

  for (let leftIndex = 0; leftIndex < magnets.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < magnets.length; rightIndex += 1) {
      const left = magnets[leftIndex];
      const right = magnets[rightIndex];
      const leftSize = getSize(left);
      const rightSize = getSize(right);
      const minSeparationX = leftSize.width / 2 + rightSize.width / 2 + gapMm;
      const minSeparationY = leftSize.height / 2 + rightSize.height / 2 + gapMm;
      const deltaX = Math.abs(left.center_x_mm - right.center_x_mm);
      const deltaY = Math.abs(left.center_y_mm - right.center_y_mm);

      expect(deltaX >= minSeparationX || deltaY >= minSeparationY).toBe(true);
    }
  }
}

describe('Converter_Store 默认值', () => {
  beforeEach(() => {
    resetStore();
  });

  it('autoHeightMode 默认为 "darker-higher"', () => {
    const state = useConverterStore.getState();
    expect(state.autoHeightMode).toBe('darker-higher');
  });

  it('selectedColor 默认为 null', () => {
    const state = useConverterStore.getState();
    expect(state.selectedColor).toBeNull();
  });

  it('colorRemapMap 默认为空对象', () => {
    const state = useConverterStore.getState();
    expect(state.colorRemapMap).toEqual({});
  });

  it('remapHistory 默认为空数组', () => {
    const state = useConverterStore.getState();
    expect(state.remapHistory).toEqual([]);
  });
});

describe('setSelectedColor', () => {
  beforeEach(() => {
    resetStore();
  });

  it('设置 selectedColor 为指定 hex 值', () => {
    useConverterStore.getState().setSelectedColor('ff0000');
    expect(useConverterStore.getState().selectedColor).toBe('ff0000');
  });

  it('设置 selectedColor 为 null 清除选中', () => {
    useConverterStore.getState().setSelectedColor('ff0000');
    useConverterStore.getState().setSelectedColor(null);
    expect(useConverterStore.getState().selectedColor).toBeNull();
  });
});

describe('submitGenerate 浮雕验证', () => {
  beforeEach(() => {
    resetStore();
  });

  it('enable_relief 为 true 且 color_height_map 为空时阻止生成并提示', async () => {
    useConverterStore.setState({
      sessionId: 'test-session',
      enable_relief: true,
      color_height_map: {},
      autoHeightMode: 'darker-higher',
    });

    const result = await useConverterStore.getState().submitGenerate();

    expect(result).toBeNull();
    expect(useConverterStore.getState().error).toBe('请先设置颜色高度映射后再生成');
    expect(useConverterStore.getState().isLoading).toBe(false);
  });

  it('enable_relief 为 true 且 autoHeightMode 为 use-heightmap 且 color_height_map 为空时提示上传高度图', async () => {
    useConverterStore.setState({
      sessionId: 'test-session',
      enable_relief: true,
      color_height_map: {},
      autoHeightMode: 'use-heightmap',
    });

    const result = await useConverterStore.getState().submitGenerate();

    expect(result).toBeNull();
    expect(useConverterStore.getState().error).toBe('请先上传高度图并获取高度映射后再生成');
    expect(useConverterStore.getState().isLoading).toBe(false);
  });

  it('enable_relief 为 true 且 color_height_map 非空时不阻止', async () => {
    useConverterStore.setState({
      sessionId: 'test-session',
      enable_relief: true,
      color_height_map: { 'ff0000': 2.5 },
      autoHeightMode: 'darker-higher',
    });

    // submitGenerate will proceed past validation and hit the API call
    // which will fail since we don't mock it, but the point is it doesn't
    // return null from the validation check
    await useConverterStore.getState().submitGenerate();

    // It should have attempted the API call (error will be from network, not validation)
    const error = useConverterStore.getState().error;
    expect(error).not.toBe('请先设置颜色高度映射后再生成');
    expect(error).not.toBe('请先上传高度图并获取高度映射后再生成');
  });

  it('enable_relief 为 false 时不检查 color_height_map', async () => {
    useConverterStore.setState({
      sessionId: 'test-session',
      enable_relief: false,
      color_height_map: {},
    });

    await useConverterStore.getState().submitGenerate();

    const error = useConverterStore.getState().error;
    expect(error).not.toBe('请先设置颜色高度映射后再生成');
    expect(error).not.toBe('请先上传高度图并获取高度映射后再生成');
  });
});

describe('clearAllRemaps', () => {
  beforeEach(() => {
    resetStore();
  });

  it('执行若干替换后 clearAllRemaps 清空 map 和 history', () => {
    const store = useConverterStore.getState;

    store().applyColorRemap('ff0000', '00ff00');
    store().applyColorRemap('0000ff', 'ffff00');

    expect(Object.keys(store().colorRemapMap).length).toBeGreaterThan(0);
    expect(store().remapHistory.length).toBeGreaterThan(0);

    store().clearAllRemaps();

    expect(store().colorRemapMap).toEqual({});
    expect(store().remapHistory).toEqual([]);
  });
});

describe('handleFilesSelect clears stale puzzle state', () => {
  beforeEach(() => {
    resetConverterState({
      puzzleEnabled: true,
      puzzleOverlayUrl: '/api/files/overlay',
      puzzleWarnings: ['warning'],
      puzzleResolvedRows: 2,
      puzzleResolvedCols: 3,
      puzzleResolvedPieceCount: 6,
    });
  });

  it('clears puzzle mode when selecting a new single file', () => {
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = () => 'blob:test-preview';
    URL.revokeObjectURL = () => {};

    try {
      const file = new File(['png'], 'fresh.png', { type: 'image/png' });

      useConverterStore.getState().handleFilesSelect([file]);

      const state = useConverterStore.getState();
      expect(state.puzzleEnabled).toBe(false);
      expect(state.puzzleOverlayUrl).toBeNull();
      expect(state.puzzleWarnings).toEqual([]);
    } finally {
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
    }
  });
});


describe('SVG vector mode guard', () => {
  beforeEach(() => {
    resetConverterState({
      imageFile: null,
      imagePreviewUrl: null,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
    });
  });

  it('prevents selecting vector mode before an SVG is loaded', () => {
    useConverterStore.getState().setModelingMode(ModelingMode.VECTOR);

    expect(useConverterStore.getState().modeling_mode).toBe(ModelingMode.HIGH_FIDELITY);
  });

  it('allows selecting vector mode when current image is SVG', () => {
    const svgFile = new File(['<svg/>'], 'input.svg', { type: 'image/svg+xml' });
    useConverterStore.setState({ imageFile: svgFile });

    useConverterStore.getState().setModelingMode(ModelingMode.VECTOR);

    expect(useConverterStore.getState().modeling_mode).toBe(ModelingMode.VECTOR);
  });

  it('downgrades vector mode when replacing SVG with a raster image', () => {
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => 'blob:raster-preview');
    URL.revokeObjectURL = vi.fn();

    try {
      const pngFile = new File(['png'], 'input.png', { type: 'image/png' });
      useConverterStore.setState({ modeling_mode: ModelingMode.VECTOR });

      useConverterStore.getState().setImageFile(pngFile);

      expect(useConverterStore.getState().modeling_mode).toBe(ModelingMode.HIGH_FIDELITY);
    } finally {
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
    }
  });

  it('downgrades vector mode when selecting a raster image through the upload handler', () => {
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => 'blob:raster-upload-preview');
    URL.revokeObjectURL = vi.fn();

    try {
      const pngFile = new File(['png'], 'input.png', { type: 'image/png' });
      useConverterStore.setState({ modeling_mode: ModelingMode.VECTOR });

      useConverterStore.getState().handleFilesSelect([pngFile]);

      expect(useConverterStore.getState().modeling_mode).toBe(ModelingMode.HIGH_FIDELITY);
    } finally {
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
    }
  });

  it('downgrades vector mode when selecting multiple raster images', () => {
    const firstPng = new File(['png-a'], 'first.png', { type: 'image/png' });
    const secondPng = new File(['png-b'], 'second.png', { type: 'image/png' });
    useConverterStore.setState({ modeling_mode: ModelingMode.VECTOR });

    useConverterStore.getState().handleFilesSelect([firstPng, secondPng]);

    expect(useConverterStore.getState().batchMode).toBe(true);
    expect(useConverterStore.getState().modeling_mode).toBe(ModelingMode.HIGH_FIDELITY);
  });
});

describe('RAW image preview upload failures', () => {
  beforeEach(() => {
    resetConverterState({
      enableCrop: true,
      error: null,
      imageFile: null,
      imagePreviewUrl: null,
      aspectRatio: null,
    });
    vi.mocked(uploadImagePreview).mockReset();
  });

  it('sets an actionable error when setImageFile cannot prepare a RAW preview', async () => {
    vi.mocked(uploadImagePreview).mockRejectedValueOnce(
      new Error(rawUnsupportedDetail),
    );
    const rawFile = new File(['raw'], 'camera.dng', { type: '' });

    useConverterStore.getState().setImageFile(rawFile);
    await flushPromises();

    const state = useConverterStore.getState();
    expect(state.imageFile).toBe(rawFile);
    expect(state.imagePreviewUrl).toBeNull();
    expect(state.aspectRatio).toBeNull();
    expect(state.error).toContain('RAW');
    expect(state.error).toContain('PNG/JPEG');
    expect(state.error).not.toMatch(/rawpy|pip install|pillow-heif/i);
  });

  it('sets an actionable error when handleFilesSelect cannot prepare a RAW preview', async () => {
    vi.mocked(uploadImagePreview).mockRejectedValueOnce(
      new Error('Preview service unavailable'),
    );
    const rawFile = new File(['raw'], 'camera.cr3', { type: '' });

    useConverterStore.getState().handleFilesSelect([rawFile]);
    await flushPromises();

    const state = useConverterStore.getState();
    expect(state.imageFile).toBe(rawFile);
    expect(state.batchMode).toBe(false);
    expect(state.imagePreviewUrl).toBeNull();
    expect(state.aspectRatio).toBeNull();
    expect(state.error).toContain('RAW');
    expect(state.error).toContain('Preview service unavailable');
  });

  it('does not let a stale RAW preview failure overwrite a newer file selection', async () => {
    let rejectRawPreview!: (reason?: unknown) => void;
    vi.mocked(uploadImagePreview).mockImplementationOnce(
      () =>
        new Promise((_, reject) => {
          rejectRawPreview = reject;
        }),
    );
    const rawFile = new File(['raw'], 'stale.nef', { type: '' });
    const pngFile = new File(['png'], 'fresh.png', { type: 'image/png' });
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => 'blob:fresh-preview');
    URL.revokeObjectURL = vi.fn();

    try {
      useConverterStore.getState().setImageFile(rawFile);
      useConverterStore.getState().setImageFile(pngFile);
      rejectRawPreview(new Error(rawUnsupportedDetail));
      await flushPromises();

      const state = useConverterStore.getState();
      expect(state.imageFile).toBe(pngFile);
      expect(state.imagePreviewUrl).toBe('blob:fresh-preview');
      expect(state.error).toBeNull();
    } finally {
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
    }
  });

  it('sets an actionable error when batch removal downgrades to a RAW file without a preview', async () => {
    vi.mocked(uploadImagePreview).mockRejectedValueOnce(
      new Error(rawUnsupportedDetail),
    );
    const pngFile = new File(['png'], 'remove.png', { type: 'image/png' });
    const rawFile = new File(['raw'], 'remaining.raf', { type: '' });
    useConverterStore.setState({
      batchFiles: [pngFile, rawFile],
      batchMode: true,
      imageFile: null,
      imagePreviewUrl: null,
      aspectRatio: null,
      error: null,
    });

    useConverterStore.getState().removeBatchFile(0);
    await flushPromises();

    const state = useConverterStore.getState();
    expect(state.batchFiles).toEqual([]);
    expect(state.batchMode).toBe(false);
    expect(state.imageFile).toBe(rawFile);
    expect(state.imagePreviewUrl).toBeNull();
    expect(state.aspectRatio).toBeNull();
    expect(state.error).toContain('RAW');
    expect(state.error).toContain('PNG/JPEG');
    expect(state.error).not.toMatch(/rawpy|pip install|pillow-heif/i);
  });
});


describe('setModelBounds', () => {
  beforeEach(() => {
    resetStore();
    useConverterStore.setState({ modelBounds: null });
  });

  it('stores modelBounds correctly', () => {
    const bounds = { minX: -10, maxX: 10, minY: -5, maxY: 5, maxZ: 3 };
    useConverterStore.getState().setModelBounds(bounds);
    expect(useConverterStore.getState().modelBounds).toEqual(bounds);
  });

  it('sets modelBounds to null', () => {
    useConverterStore.getState().setModelBounds({ minX: 0, maxX: 1, minY: 0, maxY: 1, maxZ: 1 });
    useConverterStore.getState().setModelBounds(null);
    expect(useConverterStore.getState().modelBounds).toBeNull();
  });
});

describe('setEnableRelief auto-initialization', () => {
  beforeEach(() => {
    resetStore();
    useConverterStore.setState({
      enable_relief: false,
      color_height_map: {},
      heightmap_max_height: 5.0,
      palette: [],
    });
  });

  it('auto-initializes color_height_map when palette non-empty and map empty', () => {
    useConverterStore.setState({
      palette: [
        { quantized_hex: 'ff0000', matched_hex: 'ee0000', pixel_count: 100, percentage: 50 },
        { quantized_hex: '00ff00', matched_hex: '00ee00', pixel_count: 100, percentage: 50 },
      ],
      color_height_map: {},
      heightmap_max_height: 4.0,
    });

    useConverterStore.getState().setEnableRelief(true);

    const state = useConverterStore.getState();
    expect(state.enable_relief).toBe(true);
    // Now uses computeAutoHeightMap (darker-higher by default),
    // so heights vary by luminance instead of uniform 50%
    expect(Object.keys(state.color_height_map)).toEqual(
      expect.arrayContaining(['ee0000', '00ee00']),
    );
    // Each color should have a height within valid range
    for (const h of Object.values(state.color_height_map)) {
      expect(h).toBeGreaterThanOrEqual(0.08);
      expect(h).toBeLessThanOrEqual(4.0);
    }
    // Different colors should have different heights (luminance-based)
    const heights = Object.values(state.color_height_map);
    expect(heights[0]).not.toBeCloseTo(heights[1], 1);
  });

  it('does NOT overwrite existing color_height_map', () => {
    useConverterStore.setState({
      palette: [
        { quantized_hex: 'ff0000', matched_hex: 'ee0000', pixel_count: 100, percentage: 50 },
        { quantized_hex: '00ff00', matched_hex: '00ee00', pixel_count: 100, percentage: 50 },
      ],
      color_height_map: { 'ee0000': 3.5 },
      heightmap_max_height: 4.0,
    });

    useConverterStore.getState().setEnableRelief(true);

    const state = useConverterStore.getState();
    expect(state.enable_relief).toBe(true);
    // Should keep the existing map untouched
    expect(state.color_height_map).toEqual({ 'ee0000': 3.5 });
  });

  it('does NOT auto-initialize when palette is empty', () => {
    useConverterStore.setState({
      palette: [],
      color_height_map: {},
      heightmap_max_height: 4.0,
    });

    useConverterStore.getState().setEnableRelief(true);

    expect(useConverterStore.getState().color_height_map).toEqual({});
  });

  it('disables cloisonne when enabling relief', () => {
    useConverterStore.setState({ enable_cloisonne: true });

    useConverterStore.getState().setEnableRelief(true);

    expect(useConverterStore.getState().enable_cloisonne).toBe(false);
  });

  it('does not enable relief in 5-Color Extended mode', () => {
    useConverterStore.setState({
      modeling_mode: ModelingMode.VECTOR,
      color_mode: ColorMode.FIVE_COLOR_EXT,
      structure_mode: StructureMode.SINGLE_SIDED,
      enable_fridge_magnet: false,
    });

    useConverterStore.getState().setEnableRelief(true);

    expect(useConverterStore.getState().enable_relief).toBe(false);
  });

  it('does not enable relief in double-sided vector mode', () => {
    useConverterStore.setState({
      modeling_mode: ModelingMode.VECTOR,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      structure_mode: StructureMode.DOUBLE_SIDED,
      enable_fridge_magnet: false,
    });

    useConverterStore.getState().setEnableRelief(true);

    expect(useConverterStore.getState().enable_relief).toBe(false);
  });

  it('disables relief when switching to 5-Color Extended mode', () => {
    useConverterStore.setState({
      modeling_mode: ModelingMode.VECTOR,
      structure_mode: StructureMode.SINGLE_SIDED,
      enable_relief: true,
    });

    useConverterStore.getState().setColorMode(ColorMode.FIVE_COLOR_EXT);

    expect(useConverterStore.getState().enable_relief).toBe(false);
  });

  it('disables relief when entering vector mode with 5-Color Extended', () => {
    useConverterStore.setState({
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      color_mode: ColorMode.FIVE_COLOR_EXT,
      structure_mode: StructureMode.SINGLE_SIDED,
      enable_relief: true,
      imageFile: new File(["<svg/>"], "relief.svg", {
        type: "image/svg+xml",
      }),
    });

    useConverterStore.getState().setModelingMode(ModelingMode.VECTOR);

    expect(useConverterStore.getState().enable_relief).toBe(false);
  });

  it('disables relief when entering vector mode with double-sided structure', () => {
    useConverterStore.setState({
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      structure_mode: StructureMode.DOUBLE_SIDED,
      enable_relief: true,
      imageFile: new File(["<svg/>"], "relief.svg", {
        type: "image/svg+xml",
      }),
    });

    useConverterStore.getState().setModelingMode(ModelingMode.VECTOR);

    expect(useConverterStore.getState().enable_relief).toBe(false);
  });

  it('keeps single-sided structure while relief is enabled', () => {
    useConverterStore.setState({
      modeling_mode: ModelingMode.VECTOR,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      enable_relief: true,
      enable_fridge_magnet: false,
      structure_mode: StructureMode.SINGLE_SIDED,
    });

    useConverterStore.getState().setStructureMode(StructureMode.DOUBLE_SIDED);

    expect(useConverterStore.getState().structure_mode).toBe(
      StructureMode.SINGLE_SIDED,
    );
  });
});

describe('fridge magnet mode', () => {
  beforeEach(() => {
    resetConverterState({
      modelBounds: { minX: 0, maxX: 100, minY: 0, maxY: 40, maxZ: 5 },
      spacer_thick: 1.2,
      base_spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      largeFormatEnabled: true,
      puzzleEnabled: true,
      add_loop: true,
      puzzleOverlayUrl: '/api/files/overlay',
      puzzleWarnings: ['warning'],
      puzzleResolvedRows: 2,
      puzzleResolvedCols: 3,
      puzzleResolvedPieceCount: 6,
      puzzleDerivedPieceWidthMm: 12,
      puzzleDerivedPieceHeightMm: 10,
      enable_fridge_magnet: false,
      fridge_magnets: [],
      selectedFridgeMagnetId: null,
    });
  });

  it('enabling fridge mode forces single-sided mode, clears mutually exclusive modes, and seeds a default layout once', () => {
    const store = useConverterStore.getState();

    store.setEnableFridgeMagnet(true);

    const state = useConverterStore.getState();
    expect(state.enable_fridge_magnet).toBe(true);
    expect(state.structure_mode).toBe(StructureMode.SINGLE_SIDED);
    expect(state.largeFormatEnabled).toBe(false);
    expect(state.puzzleEnabled).toBe(false);
    expect(state.add_loop).toBe(false);
    expect(state.puzzleOverlayUrl).toBeNull();
    expect(state.puzzleWarnings).toEqual([]);
    expect(state.fridge_magnets).toHaveLength(1);
    expect(state.fridge_magnets[0]).toMatchObject({
      shape: 'round',
      preset_key: 'round-d12x3',
      center_x_mm: 50,
      center_y_mm: 20,
      diameter_mm: 12,
      thickness_mm: 3,
    });

    store.setEnableFridgeMagnet(false);
    store.setEnableFridgeMagnet(true);

    expect(useConverterStore.getState().fridge_magnets).toHaveLength(1);
    expect(useConverterStore.getState().fridge_magnets[0].id).toBe(
      state.fridge_magnets[0].id,
    );
  });

  it('chooses default layout count from model area thresholds', () => {
    useConverterStore.setState({
      enable_fridge_magnet: false,
      fridge_magnets: [],
      modelBounds: { minX: 10, maxX: 60, minY: 10, maxY: 110, maxZ: 5 },
    });
    useConverterStore.getState().setEnableFridgeMagnet(true);
    expect(useConverterStore.getState().fridge_magnets).toHaveLength(1);

    useConverterStore.setState({
      enable_fridge_magnet: false,
      fridge_magnets: [],
      modelBounds: { minX: 0, maxX: 100, minY: 0, maxY: 100, maxZ: 5 },
    });
    useConverterStore.getState().setEnableFridgeMagnet(true);
    expect(useConverterStore.getState().fridge_magnets).toHaveLength(2);
    expect(
      useConverterStore.getState().fridge_magnets.map((item) => item.center_x_mm),
    ).toEqual([30, 70]);

    useConverterStore.setState({
      enable_fridge_magnet: false,
      fridge_magnets: [],
      modelBounds: { minX: -50, maxX: 150, minY: -20, maxY: 100, maxZ: 5 },
    });
    useConverterStore.getState().setEnableFridgeMagnet(true);
    expect(useConverterStore.getState().fridge_magnets).toHaveLength(4);
    expect(
      useConverterStore.getState().fridge_magnets.map((item) => [
        item.center_x_mm,
        item.center_y_mm,
      ]),
    ).toEqual([
      [10, 16],
      [90, 16],
      [10, 64],
      [90, 64],
    ]);
  });

  it('setSpacerThick tracks a base spacer thickness while fridge magnets raise and lower the visible spacer thickness', () => {
    const store = useConverterStore.getState();

    store.setEnableFridgeMagnet(true);
    store.setSpacerThick(0.8);

    let state = useConverterStore.getState();
    expect(state.base_spacer_thick).toBe(0.8);
    expect(state.spacer_thick).toBe(3.44);

    const magnetId = state.fridge_magnets[0].id;
    store.updateFridgeMagnet(magnetId, { thickness_mm: 1.5 });

    state = useConverterStore.getState();
    expect(state.spacer_thick).toBe(1.92);

    store.removeFridgeMagnet(magnetId);
    state = useConverterStore.getState();
    expect(state.spacer_thick).toBe(0.8);

    store.addFridgeMagnet();
    const addedId = useConverterStore.getState().fridge_magnets[0].id;
    store.updateFridgeMagnet(addedId, { thickness_mm: 2.2 });
    expect(useConverterStore.getState().spacer_thick).toBe(2.64);

    store.setEnableFridgeMagnet(false);
    expect(useConverterStore.getState().spacer_thick).toBe(0.8);
  });

  it('accounts for 0.08mm layer quantization when auto-raising spacer thickness for fridge magnets', () => {
    const store = useConverterStore.getState();

    store.setEnableFridgeMagnet(true);

    const state = useConverterStore.getState();
    expect(state.fridge_magnets).toHaveLength(1);
    expect(state.fridge_magnets[0].thickness_mm).toBe(3);
    expect(state.spacer_thick).toBe(3.44);
  });

  it('adds, updates, selects, repositions, resets, and removes fridge magnets', () => {
    const store = useConverterStore.getState();

    store.setEnableFridgeMagnet(true);
    store.addFridgeMagnet();

    let state = useConverterStore.getState();
    expect(state.fridge_magnets).toHaveLength(2);
    const addedMagnet = state.fridge_magnets[1];
    expectMagnetsToNotOverlap(state.fridge_magnets);

    store.selectFridgeMagnet(addedMagnet.id);
    expect(useConverterStore.getState().selectedFridgeMagnetId).toBe(addedMagnet.id);

    store.updateFridgeMagnet(addedMagnet.id, {
      shape: 'rect',
      preset_key: 'rect-20x10x2',
      diameter_mm: null,
      width_mm: 20,
      height_mm: 10,
      thickness_mm: 2,
    });
    store.updateFridgeMagnetCenter(addedMagnet.id, 40, 12);

    state = useConverterStore.getState();
    expect(
      state.fridge_magnets.find((item) => item.id === addedMagnet.id),
    ).toMatchObject({
      shape: 'rect',
      preset_key: 'rect-20x10x2',
      width_mm: 20,
      height_mm: 10,
      diameter_mm: null,
      center_x_mm: 40,
      center_y_mm: 12,
    });

    store.resetFridgeMagnetLayout();
    state = useConverterStore.getState();
    expect(state.fridge_magnets).toHaveLength(2);
    expect(state.selectedFridgeMagnetId).toBeNull();
    expectMagnetsToNotOverlap(state.fridge_magnets);
    expect(
      state.fridge_magnets.find((item) => item.id === addedMagnet.id),
    ).toMatchObject({
      shape: 'rect',
      preset_key: 'rect-20x10x2',
      width_mm: 20,
      height_mm: 10,
    });

    const remainingId = state.fridge_magnets[0].id;
    store.selectFridgeMagnet(remainingId);
    store.removeFridgeMagnet(remainingId);
    expect(useConverterStore.getState().fridge_magnets).toHaveLength(1);
    expect(useConverterStore.getState().selectedFridgeMagnetId).toBeNull();

    store.removeFridgeMagnet(addedMagnet.id);
    expect(useConverterStore.getState().fridge_magnets).toEqual([]);

    store.clearSelectedFridgeMagnet();
    expect(useConverterStore.getState().selectedFridgeMagnetId).toBeNull();
  });

  it('sanitizes manual fridge magnet center edits by preserving finite values and clamping to bounds', () => {
    const store = useConverterStore.getState();

    store.setEnableFridgeMagnet(true);

    const state = useConverterStore.getState();
    const magnet = state.fridge_magnets[0];

    store.updateFridgeMagnetCenter(magnet.id, Number.NaN, Number.POSITIVE_INFINITY);
    expect(useConverterStore.getState().fridge_magnets[0]).toMatchObject({
      center_x_mm: magnet.center_x_mm,
      center_y_mm: magnet.center_y_mm,
    });

    store.updateFridgeMagnetCenter(magnet.id, -500, 500);
    expect(useConverterStore.getState().fridge_magnets[0]).toMatchObject({
      center_x_mm: 6,
      center_y_mm: 34,
    });
  });

  it('re-clamps existing fridge magnets when model bounds change after preview regeneration', () => {
    const store = useConverterStore.getState();

    store.setEnableFridgeMagnet(true);

    const magnetId = useConverterStore.getState().fridge_magnets[0].id;
    store.updateFridgeMagnetCenter(magnetId, 94, 34);

    store.setModelBounds({
      minX: 0,
      maxX: 20,
      minY: 0,
      maxY: 20,
      maxZ: 5,
    });

    expect(useConverterStore.getState().fridge_magnets[0]).toMatchObject({
      center_x_mm: 14,
      center_y_mm: 14,
    });
  });

  it('keeps auto layout as a pure reposition action when no magnets exist', () => {
    const store = useConverterStore.getState();

    expect(useConverterStore.getState().fridge_magnets).toEqual([]);

    store.resetFridgeMagnetLayout();

    expect(useConverterStore.getState().fridge_magnets).toEqual([]);
  });

  it('uses size-aware placement on tall narrow models so added magnets do not overlap', () => {
    resetConverterState({
      modelBounds: { minX: 0, maxX: 20, minY: 0, maxY: 200, maxZ: 5 },
      enable_fridge_magnet: false,
      fridge_magnets: [],
      selectedFridgeMagnetId: null,
    });
    const store = useConverterStore.getState();

    store.setEnableFridgeMagnet(true);
    store.addFridgeMagnet();

    const state = useConverterStore.getState();
    expect(state.fridge_magnets).toHaveLength(2);
    expectMagnetsToNotOverlap(state.fridge_magnets);
    expect(new Set(state.fridge_magnets.map((item) => item.center_y_mm)).size).toBeGreaterThan(1);
  });

  it('keeps mutually exclusive modes disabled after fridge mode is enabled', () => {
    const store = useConverterStore.getState();

    store.setEnableFridgeMagnet(true);
    store.setStructureMode(StructureMode.DOUBLE_SIDED);
    store.setLargeFormatEnabled(true);
    store.setAddLoop(true);

    const state = useConverterStore.getState();
    expect(state.enable_fridge_magnet).toBe(true);
    expect(state.structure_mode).toBe(StructureMode.SINGLE_SIDED);
    expect(state.largeFormatEnabled).toBe(false);
    expect(state.add_loop).toBe(false);
  });
});


describe('toggleColorInSelection', () => {
  beforeEach(() => {
    resetStore();
    useConverterStore.setState({
      selectionMode: 'multi-select',
      selectedColors: new Set<string>(),
    });
  });

  it('添加不存在的颜色到 selectedColors', () => {
    useConverterStore.getState().toggleColorInSelection('ff0000');
    expect(useConverterStore.getState().selectedColors.has('ff0000')).toBe(true);
  });

  it('移除已存在的颜色从 selectedColors', () => {
    useConverterStore.setState({ selectedColors: new Set(['ff0000', '00ff00']) });
    useConverterStore.getState().toggleColorInSelection('ff0000');
    expect(useConverterStore.getState().selectedColors.has('ff0000')).toBe(false);
    expect(useConverterStore.getState().selectedColors.has('00ff00')).toBe(true);
  });

  it('连续 toggle 同一颜色两次恢复原状', () => {
    useConverterStore.getState().toggleColorInSelection('aabbcc');
    expect(useConverterStore.getState().selectedColors.has('aabbcc')).toBe(true);
    useConverterStore.getState().toggleColorInSelection('aabbcc');
    expect(useConverterStore.getState().selectedColors.has('aabbcc')).toBe(false);
  });

  it('toggle 不影响其他已选中的颜色', () => {
    useConverterStore.setState({ selectedColors: new Set(['111111', '222222']) });
    useConverterStore.getState().toggleColorInSelection('333333');
    const colors = useConverterStore.getState().selectedColors;
    expect(colors.has('111111')).toBe(true);
    expect(colors.has('222222')).toBe(true);
    expect(colors.has('333333')).toBe(true);
  });
});
