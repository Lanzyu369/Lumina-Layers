import { describe, it, expect, vi, beforeEach } from "vitest";
import apiClient from "../api/client";
import {
  convertPreview,
  convertGenerate,
  convertGenerateLargeFormat,
  convertGeneratePuzzle,
  convertPuzzleLayoutPreview,
  fetchLutList,
  getFileUrl,
} from "../api/converter";
import { fetchLutCatalog } from "../api/lut";
import {
  ColorMode,
  ModelingMode,
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
    auto_bg: true,
    bg_tol: 40,
    color_mode: ColorMode.FOUR_COLOR_RYBW,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
    quantize_colors: 48,
    enable_cleanup: true,
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
    expect(fd.get("auto_bg")).toBe("true");
    expect(fd.get("bg_tol")).toBe("40");
    expect(fd.get("color_mode")).toBe(ColorMode.FOUR_COLOR_RYBW);
    expect(fd.get("modeling_mode")).toBe(ModelingMode.HIGH_FIDELITY);
    expect(fd.get("quantize_colors")).toBe("48");
    expect(fd.get("enable_cleanup")).toBe("true");

    // 不应设置 responseType: blob（后端返回 JSON）
    expect(config).toMatchObject({ timeout: 0 });
    // 确认没有手动设置 Content-Type（让 axios 自动处理 FormData boundary）
    expect(config).not.toHaveProperty("headers");

    expect(result).toEqual(fakeResponse);
    expect(result.session_id).toBe("sess-123");
    expect(result.preview_url).toBe("/api/files/prev-abc");
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
      auto_bg: true,
      bg_tol: 40,
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
});

describe("convertGenerate", () => {
  const generateParams: ConvertGenerateRequest = {
    source_kind: "legacy_single",
    lut_name: "gen-lut",
    target_width_mm: 100,
    auto_bg: false,
    bg_tol: 30,
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

  it("sends JSON body with session_id and params", async () => {
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

    // 后端期望 JSON body: { session_id, params }
    expect(body).toEqual({
      session_id: "sess-abc",
      params: generateParams,
    });

    expect(config).toMatchObject({ timeout: 0 });
    expect(result).toEqual(fakeResponse);
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
      auto_bg: false,
      bg_tol: 30,
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
      params: nativeParams,
    });
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
        auto_bg: false,
        bg_tol: 30,
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
        auto_bg: false,
        bg_tol: 30,
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
