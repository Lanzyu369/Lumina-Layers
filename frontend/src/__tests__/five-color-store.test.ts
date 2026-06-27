import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useFiveColorStore,
  type CollectedRecipe,
} from "../stores/fiveColorStore";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { FiveColorCardCoordinate } from "../api/types";
import { tRuntime } from "../i18n/runtime";

vi.mock("../api/fiveColor", () => ({
  fetchBaseColors: vi.fn(),
  queryFiveColor: vi.fn(),
  matchFiveColorByHex: vi.fn(),
  generateRecipeSwatch: vi.fn(),
}));

import { fetchBaseColors, generateRecipeSwatch, matchFiveColorByHex, queryFiveColor } from "../api/fiveColor";

const mockFetchBaseColors = vi.mocked(fetchBaseColors);
const mockGenerateRecipeSwatch = vi.mocked(generateRecipeSwatch);
const mockMatchFiveColorByHex = vi.mocked(matchFiveColorByHex);
const mockQueryFiveColor = vi.mocked(queryFiveColor);

function apiFailure(
  data: unknown,
  message = "Request failed with status code 422",
  status = 422,
) {
  return {
    message,
    response: {
      status,
      data,
    },
  };
}

const staleRecipe: CollectedRecipe = {
  id: "old-lut_0-1-2-3-4_1",
  selectedIndices: [0, 1, 2, 3, 4],
  resultHex: "#123456",
  baseColorNames: ["Old 0", "Old 1", "Old 2", "Old 3", "Old 4"],
  baseColorHexes: ["#111111", "#222222", "#333333", "#444444", "#555555"],
  label: "Old 0 → Old 1 → Old 2 → Old 3 → Old 4",
};

function cardCoordinate(
  overrides: Partial<FiveColorCardCoordinate> = {},
): FiveColorCardCoordinate {
  const gridSize = overrides.grid_size ?? 2;
  const row = overrides.row ?? 0;
  const col = overrides.col ?? 0;
  return {
    card_index: 0,
    card_label: "1",
    page_index: 0,
    page_label: "1",
    grid_size: gridSize,
    data_rows: gridSize,
    data_cols: gridSize,
    row,
    col,
    data_row: row,
    data_col: col,
    display_row: row + 1,
    display_col: col + 1,
    physical_row: row,
    physical_col: col,
    row_index: row * gridSize + col,
    ...overrides,
  };
}

