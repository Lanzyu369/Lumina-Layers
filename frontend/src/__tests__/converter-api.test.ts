import { describe, it, expect, vi, beforeEach } from "vitest";
import apiClient from "../api/client";
import {
  convertBatch,
  convertPreview,
  convertGenerate,
  convertGenerateLargeFormat,
  convertGeneratePuzzle,
  convertPuzzleLayoutPreview,
  beaconCleanupSessionFiles,
  cleanupSessionFiles,
  detectRegion,
  fetchLutList,
  getFileUrl,
  generateColorCard,
} from "../api/converter";
import { fetchLutCatalog } from "../api/lut";
import {
  ColorMode,
  ModelingMode,
  type BatchConvertParams,
  type PuzzleGenerateRequest,
  type PuzzleLayoutPreviewRequest,
  StructureMode,
  type ConvertPreviewRequest,
  type ConvertGenerateRequest,
  type LargeFormatConvertGenerateRequest,
  type LargeFormatGenerateRequest,
} from "../api/types";

vi.mock("../api/client", () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}));

const mockPost = vi.mocked(apiClient.post);
const mockGet = vi.mocked(apiClient.get);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("convertPreview", () => {
  const previewParams: ConvertPreviewRequest = {
    source_kind: "legacy_single",
    lut_name: "test-lut",
    target_width_mm: 80,
    color_mode: ColorMode.FOUR_COLOR_RYBW,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
    quantize_colors: 48,
    enable_cleanup: true,
    enable_outline: true,
    outline_width: 2.5,
    svg_pixels_per_mm: 25.5,
    enable_smooth_vector_preview: false,
    hue_weight: 0,
    chroma_gate: 0,
    is_dark: false,
  };

  it("builds correct FormData and calls POST /convert/preview", async () => {
    const fakeResponse = {
      session_id: "sess-123",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/prev-abc",
      palette: [],
      dimensions: { width: 200, height: 150 },
    };
    mockPost.mockResolvedValueOnce({ data: fakeResponse });

    const file = new File(["img-data"], "photo.png", { type: "image/png" });
    const result = await convertPreview(file, previewParams);

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, formData, config] = mockPost.mock.calls[0];
    expect(url).toBe("/convert/preview");
    expect(formData).toBeInstanceOf(FormData);

    const fd = formData as FormData;
    expect(fd.get("image")).toBeInstanceOf(File);
    expect(fd.get("lut_name")).toBe("test-lut");
    expect(fd.get("target_width_mm")).toBe("80");
    expect(fd.get("color_mode")).toBe(ColorMode.FOUR_COLOR_RYBW);
    expect(fd.get("modeling_mode")).toBe(ModelingMode.HIGH_FIDELITY);
    expect(fd.get("quantize_colors")).toBe("48");
    expect(fd.get("enable_cleanup")).toBe("true");
    expect(fd.get("enable_outline")).toBe("true");
    expect(fd.get("outline_width")).toBe("2.5");
    expect(fd.get("svg_pixels_per_mm")).toBe("25.5");
    expect(fd.get("enable_smooth_vector_preview")).toBe("false");

    // 不应设置 responseType: blob（后端返回 JSON）
    expect(config).toMatchObject({ timeout: 0 });
    // 确认没有手动设置 Content-Type（让 axios 自动处理 FormData boundary）
    expect(config).not.toHaveProperty("headers");

    expect(result).toEqual(fakeResponse);
    expect(result.session_id).toBe("sess-123");
    expect(result.preview_url).toBe("/api/files/prev-abc");
  });

  it("serializes preview replacement regions as JSON FormData", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        session_id: "sess-replay",
        status: "ok",
        message: "Preview generated",
        preview_url: "/api/files/prev-replay",
        palette: [],
        dimensions: { width: 200, height: 150 },
      },
    });

    const file = new File(["img-data"], "photo.png", { type: "image/png" });
    await convertPreview(file, {
      ...previewParams,
      replacement_regions: [
        {
          quantized_hex: "#111111",
          matched_hex: "#111111",
          replacement_hex: "#222222",
        },
      ],
    });

    const formData = mockPost.mock.calls[0][1] as FormData;
    expect(formData.get("replacement_regions")).toBe(
      JSON.stringify([
        {
          quantized_hex: "#111111",
          matched_hex: "#111111",
          replacement_hex: "#222222",
        },
      ]),
    );
  });

  it("serializes exact dynamic material preview fields into FormData", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        session_id: "sess-dynamic",
        status: "ok",
        message: "Preview generated",
        preview_url: "/api/files/dynamic-prev",
        preview_glb_url: null,
        palette: [],
        dimensions: { width: 200, height: 150 },
      },
    });

    const file = new File(["img-data"], "photo.png", { type: "image/png" });
    await convertPreview(file, {
      ...previewParams,
      lut_name: "__material_archive__",
      material_source: "material_archive",
      selected_materials: ["brand/white", "brand/blue"],
      material_dynamic_layer_count_enabled: true,
      material_min_layer_count: 6,
      material_max_layer_count: 9,
      material_delta_e00_tolerance: 0.7,
    });

    const formData = mockPost.mock.calls[0][1] as FormData;
    expect(formData.get("material_dynamic_layer_count_enabled")).toBe("true");
    expect(formData.get("material_min_layer_count")).toBe("6");
    expect(formData.get("material_max_layer_count")).toBe("9");
    expect(formData.get("material_delta_e00_tolerance")).toBe("0.7");
  });

  it("propagates network errors", async () => {
    mockPost.mockRejectedValueOnce(new Error("Network Error"));

    const file = new File(["x"], "a.png", { type: "image/png" });
    await expect(convertPreview(file, previewParams)).rejects.toThrow(
      "Network Error"
    );
  });

  it("serializes native bundle source fields into FormData", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        session_id: "sess-native",
        status: "ok",
        message: "Preview generated",
        preview_url: "/api/files/native-prev",
        palette: [],
        dimensions: { width: 200, height: 150 },
      },
    });

    const file = new File(["img-data"], "photo.png", { type: "image/png" });
    const result = await convertPreview(file, {
      source_kind: "native_bundle",
      material_type: "PLA",
      vendor: "Vendor A",
      db_names: ["DB-A", "DB-B"],
      color_layers: 5,
      layer_height_mm: 0.08,
      model_enable: true,
      model_only: false,
      target_width_mm: 80,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_weight: 0,
      chroma_gate: 0,
      is_dark: false,
    });

    const [, rawFormData] = mockPost.mock.calls[0];
    const formData = rawFormData as FormData;
    expect(formData.get("source_kind")).toBe("native_bundle");
    expect(formData.get("material_type")).toBe("PLA");
    expect(formData.get("vendor")).toBe("Vendor A");
    expect(formData.get("db_names")).toBe(JSON.stringify(["DB-A", "DB-B"]));
    expect(formData.get("color_layers")).toBe("5");
    expect(formData.get("layer_height_mm")).toBe("0.08");
    expect(formData.get("model_enable")).toBe("true");
    expect(formData.get("model_only")).toBe("false");
    expect(formData.has("model_threshold")).toBe(false);
    expect(formData.has("model_margin")).toBe(false);
    expect(result.session_id).toBe("sess-native");
  });

  it("serializes legacy multi LUT names into FormData", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        session_id: "sess-legacy-multi",
        status: "ok",
        message: "Preview generated",
        preview_url: "/api/files/legacy-multi-prev",
        palette: [],
        dimensions: { width: 200, height: 150 },
      },
    });

    const file = new File(["img-data"], "photo.png", { type: "image/png" });
    await convertPreview(file, {
      ...previewParams,
      source_kind: "legacy_multi",
      lut_name: "lut-a",
      lut_names: ["lut-a", "lut-b"],
    });

    const [, rawFormData] = mockPost.mock.calls[0];
    const formData = rawFormData as FormData;
    expect(formData.get("source_kind")).toBe("legacy_multi");
    expect(formData.get("lut_name")).toBe("lut-a");
    expect(formData.get("lut_names")).toBe(JSON.stringify(["lut-a", "lut-b"]));
  });
});

