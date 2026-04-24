import { describe, it, beforeEach, vi, expect } from "vitest";
import { useConverterStore } from "../stores/converter";
import type { ConverterState } from "../stores/converter";
import type { RegionReplaceResponse } from "../api/types";

/*
 * Regression tests for ``applyGradientRegionPixelReplace``.
 *
 * The store action wraps ``POST /api/convert/region-replace`` with the
 * gradient scope (``gradient_group_index`` / ``gradient_region_index``)
 * so the backend rebuilds the mask from the cached per-pixel region_id_map
 * and only that banded sub-region is edited. Without it, a LUT click while
 * a region was highlighted would fall back to the whole-image hex-remap
 * and recolour every matching pixel across the canvas — the "replace cyan
 * band → whole body turns red" bug we are pinning here.
 * ``applyGradientRegionPixelReplace`` 回归测试：验证 store action 携带
 * gradient scope 调用 regionReplace，避免落回全图 hex 替换路径。
 */

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
  colorHighlight: vi.fn(),
  detectRegion: vi.fn(),
  regionReplace: vi.fn(),
  resetReplacements: vi.fn(),
  autoDetectColors: vi.fn(),
  fetchGradientGroups: vi.fn(),
  fetchMaterialColorSuggestions: vi.fn(),
}));

import { regionReplace } from "../api/converter";

const mockRegionReplace = vi.mocked(regionReplace);

function seedStore(overrides: Partial<ConverterState> = {}) {
  useConverterStore.setState({
    sessionId: "sess-gradient-region",
    previewImageUrl: "/api/files/preview-old",
    previewBaseImageUrl: "/api/files/preview-old",
    previewGlbUrl: null,
    regionReplacementCount: 0,
    replacePreviewLoading: false,
    error: null,
    gradientSelection: { kind: "region", groupIndex: 3, regionIndex: 1 },
    selectedColors: new Set(["aabbcc", "ddeeff"]),
    selectedColor: "aabbcc",
    // A prior layer-images fetch that should be invalidated on replace.
    // 成功替换后应被清空的 layerImages 缓存。
    layerImages: [
      { layer_index: 0, name: "L0", url: "/api/files/old-layer-0" },
    ],
    layerImagesSourceKey: "stale-source-key",
    ...overrides,
  } as Partial<ConverterState>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("applyGradientRegionPixelReplace", () => {
  it("calls regionReplace with the gradient scope and advances the preview URLs", async () => {
    seedStore();
    const response: RegionReplaceResponse = {
      preview_url: "/api/files/preview-region-only",
      preview_glb_url: "/api/files/preview-region-only.glb",
      color_contours: null,
      message: "ok",
    };
    mockRegionReplace.mockResolvedValue(response);

    await useConverterStore
      .getState()
      .applyGradientRegionPixelReplace(3, 1, "ff0000");

    // The API must be called with the gradient scope so the server
    // rebuilds the mask from region_id_map — that's the whole point.
    // 必须带 gradient scope 调用，后端才会走精确 mask 分支。
    expect(mockRegionReplace).toHaveBeenCalledTimes(1);
    expect(mockRegionReplace).toHaveBeenCalledWith(
      "sess-gradient-region",
      "#ff0000",
      { gradientGroupIndex: 3, gradientRegionIndex: 1 },
    );

    const state = useConverterStore.getState();
    expect(state.previewImageUrl).toBe("/api/files/preview-region-only");
    expect(state.previewBaseImageUrl).toBe("/api/files/preview-region-only");
    expect(state.previewGlbUrl).toBe("/api/files/preview-region-only.glb");
    expect(state.replacePreviewLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("clears gradientSelection + selectedColors so the panel returns to the default state after the edit", async () => {
    seedStore();
    mockRegionReplace.mockResolvedValue({
      preview_url: "/api/files/preview-next",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    await useConverterStore
      .getState()
      .applyGradientRegionPixelReplace(3, 1, "ff0000");

    const state = useConverterStore.getState();
    expect(state.gradientSelection).toBeNull();
    expect(state.selectedColors.size).toBe(0);
    expect(state.selectedColor).toBeNull();
  });

  it("increments regionReplacementCount so subsequent generate reuses the cached matched_rgb", async () => {
    // The backend mutates the cached matched_rgb in place; generate() must
    // pass ``use_cached_matched_rgb=true`` or it would re-run the pipeline
    // from scratch and lose the spatial edit. Mirrors applyRegionReplace.
    // generate 必须走 use_cached_matched_rgb，否则会丢失空间替换结果。
    seedStore({ regionReplacementCount: 2 });
    mockRegionReplace.mockResolvedValue({
      preview_url: "/api/files/preview-next",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    await useConverterStore
      .getState()
      .applyGradientRegionPixelReplace(3, 1, "ff0000");

    expect(useConverterStore.getState().regionReplacementCount).toBe(3);
  });

  it("invalidates the per-layer image cache so hover tooltips refetch for the new preview", async () => {
    seedStore();
    mockRegionReplace.mockResolvedValue({
      preview_url: "/api/files/preview-next",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    await useConverterStore
      .getState()
      .applyGradientRegionPixelReplace(3, 1, "ff0000");

    const state = useConverterStore.getState();
    expect(state.layerImages).toEqual([]);
    expect(state.layerImagesSourceKey).toBeNull();
  });

  it("normalises the target hex (strips `#`, lowercases) before forwarding it", async () => {
    seedStore();
    mockRegionReplace.mockResolvedValue({
      preview_url: "/api/files/preview-next",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    await useConverterStore
      .getState()
      .applyGradientRegionPixelReplace(3, 1, "#AABBCC");

    expect(mockRegionReplace).toHaveBeenCalledWith(
      "sess-gradient-region",
      "#aabbcc",
      { gradientGroupIndex: 3, gradientRegionIndex: 1 },
    );
  });

  it("no-ops with an error when sessionId is missing", async () => {
    seedStore({ sessionId: null as unknown as string });

    await useConverterStore
      .getState()
      .applyGradientRegionPixelReplace(3, 1, "ff0000");

    expect(mockRegionReplace).not.toHaveBeenCalled();
    expect(useConverterStore.getState().error).toBeTruthy();
    expect(useConverterStore.getState().replacePreviewLoading).toBe(false);
  });

  it("surfaces backend errors via `error` and clears the loading flag", async () => {
    seedStore();
    mockRegionReplace.mockRejectedValueOnce(new Error("backend exploded"));

    await useConverterStore
      .getState()
      .applyGradientRegionPixelReplace(3, 1, "ff0000");

    const state = useConverterStore.getState();
    expect(state.error).toBe("backend exploded");
    expect(state.replacePreviewLoading).toBe(false);
    // Preview must stay unchanged when the API call failed; otherwise the
    // UI would anchor the user to a phantom preview that was never produced.
    // 后端失败时预览 URL 应保持旧值，避免跳到不存在的图。
    expect(state.previewBaseImageUrl).toBe("/api/files/preview-old");
  });
});