function resetStore() {
  useFiveColorStore.setState({
    lutName: "",
    baseColors: [],
    combinations: null,
    selectedIndices: [],
    manualSelectedIndices: [],
    selectionSource: "manual",
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
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
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

  it("clears current selection after successfully adding a recipe to the collection", () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      baseColors: [
        { index: 0, rgb: [255, 0, 0], name: "Red", hex: "#FF0000" },
        { index: 1, rgb: [0, 255, 0], name: "Green", hex: "#00FF00" },
        { index: 2, rgb: [0, 0, 255], name: "Blue", hex: "#0000FF" },
        { index: 3, rgb: [255, 255, 0], name: "Yellow", hex: "#FFFF00" },
        { index: 4, rgb: [255, 255, 255], name: "White", hex: "#FFFFFF" },
      ],
      selectedIndices: [0, 1, 2, 3, 4],
      queryResult: {
        found: true,
        selected_indices: [0, 1, 2, 3, 4],
        result_rgb: [18, 52, 86],
        result_hex: "#123456",
        row_index: 7,
        message: "found",
        source: "lut",
      },
    });

    useFiveColorStore.getState().addToCollection();

    const state = useFiveColorStore.getState();
    expect(state.collectedRecipes).toHaveLength(1);
    expect(state.selectedIndices).toEqual([]);
    expect(state.queryResult).toBeNull();
  });

  it("passes printer tuple from settings into swatch export", async () => {
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      printerModel: "bambu-h2d",
      slicerSoftware: "BambuStudio",
      nozzleSize: "0.2",
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.2",
    });
    useFiveColorStore.setState({
      lutName: "test-lut",
      collectedRecipes: [staleRecipe],
    });
    mockGenerateRecipeSwatch.mockResolvedValueOnce({
      status: "ok",
      message: "ok",
      download_url: "/api/files/swatch.3mf",
      preview_url: "/api/files/swatch.png",
      recipe_count: 1,
    });

    await useFiveColorStore.getState().generateSwatch();

    expect(mockGenerateRecipeSwatch).toHaveBeenCalledOnce();
    expect(mockGenerateRecipeSwatch).toHaveBeenCalledWith(
      expect.objectContaining({
        printer_id: "bambu-h2d",
        slicer: "BambuStudio",
        nozzle_size: "0.2",
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.2",
      }),
    );
  });

  it("maps base color loading failures to a localized error key", async () => {
    mockFetchBaseColors.mockRejectedValueOnce(new Error("backend detail leaked"));

    await useFiveColorStore.getState().loadBaseColors("broken-lut");

    const state = useFiveColorStore.getState();
    expect(state.error).toBe("five_color_error_load_base_colors_failed");
    expect(state.isLoading).toBe(false);
  });

  it("preserves backend detail when base color loading fails", async () => {
    mockFetchBaseColors.mockRejectedValueOnce(
      apiFailure({ detail: "Selected LUT does not expose a five-color base palette" }),
    );

    await useFiveColorStore.getState().loadBaseColors("broken-lut");

    const state = useFiveColorStore.getState();
    expect(state.error).toBe("Selected LUT does not expose a five-color base palette");
    expect(state.isLoading).toBe(false);
  });

  it("hides missing LUT backend details when base color loading fails", async () => {
    mockFetchBaseColors.mockRejectedValueOnce(
      apiFailure(
        { detail: "LUT not found: stale-five-color" },
        "Request failed with status code 404",
        404,
      ),
    );

    await useFiveColorStore.getState().loadBaseColors("stale-five-color");

    const state = useFiveColorStore.getState();
    expect(state.error).toBe(tRuntime("lut_error_missing_refresh"));
    expect(state.error).not.toMatch(/LUT not found/i);
    expect(state.isLoading).toBe(false);
  });

  it("clears stale base colors when loading a different LUT fails", async () => {
    mockFetchBaseColors.mockResolvedValueOnce({
      lut_name: "old-lut",
      color_count: 5,
      colors: [
        { index: 0, rgb: [255, 0, 0], name: "Old Red", hex: "#FF0000" },
        { index: 1, rgb: [0, 255, 0], name: "Old Green", hex: "#00FF00" },
      ],
      combinations: null,
    });
    mockFetchBaseColors.mockRejectedValueOnce(new Error("new LUT failed"));

    await useFiveColorStore.getState().loadBaseColors("old-lut");
    expect(useFiveColorStore.getState().baseColors).toHaveLength(2);

    await useFiveColorStore.getState().loadBaseColors("broken-lut");

    const state = useFiveColorStore.getState();
    expect(state.lutName).toBe("broken-lut");
    expect(state.baseColors).toEqual([]);
    expect(state.combinations).toBeNull();
    expect(state.error).toBe("five_color_error_load_base_colors_failed");
  });

  it("maps swatch generation failures to a localized error key", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      collectedRecipes: [staleRecipe],
    });
    mockGenerateRecipeSwatch.mockRejectedValueOnce(new Error("raw swatch failure"));

    await useFiveColorStore.getState().generateSwatch();

    const state = useFiveColorStore.getState();
    expect(state.error).toBe("five_color_error_generate_swatch_failed");
    expect(state.isGeneratingSwatch).toBe(false);
  });

  it("keeps the localized fallback for raw status-code swatch failures", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      collectedRecipes: [staleRecipe],
    });
    mockGenerateRecipeSwatch.mockRejectedValueOnce(new Error("Request failed with status code 500"));

    await useFiveColorStore.getState().generateSwatch();

    const state = useFiveColorStore.getState();
    expect(state.error).toBe("five_color_error_generate_swatch_failed");
    expect(state.isGeneratingSwatch).toBe(false);
  });

  it("hides missing LUT backend details when swatch generation fails", async () => {
    useFiveColorStore.setState({
      lutName: "stale-five-color",
      collectedRecipes: [staleRecipe],
    });
    mockGenerateRecipeSwatch.mockRejectedValueOnce(
      apiFailure(
        { detail: "LUT not found: stale-five-color" },
        "Request failed with status code 404",
        404,
      ),
    );

    await useFiveColorStore.getState().generateSwatch();

    const state = useFiveColorStore.getState();
    expect(state.error).toBe(tRuntime("lut_error_missing_refresh"));
    expect(state.error).not.toMatch(/LUT not found/i);
    expect(state.isGeneratingSwatch).toBe(false);
  });

  it("hides backend validation paths when swatch generation fails", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      collectedRecipes: [staleRecipe],
    });
    mockGenerateRecipeSwatch.mockRejectedValueOnce(
      apiFailure({
        detail: [
          {
            loc: ["body", "recipes", 0, "selected_indices"],
            msg: "Recipe must contain exactly five material indices",
          },
        ],
      }),
    );

    await useFiveColorStore.getState().generateSwatch();

    const state = useFiveColorStore.getState();
    expect(state.error).toBe("five_color_error_generate_swatch_failed");
    expect(state.error).not.toContain("body.recipes.0.selected_indices");
    expect(state.error).not.toContain("selected_indices");
    expect(state.isGeneratingSwatch).toBe(false);
  });

  it("matches a target hex and syncs the returned recipe into the current selection", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [0, 0, 0, 0, 0],
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
      target_rgb: [242, 10, 0],
      target_hex: "#F20A00",
      matched_rgb: [240, 10, 0],
      matched_hex: "#F00A00",
      delta_e: 1.25,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 2,
        row: 0,
        col: 1,
        display_row: 1,
        display_col: 2,
      }),
      neighborhood: [],
    });

    await useFiveColorStore.getState().matchColorByHex("#F20A00");

    expect(mockMatchFiveColorByHex).toHaveBeenCalledWith({
      lut_name: "test-lut",
      target_hex: "#F20A00",
      neighborhood_radius: 2,
    });
    const state = useFiveColorStore.getState();
    expect(state.selectedIndices).toEqual([0, 1, 2, 3, 4]);
    expect(state.queryResult?.result_hex).toBe("#F00A00");
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("submits a six-layer recipe when the loaded combinations are six-wide", async () => {
    useFiveColorStore.setState({
      lutName: "extended-lut",
      combinations: [[4, 1, 2, 3, 0, 4]],
      selectedIndices: [],
      queryResult: null,
    });
    for (const index of [4, 1, 2, 3, 0, 4]) {
      useFiveColorStore.getState().addSelection(index);
    }
    mockQueryFiveColor.mockResolvedValueOnce({
      found: true,
      selected_indices: [4, 1, 2, 3, 0, 4],
      result_rgb: [4, 5, 6],
      result_hex: "#040506",
      row_index: 1,
      message: "found",
      source: "extended",
    });

    await useFiveColorStore.getState().submitQuery();

    expect(mockQueryFiveColor).toHaveBeenCalledWith({
      lut_name: "extended-lut",
      selected_indices: [4, 1, 2, 3, 0, 4],
    });
    const state = useFiveColorStore.getState();
    expect(state.selectedIndices).toEqual([4, 1, 2, 3, 0, 4]);
    expect(state.queryResult?.result_hex).toBe("#040506");
  });

  it("allows six-layer manual selection when mixed combinations start with a five-layer row", async () => {
    useFiveColorStore.setState({
      lutName: "mixed-extended-lut",
      combinations: [
        [0, 1, 2, 3, 4],
        [4, 1, 2, 3, 0, 4],
      ],
      selectedIndices: [],
      queryResult: null,
    });
    for (const index of [4, 1, 2, 3, 0, 4]) {
      useFiveColorStore.getState().addSelection(index);
    }
    mockQueryFiveColor.mockResolvedValueOnce({
      found: true,
      selected_indices: [4, 1, 2, 3, 0, 4],
      result_rgb: [4, 5, 6],
      result_hex: "#040506",
      row_index: 1,
      message: "found",
      source: "extended",
    });

    await useFiveColorStore.getState().submitQuery();

    expect(mockQueryFiveColor).toHaveBeenCalledWith({
      lut_name: "mixed-extended-lut",
      selected_indices: [4, 1, 2, 3, 0, 4],
    });
    expect(useFiveColorStore.getState().selectedIndices).toEqual([4, 1, 2, 3, 0, 4]);
  });

  it("allows submitting a five-layer recipe that is also a six-layer prefix", async () => {
    useFiveColorStore.setState({
      lutName: "mixed-prefix-lut",
      combinations: [
        [0, 1, 2, 3, 4],
        [0, 1, 2, 3, 4, 5],
      ],
      selectedIndices: [0, 1, 2, 3, 4],
      queryResult: null,
    });
    mockQueryFiveColor.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [1, 2, 3],
      result_hex: "#010203",
      row_index: 0,
      message: "found",
      source: "legacy",
    });

    await useFiveColorStore.getState().submitQuery();

    expect(mockQueryFiveColor).toHaveBeenCalledWith({
      lut_name: "mixed-prefix-lut",
      selected_indices: [0, 1, 2, 3, 4],
    });
    expect(useFiveColorStore.getState().queryResult?.result_hex).toBe("#010203");
  });

  it("ignores stale target-match responses after switching LUTs", async () => {
    let resolveMatch: (value: Awaited<ReturnType<typeof matchFiveColorByHex>>) => void;
    const matchPromise = new Promise<Awaited<ReturnType<typeof matchFiveColorByHex>>>((resolve) => {
      resolveMatch = resolve;
    });
    mockMatchFiveColorByHex.mockReturnValueOnce(matchPromise);
    mockFetchBaseColors.mockResolvedValueOnce({
      lut_name: "lut-b",
      color_count: 5,
      colors: [
        { index: 0, rgb: [1, 1, 1], name: "B0", hex: "#010101" },
        { index: 1, rgb: [2, 2, 2], name: "B1", hex: "#020202" },
      ],
      combinations: null,
    });
    useFiveColorStore.setState({
      lutName: "lut-a",
      selectedIndices: [4, 3, 2, 1, 0],
      manualSelectedIndices: [4, 3, 2, 1, 0],
      selectionSource: "manual",
    });

    const staleRequest = useFiveColorStore.getState().matchColorByHex("#AA0000");
    await useFiveColorStore.getState().loadBaseColors("lut-b");

    resolveMatch!({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [170, 0, 0],
      result_hex: "#AA0000",
      row_index: 12,
      message: "found",
      source: "lut-a",
      target_rgb: [170, 0, 0],
      target_hex: "#AA0000",
      matched_rgb: [170, 0, 0],
      matched_hex: "#AA0000",
      delta_e: 0,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 4,
        row: 3,
        col: 0,
        display_row: 4,
        display_col: 1,
      }),
      neighborhood: [],
    });
    await staleRequest;

    const state = useFiveColorStore.getState();
    expect(state.lutName).toBe("lut-b");
    expect(state.selectedIndices).toEqual([]);
    expect(state.manualSelectedIndices).toEqual([]);
    expect(state.selectionSource).toBe("manual");
    expect(state.queryResult).toBeNull();
  });

  it("ignores stale query responses after switching LUTs", async () => {
    let resolveQuery: (value: Awaited<ReturnType<typeof queryFiveColor>>) => void;
    const queryPromise = new Promise<Awaited<ReturnType<typeof queryFiveColor>>>((resolve) => {
      resolveQuery = resolve;
    });
    mockQueryFiveColor.mockReturnValueOnce(queryPromise);
    mockFetchBaseColors.mockResolvedValueOnce({
      lut_name: "lut-b",
      color_count: 5,
      colors: [
        { index: 0, rgb: [1, 1, 1], name: "B0", hex: "#010101" },
        { index: 1, rgb: [2, 2, 2], name: "B1", hex: "#020202" },
      ],
      combinations: null,
    });
    useFiveColorStore.setState({
      lutName: "lut-a",
      selectedIndices: [0, 1, 2, 3, 4],
      manualSelectedIndices: [0, 1, 2, 3, 4],
      selectionSource: "manual",
      queryResult: null,
    });

    const staleRequest = useFiveColorStore.getState().submitQuery();
    await useFiveColorStore.getState().loadBaseColors("lut-b");

    resolveQuery!({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [170, 0, 0],
      result_hex: "#AA0000",
      row_index: 12,
      message: "found",
      source: "lut-a",
    });
    await staleRequest;

    const state = useFiveColorStore.getState();
    expect(state.lutName).toBe("lut-b");
    expect(state.selectedIndices).toEqual([]);
    expect(state.manualSelectedIndices).toEqual([]);
    expect(state.selectionSource).toBe("manual");
    expect(state.queryResult).toBeNull();
    expect(state.isLoading).toBe(false);
  });

  it("ignores target-match responses after manual edits during the request", async () => {
    let resolveMatch: (value: Awaited<ReturnType<typeof matchFiveColorByHex>>) => void;
    const matchPromise = new Promise<Awaited<ReturnType<typeof matchFiveColorByHex>>>((resolve) => {
      resolveMatch = resolve;
    });
    mockMatchFiveColorByHex.mockReturnValueOnce(matchPromise);
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [4],
      manualSelectedIndices: [4],
      selectionSource: "manual",
      queryResult: null,
    });

    const pendingMatch = useFiveColorStore.getState().matchColorByHex("#AA0000");
    useFiveColorStore.getState().addSelection(3);

    resolveMatch!({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [170, 0, 0],
      result_hex: "#AA0000",
      row_index: 12,
      message: "found",
      source: "test",
      target_rgb: [170, 0, 0],
      target_hex: "#AA0000",
      matched_rgb: [170, 0, 0],
      matched_hex: "#AA0000",
      delta_e: 0,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 4,
        row: 3,
        col: 0,
        display_row: 4,
        display_col: 1,
      }),
      neighborhood: [],
    });
    await pendingMatch;

    const state = useFiveColorStore.getState();
    expect(state.selectedIndices).toEqual([4, 3]);
    expect(state.manualSelectedIndices).toEqual([4, 3]);
    expect(state.selectionSource).toBe("manual");
    expect(state.queryResult).toBeNull();
    expect(state.isLoading).toBe(false);
  });

  it("rejects invalid target hex values before calling the API", async () => {
    useFiveColorStore.setState({ lutName: "test-lut" });

    await useFiveColorStore.getState().matchColorByHex("bad");

    expect(mockMatchFiveColorByHex).not.toHaveBeenCalled();
    const state = useFiveColorStore.getState();
    expect(state.error).toBe("five_color_error_invalid_hex");
    expect(state.isLoading).toBe(false);
  });

  it("clears stale match results when a target hex lookup fails", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [4, 3, 2, 1, 0],
      manualSelectedIndices: [4, 3, 2, 1, 0],
      selectionSource: "manual",
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
      target_rgb: [242, 10, 0],
      target_hex: "#F20A00",
      matched_rgb: [240, 10, 0],
      matched_hex: "#F00A00",
      delta_e: 1.25,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 2,
        row: 0,
        col: 1,
        display_row: 1,
        display_col: 2,
      }),
      neighborhood: [],
    });
    await useFiveColorStore.getState().matchColorByHex("#F20A00");
    expect(useFiveColorStore.getState().selectedIndices).toEqual([0, 1, 2, 3, 4]);

    await useFiveColorStore.getState().matchColorByHex("bad");

    const state = useFiveColorStore.getState();
    expect(state.queryResult).toBeNull();
    expect(state.selectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.error).toBe("five_color_error_invalid_hex");
    expect(state.isLoading).toBe(false);
  });

  it("preserves backend detail when target hex lookup fails", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [4, 3, 2, 1, 0],
      manualSelectedIndices: [4, 3, 2, 1, 0],
      selectionSource: "manual",
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockRejectedValueOnce(
      apiFailure({ detail: "Target color is outside the loaded five-color LUT gamut" }),
    );

    await useFiveColorStore.getState().matchColorByHex("#F20A00");

    const state = useFiveColorStore.getState();
    expect(state.queryResult).toBeNull();
    expect(state.selectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.error).toBe("Target color is outside the loaded five-color LUT gamut");
    expect(state.isLoading).toBe(false);
  });

  it("hides missing LUT backend details when target hex lookup fails", async () => {
    useFiveColorStore.setState({
      lutName: "stale-five-color",
      selectedIndices: [4, 3, 2, 1, 0],
      manualSelectedIndices: [4, 3, 2, 1, 0],
      selectionSource: "manual",
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockRejectedValueOnce(
      apiFailure(
        { detail: "LUT not found: stale-five-color" },
        "Request failed with status code 404",
        404,
      ),
    );

    await useFiveColorStore.getState().matchColorByHex("#F20A00");

    const state = useFiveColorStore.getState();
    expect(state.queryResult).toBeNull();
    expect(state.error).toBe(tRuntime("lut_error_missing_refresh"));
    expect(state.error).not.toMatch(/LUT not found/i);
    expect(state.selectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.isLoading).toBe(false);
  });

  it("restores the manual selection when a target hex lookup has no recipe after a match", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [4, 3, 2, 1, 0],
      manualSelectedIndices: [4, 3, 2, 1, 0],
      selectionSource: "manual",
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
      target_rgb: [242, 10, 0],
      target_hex: "#F20A00",
      matched_rgb: [240, 10, 0],
      matched_hex: "#F00A00",
      delta_e: 1.25,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 2,
        row: 0,
        col: 1,
        display_row: 1,
        display_col: 2,
      }),
      neighborhood: [],
    });
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: false,
      selected_indices: [],
      result_rgb: null,
      result_hex: null,
      row_index: 33,
      message: "Matched row 33, but no five-layer recipe is available for this LUT row.",
      reason: "recipe_unavailable",
      source: "test",
      target_rgb: [220, 10, 30],
      target_hex: "#DC0A1E",
      matched_rgb: [220, 10, 30],
      matched_hex: "#DC0A1E",
      delta_e: 0,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 7,
        row: 4,
        col: 5,
        display_row: 5,
        display_col: 6,
      }),
      neighborhood: [],
    });

    await useFiveColorStore.getState().matchColorByHex("#F20A00");
    expect(useFiveColorStore.getState().selectedIndices).toEqual([0, 1, 2, 3, 4]);

    await useFiveColorStore.getState().matchColorByHex("#DC0A1E");

    const state = useFiveColorStore.getState();
    expect(state.selectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.queryResult?.found).toBe(false);
    expect(state.queryResult && "matched_hex" in state.queryResult ? state.queryResult.matched_hex : null)
      .toBe("#DC0A1E");
    expect(state.error).toBeNull();
  });

  it("does not pollute manual fallback when a standard query fails after target matching", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [4, 3, 2, 1, 0],
      manualSelectedIndices: [4, 3, 2, 1, 0],
      selectionSource: "manual",
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
      target_rgb: [242, 10, 0],
      target_hex: "#F20A00",
      matched_rgb: [240, 10, 0],
      matched_hex: "#F00A00",
      delta_e: 1.25,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 2,
        row: 0,
        col: 1,
        display_row: 1,
        display_col: 2,
      }),
      neighborhood: [],
    });
    mockQueryFiveColor.mockRejectedValueOnce(new Error("query failed"));

    await useFiveColorStore.getState().matchColorByHex("#F20A00");
    await useFiveColorStore.getState().submitQuery();

    const state = useFiveColorStore.getState();
    expect(state.queryResult).toBeNull();
    expect(state.error).toBe("five_color_error_query_failed");
    expect(state.selectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.manualSelectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.selectionSource).toBe("manual");
  });

  it("preserves backend detail when a standard query fails", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [0, 1, 2, 3, 4],
      manualSelectedIndices: [0, 1, 2, 3, 4],
      selectionSource: "manual",
      queryResult: null,
    });
    mockQueryFiveColor.mockRejectedValueOnce(
      apiFailure({ detail: "Selected LUT does not contain five-color recipes" }),
    );

    await useFiveColorStore.getState().submitQuery();

    const state = useFiveColorStore.getState();
    expect(state.queryResult).toBeNull();
    expect(state.error).toBe("Selected LUT does not contain five-color recipes");
    expect(state.selectedIndices).toEqual([0, 1, 2, 3, 4]);
    expect(state.manualSelectedIndices).toEqual([0, 1, 2, 3, 4]);
    expect(state.selectionSource).toBe("manual");
    expect(state.isLoading).toBe(false);
  });

  it("hides missing LUT backend details when a standard query fails", async () => {
    useFiveColorStore.setState({
      lutName: "stale-five-color",
      selectedIndices: [0, 1, 2, 3, 4],
      manualSelectedIndices: [0, 1, 2, 3, 4],
      selectionSource: "manual",
      queryResult: null,
    });
    mockQueryFiveColor.mockRejectedValueOnce(
      apiFailure(
        { detail: "LUT not found: stale-five-color" },
        "Request failed with status code 404",
        404,
      ),
    );

    await useFiveColorStore.getState().submitQuery();

    const state = useFiveColorStore.getState();
    expect(state.queryResult).toBeNull();
    expect(state.error).toBe(tRuntime("lut_error_missing_refresh"));
    expect(state.error).not.toMatch(/LUT not found/i);
    expect(state.selectedIndices).toEqual([0, 1, 2, 3, 4]);
    expect(state.manualSelectedIndices).toEqual([0, 1, 2, 3, 4]);
    expect(state.selectionSource).toBe("manual");
    expect(state.isLoading).toBe(false);
  });

  it("normalizes target-match state when a standard query succeeds after target matching", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [4, 3, 2, 1, 0],
      manualSelectedIndices: [4, 3, 2, 1, 0],
      selectionSource: "manual",
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
      target_rgb: [242, 10, 0],
      target_hex: "#F20A00",
      matched_rgb: [240, 10, 0],
      matched_hex: "#F00A00",
      delta_e: 1.25,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 2,
        row: 0,
        col: 1,
        display_row: 1,
        display_col: 2,
      }),
      neighborhood: [],
    });
    mockQueryFiveColor.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
    });

    await useFiveColorStore.getState().matchColorByHex("#F20A00");
    await useFiveColorStore.getState().submitQuery();
    useFiveColorStore.getState().removeLastSelection();

    const state = useFiveColorStore.getState();
    expect(state.selectedIndices).toEqual([0, 1, 2, 3]);
    expect(state.manualSelectedIndices).toEqual([0, 1, 2, 3]);
    expect(state.selectionSource).toBe("manual");
  });

  it("undoes the visible recipe after a target match", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [9, 8, 7, 6, 5],
      manualSelectedIndices: [9, 8, 7, 6, 5],
      selectionSource: "manual",
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
      target_rgb: [242, 10, 0],
      target_hex: "#F20A00",
      matched_rgb: [240, 10, 0],
      matched_hex: "#F00A00",
      delta_e: 1.25,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 2,
        row: 0,
        col: 1,
        display_row: 1,
        display_col: 2,
      }),
      neighborhood: [],
    });

    await useFiveColorStore.getState().matchColorByHex("#F20A00");
    useFiveColorStore.getState().removeLastSelection();

    const state = useFiveColorStore.getState();
    expect(state.selectedIndices).toEqual([0, 1, 2, 3]);
    expect(state.manualSelectedIndices).toEqual([0, 1, 2, 3]);
    expect(state.selectionSource).toBe("manual");
    expect(state.queryResult).toBeNull();
  });

  it("reverses the visible recipe after a target match", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [9, 8, 7, 6, 5],
      manualSelectedIndices: [9, 8, 7, 6, 5],
      selectionSource: "manual",
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
      target_rgb: [242, 10, 0],
      target_hex: "#F20A00",
      matched_rgb: [240, 10, 0],
      matched_hex: "#F00A00",
      delta_e: 1.25,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 2,
        row: 0,
        col: 1,
        display_row: 1,
        display_col: 2,
      }),
      neighborhood: [],
    });

    await useFiveColorStore.getState().matchColorByHex("#F20A00");
    useFiveColorStore.getState().reverseSelection();

    const state = useFiveColorStore.getState();
    expect(state.selectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.manualSelectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.selectionSource).toBe("manual");
    expect(state.queryResult).toBeNull();
  });

  it("persists target-match selections as the visible manual state", () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [0, 1, 2, 3, 4],
      manualSelectedIndices: [9, 8, 7, 6, 5],
      selectionSource: "target-match",
      queryResult: null,
    });

    const raw = window.localStorage.getItem("five-color-store");
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw ?? "{}").state;

    expect(persisted.selectedIndices).toEqual([0, 1, 2, 3, 4]);
    expect(persisted.manualSelectedIndices).toEqual([0, 1, 2, 3, 4]);
    expect(persisted.selectionSource).toBe("manual");
  });

  it("persists empty combination restrictions across reloads", () => {
    useFiveColorStore.setState({
      lutName: "restricted-lut",
      baseColors: [
        { index: 0, rgb: [255, 0, 0], name: "Red", hex: "#FF0000" },
        { index: 1, rgb: [0, 255, 0], name: "Green", hex: "#00FF00" },
        { index: 2, rgb: [0, 0, 255], name: "Blue", hex: "#0000FF" },
        { index: 3, rgb: [255, 255, 0], name: "Yellow", hex: "#FFFF00" },
        { index: 4, rgb: [255, 255, 255], name: "White", hex: "#FFFFFF" },
      ],
      combinations: [],
      selectedIndices: [],
      manualSelectedIndices: [],
      selectionSource: "manual",
    });

    const raw = window.localStorage.getItem("five-color-store");
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw ?? "{}").state;

    expect(persisted.combinations).toEqual([]);
  });

  it("restores manual fallback when a standard query returns no match after target matching", async () => {
    useFiveColorStore.setState({
      lutName: "test-lut",
      selectedIndices: [4, 3, 2, 1, 0],
      manualSelectedIndices: [4, 3, 2, 1, 0],
      selectionSource: "manual",
      queryResult: null,
    });
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
      target_rgb: [242, 10, 0],
      target_hex: "#F20A00",
      matched_rgb: [240, 10, 0],
      matched_hex: "#F00A00",
      delta_e: 1.25,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 2,
        row: 0,
        col: 1,
        display_row: 1,
        display_col: 2,
      }),
      neighborhood: [],
    });
    mockQueryFiveColor.mockResolvedValueOnce({
      found: false,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: null,
      result_hex: null,
      row_index: -1,
      message: "missing",
      source: "test",
    });

    await useFiveColorStore.getState().matchColorByHex("#F20A00");
    await useFiveColorStore.getState().submitQuery();

    const state = useFiveColorStore.getState();
    expect(state.queryResult?.found).toBe(false);
    expect(state.selectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.manualSelectedIndices).toEqual([4, 3, 2, 1, 0]);
    expect(state.selectionSource).toBe("manual");
  });
});
