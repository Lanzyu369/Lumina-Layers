import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LutDetailsResponse } from "../api/types";
import { filterLutDetailsCatalog, useLutDetailsStore } from "../stores/lutDetailsStore";

const mockFetchLutDetailsCatalog = vi.fn();
const mockFetchLutDetails = vi.fn();

vi.mock("../api/lut", () => ({
  fetchLutDetailsCatalog: (...args: unknown[]) => mockFetchLutDetailsCatalog(...args),
  fetchLutDetails: (...args: unknown[]) => mockFetchLutDetails(...args),
}));

const CATALOG = [
  {
    manufacturer: "Bambu Lab",
    items: [
      {
        name: "Bambu Lab - PLA - RYBW",
        path: "/fake/a.json",
        fingerprint: "fp-a",
        color_mode: "4-Color (RYBW)",
        source_kind: "legacy_lookup",
        manufacturer: "Bambu Lab",
        material_type: "PLA",
        manufacturer_source: "metadata",
        material_source: "folder",
        search_tokens: ["bambulab", "bam", "ba", "拓", "pla", "basic", "plabasic", "rybw"],
      },
    ],
  },
  {
    manufacturer: "Aliz",
    items: [
      {
        name: "Aliz - PETG - CMYW",
        path: "/fake/b.json",
        fingerprint: "fp-b",
        color_mode: "4-Color (CMYW)",
        source_kind: "legacy_lookup",
        manufacturer: "Aliz",
        material_type: "PETG",
        manufacturer_source: "folder",
        material_source: "folder",
        search_tokens: ["aliz", "petg", "cmyw"],
      },
    ],
  },
];

function buildDetail(
  name: string,
  fingerprint: string,
  path: string,
  overrides: Partial<LutDetailsResponse> = {},
): LutDetailsResponse {
  return {
    name,
    path,
    fingerprint,
    manufacturer: name.startsWith("Aliz") ? "Aliz" : "Bambu Lab",
    manufacturer_source: name.startsWith("Aliz") ? "folder" : "metadata",
    material_type: name.startsWith("Aliz") ? "PETG" : "PLA",
    material_source: "folder",
    color_mode: name.startsWith("Aliz") ? "4-Color (CMYW)" : "4-Color (RYBW)",
    color_count: 4,
    source_kind: "legacy_lookup",
    schema_version: "1.0",
    capabilities: ["legacy_lookup"],
    supported_modes: [],
    raw_metadata: {},
    palette: [],
    coverage_stats: {
      entry_count: 4,
      plotted_point_count: 4,
      l_range: { min: 0, max: 100 },
      a_range: { min: -40, max: 60 },
      b_range: { min: -50, max: 50 },
      r_range: { min: 0, max: 255 },
      g_range: { min: 0, max: 255 },
      b_rgb_range: { min: 0, max: 255 },
    },
    lab_points: [],
    lab_points_3d: [],
    lab_hull: [],
    rgb_points: [],
    max_color_layers: 5,
    layer_height_mm: 0.08,
    line_width_mm: 0.42,
    base_layers: 10,
    base_channel_idx: 0,
    layer_order: "Top2Bottom",
    ...overrides,
  };
}

const DETAIL_A = buildDetail("Bambu Lab - PLA - RYBW", "fp-a", "/fake/a.json");
const DETAIL_B = buildDetail("Aliz - PETG - CMYW", "fp-b", "/fake/b.json");

function makeAxiosLikeError(
  message: string,
  status: number,
  data: unknown,
): Error & { response: { status: number; data: unknown; headers: Record<string, string> } } {
  return Object.assign(new Error(message), {
    response: { status, data, headers: {} },
  });
}

function expectNoRawHttpError(error: string | null): void {
  expect(error).toBeTruthy();
  expect(error).not.toMatch(/Request failed/i);
  expect(error).not.toMatch(/status code\s+\d{3}/i);
}

beforeEach(() => {
  vi.clearAllMocks();
  useLutDetailsStore.setState({
    catalog: [],
    catalogLoading: false,
    selectedManufacturer: "",
    selectedLutName: "",
    loadedLutName: "",
    query: "",
    detail: null,
    detailLoading: false,
    error: null,
    errorKind: null,
    hasLoadedDetail: false,
    isSelectionDirty: false,
    canLoadSelectedLut: false,
  });
});

