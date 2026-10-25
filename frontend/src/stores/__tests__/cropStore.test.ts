import { describe, it, expect, beforeEach, vi } from 'vitest';
import { DEFAULT_STATE, useConverterStore } from '../converter';
import { useWidgetStore } from '../widgetStore';
import { ModelingMode } from '../../api/types';
import { tRuntime } from '../../i18n/runtime';
import {
  collectBugReportContext,
  collectBugReportOriginalImage,
} from '../../utils/bugReportContext';

/**
 * cropStore 单元测试
 * Validates: Requirements 3.2, 3.3, 3.4, 3.5, 6.3
 */

// Mock cropImage API
vi.mock('../../api/converter', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/converter')>();
  return {
    ...actual,
    cropImage: vi.fn(),
    convertPreview: vi.fn(),
    getEditorSelection: vi.fn().mockResolvedValue({
      selection_revision: 0,
      content_revision: 0,
      editor_content_revision: 0,
      selected_pixel_count: 0,
      selected_component_count: 0,
      selected_color_hexes: [],
      region_ids: [],
      components: [],
      contours: [],
      can_undo: false,
      can_redo: false,
    }),
  };
});

import { cropImage, convertPreview } from '../../api/converter';
const mockCropImage = vi.mocked(cropImage);
const mockConvertPreview = vi.mocked(convertPreview);

// Mock fetch (used by submitCrop to download cropped blob)
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

// Mock URL.createObjectURL / revokeObjectURL
const mockCreateObjectURL = vi.fn(() => 'blob:cropped-preview');
const mockRevokeObjectURL = vi.fn();
globalThis.URL.createObjectURL = mockCreateObjectURL;
globalThis.URL.revokeObjectURL = mockRevokeObjectURL;

function resetStore(): void {
  useConverterStore.setState({
    ...DEFAULT_STATE,
    imageFile: new File(['dummy'], 'test.png', { type: 'image/png' }),
    imagePreviewUrl: 'blob:old-preview',
    isCropping: false,
    cropModalOpen: true,
    error: null,
    enableCrop: true,
    aspectRatio: null,
  });
}

