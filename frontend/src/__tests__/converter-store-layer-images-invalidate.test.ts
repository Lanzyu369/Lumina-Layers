import { describe, it, beforeEach, vi, expect } from "vitest";
import { useConverterStore } from "../stores/converter";
import type { ConverterState } from "../stores/converter";
import type {
  ColorReplaceResponse,
  RecipeOverrideApplyResponse,
} from "../api/types";

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn(),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  fetchBedSizes: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
  convertBatch: vi.fn(),
  replaceColor: vi.fn(),
  applyRecipeOverride: vi.fn(),
}));

import { replaceColor, applyRecipeOverride } from "../api/converter";

const mockReplaceColor = vi.mocked(replaceColor);
const mockApplyRecipeOverride = vi.mocked(applyRecipeOverride);

function seedStore(overrides: Partial<ConverterState> = {}) {
  useConverterStore.setState({
    sessionId: "sess-abc",
    previewImageUrl: "/api/files/preview-old",
    previewBaseImageUrl: "/api/files/preview-old",
    previewGlbUrl: null,
    colorRemapMap: {},
    remapHistory: [],
    palette: [],
    replacePreviewLoading: false,
    error: null,
    // Simulate a prior successful layer-images fetch that is now stale
    layerImages: [
      { layer_index: 0, name: "L0", url: "/api/files/old-layer-0" },
      { layer_index: 1, name: "L1", url: "/api/files/old-layer-1" },
    ],
    layerImagesLoading: false,
    layerImagesOpen: true,
    layerImagesSourceKey: "sess-abc|null|/api/files/preview-old|/api/files/preview-old",
    ...overrides,
  } as Partial<ConverterState>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("layer image cache invalidation after color replacement", () => {
  it("submitSingleReplace invalidates cached layerImages and layerImagesSourceKey so hover tooltip refetches", async () => {
    seedStore();
    const response: ColorReplaceResponse = {
      status: "ok",
      message: "ok",
      preview_url: "/api/files/preview-new",
      replacement_count: 1,
    };
    mockReplaceColor.mockResolvedValue(response);

    await useConverterStore.getState().submitSingleReplace("00ae42", "ffffff");

    const state = useConverterStore.getState();
    // Preview URL advances (main image correctly updates)
    expect(state.previewBaseImageUrl).toBe("/api/files/preview-new");
    // Stale per-layer image cache is invalidated
    expect(state.layerImages).toEqual([]);
    expect(state.layerImagesSourceKey).toBeNull();
    // User panel visibility is preserved
    expect(state.layerImagesOpen).toBe(true);
  });

  it("submitReplacePreview invalidates cached layerImages after applying pending remaps", async () => {
    seedStore({
      colorRemapMap: { "00ae42": "ffffff" },
      palette: [
        {
          quantized_hex: "00ae42",
          matched_hex: "00ae42",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockReplaceColor.mockResolvedValue({
      status: "ok",
      message: "ok",
      preview_url: "/api/files/preview-batch-new",
      replacement_count: 1,
    });

    await useConverterStore.getState().submitReplacePreview();

    const state = useConverterStore.getState();
    expect(state.previewBaseImageUrl).toBe("/api/files/preview-batch-new");
    expect(state.layerImages).toEqual([]);
    expect(state.layerImagesSourceKey).toBeNull();
    expect(state.layerImagesOpen).toBe(true);
  });

  it("leaves layer cache untouched when replacement fails", async () => {
    seedStore();
    mockReplaceColor.mockRejectedValue(new Error("boom"));

    await useConverterStore.getState().submitSingleReplace("00ae42", "ffffff");

    const state = useConverterStore.getState();
    // On failure, preview URL is not rotated and layer cache is not cleared
    expect(state.previewBaseImageUrl).toBe("/api/files/preview-old");
    expect(state.layerImages).toHaveLength(2);
    expect(state.layerImagesSourceKey).not.toBeNull();
  });
});

describe("layer image cache invalidation after custom recipe apply", () => {
  it("applyCustomRecipeOverride invalidates cached layerImages so the grid refetches with the new layer count", async () => {
    // Regression for "分层预览还是只显示更改配方的那几层": apply can change
    // ``color_layers`` (e.g., 3 -> 6 when the user declares a taller custom
    // recipe) and rewrite the post-apply ``material_matrix``. The pre-apply
    // layer-image list is both shorter and stale, so ``ActionBar`` only
    // renders a subset and makes the panel look half-broken. The store's
    // recipe-override path must invalidate the layer-image cache exactly
    // like the color-replacement paths do.
    // 自定义配方 apply 会改变 color_layers 并重绘 material_matrix，老缓存
    // 的 layerImages 既长度不够又是过期数据，ActionBar 只能渲染出一部分
    // 层——看起来就是 "分层预览只显示更改配方的那几层"。store 的
    // applyCustomRecipeOverride 必须跟颜色替换路径一样把 layerImages 清空。
    seedStore();
    const response: RecipeOverrideApplyResponse = {
      status: "ok",
      message: "ok",
      rgb: [17, 17, 17],
      lab: [10, 0, 0],
      source: "predictive",
      runtime_mode_key: "0.08x6",
      preview_url: "/api/files/preview-apply",
      preview_glb_url: null,
      override_count: 1,
    };
    mockApplyRecipeOverride.mockResolvedValue(response);

    await useConverterStore
      .getState()
      .applyCustomRecipeOverride(["region-1"], [1, 1, 1, 1, 1, 1], "Top2Bottom");

    const state = useConverterStore.getState();
    expect(state.previewBaseImageUrl).toBe("/api/files/preview-apply");
    expect(state.layerImages).toEqual([]);
    expect(state.layerImagesSourceKey).toBeNull();
    // The panel's open state is preserved so the grid re-populates as soon
    // as the user hovers or the auto-fetch effect fires.
    // 保留面板可见性，用户下一次 hover / 自动 fetch 生效时会立刻刷新。
    expect(state.layerImagesOpen).toBe(true);
  });
});
