import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConverterStore } from "../stores/converter";
import type { ConverterState } from "../stores/converter";
import type {
  ColorReplaceResponse,
  RegionReplaceResponse,
} from "../api/types";

/*
 * Regression tests for :func:`confirmReplacement` when the pending
 * replacement was seeded by a Gradient Groups *region* button.
 *
 * The user's mental model is: "I picked a region, I picked a colour,
 * now repaint that one region." The classic ``select-all`` branch of
 * ``confirmReplacement`` however applies a whole-image ``hex → hex``
 * remap via ``POST /api/convert/replace-color`` — that's the "replace
 * cyan band → every skin pixel turns red" regression we are pinning
 * here. ``confirmReplacement`` must detect ``gradientSelection.kind ===
 * 'region'`` and route to the spatial ``applyGradientRegionPixelReplace``
 * action (backed by ``/region-replace`` with gradient scope) instead.
 * 确认 confirmReplacement 在 region 来源时走空间替换路径，而不是全图 hex 替换。
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

import { regionReplace, replaceColor } from "../api/converter";

const mockRegionReplace = vi.mocked(regionReplace);
const mockReplaceColor = vi.mocked(replaceColor);

function seedStore(overrides: Partial<ConverterState> = {}) {
  useConverterStore.setState({
    sessionId: "sess-confirm",
    previewImageUrl: "/api/files/preview-old",
    previewBaseImageUrl: "/api/files/preview-old",
    previewGlbUrl: null,
    palette: [],
    colorRemapMap: {},
    remapHistory: [],
    replacePreviewLoading: false,
    error: null,
    regionReplacementCount: 0,
    selectionMode: "select-all",
    selectedColor: null,
    selectedColors: new Set(["aabbcc", "ddeeff"]),
    selectedRegions: [],
    gradientSelection: { kind: "region", groupIndex: 2, regionIndex: 3 },
    pendingReplacement: {
      sourceHex: "aabbcc",
      targetHex: "ff0000",
      mode: "select-all",
      sourceColors: ["aabbcc", "ddeeff"],
    },
    ...overrides,
  } as Partial<ConverterState>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("confirmReplacement · gradient-region scope", () => {
  it("routes to applyGradientRegionPixelReplace when gradientSelection.kind === 'region'", async () => {
    seedStore();
    const response: RegionReplaceResponse = {
      preview_url: "/api/files/preview-after.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    };
    mockRegionReplace.mockResolvedValue(response);

    await useConverterStore.getState().confirmReplacement();

    // Must call /region-replace with the gradient scope — not /replace-color.
    // 必须调 /region-replace 带 scope，不能调 /replace-color。
    expect(mockReplaceColor).not.toHaveBeenCalled();
    expect(mockRegionReplace).toHaveBeenCalledTimes(1);
    expect(mockRegionReplace).toHaveBeenCalledWith(
      "sess-confirm",
      "#ff0000",
      { gradientGroupIndex: 2, gradientRegionIndex: 3 },
    );

    const state = useConverterStore.getState();
    expect(state.pendingReplacement).toBeNull();
    expect(state.previewImageUrl).toBe("/api/files/preview-after.png");
    expect(state.regionReplacementCount).toBe(1);
  });

  it("does NOT touch colorRemapMap when taking the gradient-region path", async () => {
    // colorRemapMap is a whole-image hex→hex mapping; polluting it with
    // a region-scoped edit would cause the 3D preview / future applies
    // to recolour every matching pixel — exactly what we are avoiding.
    // 空间替换不应污染 colorRemapMap，否则 3D 预览会把全图同色都改掉。
    seedStore({ colorRemapMap: { foo: "bar" } });
    mockRegionReplace.mockResolvedValue({
      preview_url: "/api/files/preview-after.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    await useConverterStore.getState().confirmReplacement();

    expect(useConverterStore.getState().colorRemapMap).toEqual({ foo: "bar" });
  });

  it("falls through to the classic select-all hex remap when gradientSelection is null", async () => {
    // Sanity: users who never touched the Gradient Groups panel still
    // get the original whole-image remap behaviour — this path is the
    // one we must not regress.
    // gradientSelection 为空时走原 select-all → /replace-color 路径。
    seedStore({
      gradientSelection: null,
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ff0000",
        mode: "select-all",
      },
      selectedColors: new Set<string>(),
      selectedColor: "aabbcc",
    });
    const response: ColorReplaceResponse = {
      status: "ok",
      message: "ok",
      preview_url: "/api/files/preview-after.png",
      replacement_count: 1,
    };
    mockReplaceColor.mockResolvedValue(response);

    await useConverterStore.getState().confirmReplacement();

    expect(mockRegionReplace).not.toHaveBeenCalled();
    // colorRemapMap gets the hex pair written via applyColorRemap.
    // 单色 select-all 会乐观写入 colorRemapMap。
    expect(useConverterStore.getState().colorRemapMap).toMatchObject({
      aabbcc: "ff0000",
    });
  });

  it("still uses the gradient-region path even when pending.mode is 'current'", async () => {
    // Defence in depth: some UI paths set mode='current'/'region' on the
    // pending payload even though the selection actually came from a
    // gradient region button. The scope branch must trigger on
    // ``gradientSelection.kind`` alone, not on pending.mode.
    // pending.mode 不等于 region 来源；以 gradientSelection 为唯一判据。
    seedStore({
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ff0000",
        mode: "current",
      },
    });
    mockRegionReplace.mockResolvedValue({
      preview_url: "/api/files/preview-after.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    await useConverterStore.getState().confirmReplacement();

    expect(mockReplaceColor).not.toHaveBeenCalled();
    expect(mockRegionReplace).toHaveBeenCalledTimes(1);
    expect(mockRegionReplace).toHaveBeenCalledWith(
      "sess-confirm",
      "#ff0000",
      { gradientGroupIndex: 2, gradientRegionIndex: 3 },
    );
  });
});
