import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConverterStore } from "../stores/converter";
import type { ConverterState } from "../stores/converter";

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
  replaceColorsBatch: vi.fn(),
  resetReplacements: vi.fn(),
}));

import { replaceColorsBatch, resetReplacements } from "../api/converter";

const mockReplaceColorsBatch = vi.mocked(replaceColorsBatch);
const mockResetReplacements = vi.mocked(resetReplacements);
const heightMap = { bee6f8: 0.48, "112233": 2.0 };

function seedStore(overrides: Partial<ConverterState>): void {
  useConverterStore.setState({
    sessionId: "height-identity-session",
    color_height_map: { ...heightMap },
    colorRemapMap: {},
    remapHistory: [],
    replacement_regions: [],
    regionReplacementCount: 0,
    regionData: null,
    selectedRegions: [],
    gradientSelection: null,
    selectedGradientRegions: [],
    selectedColors: new Set<string>(),
    selectedColor: null,
    pendingReplacement: null,
    replacePreviewLoading: false,
    _pollAsyncGlb: vi.fn(),
    error: null,
    ...overrides,
  } as Partial<ConverterState>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockResetReplacements.mockResolvedValue({
    status: "ok",
    message: "reset",
    preview_url: "/api/files/reset",
    preview_glb_url: null,
  });
  mockReplaceColorsBatch.mockResolvedValue({
    status: "ok",
    message: "replayed",
    preview_url: "/api/files/replayed",
    replacement_count: 1,
  });
});

describe("replacement undo preserves relief height identity", () => {
  it("resets the backend before replaying the previous whole-colour map", async () => {
    seedStore({
      colorRemapMap: { bee6f8: "f46429", "112233": "f46429" },
      remapHistory: [{ bee6f8: "445566" }],
    });

    await useConverterStore.getState().undoColorRemap();

    expect(mockResetReplacements).toHaveBeenCalledWith(
      "height-identity-session",
    );
    expect(mockReplaceColorsBatch).toHaveBeenCalledWith(
      "height-identity-session",
      [{ selectedColor: "#bee6f8", replacementColor: "#445566" }],
    );
    expect(mockResetReplacements.mock.invocationCallOrder[0]).toBeLessThan(
      mockReplaceColorsBatch.mock.invocationCallOrder[0],
    );
    expect(useConverterStore.getState().color_height_map).toEqual(heightMap);
  });

  it("performs a backend reset when undoing to an empty map", async () => {
    seedStore({
      colorRemapMap: { bee6f8: "f46429" },
      remapHistory: [{}],
    });

    await useConverterStore.getState().undoColorRemap();

    expect(mockResetReplacements).toHaveBeenCalledTimes(1);
    expect(mockReplaceColorsBatch).not.toHaveBeenCalled();
    expect(useConverterStore.getState().colorRemapMap).toEqual({});
    expect(useConverterStore.getState().color_height_map).toEqual(heightMap);
  });

  it("does not discard spatial edits when undo is requested", async () => {
    seedStore({
      colorRemapMap: { bee6f8: "f46429" },
      remapHistory: [{}],
      regionReplacementCount: 1,
    });

    await useConverterStore.getState().undoColorRemap();

    expect(mockResetReplacements).not.toHaveBeenCalled();
    expect(useConverterStore.getState().colorRemapMap).toEqual({
      bee6f8: "f46429",
    });
    expect(useConverterStore.getState().error).toContain("局部替换");
  });

  it("converges to the confirmed reset state when replay fails", async () => {
    seedStore({
      colorRemapMap: { bee6f8: "f46429", "112233": "f46429" },
      remapHistory: [{ bee6f8: "445566" }],
      threemfDiskPath: "/tmp/stale.3mf",
      downloadUrl: "/api/files/stale",
      previewGlbUrl: "/api/files/stale.glb",
    });
    mockReplaceColorsBatch.mockRejectedValueOnce(new Error("replay failed"));

    await useConverterStore.getState().undoColorRemap();

    const state = useConverterStore.getState();
    expect(state.colorRemapMap).toEqual({});
    expect(state.remapHistory).toEqual([]);
    expect(state.threemfDiskPath).toBeNull();
    expect(state.downloadUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.previewImageUrl).toBe("/api/files/reset");
    expect(state.error).toContain("replay failed");
  });
});