describe("filterLutDetailsCatalog", () => {
  it("matches alias prefixes and material terms with AND semantics", () => {
    const result = filterLutDetailsCatalog(CATALOG, "拓 pla", "");
    expect(result.manufacturers).toEqual(["Bambu Lab"]);
    expect(result.items.map((item) => item.name)).toEqual(["Bambu Lab - PLA - RYBW"]);
  });

  it("normalizes common spaced and hyphenated search inputs", () => {
    const result = filterLutDetailsCatalog(CATALOG, "Bambu-Lab PLA Basic", "");
    expect(result.manufacturers).toEqual(["Bambu Lab"]);
    expect(result.items.map((item) => item.name)).toEqual(["Bambu Lab - PLA - RYBW"]);
  });

  it("keeps all query-matching manufacturers visible even when one manufacturer is selected", () => {
    const result = filterLutDetailsCatalog(CATALOG, "", "Bambu Lab");
    expect(result.manufacturers).toEqual(["Bambu Lab", "Aliz"]);
    expect(result.items.map((item) => item.name)).toEqual(["Bambu Lab - PLA - RYBW"]);
  });
});

describe("useLutDetailsStore", () => {
  it("loads the catalog without automatically loading LUT details", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });

    await useLutDetailsStore.getState().fetchCatalog();

    const state = useLutDetailsStore.getState();
    expect(state.selectedManufacturer).toBe("");
    expect(state.selectedLutName).toBe("Bambu Lab - PLA - RYBW");
    expect(state.loadedLutName).toBe("");
    expect(state.detail).toBeNull();
    expect(state.hasLoadedDetail).toBe(false);
    expect(state.isSelectionDirty).toBe(false);
    expect(state.canLoadSelectedLut).toBe(true);
    expect(mockFetchLutDetails).not.toHaveBeenCalled();
  });

  it("updates the pending LUT selection when filters change without requesting detail", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });

    await useLutDetailsStore.getState().fetchCatalog();
    useLutDetailsStore.getState().setQuery("aliz");

    const state = useLutDetailsStore.getState();
    expect(state.selectedManufacturer).toBe("");
    expect(state.selectedLutName).toBe("Aliz - PETG - CMYW");
    expect(state.loadedLutName).toBe("");
    expect(state.detail).toBeNull();
    expect(state.canLoadSelectedLut).toBe(true);
    expect(mockFetchLutDetails).not.toHaveBeenCalled();
  });

  it("loads detail only when loadSelectedLut is called", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });
    mockFetchLutDetails.mockResolvedValue(DETAIL_A);

    await useLutDetailsStore.getState().fetchCatalog();
    await useLutDetailsStore.getState().loadSelectedLut();

    const state = useLutDetailsStore.getState();
    expect(mockFetchLutDetails).toHaveBeenCalledWith("Bambu Lab - PLA - RYBW");
    expect(state.loadedLutName).toBe("Bambu Lab - PLA - RYBW");
    expect(state.detail?.fingerprint).toBe("fp-a");
    expect(state.hasLoadedDetail).toBe(true);
    expect(state.isSelectionDirty).toBe(false);
    expect(state.canLoadSelectedLut).toBe(true);
  });

  it("keeps the currently loaded detail visible while a different LUT is selected", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });
    mockFetchLutDetails.mockResolvedValue(DETAIL_A);

    await useLutDetailsStore.getState().fetchCatalog();
    await useLutDetailsStore.getState().loadSelectedLut();

    useLutDetailsStore.getState().selectLut("Aliz - PETG - CMYW");

    const state = useLutDetailsStore.getState();
    expect(state.selectedLutName).toBe("Aliz - PETG - CMYW");
    expect(state.loadedLutName).toBe("Bambu Lab - PLA - RYBW");
    expect(state.detail?.name).toBe("Bambu Lab - PLA - RYBW");
    expect(state.hasLoadedDetail).toBe(true);
    expect(state.isSelectionDirty).toBe(true);
    expect(state.detailLoading).toBe(false);
    expect(mockFetchLutDetails).toHaveBeenCalledTimes(1);
  });

  it("replaces the loaded detail only after the newly selected LUT finishes loading", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });
    mockFetchLutDetails
      .mockResolvedValueOnce(DETAIL_A)
      .mockResolvedValueOnce(DETAIL_B);

    await useLutDetailsStore.getState().fetchCatalog();
    await useLutDetailsStore.getState().loadSelectedLut();
    useLutDetailsStore.getState().selectLut("Aliz - PETG - CMYW");

    const pendingPromise = useLutDetailsStore.getState().loadSelectedLut();
    expect(useLutDetailsStore.getState().detail?.name).toBe("Bambu Lab - PLA - RYBW");
    expect(useLutDetailsStore.getState().detailLoading).toBe(true);

    await pendingPromise;

    const state = useLutDetailsStore.getState();
    expect(state.loadedLutName).toBe("Aliz - PETG - CMYW");
    expect(state.detail?.name).toBe("Aliz - PETG - CMYW");
    expect(state.isSelectionDirty).toBe(false);
  });

  it("keeps the old loaded detail when loading the new selection fails", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });
    mockFetchLutDetails
      .mockResolvedValueOnce(DETAIL_A)
      .mockRejectedValueOnce(new Error("detail failed"));

    await useLutDetailsStore.getState().fetchCatalog();
    await useLutDetailsStore.getState().loadSelectedLut();
    useLutDetailsStore.getState().selectLut("Aliz - PETG - CMYW");
    await useLutDetailsStore.getState().loadSelectedLut();

    const state = useLutDetailsStore.getState();
    expect(state.loadedLutName).toBe("Bambu Lab - PLA - RYBW");
    expect(state.detail?.name).toBe("Bambu Lab - PLA - RYBW");
    expect(state.error).toBe("detail failed");
    expect(state.errorKind).toBe("detail");
    expect(state.isSelectionDirty).toBe(true);
  });

  it("uses readable backend detail when a LUT detail request fails", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });
    mockFetchLutDetails
      .mockResolvedValueOnce(DETAIL_A)
      .mockRejectedValueOnce(makeAxiosLikeError(
        "Request failed with status code 404",
        404,
        { detail: "LUT not found: stale" },
      ));

    await useLutDetailsStore.getState().fetchCatalog();
    await useLutDetailsStore.getState().loadSelectedLut();
    useLutDetailsStore.getState().selectLut("Aliz - PETG - CMYW");
    await useLutDetailsStore.getState().loadSelectedLut();

    const state = useLutDetailsStore.getState();
    expect(state.error).toBe("LUT not found: stale");
    expectNoRawHttpError(state.error);
    expect(state.errorKind).toBe("detail");
    expect(state.loadedLutName).toBe("Bambu Lab - PLA - RYBW");
  });

  it("normalizes generic network failures for LUT detail requests", async () => {
    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });
    mockFetchLutDetails.mockRejectedValueOnce(new Error("Network Error"));

    await useLutDetailsStore.getState().fetchCatalog();
    await useLutDetailsStore.getState().loadSelectedLut();

    const state = useLutDetailsStore.getState();
    expectNoRawHttpError(state.error);
    expect(state.error).not.toBe("Network Error");
    expect(state.error).not.toBe("lut_details_error_load_detail");
    expect(state.errorKind).toBe("detail");
  });

  it("refreshes the loaded detail when the catalog refresh changes the same-name fingerprint", async () => {
    useLutDetailsStore.setState({
      catalog: CATALOG,
      selectedManufacturer: "",
      selectedLutName: "Bambu Lab - PLA - RYBW",
      loadedLutName: "Bambu Lab - PLA - RYBW",
      query: "",
      detail: buildDetail("Bambu Lab - PLA - RYBW", "fp-old", "/fake/a.json", {
        raw_metadata: { request: "old" },
      }),
      detailLoading: false,
      error: null,
      errorKind: null,
      catalogLoading: false,
      hasLoadedDetail: true,
      isSelectionDirty: false,
      canLoadSelectedLut: true,
    });

    mockFetchLutDetailsCatalog.mockResolvedValueOnce({
      groups: [
        {
          manufacturer: "Bambu Lab",
          items: [
            {
              name: "Bambu Lab - PLA - RYBW",
              path: "/fake/a-v2.json",
              fingerprint: "fp-new",
              color_mode: "4-Color (RYBW)",
              source_kind: "legacy_lookup",
              manufacturer: "Bambu Lab",
              material_type: "PLA",
              manufacturer_source: "metadata",
              material_source: "folder",
              search_tokens: ["bambulab", "pla", "rybw"],
            },
          ],
        },
      ],
    });
    mockFetchLutDetails.mockResolvedValueOnce(
      buildDetail("Bambu Lab - PLA - RYBW", "fp-new", "/fake/a-v2.json", {
        raw_metadata: { request: "new" },
      }),
    );

    await useLutDetailsStore.getState().fetchCatalog();

    const state = useLutDetailsStore.getState();
    expect(mockFetchLutDetails).toHaveBeenCalledWith("Bambu Lab - PLA - RYBW");
    expect(state.detail?.fingerprint).toBe("fp-new");
    expect(state.detail?.raw_metadata).toEqual({ request: "new" });
    expect(state.loadedLutName).toBe("Bambu Lab - PLA - RYBW");
  });

  it("clears the loaded detail when the catalog refresh removes the loaded LUT", async () => {
    useLutDetailsStore.setState({
      catalog: CATALOG,
      selectedManufacturer: "",
      selectedLutName: "Bambu Lab - PLA - RYBW",
      loadedLutName: "Bambu Lab - PLA - RYBW",
      query: "",
      detail: DETAIL_A,
      detailLoading: false,
      error: null,
      errorKind: null,
      catalogLoading: false,
      hasLoadedDetail: true,
      isSelectionDirty: false,
      canLoadSelectedLut: true,
    });

    mockFetchLutDetailsCatalog.mockResolvedValueOnce({
      groups: [
        {
          manufacturer: "Aliz",
          items: [
            {
              name: "Aliz - PETG - CMYW",
              path: "/fake/b.json",
              fingerprint: "fp-b",
              color_mode: "4-Color (CMYW)",
              source_kind: "legacy_lookup",
              manufacturer: "Aliz",
              material_type: "PETG",
              manufacturer_source: "folder",
              material_source: "folder",
              search_tokens: ["aliz", "petg", "cmyw"],
            },
          ],
        },
      ],
    });

    await useLutDetailsStore.getState().fetchCatalog();

    const state = useLutDetailsStore.getState();
    expect(mockFetchLutDetails).not.toHaveBeenCalled();
    expect(state.selectedLutName).toBe("Aliz - PETG - CMYW");
    expect(state.loadedLutName).toBe("");
    expect(state.detail).toBeNull();
    expect(state.hasLoadedDetail).toBe(false);
    expect(state.isSelectionDirty).toBe(false);
    expect(state.canLoadSelectedLut).toBe(true);
  });

  it("stores fallback translation keys for non-Error failures and clears them", async () => {
    mockFetchLutDetailsCatalog.mockRejectedValueOnce("boom");

    await useLutDetailsStore.getState().fetchCatalog();
    expect(useLutDetailsStore.getState().error).toBe("lut_details_error_load_catalog");
    expect(useLutDetailsStore.getState().errorKind).toBe("catalog");

    useLutDetailsStore.getState().clearError();
    expect(useLutDetailsStore.getState().error).toBeNull();
    expect(useLutDetailsStore.getState().errorKind).toBeNull();

    mockFetchLutDetailsCatalog.mockResolvedValue({ groups: CATALOG });
    mockFetchLutDetails.mockRejectedValueOnce("boom");

    await useLutDetailsStore.getState().fetchCatalog();
    await useLutDetailsStore.getState().loadSelectedLut();

    expect(useLutDetailsStore.getState().error).toBe("lut_details_error_load_detail");
    expect(useLutDetailsStore.getState().errorKind).toBe("detail");
  });
});
