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
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:mock-url"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
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

  it("constrains 10-layer material archive relief totals to the optical stack height", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      source_version: "material",
      selectedMaterialDirNames: ["mat-black", "mat-white"],
      materialLayerCount: 10,
      materialLayerHeightMm: 0.08,
      spacer_thick: 0.2,
      enable_relief: true,
      autoHeightMode: "darker-higher",
      color_height_map: { "111111": 0.08 },
      heightmap_max_height: 0.08,
    });

    await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    const [, generateParams] = mocks.convertGenerate.mock.calls[0];
    expect(generateParams.material_source).toBe("material_archive");
    expect(generateParams.color_height_map).toEqual({ "111111": 0.8 });
    expect(generateParams.heightmap_max_height).toBeCloseTo(0.8, 10);
    expect(useConverterStore.getState().color_height_map).toEqual({
      "111111": 0.08,
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
      heightmapUploadSessionId: "session-relief",
      heightmap_max_height: 3,
    });

    await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    const [, generateParams] = mocks.convertGenerate.mock.calls[0];
    expect(generateParams.height_mode).toBe("heightmap");
    expect(generateParams.heightmap_max_height).toBeCloseTo(4.2, 10);
  });

  it("shows the generated GLB after heightmap relief generation even when a preview GLB exists", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      palette: PREVIEW_PALETTE,
      previewGlbUrl: "/api/files/flat-preview.glb",
      spacer_thick: 1.2,
      enable_relief: true,
      autoHeightMode: "use-heightmap",
      color_height_map: { "111111": 0.5 },
      heightmapUploadSessionId: "session-relief",
      heightmap_max_height: 3,
    });

    await useConverterStore.getState().submitGenerate();

    expect(useConverterStore.getState().modelUrl).toBe("/api/files/model.glb");
    expect(useConverterStore.getState().previewGlbUrl).toBe(
      "/api/files/flat-preview.glb",
    );
  });

  it("clears stale color relief mapping when switching into heightmap mode", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      palette: PREVIEW_PALETTE,
      enable_relief: true,
      autoHeightMode: "darker-higher",
      color_height_map: { "111111": 0.5 },
      heightmapThumbnailUrl: "/api/files/old-heightmap.png",
      heightmap_max_height: 3,
    });

    useConverterStore.getState().setAutoHeightMode("use-heightmap");

    expect(useConverterStore.getState().color_height_map).toEqual({});
    expect(useConverterStore.getState().heightmapThumbnailUrl).toBeNull();
  });

  it("blocks heightmap generation when only stale color relief mapping exists", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "session-relief",
      palette: PREVIEW_PALETTE,
      enable_relief: true,
      autoHeightMode: "use-heightmap",
      color_height_map: { "111111": 0.5 },
      heightmap_max_height: 3,
    });

    const result = await useConverterStore.getState().submitGenerate();

    expect(result).toBeNull();
    expect(mocks.convertGenerate).not.toHaveBeenCalled();
    expect(useConverterStore.getState().error).toBe(
      "relief_heightmap_generate_requires_upload",
    );
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
    expect(useConverterStore.getState().heightmapUploadSessionId).toBe(
      "session-relief",
    );
  });

  it("clears loading and ignores a stale heightmap upload response after replacing the image", async () => {
    const useConverterStore = await loadStore();
    const file = new File(["heightmap"], "heightmap.png", {
      type: "image/png",
    });
    const newFile = new File(["replacement"], "replacement.png", {
      type: "image/png",
    });
    let resolveUpload!: (value: {
      status: string;
      message: string;
      thumbnail_url: string;
      color_height_map: Record<string, number>;
    }) => void;
    mocks.uploadHeightmap.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "old-session",
      heightmapFile: file,
      heightmapThumbnailUrl: "/api/files/current-heightmap.png",
      color_height_map: { current: 1.1 },
    });

    const uploadPromise = useConverterStore.getState().uploadHeightmap();
    expect(mocks.uploadHeightmap).toHaveBeenCalledWith(file, "old-session", 3);
    expect(useConverterStore.getState().isLoading).toBe(true);

    useConverterStore.getState().setImageFile(newFile);
    expect(useConverterStore.getState().isLoading).toBe(false);
    resolveUpload({
      status: "ok",
      message: "stale upload finished",
      thumbnail_url: "/api/files/stale-heightmap.png",
      color_height_map: { stale: 0.2 },
    });

    await uploadPromise;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBeNull();
    expect(state.imageFile).toBe(newFile);
    expect(state.isLoading).toBe(false);
    expect(state.heightmapThumbnailUrl).toBe("/api/files/current-heightmap.png");
    expect(state.color_height_map).toEqual({ current: 1.1 });
    expect(state.error).toBeNull();
  });

  it("clears loading and ignores a stale heightmap upload rejection after replacing the image", async () => {
    const useConverterStore = await loadStore();
    const file = new File(["heightmap"], "heightmap.png", {
      type: "image/png",
    });
    const newFile = new File(["replacement"], "replacement.png", {
      type: "image/png",
    });
    let rejectUpload!: (reason?: unknown) => void;
    mocks.uploadHeightmap.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectUpload = reject;
      }),
    );
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "old-session",
      heightmapFile: file,
      heightmapThumbnailUrl: "/api/files/current-heightmap.png",
      color_height_map: { current: 1.1 },
    });

    const uploadPromise = useConverterStore.getState().uploadHeightmap();
    expect(mocks.uploadHeightmap).toHaveBeenCalledWith(file, "old-session", 3);
    expect(useConverterStore.getState().isLoading).toBe(true);

    useConverterStore.getState().setImageFile(newFile);
    expect(useConverterStore.getState().isLoading).toBe(false);
    rejectUpload(new Error("stale heightmap upload failed"));

    await uploadPromise;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBeNull();
    expect(state.imageFile).toBe(newFile);
    expect(state.isLoading).toBe(false);
    expect(state.heightmapThumbnailUrl).toBe("/api/files/current-heightmap.png");
    expect(state.color_height_map).toEqual({ current: 1.1 });
    expect(state.error).toBeNull();
  });

  it("reuploads the selected heightmap to the refreshed preview session before generating", async () => {
    const useConverterStore = await loadStore();
    const file = new File(["heightmap"], "heightmap.png", {
      type: "image/png",
    });
    mocks.uploadHeightmap.mockResolvedValueOnce({
      status: "ok",
      message: "Heightmap uploaded to refreshed session",
      thumbnail_url: "/api/files/new-heightmap.png",
      color_height_map: { "111111": 0.92 },
    });
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: null,
      palette: [],
      spacer_thick: 1.2,
      enable_relief: true,
      autoHeightMode: "use-heightmap",
      heightmapFile: file,
      color_height_map: {},
      heightmap_max_height: 3,
    });

    const result = await useConverterStore.getState().submitFullPipeline();

    expect(result).toBe("/api/files/model.glb");
    expect(mocks.convertPreview).toHaveBeenCalledOnce();
    expect(mocks.uploadHeightmap).toHaveBeenCalledWith(
      file,
      "session-relief",
      3,
    );
    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    expect(mocks.uploadHeightmap.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.convertGenerate.mock.invocationCallOrder[0],
    );
    const [, generateParams] = mocks.convertGenerate.mock.calls[0];
    expect(generateParams.height_mode).toBe("heightmap");
    expect(generateParams.heightmap_max_height).toBeCloseTo(4.2, 10);
    expect(useConverterStore.getState().color_height_map).toEqual({
      "111111": 0.92,
    });
    expect(useConverterStore.getState().heightmapUploadSessionId).toBe(
      "session-relief",
    );
  });

  it("clears stale heightmap mapping after reupload failure and blocks later generate", async () => {
    const useConverterStore = await loadStore();
    const file = new File(["heightmap"], "heightmap.png", {
      type: "image/png",
    });
    mocks.uploadHeightmap.mockRejectedValueOnce(
      new Error("heightmap upload failed"),
    );
    useConverterStore.setState({
      ...baseReadyState(),
      sessionId: "old-session",
      palette: PREVIEW_PALETTE,
      enable_relief: true,
      autoHeightMode: "use-heightmap",
      heightmapFile: file,
      heightmapThumbnailUrl: "/api/files/old-heightmap.png",
      color_height_map: { "111111": 0.5 },
      heightmap_max_height: 3,
    });

    await useConverterStore.getState().submitPreview();

    let state = useConverterStore.getState();
    expect(mocks.uploadHeightmap).toHaveBeenCalledWith(
      file,
      "session-relief",
      3,
    );
    expect(state.sessionId).toBe("session-relief");
    expect(state.color_height_map).toEqual({});
    expect(state.heightmapThumbnailUrl).toBeNull();
    expect(state.heightmapUploadSessionId).toBeNull();
    expect(state.error).toBe("heightmap upload failed");

    const result = await useConverterStore.getState().submitFullPipeline();

    state = useConverterStore.getState();
    expect(result).toBeNull();
    expect(mocks.convertPreview).toHaveBeenCalledOnce();
    expect(mocks.convertGenerate).not.toHaveBeenCalled();
    expect(state.error).toBe("relief_heightmap_generate_requires_upload");
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
      "relief_heightmap_generate_requires_upload",
    );
  });
});