describe("convertBatch", () => {
  const baseBatchParams: BatchConvertParams = {
    source_kind: "legacy_single",
    lut_name: "test-lut",
    target_width_mm: 80,
    spacer_thick: 1.2,
    structure_mode: StructureMode.DOUBLE_SIDED,
    color_mode: ColorMode.FOUR_COLOR_RYBW,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
    color_layers: 5,
    layer_height_mm: 0.08,
    quantize_colors: 48,
    enable_cleanup: true,
    hue_weight: 0,
    chroma_gate: 0,
    use_lut_constrained: false,
    auto_dynamic_range: false,
    enable_relief: false,
  };

  it("serializes material archive batch fields into FormData", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "Batch generated",
        download_url: "/api/files/batch.3mf",
        preview_3d_url: null,
        preview_items: [],
        results: [],
        warnings: [],
      },
    });

    await convertBatch([new File(["a"], "a.png", { type: "image/png" })], {
      ...baseBatchParams,
      lut_name: "__material_archive__",
      material_source: "material_archive",
      selected_materials: ["brand/red", "brand/white"],
      material_layer_count: 7,
      material_layer_height_mm: 0.06,
      material_grid_resolution: 33,
      material_backing_material_index: 1,
      material_dynamic_layer_count_enabled: true,
      material_min_layer_count: 6,
      material_max_layer_count: 9,
      material_delta_e00_tolerance: 0.7,
      separate_backing: true,
      color_layers: 7,
      layer_height_mm: 0.06,
    });

    const [url, rawFormData] = mockPost.mock.calls[0];
    const formData = rawFormData as FormData;
    expect(url).toBe("/convert/batch");
    expect(formData.getAll("images")).toHaveLength(1);
    expect(formData.get("lut_name")).toBe("__material_archive__");
    expect(formData.get("material_source")).toBe("material_archive");
    expect(formData.get("selected_materials")).toBe(JSON.stringify(["brand/red", "brand/white"]));
    expect(formData.get("material_layer_count")).toBe("7");
    expect(formData.get("material_layer_height_mm")).toBe("0.06");
    expect(formData.get("material_grid_resolution")).toBe("33");
    expect(formData.get("material_backing_material_index")).toBe("1");
    expect(formData.get("material_dynamic_layer_count_enabled")).toBe("true");
    expect(formData.get("material_min_layer_count")).toBe("6");
    expect(formData.get("material_max_layer_count")).toBe("9");
    expect(formData.get("material_delta_e00_tolerance")).toBe("0.7");
    expect(formData.get("separate_backing")).toBe("true");
  });

  it("serializes native reverse LUT batch fields into FormData", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "Batch generated",
        download_url: "/api/files/batch.3mf",
        preview_3d_url: null,
        preview_items: [],
        results: [],
        warnings: [],
      },
    });

    await convertBatch([new File(["a"], "a.png", { type: "image/png" })], {
      ...baseBatchParams,
      source_kind: "native_bundle",
      lut_name: undefined,
      material_type: "PLA",
      vendor: "Bambu",
      db_names: ["red.cdb", "white.cdb"],
      color_layers: 6,
      layer_height_mm: 0.08,
      model_enable: true,
      model_only: true,
      model_threshold: 0.3,
      model_margin: 0.1,
      use_lut_constrained: true,
      auto_dynamic_range: true,
      high_precision_3d_preview: true,
    });

    const [url, rawFormData] = mockPost.mock.calls[0];
    const formData = rawFormData as FormData;
    expect(url).toBe("/convert/batch");
    expect(formData.getAll("images")).toHaveLength(1);
    expect(formData.get("source_kind")).toBe("native_bundle");
    expect(formData.has("lut_name")).toBe(false);
    expect(formData.get("material_type")).toBe("PLA");
    expect(formData.get("vendor")).toBe("Bambu");
    expect(formData.get("db_names")).toBe(JSON.stringify(["red.cdb", "white.cdb"]));
    expect(formData.get("model_enable")).toBe("true");
    expect(formData.get("model_only")).toBe("true");
    expect(formData.get("model_threshold")).toBe("0.3");
    expect(formData.get("model_margin")).toBe("0.1");
    expect(formData.get("use_lut_constrained")).toBe("true");
    expect(formData.get("auto_dynamic_range")).toBe("true");
    expect(formData.get("high_precision_3d_preview")).toBe("true");
  });

  it("serializes legacy multi LUT names into batch FormData", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "Batch generated",
        download_url: "/api/files/batch.3mf",
        preview_3d_url: null,
        preview_items: [],
        results: [],
        warnings: [],
      },
    });

    await convertBatch([new File(["a"], "a.png", { type: "image/png" })], {
      ...baseBatchParams,
      source_kind: "legacy_multi",
      lut_name: "lut-a",
      lut_names: ["lut-a", "lut-b"],
    });

    const [, rawFormData] = mockPost.mock.calls[0];
    const formData = rawFormData as FormData;
    expect(formData.get("source_kind")).toBe("legacy_multi");
    expect(formData.get("lut_name")).toBe("lut-a");
    expect(formData.get("lut_names")).toBe(JSON.stringify(["lut-a", "lut-b"]));
  });
});

