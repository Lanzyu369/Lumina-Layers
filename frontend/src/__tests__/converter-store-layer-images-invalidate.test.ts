import { describe, it, beforeEach, vi, expect } from "vitest";
import { useConverterStore } from "../stores/converter";
import type { ConverterState } from "../stores/converter";
import type { ColorReplaceResponse } from "../api/types";

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
}));

import { replaceColor } from "../api/converter";

const mockReplaceColor = vi.mocked(replaceColor);

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
