import { beforeEach, describe, expect, it, vi } from "vitest";
import { ColorMode, ModelingMode, StructureMode } from "../api/types";
import type { PaletteEntry } from "../api/types";

const mocks = vi.hoisted(() => ({
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  convertGenerateLargeFormat: vi.fn(),
  convertGeneratePuzzle: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchGradientGroups: vi.fn(),
  fetchSessionLutInfo: vi.fn(),
}));

vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>("../api/converter");
  return {
    ...actual,
    convertPreview: mocks.convertPreview,
    convertGenerate: mocks.convertGenerate,
    convertGenerateLargeFormat: mocks.convertGenerateLargeFormat,
    convertGeneratePuzzle: mocks.convertGeneratePuzzle,
    uploadHeightmap: mocks.uploadHeightmap,
    fetchGradientGroups: mocks.fetchGradientGroups,
  };
});

vi.mock("../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../api/lut")>("../api/lut");
  return {
    ...actual,
    fetchSessionLutInfo: mocks.fetchSessionLutInfo,
  };
});

async function loadStore() {
  const mod = await import("../stores/converter");
  return mod.useConverterStore;
}

const PREVIEW_PALETTE: PaletteEntry[] = [
  {
    quantized_hex: "#111111",
    matched_hex: "#111111",
    pixel_count: 12,
    percentage: 60,
  },
  {
    quantized_hex: "#eeeeee",
    matched_hex: "#eeeeee",
    pixel_count: 8,
    percentage: 40,
  },
];

function previewResponse(palette: PaletteEntry[] = PREVIEW_PALETTE) {
  return {
    session_id: "session-relief",
    status: "ok",
    message: "Preview generated",
    preview_url: "/api/files/preview.png",
    preview_glb_url: null,
    performance_timing: {
      total_ms: 101,
      upload_ms: 2,
      worker_ms: 90,
      pickle_load_ms: 3,
      segmented_glb_ms: 4,
      palette_ms: 2,
    },
    palette,
    contours: {},
    dimensions: {
      width: 100,
      height: 80,
      preview_raw_url: "/api/files/raw.png",
    },
  };
}

function generateResponse() {
  return {
    status: "ok",
    message: "Model generated",
    download_url: "/api/files/model.3mf",
    preview_3d_url: "/api/files/model.glb",
    performance_timing: {
      total_ms: 202,
      worker_ms: 180,
      overhead_ms: 22,
    },
  };
}

function baseReadyState() {
  return {
    imageFile: new File(["png"], "relief.png", { type: "image/png" }),
    source_version: "legacy" as const,
    lut_name: "legacy-lut",
    target_width_mm: 90,
    target_height_mm: 72,
    color_mode: ColorMode.FOUR_COLOR_RYBW,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
    color_layers: 5,
    layer_height_mm: 0.08,
    quantize_colors: 48,
    enable_cleanup: true,
    hue_enable: false,
    chroma_gate: 15,
    spacer_thick: 1.2,
    structure_mode: StructureMode.SINGLE_SIDED,
    separate_backing: false,
    add_loop: false,
    loop_width: 4,
    loop_length: 8,
    loop_hole: 2.5,
    loop_angle: 0,
    loop_offset_x: 0,
    loop_offset_y: 0,
    loop_position_preset: "top-center",
    enable_outline: false,
    outline_width: 2,
    enable_cloisonne: false,
    wire_width_mm: 0.4,
    wire_height_mm: 0.4,
    enable_coating: false,
    coating_height_mm: 0.08,
    enable_fridge_magnet: false,
    fridge_magnets: [],
    puzzleEnabled: false,
    largeFormatEnabled: false,
  };
}