describe("convertGenerate", () => {
  const generateParams: ConvertGenerateRequest = {
    source_kind: "legacy_single",
    lut_name: "gen-lut",
    target_width_mm: 100,
    color_mode: ColorMode.EIGHT_COLOR,
    modeling_mode: ModelingMode.PIXEL,
    quantize_colors: 64,
    enable_cleanup: false,
    hue_weight: 0,
    chroma_gate: 0,
    is_dark: false,
    spacer_thick: 1.2,
    structure_mode: StructureMode.DOUBLE_SIDED,
    separate_backing: true,
    add_loop: true,
    loop_width: 4,
    loop_length: 8,
    loop_hole: 2.5,
    enable_relief: false,
    heightmap_max_height: 5.0,
    enable_outline: true,
    outline_width: 2.0,
    enable_cloisonne: false,
    wire_width_mm: 0.4,
    wire_height_mm: 0.4,
    enable_coating: true,
    coating_height_mm: 0.08,
    enable_fridge_magnet: false,
    fridge_magnets: [],
  };

  it("defaults the upload-filename preference off in the JSON body", async () => {
    const fakeResponse = {
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/dl-123",
      preview_3d_url: "/api/files/glb-456",
    };
    mockPost.mockResolvedValueOnce({ data: fakeResponse });

    const result = await convertGenerate("sess-abc", generateParams);

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, body, config] = mockPost.mock.calls[0];
    expect(url).toBe("/convert/generate");

    // 后端期望命名偏好位于 params 外层，避免进入模型生成参数。
    expect(body).toEqual({
      session_id: "sess-abc",
      preserve_upload_filename_for_3mf: false,
      params: generateParams,
    });

    expect(config).toMatchObject({ timeout: 0 });
    expect(result).toEqual(fakeResponse);
  });

  it("sends the enabled upload-filename preference outside params", async () => {
    mockPost.mockResolvedValueOnce({
      data: { status: "ok", message: "done", download_url: "/api/files/x" },
    });

    await convertGenerate("sess-enabled", generateParams, true);

    expect(mockPost.mock.calls[0][1]).toEqual({
      session_id: "sess-enabled",
      preserve_upload_filename_for_3mf: true,
      params: generateParams,
    });
  });

  it("includes optional fields in params when provided", async () => {
    const paramsWithOptionals: ConvertGenerateRequest = {
      ...generateParams,
      color_height_map: { "#FF0000": 1.5, "#00FF00": 2.0 },
      replacement_regions: [
        {
          quantized_hex: "#AAA",
          matched_hex: "#BBB",
          replacement_hex: "#CCC",
        },
      ],
    };
    mockPost.mockResolvedValueOnce({
      data: { status: "ok", message: "done", download_url: "/api/files/x" },
    });

    await convertGenerate("sess-xyz", paramsWithOptionals);

    const body = mockPost.mock.calls[0][1] as { session_id: string; params: ConvertGenerateRequest };
    expect(body.params.color_height_map).toEqual({
      "#FF0000": 1.5,
      "#00FF00": 2.0,
    });
    expect(body.params.replacement_regions).toEqual([
      { quantized_hex: "#AAA", matched_hex: "#BBB", replacement_hex: "#CCC" },
    ]);
  });

  it("keeps lut_name as the first legacy multi LUT while sending all lut_names", async () => {
    mockPost.mockResolvedValueOnce({
      data: { status: "ok", message: "done", download_url: "/api/files/x" },
    });

    const paramsWithMultiLuts: ConvertGenerateRequest = {
      ...generateParams,
      source_kind: "legacy_multi",
      lut_name: "lut-a",
      lut_names: ["lut-a", "lut-b"],
    };

    await convertGenerate("sess-xyz", paramsWithMultiLuts);

    const body = mockPost.mock.calls[0][1] as { session_id: string; params: ConvertGenerateRequest };
    const params = body.params as {
      source_kind?: string;
      lut_name?: string;
      lut_names?: string[];
    };
    expect(params.source_kind).toBe("legacy_multi");
    expect(params.lut_name).toBe("lut-a");
    expect(params.lut_names).toEqual(["lut-a", "lut-b"]);
  });

  it("propagates 4xx errors", async () => {
    const axiosError = new Error("Request failed with status code 422") as Error & {
      response?: { status: number; data: { detail: string } };
      isAxiosError?: boolean;
    };
    axiosError.response = { status: 422, data: { detail: "Invalid params" } };
    axiosError.isAxiosError = true;
    mockPost.mockRejectedValueOnce(axiosError);

    await expect(convertGenerate("sess-1", generateParams)).rejects.toThrow(
      "Request failed with status code 422"
    );
  });

  it("propagates 5xx errors", async () => {
    const serverError = new Error("Request failed with status code 500") as Error & {
      response?: { status: number };
      isAxiosError?: boolean;
    };
    serverError.response = { status: 500 };
    serverError.isAxiosError = true;
    mockPost.mockRejectedValueOnce(serverError);

    await expect(convertGenerate("sess-2", generateParams)).rejects.toThrow(
      "Request failed with status code 500"
    );
  });

  it("sends native bundle source fields in the JSON body", async () => {
    mockPost.mockResolvedValueOnce({
      data: { status: "ok", message: "done", download_url: "/api/files/native-model" },
    });

    const nativeParams: ConvertGenerateRequest = {
      source_kind: "native_bundle",
      material_type: "PLA",
      vendor: "Vendor A",
      db_names: ["DB-A"],
      color_layers: 5,
      layer_height_mm: 0.08,
      model_enable: true,
      model_only: false,
      target_width_mm: 100,
      color_mode: ColorMode.EIGHT_COLOR,
      modeling_mode: ModelingMode.PIXEL,
      quantize_colors: 64,
      enable_cleanup: false,
      hue_weight: 0,
      chroma_gate: 0,
      is_dark: true,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      separate_backing: true,
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
    };

    await convertGenerate("sess-native", nativeParams);

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, body] = mockPost.mock.calls[0];
    expect(url).toBe("/convert/generate");
    expect(body).toEqual({
      session_id: "sess-native",
      preserve_upload_filename_for_3mf: false,
      params: nativeParams,
    });
  });
});