describe('submitCrop', () => {
  beforeEach(() => {
    resetStore();
    useWidgetStore.setState({ activeTab: 'converter' });
    vi.clearAllMocks();
  });

  it('成功后更新 imagePreviewUrl 并关闭弹窗', async () => {
    mockCropImage.mockResolvedValue({
      status: 'ok',
      message: 'Cropped',
      cropped_url: '/api/files/abc123',
      width: 200,
      height: 100,
    });
    mockFetch.mockResolvedValue({
      blob: () => Promise.resolve(new Blob(['img'], { type: 'image/png' })),
    });

    await useConverterStore.getState().submitCrop(10, 20, 200, 100);

    const state = useConverterStore.getState();
    expect(state.imagePreviewUrl).toBe('blob:cropped-preview');
    expect(state.cropModalOpen).toBe(false);
    expect(state.isCropping).toBe(false);
    expect(state.error).toBeNull();
    expect(state.aspectRatio).toBe(2); // 200/100
  });

  it('RAW 裁剪后 Bug 报告仍附带用户选择的原始字节', async () => {
    const rawBytes = new Uint8Array([0x49, 0x49, 0x2a, 0x00, 0x52, 0x41, 0x57]);
    const rawFile = new File([rawBytes], 'camera.dng', {
      type: 'application/octet-stream',
    });
    useConverterStore.setState({
      imageFile: rawFile,
      imagePreviewUrl: '/api/files/raw-preview',
    });
    mockCropImage.mockResolvedValue({
      status: 'ok',
      message: 'Cropped',
      cropped_url: '/api/files/cropped-raw',
      width: 200,
      height: 100,
    });
    mockFetch.mockResolvedValue({
      blob: () => Promise.resolve(new Blob(['png-bytes'], { type: 'image/png' })),
    });

    await useConverterStore.getState().submitCrop(0, 0, 200, 100);

    const croppedFile = useConverterStore.getState().imageFile;
    expect(croppedFile).not.toBe(rawFile);
    expect(croppedFile?.name).toBe('camera_cropped.png');
    expect(croppedFile?.type).toBe('image/png');
    const reportFile = collectBugReportOriginalImage();
    expect(reportFile).toBe(rawFile);
    expect(new Uint8Array(await reportFile!.arrayBuffer())).toEqual(rawBytes);
    expect(collectBugReportContext().active_original_image_ref?.filename).toBe(
      'camera.dng',
    );
  });

  it('失败后设置 error 状态', async () => {
    mockCropImage.mockRejectedValue(new Error('Network error'));

    await useConverterStore.getState().submitCrop(0, 0, 100, 100);

    const state = useConverterStore.getState();
    expect(state.error).toBe(tRuntime('api_error_no_response'));
    expect(state.isCropping).toBe(false);
    expect(state.cropModalOpen).toBe(true); // stays open on failure
  });

  it('资源下载失败时不把错误响应当作裁剪图片', async () => {
    mockCropImage.mockResolvedValue({
      status: 'ok',
      message: 'Cropped',
      cropped_url: '/api/files/expired-crop',
      width: 200,
      height: 100,
    });
    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      headers: { get: () => 'application/json' },
      json: () => Promise.resolve({ detail: 'Not Found' }),
    });

    await useConverterStore.getState().submitCrop(10, 20, 200, 100);

    const state = useConverterStore.getState();
    expect(mockCreateObjectURL).not.toHaveBeenCalled();
    expect(state.imagePreviewUrl).toBe('blob:old-preview');
    expect(state.cropModalOpen).toBe(true);
    expect(state.isCropping).toBe(false);
    expect(state.error).toMatch(/requested resource|请求的资源/);
    expect(state.error).not.toContain('404');
  });

  it('请求期间 isCropping 为 true', async () => {
    let resolveApi: (value: unknown) => void;
    const pending = new Promise((resolve) => { resolveApi = resolve; });
    mockCropImage.mockReturnValue(pending as ReturnType<typeof cropImage>);

    const promise = useConverterStore.getState().submitCrop(0, 0, 50, 50);

    // During the request, isCropping should be true
    expect(useConverterStore.getState().isCropping).toBe(true);

    // Resolve the API call
    resolveApi!({
      status: 'ok',
      message: 'Cropped',
      cropped_url: '/api/files/xyz',
      width: 50,
      height: 50,
    });
    mockFetch.mockResolvedValue({
      blob: () => Promise.resolve(new Blob(['img'], { type: 'image/png' })),
    });

    await promise;

    expect(useConverterStore.getState().isCropping).toBe(false);
  });
});

describe('使用原图 (setCropModalOpen)', () => {
  beforeEach(() => {
    resetStore();
  });

  it('setCropModalOpen(false) 关闭弹窗并保留原始图片', () => {
    expect(useConverterStore.getState().cropModalOpen).toBe(true);

    useConverterStore.getState().setCropModalOpen(false);

    const state = useConverterStore.getState();
    expect(state.cropModalOpen).toBe(false);
    // Original image is preserved
    expect(state.imagePreviewUrl).toBe('blob:old-preview');
    expect(state.imageFile).not.toBeNull();
  });
});