describe("converter store relief generate flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    mocks.convertPreview.mockResolvedValue(previewResponse());
    mocks.convertGenerate.mockResolvedValue(generateResponse());
    mocks.convertGenerateLargeFormat.mockResolvedValue({
      status: "ok",
      message: "Large format generated",
      download_url: "/api/files/tiles.zip",
      warnings: [],
    });
    mocks.convertGeneratePuzzle.mockResolvedValue({
      status: "ok",
      message: "Puzzle generated",
      download_url: "/api/files/puzzle.3mf",
      threemf_disk_path: null,
      warnings: [],
      grid_rows: 2,
      grid_cols: 2,
      piece_count: 4,
    });
    mocks.uploadHeightmap.mockResolvedValue({
      status: "ok",
      message: "Heightmap uploaded",
      thumbnail_url: "/api/files/heightmap.png",
      color_height_map: { "111111": 0.5 },
    });
    mocks.fetchGradientGroups.mockResolvedValue({ groups: [] });
    mocks.fetchSessionLutInfo.mockResolvedValue(null);
  });

  it("auto-builds color height map when relief is enabled before the first full generate preview", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: null,
      palette: [],
      enable_relief: true,
      autoHeightMode: "darker-higher",
      color_height_map: {},
      heightmap_max_height: 3,
    });

    const result = await useConverterStore.getState().submitFullPipeline();

    expect(result).toBe("/api/files/model.glb");
    expect(mocks.convertPreview).toHaveBeenCalledOnce();
    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    const [, generateParams] = mocks.convertGenerate.mock.calls[0];
    expect(generateParams.enable_relief).toBe(true);
    expect(generateParams.height_mode).toBe("color");
    expect(generateParams.color_height_map).toEqual(
      expect.objectContaining({
        "111111": expect.any(Number),
        eeeeee: expect.any(Number),
      }),
    );
    expect(useConverterStore.getState().error).toBeNull();
  });

  it("sends manual relief color heights as absolute total heights without mutating the store map", async () => {
    const useConverterStore = await loadStore();
    const manualMap = { "111111": 0.88 };
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      palette: PREVIEW_PALETTE,
      spacer_thick: 2.0,
      enable_relief: true,
      autoHeightMode: "darker-higher",
      color_height_map: manualMap,
      heightmap_max_height: 3,
    });

    await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    const [, generateParams] = mocks.convertGenerate.mock.calls[0];
    expect(generateParams.color_height_map).toEqual({ "111111": 2.88 });
    expect(useConverterStore.getState().color_height_map).toEqual({
      "111111": 0.88,
    });
  });

  it("stores preview and generate performance timing from successful responses", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: null,
      palette: [],
    });

    await useConverterStore.getState().submitFullPipeline();

    expect(useConverterStore.getState().previewPerformanceTiming).toMatchObject({
      total_ms: 101,
      segmented_glb_ms: 4,
    });
    expect(useConverterStore.getState().generatePerformanceTiming).toMatchObject({
      total_ms: 202,
      overhead_ms: 22,
    });

    useConverterStore.getState().setImageFile(null);

    expect(useConverterStore.getState().previewPerformanceTiming).toBeNull();
    expect(useConverterStore.getState().generatePerformanceTiming).toBeNull();
  });

  it("sends auto-built relief heights as store values plus spacer thickness", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: null,
      palette: [],
      spacer_thick: 1.2,
      enable_relief: true,
      autoHeightMode: "lighter-higher",
      color_height_map: {},
      heightmap_max_height: 3,
    });

    await useConverterStore.getState().submitFullPipeline();

    const storeMap = useConverterStore.getState().color_height_map;
    const [, generateParams] = mocks.convertGenerate.mock.calls[0];
    for (const [hex, reliefExtra] of Object.entries(storeMap)) {
      expect(generateParams.color_height_map[hex]).toBeCloseTo(
        reliefExtra + 1.2,
        10,
      );
    }
  });

  it("sends heightmap max height as spacer plus configured relief height in heightmap mode", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      palette: PREVIEW_PALETTE,
      spacer_thick: 1.2,
      enable_relief: true,
      autoHeightMode: "use-heightmap",
      color_height_map: { "111111": 0.5 },
      heightmap_max_height: 3,
    });

    await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    const [, generateParams] = mocks.convertGenerate.mock.calls[0];
    expect(generateParams.height_mode).toBe("heightmap");
    expect(generateParams.heightmap_max_height).toBeCloseTo(4.2, 10);
  });

  it("uses converted relief params inside puzzle generation request params", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      palette: PREVIEW_PALETTE,
      spacer_thick: 2.0,
      target_height_mm: 72,
      puzzleEnabled: true,
      puzzleRows: 2,
      puzzleCols: 2,
      enable_relief: true,
      autoHeightMode: "darker-higher",
      color_height_map: { "111111": 0.88 },
      heightmap_max_height: 3,
    });

    await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGeneratePuzzle).toHaveBeenCalledOnce();
    const [, puzzleRequest] = mocks.convertGeneratePuzzle.mock.calls[0];
    expect(puzzleRequest.params.color_height_map).toEqual({ "111111": 2.88 });
    expect(puzzleRequest.params.heightmap_max_height).toBeCloseTo(5, 10);
    expect(useConverterStore.getState().color_height_map).toEqual({
      "111111": 0.88,
    });
  });

  it("uses converted relief params inside large-format generation request params", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      palette: PREVIEW_PALETTE,
      spacer_thick: 2.0,
      target_height_mm: 120,
      largeFormatEnabled: true,
      tileWidthMm: 80,
      tileHeightMm: 90,
      enable_relief: true,
      autoHeightMode: "darker-higher",
      color_height_map: { "111111": 0.88 },
      heightmap_max_height: 3,
    });

    await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerateLargeFormat).toHaveBeenCalledOnce();
    const [, largeFormatRequest] = mocks.convertGenerateLargeFormat.mock.calls[0];
    expect(largeFormatRequest.target_height_mm).toBeUndefined();
    expect(largeFormatRequest.params.color_height_map).toEqual({
      "111111": 2.88,
    });
    expect(largeFormatRequest.params.heightmap_max_height).toBeCloseTo(5, 10);
    expect(useConverterStore.getState().color_height_map).toEqual({
      "111111": 0.88,
    });
  });

  it("passes the configured extra relief height when uploading a heightmap", async () => {
    const useConverterStore = await loadStore();
    const file = new File(["heightmap"], "heightmap.png", {
      type: "image/png",
    });
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      heightmapFile: file,
      heightmap_max_height: 4.4,
    });

    await useConverterStore.getState().uploadHeightmap();

    expect(mocks.uploadHeightmap).toHaveBeenCalledWith(
      file,
      "session-relief",
      4.4,
    );
  });

  it("does not overwrite an existing manual color height map after preview refreshes the palette", async () => {
    const useConverterStore = await loadStore();
    const manualMap = { "111111": 1.25 };
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: null,
      palette: [],
      enable_relief: true,
      autoHeightMode: "lighter-higher",
      color_height_map: manualMap,
      heightmap_max_height: 5,
    });

    await useConverterStore.getState().submitPreview();

    expect(useConverterStore.getState().color_height_map).toEqual(manualMap);
  });

  it("keeps heightmap mode blocked until a heightmap mapping exists", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      palette: PREVIEW_PALETTE.map((entry) => ({
        ...entry,
        quantized_hex: entry.quantized_hex.replace(/^#/, ""),
        matched_hex: entry.matched_hex.replace(/^#/, ""),
      })),
      enable_relief: true,
      autoHeightMode: "use-heightmap",
      color_height_map: {},
      heightmap_max_height: 5,
    });

    const result = await useConverterStore.getState().submitGenerate();

    expect(result).toBeNull();
    expect(mocks.convertGenerate).not.toHaveBeenCalled();
    expect(useConverterStore.getState().error).toBe(
      "请先上传高度图并获取高度映射后再生成",
    );
  });
});
