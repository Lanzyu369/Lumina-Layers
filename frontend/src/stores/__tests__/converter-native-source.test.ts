import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_STATE,
  resolveConverterSourceSelection,
  useConverterStore,
} from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import * as lutApi from "../../api/lut";
import { ColorMode, ModelingMode, StructureMode } from "../../api/types";

const mocks = vi.hoisted(() => ({
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  convertGenerateLargeFormat: vi.fn(),
  convertGeneratePuzzle: vi.fn(),
  applyRecipeOverride: vi.fn(),
  getGlbStatus: vi.fn(),
}));

vi.mock("../../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../../api/converter")>(
    "../../api/converter",
  );
  return {
    ...actual,
    convertPreview: mocks.convertPreview,
    convertGenerate: mocks.convertGenerate,
    convertGenerateLargeFormat: mocks.convertGenerateLargeFormat,
    convertGeneratePuzzle: mocks.convertGeneratePuzzle,
    applyRecipeOverride: mocks.applyRecipeOverride,
    getGlbStatus: mocks.getGlbStatus,
  };
});

vi.mock("../../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../../api/lut")>(
    "../../api/lut",
  );
  return {
    ...actual,
    fetchLutInfo: vi.fn(),
    fetchLutCatalog: vi.fn(),
    fetchLutDetailsCatalog: vi.fn(),
  };
});

function resetStore(): void {
  useConverterStore.setState({
    ...DEFAULT_STATE,
    source_version: "legacy",
    lut_name: "",
    nativeBrandGroups: [],
    nativeBrandGroupsLoading: false,
    selectedNativeBrandKey: "",
    selectedNativeDbNames: [],
    legacyCatalogGroups: [],
    legacyCatalogLoading: false,
    selectedLegacyManufacturer: "",
  });
}

function makeDbOption(name: string) {
  return {
    name,
    path: `/${name}.json`,
    color_mode: "8-Color Max",
    fingerprint: `fp-${name}`,
  };
}

function makePredictiveBrand() {
  return {
    brand_key: "brand-a",
    material_type: "PLA",
    vendor: "Vendor A",
    display_name: "Brand A",
    db_options: [makeDbOption("A1"), makeDbOption("A2")],
    default_db_names: ["A2"],
    package_name: "brand-a-package",
    model_name: "brand-a-model",
    supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
  };
}

function makeNonPredictiveBrand() {
  return {
    brand_key: "brand-b",
    material_type: "PLA",
    vendor: "Vendor B",
    display_name: "Vendor B PLA",
    db_options: [
      { name: "DB-B1", path: "/db-b1.json", color_mode: "4-Color (RYBW)", fingerprint: "fp-b1" },
    ],
    default_db_names: ["DB-B1"],
    supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
  };
}

function makeLegacyDetailsCatalog() {
  return {
    groups: [
      {
        manufacturer: "Brand A",
        items: [
          {
            name: "legacy-a",
            path: "/legacy-a.npy",
            fingerprint: "fp-a",
            color_mode: ColorMode.FOUR_COLOR_RYBW,
            source_kind: "legacy_lookup",
            manufacturer: "Brand A",
            material_type: "",
            manufacturer_source: "metadata",
            material_source: "metadata",
            search_tokens: ["legacy", "a"],
          },
        ],
      },
      {
        manufacturer: "Brand B",
        items: [
          {
            name: "legacy-b",
            path: "/legacy-b.npy",
            fingerprint: "fp-b",
            color_mode: ColorMode.EIGHT_COLOR,
            source_kind: "legacy_lookup",
            manufacturer: "Brand B",
            material_type: "",
            manufacturer_source: "metadata",
            material_source: "metadata",
            search_tokens: ["legacy", "b"],
          },
        ],
      },
    ],
  };
}

function flushGlbPoll(timerStep = 600): Promise<void> {
  vi.advanceTimersByTime(timerStep);
  return Promise.resolve().then(() => Promise.resolve());
}