describe('矢量化 SVG 导入', () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it('loadVectorizedSvgIntoConverter 载入 SVG 时关闭裁剪并切换到矢量模式', () => {
    const svgFile = new File(['<svg/>'], 'vectorized.svg', {
      type: 'image/svg+xml',
    });
    useConverterStore.setState({
      imagePreviewUrl: 'blob:old-preview',
      cropModalOpen: true,
      enableCrop: true,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      batchMode: true,
      batchFiles: [new File(['old'], 'old.png', { type: 'image/png' })],
      sessionId: 'old-session',
      previewImageUrl: '/api/files/old-preview',
      previewGlbUrl: '/api/files/old-glb',
      downloadUrl: '/api/files/old-download',
      previewWarnings: ['old preview warning'],
      largeFormatWarnings: ['old large-format warning'],
      error: 'Invalid image file',
      source_version: 'material',
      gradientGroups: [],
      gradientGroupsLoading: true,
      gradientGroupsError: 'old gradient error',
      gradientGroupsSessionId: 'old-session',
      gradientSelection: { kind: 'group', groupIndex: 0 },
      selectedGradientRegions: [{ groupIndex: 0, regionIndex: 1 }],
    });

    useConverterStore.getState().loadVectorizedSvgIntoConverter(svgFile);

    const state = useConverterStore.getState();
    expect(mockRevokeObjectURL).toHaveBeenCalledWith('blob:old-preview');
    expect(state.imageFile).toBe(svgFile);
    expect(state.imagePreviewUrl).toBe('blob:cropped-preview');
    expect(state.modeling_mode).toBe(ModelingMode.VECTOR);
    expect(state.cropModalOpen).toBe(false);
    expect(state.batchMode).toBe(false);
    expect(state.batchFiles).toEqual([]);
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.downloadUrl).toBeNull();
    expect(state.previewWarnings).toEqual([]);
    expect(state.largeFormatWarnings).toEqual([]);
    expect(state.error).toBeNull();
    expect(state.gradientGroups).toBeNull();
    expect(state.gradientGroupsLoading).toBe(false);
    expect(state.gradientGroupsError).toBeNull();
    expect(state.gradientGroupsSessionId).toBeNull();
    expect(state.gradientSelection).toBeNull();
    expect(state.selectedGradientRegions).toEqual([]);
  });

  it('loadVectorizedSvgIntoConverter 取消未完成预览并阻止旧响应回写', async () => {
    let resolvePreview!: (value: Awaited<ReturnType<typeof convertPreview>>) => void;
    let previewSignal: AbortSignal | undefined;
    mockConvertPreview.mockImplementation((_file, _params, signal) => {
      previewSignal = signal;
      return new Promise((resolve) => {
        resolvePreview = resolve;
      });
    });
    mockFetch.mockResolvedValue({
      blob: () => Promise.resolve(new Blob(['ignored'], { type: 'image/png' })),
    });
    useConverterStore.setState({
      imageFile: new File(['old'], 'old.png', { type: 'image/png' }),
      imagePreviewUrl: 'blob:old-preview',
      source_version: 'legacy',
      lut_name: 'test-lut',
      isLoading: false,
      sessionId: null,
      previewImageUrl: null,
      previewGlbUrl: null,
    });

    const previewPromise = useConverterStore.getState().submitPreview();
    expect(useConverterStore.getState().isLoading).toBe(true);
    expect(previewSignal?.aborted).toBe(false);

    const svgFile = new File(['<svg/>'], 'vectorized.svg', {
      type: 'image/svg+xml',
    });
    useConverterStore.getState().loadVectorizedSvgIntoConverter(svgFile);

    expect(previewSignal?.aborted).toBe(true);
    expect(useConverterStore.getState().isLoading).toBe(false);

    resolvePreview({
      session_id: 'stale-session',
      status: 'ok',
      message: 'stale',
      preview_url: '/api/files/stale-preview',
      preview_glb_url: '/api/files/stale-glb',
      palette: [],
      dimensions: { width: 10, height: 10 },
      warnings: ['stale warning'],
    });
    await previewPromise;

    const state = useConverterStore.getState();
    expect(state.imageFile).toBe(svgFile);
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.previewWarnings).toEqual([]);
  });

  it.each([
    ['首次', false, null],
    ['既有', true, 'established-session'],
  ])('%s预览请求保持自动刷新资格，允许参数变化取消在途请求', async (
    _label,
    initialManualPreview,
    initialSessionId,
  ) => {
    let resolvePreview!: (value: Awaited<ReturnType<typeof convertPreview>>) => void;
    mockConvertPreview.mockImplementation(
      () => new Promise((resolve) => {
        resolvePreview = resolve;
      }),
    );
    useConverterStore.setState({
      imageFile: new File(['old'], 'old.png', { type: 'image/png' }),
      source_version: 'legacy',
      lut_name: 'test-lut',
      lut_names: ['test-lut'],
      cropModalOpen: false,
      hasManualPreview: initialManualPreview,
      sessionId: initialSessionId,
      previewImageUrl: initialSessionId
        ? '/api/files/established-preview'
        : null,
    });

    const previewPromise = useConverterStore.getState().submitPreview();

    expect(useConverterStore.getState().isLoading).toBe(true);
    expect(useConverterStore.getState().hasManualPreview).toBe(true);

    // A current session first crosses the editor checkpoint barrier. Cancel
    // only after the preview request is in flight, as this test promises.
    await vi.waitFor(() => expect(mockConvertPreview).toHaveBeenCalledOnce());
    useConverterStore.getState().invalidatePreviewForAutoRefresh();
    resolvePreview({
      session_id: 'obsolete-session',
      status: 'ok',
      message: 'obsolete',
      preview_url: '/api/files/obsolete-preview',
      preview_glb_url: '/api/files/obsolete-glb',
      palette: [],
      dimensions: { width: 10, height: 10 },
      warnings: [],
    });
    await previewPromise;

    const finalState = useConverterStore.getState();
    expect(finalState.sessionId).toBeNull();
    expect(finalState.previewImageUrl).toBeNull();
    expect(finalState.previewGlbUrl).toBeNull();
  });

  it('setImageFile 替换当前 SVG 时保持裁剪弹窗关闭', () => {
    const currentSvg = new File(['<svg/>'], 'current.svg', {
      type: 'image/svg+xml',
    });
    const replacementSvg = new File(['<svg/>'], 'replacement.svg', {
      type: 'image/svg+xml',
    });
    useConverterStore.setState({
      imageFile: currentSvg,
      imagePreviewUrl: 'blob:current-svg',
      cropModalOpen: false,
      enableCrop: true,
      modeling_mode: ModelingMode.VECTOR,
    });

    useConverterStore.getState().setImageFile(replacementSvg);

    const state = useConverterStore.getState();
    expect(state.imageFile).toBe(replacementSvg);
    expect(state.cropModalOpen).toBe(false);
    expect(state.modeling_mode).toBe(ModelingMode.VECTOR);
  });

  it('setImageFile 用 SVG 替换栅格图时关闭裁剪并切换到矢量模式', () => {
    const currentPng = new File(['png'], 'current.png', {
      type: 'image/png',
    });
    const replacementSvg = new File(['<svg/>'], 'replacement.svg', {
      type: 'image/svg+xml',
    });
    useConverterStore.setState({
      imageFile: currentPng,
      imagePreviewUrl: 'blob:current-png',
      cropModalOpen: false,
      enableCrop: true,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
    });

    useConverterStore.getState().setImageFile(replacementSvg);

    const state = useConverterStore.getState();
    expect(state.imageFile).toBe(replacementSvg);
    expect(state.cropModalOpen).toBe(false);
    expect(state.modeling_mode).toBe(ModelingMode.VECTOR);
  });

  it('setImageFile 用栅格图替换 SVG 时打开裁剪并退出矢量模式', () => {
    const currentSvg = new File(['<svg/>'], 'current.svg', {
      type: 'image/svg+xml',
    });
    const replacementPng = new File(['png'], 'replacement.png', {
      type: 'image/png',
    });
    useConverterStore.setState({
      imageFile: currentSvg,
      imagePreviewUrl: 'blob:current-svg',
      cropModalOpen: false,
      enableCrop: true,
      modeling_mode: ModelingMode.VECTOR,
    });

    useConverterStore.getState().setImageFile(replacementPng);

    const state = useConverterStore.getState();
    expect(state.imageFile).toBe(replacementPng);
    expect(state.cropModalOpen).toBe(true);
    expect(state.modeling_mode).toBe(ModelingMode.HIGH_FIDELITY);
  });
});