describe("detectRegion", () => {
  it("defaults to the no-PNG fast path", async () => {
    const fakeResponse = {
      region_id: "region-1",
      color_hex: "#ffffff",
      pixel_count: 8,
      preview_url: null,
      contours: [],
    };
    mockPost.mockResolvedValueOnce({ data: fakeResponse });

    const result = await detectRegion("sess-region", 3, 4);

    expect(mockPost).toHaveBeenCalledWith(
      "/convert/region-detect",
      {
        session_id: "sess-region",
        x: 3,
        y: 4,
        include_preview: false,
      },
      { timeout: 3_600_000 },
    );
    expect(result).toEqual(fakeResponse);
  });

  it("only requests a highlight PNG when includePreview is explicitly true", async () => {
    const fakeResponse = {
      region_id: "region-1",
      color_hex: "#ffffff",
      pixel_count: 8,
      preview_url: "/api/files/region-highlight.png",
      contours: [],
    };
    mockPost.mockResolvedValueOnce({ data: fakeResponse });

    await detectRegion("sess-region", 3, 4, { includePreview: true });

    expect(mockPost).toHaveBeenCalledWith(
      "/convert/region-detect",
      {
        session_id: "sess-region",
        x: 3,
        y: 4,
        include_preview: true,
      },
      { timeout: 3_600_000 },
    );
  });

});

