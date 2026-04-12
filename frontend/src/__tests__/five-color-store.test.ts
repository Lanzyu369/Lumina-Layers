import { beforeEach, describe, expect, it, vi } from "vitest";
import { useFiveColorStore, type CollectedRecipe } from "../stores/fiveColorStore";

vi.mock("../api/fiveColor", () => ({
  fetchBaseColors: vi.fn(),
  queryFiveColor: vi.fn(),
  generateRecipeSwatch: vi.fn(),
}));

import { fetchBaseColors, generateRecipeSwatch } from "../api/fiveColor";

const mockFetchBaseColors = vi.mocked(fetchBaseColors);
const mockGenerateRecipeSwatch = vi.mocked(generateRecipeSwatch);

const staleRecipe: CollectedRecipe = {
  id: "old-lut_0-1-2-3-4_1",
  selectedIndices: [0, 1, 2, 3, 4],
  resultHex: "#123456",
  baseColorNames: ["Old 0", "Old 1", "Old 2", "Old 3", "Old 4"],
  baseColorHexes: ["#111111", "#222222", "#333333", "#444444", "#555555"],
  label: "Old 0 → Old 1 → Old 2 → Old 3 → Old 4",
};

function resetStore() {
  useFiveColorStore.setState({
    lutName: "",
    baseColors: [],
    combinations: null,
    selectedIndices: [],
    queryResult: null,
    isLoading: false,
    error: null,
    collectedRecipes: [],
    swatchBlockSize: 15,
    swatchGap: 2,
    swatchCols: 0,
    swatchStructureMode: "Single-sided",
    isGeneratingSwatch: false,
    swatchDownloadUrl: null,
    swatchPreviewUrl: null,
  });
}

describe("fiveColorStore LUT switching", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    resetStore();
  });

  it("clears stale collection and swatch outputs when loading a different LUT", async () => {
    useFiveColorStore.setState({
      lutName: "old-lut",
      collectedRecipes: [staleRecipe],
      swatchDownloadUrl: "/api/files/old-swatch.3mf",
      swatchPreviewUrl: "/api/files/old-swatch.png",
    });

    mockFetchBaseColors.mockResolvedValueOnce({
      lut_name: "new-lut",
      color_count: 5,
      colors: [
        { index: 0, rgb: [255, 0, 0], name: "Red", hex: "#FF0000" },
        { index: 1, rgb: [0, 255, 0], name: "Green", hex: "#00FF00" },
        { index: 2, rgb: [0, 0, 255], name: "Blue", hex: "#0000FF" },
        { index: 3, rgb: [255, 255, 0], name: "Yellow", hex: "#FFFF00" },
        { index: 4, rgb: [255, 255, 255], name: "White", hex: "#FFFFFF" },
      ],
      combinations: [[0, 1, 2, 3, 4]],
    });

    await useFiveColorStore.getState().loadBaseColors("new-lut");

    const state = useFiveColorStore.getState();
    expect(state.lutName).toBe("new-lut");
    expect(state.collectedRecipes).toEqual([]);
    expect(state.swatchDownloadUrl).toBeNull();
    expect(state.swatchPreviewUrl).toBeNull();

    await useFiveColorStore.getState().generateSwatch();

    expect(mockGenerateRecipeSwatch).not.toHaveBeenCalled();
  });
});