describe("native bundle converter flow", () => {
  beforeEach(() => {
    resetStore();
    mocks.convertPreview.mockReset();
    mocks.convertGenerate.mockReset();
    mocks.convertGenerateLargeFormat.mockReset();
    mocks.convertGeneratePuzzle.mockReset();
    mocks.applyRecipeOverride.mockReset();
    mocks.getGlbStatus.mockReset();
  });

  it("resets selected DBs to the brand defaults when the brand changes", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [
        makePredictiveBrand(),
        {
          brand_key: "brand-b",
          material_type: "PLA",
          vendor: "Vendor B",
          display_name: "Brand B",
          db_options: [makeDbOption("B1"), makeDbOption("B2"), makeDbOption("B3")],
          default_db_names: ["B1", "B3"],
          supported_modes: [{ color_layers: 8, layer_height_mm: 0.12 }],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
    } as never);

    useConverterStore.getState().setNativeBrandKey("brand-b");

    const state = useConverterStore.getState();
    expect(state.selectedNativeBrandKey).toBe("brand-b");
    expect(state.selectedNativeDbNames).toEqual(["B1", "B3"]);
    expect(state.color_layers).toBe(8);
    expect(state.layer_height_mm).toBe(0.12);
  });

  it("resolves legacy and native source readiness in one place", () => {
    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "legacy-lut",
    });
    expect(resolveConverterSourceSelection(useConverterStore.getState()).isReady).toBe(true);

    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          default_db_names: [],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: [],
    } as never);
    expect(resolveConverterSourceSelection(useConverterStore.getState()).isReady).toBe(false);

    useConverterStore.setState({ selectedNativeDbNames: ["A2"] } as never);
    expect(resolveConverterSourceSelection(useConverterStore.getState()).isReady).toBe(true);
  });

  it("falls back to brand defaults when persisted native DB names are all invalid", () => {
    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["STALE-DB"],
    } as never);

    const selection = resolveConverterSourceSelection(useConverterStore.getState());

    expect(selection.native.db_names).toEqual(["A2"]);
    expect(selection.isReady).toBe(true);
  });

  it("preserves an explicitly cleared native DB selection", () => {
    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: [],
    } as never);

    const selection = resolveConverterSourceSelection(useConverterStore.getState());

    expect(selection.native.db_names).toEqual([]);
    expect(selection.isReady).toBe(false);
  });

  it("defaults model controls when switching to a predictive native source", () => {
    useConverterStore.setState({
      source_version: "legacy",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
    } as never);

    useConverterStore.getState().setSourceVersion("native");

    const state = useConverterStore.getState();
    expect(state.source_version).toBe("native");
    expect(state.model_enable).toBe(true);
    expect(state.model_only).toBe(false);
    expect(state.model_threshold).toBeNull();
    expect(state.model_margin).toBeNull();
  });

  it("clears isGenerating and stores warnings after large-format generate", async () => {
    mocks.convertGenerateLargeFormat.mockResolvedValue({
      status: "ok",
      message: "Generated 4 tiles",
      download_url: "/api/files/lf-zip",
      tile_count: 4,
      grid_cols: 2,
      grid_rows: 2,
      warnings: ["Raster fallback was used for this large-format SVG request."],
    });

    useConverterStore.setState({
      ...DEFAULT_STATE,
      source_version: "native",
      lut_name: "",
      sessionId: "session-large",
      largeFormatEnabled: true,
      isGenerating: false,
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      nativeBrandGroups: [makePredictiveBrand()],
      model_threshold: 0.42,
      model_margin: 1.25,
      model_enable: true,
      model_only: false,
    } as never);

    await useConverterStore.getState().submitGenerate();

    const state = useConverterStore.getState();
    expect(mocks.convertGenerateLargeFormat).toHaveBeenCalledOnce();
    const [, request] = mocks.convertGenerateLargeFormat.mock.calls[0];
    expect(request.target_height_mm).toBeUndefined();
    expect(request.params.model_threshold).toBe(0.42);
    expect(request.params.model_margin).toBe(1.25);
    expect(state.isGenerating).toBe(false);
    expect(state.downloadUrl).toBe("/api/files/lf-zip");
    expect(state.largeFormatWarnings).toEqual([
      "Raster fallback was used for this large-format SVG request.",
    ]);
  });

  it("submitGenerate omits recipe_overrides when local override state is empty", async () => {
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/legacy-model",
      preview_3d_url: "/api/files/legacy-model.glb",
    });

    useConverterStore.setState({
      ...DEFAULT_STATE,
      source_version: "legacy",
      lut_name: "legacy-lut",
      sessionId: "session-legacy",
      recipe_overrides: [],
    } as never);

    await useConverterStore.getState().submitGenerate();

    const [, params] = mocks.convertGenerate.mock.calls.at(-1)!;
    expect(params.recipe_overrides).toBeUndefined();
  });

  it("defaults native layer count to 5 when entering native mode without a valid current selection", () => {
    useConverterStore.setState({
      source_version: "legacy",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: null,
      layer_height_mm: null,
    } as never);

    useConverterStore.getState().setSourceVersion("native");

    const state = useConverterStore.getState();
    expect(state.source_version).toBe("native");
    expect(state.color_layers).toBe(5);
    expect(state.layer_height_mm).toBe(0.08);
  });

  it("prefers 5 layers when entering native mode with an invalid current pair and 5L is available", () => {
    useConverterStore.setState({
      source_version: "legacy",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: 8,
      layer_height_mm: 0.08,
    } as never);

    useConverterStore.getState().setSourceVersion("native");

    const state = useConverterStore.getState();
    expect(state.color_layers).toBe(5);
    expect(state.layer_height_mm).toBe(0.08);
  });

  it("preserves a valid native selection when switching brands", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
        {
          brand_key: "brand-b",
          material_type: "PLA",
          vendor: "Vendor B",
          display_name: "Brand B",
          db_options: [makeDbOption("B1"), makeDbOption("B2")],
          default_db_names: ["B1"],
          supported_modes: [
            { color_layers: 8, layer_height_mm: 0.12 },
            { color_layers: 12, layer_height_mm: 0.12 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: 8,
      layer_height_mm: 0.12,
    } as never);

    useConverterStore.getState().setNativeBrandKey("brand-b");

    const state = useConverterStore.getState();
    expect(state.selectedNativeBrandKey).toBe("brand-b");
    expect(state.selectedNativeDbNames).toEqual(["B1"]);
    expect(state.color_layers).toBe(8);
    expect(state.layer_height_mm).toBe(0.12);
  });

  it("prefers 5 layers on brand switch when the current pair is invalid and 5L is available", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
        {
          brand_key: "brand-b",
          material_type: "PLA",
          vendor: "Vendor B",
          display_name: "Brand B",
          db_options: [makeDbOption("B1")],
          default_db_names: ["B1"],
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.08 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: 8,
      layer_height_mm: 0.12,
    } as never);

    useConverterStore.getState().setNativeBrandKey("brand-b");

    const state = useConverterStore.getState();
    expect(state.selectedNativeBrandKey).toBe("brand-b");
    expect(state.color_layers).toBe(5);
    expect(state.layer_height_mm).toBe(0.08);
  });

  it("normalizes native mode selection to a supported pair", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: 8,
      layer_height_mm: 0.08,
    } as never);

    const resolved = resolveConverterSourceSelection(useConverterStore.getState());
    expect(resolved.native?.supported_mode).toEqual({
      color_layers: 5,
      layer_height_mm: 0.08,
    });
    expect(resolved.color_layers).toBe(5);
    expect(resolved.layer_height_mm).toBe(0.08);
  });

  it("clears native dynamic values immediately when switching back to legacy LUTs", () => {
    vi.mocked(lutApi.fetchLutInfo).mockResolvedValueOnce({
      name: "legacy-lut",
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      color_count: 4,
    } as never);

    useConverterStore.setState({
      source_version: "native",
      color_layers: 8,
      layer_height_mm: 0.12,
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [{ color_layers: 8, layer_height_mm: 0.12 }],
        },
      ],
    } as never);

    useConverterStore.getState().setLutName("legacy-lut");

    const state = useConverterStore.getState();
    expect(state.source_version).toBe("legacy");
    expect(state.color_layers).toBeNull();
    expect(state.layer_height_mm).toBeNull();
    expect(state.selectedNativeBrandKey).toBe("");
    expect(state.selectedNativeDbNames).toEqual([]);
    expect(state.model_enable).toBe(false);
    expect(state.model_only).toBe(false);
    expect(state.model_threshold).toBeNull();
    expect(state.model_margin).toBeNull();
  });

  it("normalizes legacy 8-Color LUT info before storing state and sending requests", async () => {
    vi.mocked(lutApi.fetchLutInfo).mockResolvedValueOnce({
      name: "legacy-eight",
      color_mode: "8-Color",
      color_count: 8,
    } as never);
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-eight",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/eight-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/eight-model",
      preview_3d_url: "/api/files/eight-model.glb",
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "legacy-eight.png", { type: "image/png" }),
      source_version: "legacy",
      lutListFull: [
        {
          name: "legacy-eight",
          color_mode: "8-Color",
          path: "/legacy-eight.npy",
          fingerprint: "fp-eight",
        },
      ],
      target_width_mm: 90,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
    } as never);

    useConverterStore.getState().setLutName("legacy-eight");
    await Promise.resolve();

    expect(useConverterStore.getState().color_mode).toBe(ColorMode.EIGHT_COLOR);

    await useConverterStore.getState().submitPreview();
    const previewParams = mocks.convertPreview.mock.calls[0][1];
    expect(previewParams.color_mode).toBe(ColorMode.EIGHT_COLOR);

    await useConverterStore.getState().submitGenerate();
    const generateParams = mocks.convertGenerate.mock.calls[0][1];
    expect(generateParams.color_mode).toBe(ColorMode.EIGHT_COLOR);
  });

  it("hydrates the legacy LUT list from the catalog response", async () => {
    vi.mocked(lutApi.fetchLutCatalog).mockResolvedValueOnce({
      legacy_groups: [
        {
          group_name: "Preset",
          items: [
            { name: "legacy-a", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/a.npy", fingerprint: "fp-a" },
          ],
        },
        {
          group_name: "ReferenceDB",
          items: [
            { name: "legacy-b", color_mode: ColorMode.BW, path: "/b.npy", fingerprint: "fp-b" },
          ],
        },
      ],
      native_brand_groups: [],
    });

    await useConverterStore.getState().fetchLutCatalog();

    expect(useConverterStore.getState().lutList).toEqual(["legacy-a", "legacy-b"]);
    expect(useConverterStore.getState().lutListFull).toHaveLength(2);
  });

  it("fetches the legacy details catalog into converter state", async () => {
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValueOnce(
      makeLegacyDetailsCatalog(),
    );

    await useConverterStore.getState().fetchLegacyCatalog();

    expect(lutApi.fetchLutDetailsCatalog).toHaveBeenCalledOnce();
    expect(useConverterStore.getState().legacyCatalogGroups).toHaveLength(2);
    expect(useConverterStore.getState().legacyCatalogLoading).toBe(false);
  });

  it("hydrates selectedLegacyManufacturer from a remembered lut_name", async () => {
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValueOnce(
      makeLegacyDetailsCatalog(),
    );
    useConverterStore.setState({
      lut_name: "legacy-b",
      lutListFull: [
        {
          name: "legacy-b",
          color_mode: ColorMode.EIGHT_COLOR,
          path: "/legacy-b.npy",
          fingerprint: "legacy-b-fp",
        },
      ],
    });

    await useConverterStore.getState().fetchLegacyCatalog();

    expect(useConverterStore.getState().selectedLegacyManufacturer)
      .toBe("Brand B");
  });

  it("clears legacy lut_name when switching to a manufacturer that does not contain it", () => {
    useConverterStore.setState({
      legacyCatalogGroups: makeLegacyDetailsCatalog().groups,
      selectedLegacyManufacturer: "Brand A",
      lut_name: "legacy-a",
      lutListFull: [
        {
          name: "legacy-a",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          path: "/legacy-a.npy",
        },
      ],
    } as never);

    useConverterStore.getState().setLegacyManufacturer("Brand B");

    expect(useConverterStore.getState().selectedLegacyManufacturer)
      .toBe("Brand B");
    expect(useConverterStore.getState().lut_name).toBe("");
  });

  it("filters the native catalog down to the BambuLab PLA brand", async () => {
    vi.mocked(lutApi.fetchLutCatalog).mockResolvedValueOnce({
      legacy_groups: [],
      native_brand_groups: [
        {
          brand_key: "bambulab_pla",
          material_type: "PLA",
          vendor: "Bambu Lab",
          display_name: "Bambu PLA",
          db_options: [
            { ...makeDbOption("B1"), color_mode: "8-Color" },
            makeDbOption("B2"),
          ],
          default_db_names: ["B1"],
          package_name: "bambu-pla-package",
          model_name: "bambu-pla-model",
          supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
        },
        makePredictiveBrand(),
        makeNonPredictiveBrand(),
      ],
    });

    await useConverterStore.getState().fetchLutCatalog();

    expect(useConverterStore.getState().nativeBrandGroups).toHaveLength(1);
    expect(useConverterStore.getState().nativeBrandGroups[0].brand_key).toBe("bambulab_pla");
    expect(useConverterStore.getState().nativeBrandGroups[0].display_name).toBe("Bambu PLA");
    expect(useConverterStore.getState().nativeBrandGroups[0].db_options[0].color_mode).toBe(
      ColorMode.EIGHT_COLOR,
    );
  });

  it("submitPreview sends native bundle fields instead of lut_name", async () => {
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-native",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/native-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "native.png", { type: "image/png" }),
      source_version: "native",
      lut_name: "",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      color_layers: 5,
      layer_height_mm: 0.08,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      model_only: false,
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      largeFormatEnabled: true,
      nativeBrandGroups: [
        makePredictiveBrand(),
      ],
    } as never);

    useConverterStore.getState().setModelEnable(true);
    useConverterStore.getState().setModelThreshold(6.5);
    useConverterStore.getState().setModelMargin(0.9);

    await useConverterStore.getState().submitPreview();

    expect(mocks.convertPreview).toHaveBeenCalledOnce();
    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params).toMatchObject({
      source_kind: "native_bundle",
      material_type: "PLA",
      vendor: "Vendor A",
      db_names: ["A2"],
      color_layers: 5,
      layer_height_mm: 0.08,
      model_enable: true,
      model_only: false,
      model_threshold: 6.5,
      model_margin: 0.9,
      target_width_mm: 90,
      large_format_enabled: true,
    });
    expect(params).not.toHaveProperty("lut_name");
    expect(useConverterStore.getState().sessionId).toBe("session-native");
  });

  it("polls async preview GLB after preview returns no GLB URL", async () => {
    vi.useFakeTimers();
    try {
      mocks.convertPreview.mockResolvedValueOnce({
        session_id: "session-preview-async",
        status: "ok",
        message: "Preview generated",
        preview_url: "/api/files/native-preview",
        preview_glb_url: null,
        palette: [],
        dimensions: { width: 200, height: 160 },
      });
      mocks.getGlbStatus.mockResolvedValueOnce({
        session_id: "session-preview-async",
        status: "ready",
        glb_url: "/api/files/preview-ready.glb",
        job_token: "token-preview",
        error: null,
        color_contours: {
          ff0000: [[[0, 0], [1, 0], [1, 1]]],
        },
      });

      useConverterStore.setState({
        imageFile: new File(["png"], "native.png", { type: "image/png" }),
        source_version: "native",
        lut_name: "",
        target_width_mm: 90,
        color_mode: ColorMode.FOUR_COLOR_RYBW,
        modeling_mode: ModelingMode.HIGH_FIDELITY,
        color_layers: 5,
        layer_height_mm: 0.08,
        quantize_colors: 48,
        enable_cleanup: true,
        hue_enable: false,
        selectedNativeBrandKey: "brand-a",
        selectedNativeDbNames: ["A2"],
        nativeBrandGroups: [makePredictiveBrand()],
      } as never);

      await useConverterStore.getState().submitPreview();
      await flushGlbPoll();
      await flushGlbPoll(0);

      expect(mocks.getGlbStatus).toHaveBeenCalledWith("session-preview-async");
      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/preview-ready.glb",
      );
      expect(useConverterStore.getState().colorContours).toEqual({
        ff0000: [[[0, 0], [1, 0], [1, 1]]],
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("submitPreview omits model fields for non-predictive native brands", async () => {
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-native",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/native-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "native.png", { type: "image/png" }),
      source_version: "native",
      lut_name: "",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      color_layers: 5,
      layer_height_mm: 0.08,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      selectedNativeBrandKey: "brand-b",
      selectedNativeDbNames: ["DB-B1"],
      nativeBrandGroups: [makeNonPredictiveBrand()],
      model_enable: true,
      model_only: true,
    } as never);

    await useConverterStore.getState().submitPreview();

    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params).toMatchObject({
      source_kind: "native_bundle",
      material_type: "PLA",
      vendor: "Vendor B",
      db_names: ["DB-B1"],
    });
    expect(params).not.toHaveProperty("model_enable");
    expect(params).not.toHaveProperty("model_only");
    expect(params).not.toHaveProperty("model_threshold");
    expect(params).not.toHaveProperty("model_margin");
  });

  it("submitGenerate sends native bundle fields in the JSON body", async () => {
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/native-model",
      preview_3d_url: "/api/files/native-model.glb",
    });

    useConverterStore.setState({
      sessionId: "session-native",
      source_version: "native",
      lut_name: "",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      nativeBrandGroups: [
        makePredictiveBrand(),
      ],
    } as never);

    useConverterStore.getState().setModelEnable(true);
    useConverterStore.getState().setModelOnly(false);
    useConverterStore.getState().setModelThreshold(6.5);
    useConverterStore.getState().setModelMargin(0.9);

    const result = await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    const [, params] = mocks.convertGenerate.mock.calls[0];
    expect(params).toMatchObject({
      source_kind: "native_bundle",
      material_type: "PLA",
      vendor: "Vendor A",
      db_names: ["A2"],
      color_layers: 5,
      layer_height_mm: 0.08,
      model_enable: true,
      model_only: false,
      target_width_mm: 90,
    });
    expect(params).not.toHaveProperty("lut_name");
    expect(result).toBe("/api/files/native-model.glb");
  });

  it("submitGenerate uses the puzzle endpoint when puzzle mode is enabled", async () => {
    mocks.convertGeneratePuzzle.mockResolvedValueOnce({
      status: "ok",
      message: "Generated puzzle",
      download_url: "/api/files/puzzle-model",
      threemf_disk_path: "E:/tmp/puzzle.3mf",
      piece_count: 6,
      grid_cols: 3,
      grid_rows: 2,
      warnings: [],
    });

    useConverterStore.setState({
      sessionId: "session-puzzle",
      source_version: "legacy",
      lut_name: "legacy-lut",
      target_width_mm: 90,
      target_height_mm: 60,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
      puzzleEnabled: true,
      puzzleStyle: "regular",
      puzzleSizingMode: "grid",
      pieceWidthMm: 20,
      pieceHeightMm: 20,
      puzzleRows: 2,
      puzzleCols: 3,
      targetPieceCount: 6,
      connectorStyle: "classic",
      labelsEnabled: true,
      engraveBackLabels: false,
      irregularityStrength: 0.35,
      minNeckWidthMm: 1.2,
    } as never);
    useSettingsStore.setState({
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
    } as never);

    const result = await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGeneratePuzzle).toHaveBeenCalledOnce();
    expect(mocks.convertGenerate).not.toHaveBeenCalled();
    const [, params] = mocks.convertGeneratePuzzle.mock.calls[0];
    expect(params).toMatchObject({
      target_height_mm: 60,
      puzzle_style: "regular",
      sizing_mode: "grid",
      rows: 2,
      cols: 3,
      target_piece_count: 6,
    });
    expect(params.params).toMatchObject({
      lut_name: "legacy-lut",
      target_width_mm: 90,
      device_profile_id: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
    });
    expect(result).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBe("/api/files/puzzle-model");
  });

  it("submitGenerate forwards fridge magnet fields to the backend payload", async () => {
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/fridge-model",
      preview_3d_url: "/api/files/fridge-model.glb",
    });

    useConverterStore.setState({
      sessionId: "session-fridge",
      source_version: "legacy",
      lut_name: "legacy-lut",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      spacer_thick: 1.2,
      structure_mode: StructureMode.SINGLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
      enable_fridge_magnet: true,
      fridge_magnets: [
        {
          id: "magnet-1",
          shape: "round",
          preset_key: "round-d12x3",
          diameter_mm: 12,
          width_mm: null,
          height_mm: null,
          thickness_mm: 3,
          center_x_mm: 12,
          center_y_mm: 18,
        },
      ],
    } as never);

    await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    const [, params] = mocks.convertGenerate.mock.calls[0];
    expect(params).toMatchObject({
      enable_fridge_magnet: true,
      fridge_magnets: [
        {
          id: "magnet-1",
          shape: "round",
          diameter_mm: 12,
          thickness_mm: 3,
        },
      ],
    });
  });

  it("changing native source selection invalidates stale preview session state", () => {
    useConverterStore.setState({
      source_version: "native",
      sessionId: "session-stale",
      previewImageUrl: "/api/files/preview",
      originalPreviewUrl: "/api/files/preview",
      previewBaseImageUrl: "/api/files/base",
      previewGlbUrl: "/api/files/model.glb",
      threemfDiskPath: "E:/tmp/model.3mf",
      downloadUrl: "/api/files/model.3mf",
      palette: [{ quantized_hex: "ffffff", matched_hex: "ffffff", pixel_count: 1, percentage: 100 }],
      recipe_overrides: [{ region_id: "region-1", recipe: [1, 2, 3, 4, 5], layer_order: "Top2Bottom" }],
      nativeBrandGroups: [makePredictiveBrand(), makeNonPredictiveBrand()],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      imageFile: new File(["png"], "native.png", { type: "image/png" }),
      hasManualPreview: true,
    } as never);

    useConverterStore.getState().setNativeBrandKey("brand-b");

    const state = useConverterStore.getState();
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.recipe_overrides).toEqual([]);
    expect(state.hasManualPreview).toBe(false);
  });

  it("applyCustomRecipeOverride works for native sources without lut_name", async () => {
    mocks.applyRecipeOverride.mockResolvedValueOnce({
      status: "ok",
      message: "Recipe override applied",
      preview_url: "/api/files/recipe-preview",
      preview_glb_url: "/api/files/recipe-preview.glb",
      rgb: [255, 255, 255],
      lab: [100, 0, 0],
      source: "stage_model",
      runtime_mode_key: "0.08x5",
      override_count: 1,
    });

    useConverterStore.setState({
      sessionId: "session-native",
      source_version: "native",
      lut_name: "",
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      nativeBrandGroups: [makePredictiveBrand()],
      color_layers: 5,
      layer_height_mm: 0.08,
      selectedRegions: [{ regionId: "region-1", colorHex: "ffffff", pixelCount: 1, previewUrl: "/api/files/region" }],
    } as never);

    await useConverterStore.getState().applyCustomRecipeOverride(["region-1"], [1, 1, 1, 1, 1]);

    expect(mocks.applyRecipeOverride).toHaveBeenCalledOnce();
    expect(useConverterStore.getState().error).toBeNull();
  });

  it("omits model fields for legacy preview and generate payloads", async () => {
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-legacy",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/legacy-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/legacy-model",
      preview_3d_url: "/api/files/legacy-model.glb",
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "legacy.png", { type: "image/png" }),
      source_version: "legacy",
      lut_name: "legacy-lut",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      color_layers: null,
      layer_height_mm: null,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      model_enable: true,
      model_only: true,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
    } as never);

    await useConverterStore.getState().submitPreview();
    const previewParams = mocks.convertPreview.mock.calls[0][1];
    expect(previewParams).not.toHaveProperty("model_enable");
    expect(previewParams).not.toHaveProperty("model_only");
    expect(previewParams).not.toHaveProperty("model_threshold");
    expect(previewParams).not.toHaveProperty("model_margin");

    await useConverterStore.getState().submitGenerate();
    const generateParams = mocks.convertGenerate.mock.calls[0][1];
    expect(generateParams).not.toHaveProperty("model_enable");
    expect(generateParams).not.toHaveProperty("model_only");
    expect(generateParams).not.toHaveProperty("model_threshold");
    expect(generateParams).not.toHaveProperty("model_margin");
  });
});