describe("convertGenerateLargeFormat", () => {
  it("sends large-format body and returns warnings", async () => {
    const params: LargeFormatGenerateRequest = {
      tile_width_mm: 40,
      tile_height_mm: 40,
      params: {
        source_kind: "legacy_single",
        lut_name: "gen-lut",
        color_mode: ColorMode.EIGHT_COLOR,
        modeling_mode: ModelingMode.VECTOR,
        quantize_colors: 64,
        enable_cleanup: false,
        hue_weight: 0,
        chroma_gate: 0,
        is_dark: false,
        spacer_thick: 1.2,
        structure_mode: StructureMode.DOUBLE_SIDED,
        separate_backing: true,
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
        enable_fridge_magnet: false,
        fridge_magnets: [],
      } as LargeFormatConvertGenerateRequest,
    };
    const fakeResponse = {
      status: "ok",
      message: "Generated 4 tiles",
      download_url: "/api/files/zip-123",
      tile_count: 4,
      grid_cols: 2,
      grid_rows: 2,
      warnings: ["Raster fallback was used for this large-format SVG request."],
    };
    mockPost.mockResolvedValueOnce({ data: fakeResponse });

    const result = await convertGenerateLargeFormat("sess-large", params);

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, body, config] = mockPost.mock.calls[0];
    expect(url).toBe("/convert/generate-large-format");
    expect(body).toEqual({ session_id: "sess-large", params });
    expect(config).toMatchObject({ timeout: 0 });
    expect(result.warnings).toEqual(fakeResponse.warnings);
  });
});

describe("generateColorCard", () => {
  it("forwards the complete device and build plate selection", async () => {
    const response = {
      status: "ok",
      message: "generated",
      download_url: "/api/files/card",
    };
    mockPost.mockResolvedValueOnce({ data: response });

    const result = await generateColorCard(
      "sess-card",
      {
        printer_id: "bambu-p1s",
        slicer: "OrcaSlicer",
        nozzle_size: "0.2",
        device_profile_id: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
        build_plate_id: "smooth-high-temp-plate",
      },
      120,
      0.6,
      false,
    );

    expect(mockPost).toHaveBeenCalledWith(
      "/convert/color-card",
      {
        session_id: "sess-card",
        target_width_mm: 120,
        spacer_thick: 0.6,
        show_labels: false,
        printer_id: "bambu-p1s",
        slicer: "OrcaSlicer",
        nozzle_size: "0.2",
        device_profile_id: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
        build_plate_id: "smooth-high-temp-plate",
      },
      { timeout: 0 },
    );
    expect(result).toEqual(response);
  });
});

describe("convertPuzzleLayoutPreview", () => {
  it("sends session_id with puzzle preview params", async () => {
    const params: PuzzleLayoutPreviewRequest = {
      target_height_mm: 60,
      puzzle_style: "regular",
      sizing_mode: "grid",
      piece_width_mm: 20,
      piece_height_mm: 20,
      rows: 2,
      cols: 3,
      target_piece_count: 6,
      seed: 12,
      connector_style: "classic",
      labels_enabled: true,
      engrave_back_labels: false,
      irregularity_strength: 0.35,
      min_neck_width_mm: 1.2,
    };
    const fakeResponse = {
      status: "ok",
      message: "Puzzle layout preview generated",
      overlay_url: "/api/files/puzzle-overlay",
      piece_count: 6,
      grid_cols: 3,
      grid_rows: 2,
      derived_piece_width_mm: 20,
      derived_piece_height_mm: 30,
      warnings: [],
    };
    mockPost.mockResolvedValueOnce({ data: fakeResponse });

    const result = await convertPuzzleLayoutPreview("sess-puzzle", params);

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, body, config] = mockPost.mock.calls[0];
    expect(url).toBe("/convert/puzzle-layout-preview");
    expect(body).toEqual({ session_id: "sess-puzzle", params });
    expect(config).toMatchObject({ timeout: 3_600_000 });
    expect(result).toEqual(fakeResponse);
  });
});

describe("convertGeneratePuzzle", () => {
  it("sends puzzle generation params and receives a single 3MF payload", async () => {
    const params: PuzzleGenerateRequest = {
      target_height_mm: 60,
      puzzle_style: "regular",
      sizing_mode: "grid",
      piece_width_mm: 20,
      piece_height_mm: 20,
      rows: 2,
      cols: 3,
      target_piece_count: 6,
      seed: 12,
      connector_style: "classic",
      labels_enabled: true,
      engrave_back_labels: false,
      irregularity_strength: 0.35,
      min_neck_width_mm: 1.2,
      params: {
        lut_name: "gen-lut",
        target_width_mm: 100,
        color_mode: ColorMode.EIGHT_COLOR,
        modeling_mode: ModelingMode.PIXEL,
        quantize_colors: 64,
        enable_cleanup: false,
        hue_weight: 0,
        chroma_gate: 0,
        is_dark: false,
        spacer_thick: 1.2,
        structure_mode: StructureMode.DOUBLE_SIDED,
        separate_backing: true,
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
        enable_fridge_magnet: false,
        fridge_magnets: [],
      },
    };
    const fakeResponse = {
      status: "ok",
      message: "Generated 6 puzzle pieces into a single 3MF",
      download_url: "/api/files/puzzle-3mf",
      threemf_disk_path: "E:/tmp/puzzle.3mf",
      piece_count: 6,
      grid_cols: 3,
      grid_rows: 2,
      warnings: [],
    };
    mockPost.mockResolvedValueOnce({ data: fakeResponse });

    const result = await convertGeneratePuzzle("sess-puzzle", params);

    expect(mockPost).toHaveBeenCalledOnce();
    const [url, body, config] = mockPost.mock.calls[0];
    expect(url).toBe("/convert/generate-puzzle");
    expect(body).toEqual({ session_id: "sess-puzzle", params });
    expect(config).toMatchObject({ timeout: 0 });
    expect(result.threemf_disk_path).toBe("E:/tmp/puzzle.3mf");
  });
});

describe("fetchLutList", () => {
  it("returns correct LutListResponse", async () => {
    const mockData = {
      luts: [
        { name: "lut-a", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/a.npy" },
        { name: "lut-b", color_mode: ColorMode.BW, path: "/b.npy" },
      ],
    };
    mockGet.mockResolvedValueOnce({ data: mockData });

    const result = await fetchLutList();

    expect(mockGet).toHaveBeenCalledWith("/lut/list", { timeout: 3_600_000 });
    expect(result).toEqual(mockData);
    expect(result.luts).toHaveLength(2);
    expect(result.luts[0].name).toBe("lut-a");
    expect(result.luts[0].color_mode).toBe(ColorMode.FOUR_COLOR_RYBW);
  });

  it("can suppress client logs for background LUT list probes", async () => {
    const mockData = { luts: [] };
    mockGet.mockResolvedValueOnce({ data: mockData });

    const result = await fetchLutList({ suppressClientLog: true });

    expect(mockGet).toHaveBeenCalledWith("/lut/list", {
      timeout: 3_600_000,
      suppressClientLog: true,
    });
    expect(result).toEqual(mockData);
  });

  it("propagates network errors", async () => {
    mockGet.mockRejectedValueOnce(new Error("Network Error"));
    await expect(fetchLutList()).rejects.toThrow("Network Error");
  });
});

describe("fetchLutCatalog", () => {
  it("returns the grouped legacy catalog and native db option objects", async () => {
    const mockData = {
      legacy_groups: [
        {
          group_name: "Preset",
          items: [
            { name: "lut-a", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/a.npy", fingerprint: "fp-a" },
          ],
        },
      ],
      native_brand_groups: [
        {
          brand_key: "bambulab_pla",
          material_type: "PLA",
          vendor: "Bambu Lab",
          display_name: "Bambu PLA",
          db_options: [
            { name: "DB-A", path: "/DB-A.json", color_mode: "8-Color Max", fingerprint: "fp-db-a" },
          ],
          default_db_names: ["DB-A"],
          supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
        },
      ],
    };
    mockGet.mockResolvedValueOnce({ data: mockData });

    const result = await fetchLutCatalog();

    expect(mockGet).toHaveBeenCalledWith("/lut/catalog");
    expect(result).toEqual(mockData);
    expect(result.legacy_groups[0].items[0].name).toBe("lut-a");
    expect(result.native_brand_groups[0].db_options[0].name).toBe("DB-A");
  });
});

describe("getFileUrl", () => {
  it("constructs correct URL from file_id", () => {
    expect(getFileUrl("abc123")).toBe("/api/files/abc123");
  });

  it("handles file_id with special characters", () => {
    expect(getFileUrl("file-2024-01-01_model")).toBe(
      "/api/files/file-2024-01-01_model"
    );
  });
});

describe("beaconCleanupSessionFiles", () => {
  it("falls back to cleanupSessionFiles when sendBeacon is unavailable", () => {
    const originalSendBeacon = navigator.sendBeacon;
    Object.defineProperty(navigator, "sendBeacon", {
      configurable: true,
      value: undefined,
    });
    mockPost.mockResolvedValueOnce({ data: { status: "ok" } });

    try {
      expect(() =>
        beaconCleanupSessionFiles("sess-cleanup", ["keep-model"]),
      ).not.toThrow();
      expect(mockPost).toHaveBeenCalledWith("/convert/cleanup-session-files", {
        session_id: "sess-cleanup",
        keep_file_ids: ["keep-model"],
      });
    } finally {
      Object.defineProperty(navigator, "sendBeacon", {
        configurable: true,
        value: originalSendBeacon,
      });
    }
  });

  it("uses the same cleanup payload for the direct API helper", async () => {
    mockPost.mockResolvedValueOnce({ data: { status: "ok" } });

    await cleanupSessionFiles("sess-cleanup", ["keep-model"]);

    expect(mockPost).toHaveBeenCalledWith("/convert/cleanup-session-files", {
      session_id: "sess-cleanup",
      keep_file_ids: ["keep-model"],
    });
  });
});
