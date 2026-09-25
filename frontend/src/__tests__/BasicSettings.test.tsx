import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import BasicSettings from "../components/sections/BasicSettings";
import BedSizeSelector from "../components/sections/BedSizeSelector";
import ReliefSettings from "../components/sections/ReliefSettings";
import { useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import * as converterApi from "../api/converter";
import * as lutApi from "../api/lut";
import * as extractorApi from "../api/extractor";
import {
  ColorMode as ColorModeEnum,
  StructureMode as StructureModeEnum,
  ModelingMode as ModelingModeEnum,
} from "../api/types";
import type { LutDetailsCatalogGroup, SavedMaterialLibraryItem } from "../api/types";

vi.mock("../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../api/lut")>(
    "../api/lut",
  );
  return {
    ...actual,
    fetchLutInfo: vi.fn(),
    fetchLutCatalog: vi.fn(),
    fetchLutDetailsCatalog: vi.fn(),
  };
});

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    fetchLutList: vi.fn(),
    uploadModelSurface: vi.fn(),
  };
});

vi.mock("../api/extractor", async () => {
  const actual = await vi.importActual<typeof import("../api/extractor")>(
    "../api/extractor",
  );
  return {
    ...actual,
    listGradientCardMaterials: vi.fn(),
  };
});

function makeLegacyCatalogGroups(): LutDetailsCatalogGroup[] {
  return [
    {
      manufacturer: "Brand A",
      items: [
        {
          name: "A 4C",
          path: "lut-ref/fp-a4.npy",
          fingerprint: "fp-a4",
          color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
          compatibility_key: "sig-a4",
          source_kind: "legacy_lookup",
          manufacturer: "Brand A",
          material_type: "",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["brand", "a", "4c"],
        },
        {
          name: "A 4C Alt",
          path: "lut-ref/fp-a4-alt.npy",
          fingerprint: "fp-a4-alt",
          color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
          compatibility_key: "sig-a4-alt",
          source_kind: "legacy_lookup",
          manufacturer: "Brand A",
          material_type: "",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["brand", "a", "4c", "alt"],
        },
        {
          name: "A 8C",
          path: "lut-ref/fp-a8.npy",
          fingerprint: "fp-a8",
          color_mode: ColorModeEnum.EIGHT_COLOR,
          compatibility_key: "sig-a8",
          source_kind: "legacy_lookup",
          manufacturer: "Brand A",
          material_type: "",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["brand", "a", "8c"],
        },
      ],
    },
    {
      manufacturer: "Brand B",
      items: [
        {
          name: "B BW",
          path: "lut-ref/fp-bbw.npy",
          fingerprint: "fp-bbw",
          color_mode: ColorModeEnum.BW,
          compatibility_key: "sig-bw",
          source_kind: "legacy_lookup",
          manufacturer: "Brand B",
          material_type: "",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["brand", "b", "bw"],
        },
      ],
    },
    {
      manufacturer: "Unlabeled",
      items: [
        {
          name: "Loose Merged",
          path: "lut-ref/fp-loose.npy",
          fingerprint: "fp-loose",
          color_mode: ColorModeEnum.MERGED,
          compatibility_key: "sig-merged",
          source_kind: "legacy_lookup",
          manufacturer: "Unlabeled",
          material_type: "",
          manufacturer_source: "fallback",
          material_source: "fallback",
          search_tokens: ["loose", "merged"],
        },
      ],
    },
  ];
}

// Reset store to a clean state before each test
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(converterApi.fetchLutList).mockResolvedValue({
    luts: [
      {
        name: "Brand A - A4",
        color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
        path: "lut-ref/fp-a4.npy",
        fingerprint: "fp-a4",
      },
    ],
  });
  vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({
    groups: makeLegacyCatalogGroups(),
  });
  vi.mocked(lutApi.fetchLutCatalog).mockResolvedValue({
    legacy_groups: [],
    native_brand_groups: [],
  });
  vi.mocked(lutApi.fetchLutInfo).mockResolvedValue({
    name: "A 4C",
    color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
    color_count: 4,
  });
  vi.mocked(converterApi.uploadModelSurface).mockResolvedValue({
    status: "ok",
    model_file_id: "model-file-1",
    summary: {
      vertex_count: 8,
      face_count: 12,
      bounds_min_mm: [0, 0, 0],
      bounds_max_mm: [20, 10, 2],
      extents_mm: [20, 10, 2],
      is_watertight: true,
      is_winding_consistent: true,
      body_count: 1,
      unit_warning: null,
    },
    surface_candidates: [],
    warnings: [],
  });
  vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({
    status: "success",
    message: "ok",
    materials: [],
  });
  useConverterStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    source_version: "legacy",
    batchMode: false,
    batchFiles: [],
    enableCrop: false,
    cropModalOpen: false,
    isCropping: false,
    lut_name: "",
    lutList: [],
    lutListFull: [
      {
        name: "Brand A - A4",
        color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
        path: "lut-ref/fp-a4.npy",
        fingerprint: "fp-a4",
      },
      {
        name: "Brand A - A4 Alt",
        color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
        path: "lut-ref/fp-a4-alt.npy",
        fingerprint: "fp-a4-alt",
      },
      {
        name: "Brand A - A8",
        color_mode: ColorModeEnum.EIGHT_COLOR,
        path: "lut-ref/fp-a8.npy",
        fingerprint: "fp-a8",
      },
      {
        name: "Brand B - BW",
        color_mode: ColorModeEnum.BW,
        path: "lut-ref/fp-bbw.npy",
        fingerprint: "fp-bbw",
      },
      {
        name: "Loose Merged",
        color_mode: ColorModeEnum.MERGED,
        path: "lut-ref/fp-loose.npy",
        fingerprint: "fp-loose",
      },
    ],
    lutListLoading: false,
    legacyCatalogGroups: makeLegacyCatalogGroups(),
    legacyCatalogLoading: false,
    selectedLegacyManufacturer: "",
    nativeBrandGroups: [],
    nativeBrandGroupsLoading: false,
    selectedNativeBrandKey: "",
    selectedNativeDbNames: [],
    color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
    target_width_mm: 80,
    target_height_mm: 80,
    spacer_thick: 0.64,
    structure_mode: StructureModeEnum.SINGLE_SIDED,
    modeling_mode: ModelingModeEnum.HIGH_FIDELITY,
    enable_relief: false,
    modelSurfaceEnabled: false,
    modelSurfaceFile: null,
    modelSurfacePreviewUrl: null,
    modelSurfaceModelFileId: null,
    modelSurfaceSummary: null,
    modelSurfaceSelectionId: null,
    modelSurfaceSelection: null,
    modelSurfaceFootprint: null,
    modelSurfaceCandidates: [],
    modelSurfaceLoading: false,
    modelSurfaceSelecting: false,
    modelSurfaceError: null,
    modelSurfaceWarnings: [],
    previewWarnings: [],
    largeFormatWarnings: [],
    materialDynamicLayerCountEnabled: false,
    materialMinLayerCount: 5,
    materialMaxLayerCount: 10,
    materialDynamicRecipes: [],
    materialLayerBenefitCurve: [],
  });
  useSettingsStore.setState({
    ...DEFAULT_SETTINGS,
    language: "zh",
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

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
    brand_key: "bambulab_pla",
    material_type: "PLA",
    vendor: "Bambu Lab",
    display_name: "Bambu PLA",
    db_options: [makeDbOption("DB-A"), makeDbOption("DB-B"), makeDbOption("DB-C")],
    default_db_names: ["DB-B", "DB-C"],
    package_name: "bambu-pla-package",
    model_name: "bambu-pla-model",
    supported_modes: [
      { color_layers: 5, layer_height_mm: 0.08 },
      { color_layers: 8, layer_height_mm: 0.12 },
    ],
  };
}

function makeMaterial(
  directoryName: string,
  materialName: string,
): SavedMaterialLibraryItem {
  return {
    material_name: materialName,
    directory_name: directoryName,
    material_file_url: `/materials/${directoryName}/material.json`,
    estimated_rgb: [255, 255, 255],
  };
}

function isMultipleOfStep(value: number, step: number): boolean {
  const ratio = value / step;
  return Math.abs(ratio - Math.round(ratio)) < 1e-9;
}

describe("BasicSettings", () => {
  it("shows exact fractional workshop dimensions without changing integer defaults", () => {
    useConverterStore.setState({
      target_width_mm: 20.8,
      target_height_mm: 62.4,
    });

    render(<BasicSettings />);

    expect(
      screen.getByRole("slider", { name: "宽度" }),
    ).toHaveAttribute("step", "0.1");
    expect(
      screen.getByRole("textbox", { name: "宽度 value" }),
    ).toHaveValue("20.8");
    expect(
      screen.getByRole("slider", { name: "高度" }),
    ).toHaveAttribute("step", "0.1");
    expect(
      screen.getByRole("textbox", { name: "高度 value" }),
    ).toHaveValue("62.4");

    act(() => {
      useConverterStore.setState({
        target_width_mm: 80,
        target_height_mm: 80,
      });
    });

    expect(
      screen.getByRole("slider", { name: "宽度" }),
    ).toHaveAttribute("step", "1");
    expect(
      screen.getByRole("textbox", { name: "宽度 value" }),
    ).toHaveValue("80");
  });

  it("keeps large-format manual dimensions above the everyday slider range", () => {
    useConverterStore.setState({
      largeFormatEnabled: true,
      target_width_mm: 120,
      target_height_mm: 160,
      tileWidthMm: 200,
      tileHeightMm: 200,
    } as never);

    render(<BasicSettings />);

    expect(screen.getByRole("slider", { name: "宽度" })).toHaveAttribute("max", "400");
    expect(screen.getByRole("slider", { name: "高度" })).toHaveAttribute("max", "400");
    expect(screen.getByRole("slider", { name: "切片宽度" })).toHaveAttribute("max", "500");
    expect(screen.getByRole("slider", { name: "切片高度" })).toHaveAttribute("max", "500");

    const widthInput = screen.getByRole("textbox", { name: "宽度 value" });
    fireEvent.change(widthInput, { target: { value: "30000" } });
    fireEvent.blur(widthInput);

    expect(useConverterStore.getState().target_width_mm).toBe(30000);
    expect(widthInput).toHaveValue("30000");
  });

  it("backs off failed startup LUT loads instead of retrying immediately", async () => {
    vi.useFakeTimers();
    vi.mocked(converterApi.fetchLutList)
      .mockRejectedValueOnce(new Error("backend offline"))
      .mockResolvedValue({
        luts: [
          {
            name: "Recovered LUT",
            color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
            path: "/recovered.npy",
            fingerprint: "fp-recovered",
          },
        ],
      });
    vi.mocked(lutApi.fetchLutDetailsCatalog)
      .mockRejectedValueOnce(new Error("backend offline"))
      .mockResolvedValue({ groups: makeLegacyCatalogGroups() });
    useConverterStore.setState({
      source_version: "legacy",
      lutList: [],
      lutListFull: [],
      lutListLoading: false,
      legacyCatalogGroups: [],
      legacyCatalogLoading: false,
    });

    try {
      render(<BasicSettings />);

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
        await Promise.resolve();
      });

      expect(converterApi.fetchLutList).toHaveBeenCalledTimes(1);
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenCalledTimes(1);
      expect(converterApi.fetchLutList).toHaveBeenNthCalledWith(1, {
        suppressClientLog: true,
      });
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenNthCalledWith(1, {
        suppressClientLog: true,
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(converterApi.fetchLutList).toHaveBeenCalledTimes(2);
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenCalledTimes(2);
      expect(converterApi.fetchLutList).toHaveBeenNthCalledWith(2, {
        suppressClientLog: true,
      });
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenNthCalledWith(2, {
        suppressClientLog: true,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops startup LUT retries after repeated backend failures", async () => {
    vi.useFakeTimers();
    vi.mocked(converterApi.fetchLutList).mockRejectedValue(
      new Error("backend offline"),
    );
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockRejectedValue(
      new Error("backend offline"),
    );
    useConverterStore.setState({
      source_version: "legacy",
      lutList: [],
      lutListFull: [],
      lutListLoading: false,
      legacyCatalogGroups: [],
      legacyCatalogLoading: false,
    });

    try {
      render(<BasicSettings />);

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(converterApi.fetchLutList).toHaveBeenCalledTimes(2);
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenCalledTimes(2);
      expect(converterApi.fetchLutList).toHaveBeenNthCalledWith(2, {
        suppressClientLog: true,
      });
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenNthCalledWith(2, {
        suppressClientLog: true,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  // Req 2.1: "批量模式" checkbox removed
  it("does NOT render the batch mode checkbox", () => {
    render(<BasicSettings />);
    expect(screen.queryByText("批量模式")).not.toBeInTheDocument();
  });

  // Req 3.2: crop checkbox visible in SingleMode
  it("renders crop checkbox in SingleMode (imageFile set, batchFiles empty)", () => {
    const file = new File(["img"], "test.jpg", { type: "image/jpeg" });
    useConverterStore.setState({
      imageFile: file,
      imagePreviewUrl: "data:image/jpeg;base64,fake",
      batchMode: false,
      batchFiles: [],
    });
    render(<BasicSettings />);
    expect(screen.getByText("上传后裁剪")).toBeInTheDocument();
  });

  // Req 4.4: crop checkbox hidden in BatchMode
  it("does NOT render crop checkbox in BatchMode (batchFiles has items)", () => {
    const files = [
      new File(["a"], "a.jpg", { type: "image/jpeg" }),
      new File(["b"], "b.png", { type: "image/png" }),
    ];
    useConverterStore.setState({
      imageFile: null,
      imagePreviewUrl: null,
      batchMode: true,
      batchFiles: files,
    });
    render(<BasicSettings />);
    expect(screen.queryByText("上传后裁剪")).not.toBeInTheDocument();
  });

  // UnifiedUploader is rendered (present in both modes)
  it("renders UnifiedUploader in empty state", () => {
    render(<BasicSettings />);
    // UnifiedUploader shows the translated upload hint in empty state
    expect(
      screen.getByText("拖拽图片或 Lumina 项目文件（图片支持多选）"),
    ).toBeInTheDocument();
  });

  it("routes a model file dropped anywhere in the converter to model surface upload", async () => {
    const file = new File(["solid"], "pegboard.STL", {
      type: "application/octet-stream",
    });

    render(<BasicSettings />);
    fireEvent.drop(window, {
      dataTransfer: {
        files: [file],
        types: ["Files"],
      },
    });

    await waitFor(() => {
      expect(converterApi.uploadModelSurface).toHaveBeenCalledWith(file);
    });
    const state = useConverterStore.getState();
    expect(state.modelSurfaceEnabled).toBe(true);
    expect(state.modelSurfaceFile).toBe(file);
    expect(state.imageFile).toBeNull();
  });

  it("does not tell users to pick a face when model surface analysis fails", async () => {
    vi.mocked(converterApi.uploadModelSurface).mockRejectedValueOnce(
      new Error("backend unavailable"),
    );
    const file = new File(["solid"], "pegboard.stl", {
      type: "application/octet-stream",
    });

    render(<BasicSettings />);
    fireEvent.drop(window, {
      dataTransfer: {
        files: [file],
        types: ["Files"],
      },
    });

    expect(await screen.findByText("模型分析失败")).toBeInTheDocument();
    expect(screen.queryByText("右侧点选面")).not.toBeInTheDocument();
    expect(
      screen.queryByText("请在右侧 3D 预览中旋转模型、选择或重选面；选好后再移动、旋转或缩放贴图。"),
    ).not.toBeInTheDocument();
    expect(useConverterStore.getState().modelSurfaceModelFileId).toBeNull();
  });

  it("routes an image file dropped anywhere in the converter to image upload", async () => {
    const file = new File(["img"], "artwork.jpg", { type: "image/jpeg" });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:artwork");

    render(<BasicSettings />);
    fireEvent.drop(window, {
      dataTransfer: {
        files: [file],
        types: ["Files"],
      },
    });

    await waitFor(() => {
      expect(useConverterStore.getState().imageFile).toBe(file);
    });
    expect(converterApi.uploadModelSurface).not.toHaveBeenCalled();
    expect(useConverterStore.getState().modelSurfaceFile).toBeNull();
  });

  it("keeps a dropped relief heightmap out of the main image uploader", async () => {
    const heightmap = new File(["heightmap"], "heightmap.png", {
      type: "image/png",
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:heightmap");
    useConverterStore.setState({
      enable_relief: true,
      autoHeightMode: "use-heightmap",
      heightmapFile: null,
      heightmapThumbnailUrl: null,
    });

    render(
      <>
        <BasicSettings />
        <ReliefSettings />
      </>,
    );

    fireEvent.drop(
      screen.getByRole("button", { name: "拖拽图片或点击上传" }),
      {
        dataTransfer: {
          files: [heightmap],
          types: ["Files"],
        },
      },
    );

    await waitFor(() => {
      expect(useConverterStore.getState().heightmapFile).toBe(heightmap);
    });
    expect(useConverterStore.getState().imageFile).toBeNull();
  });

  it("still routes model files dropped on a local image uploader to model surface upload", async () => {
    const model = new File(["solid"], "relief-source.stl", {
      type: "application/octet-stream",
    });
    useConverterStore.setState({
      enable_relief: true,
      autoHeightMode: "use-heightmap",
      heightmapFile: null,
    });

    render(
      <>
        <BasicSettings />
        <ReliefSettings />
      </>,
    );

    fireEvent.drop(
      screen.getByRole("button", { name: "拖拽图片或点击上传" }),
      {
        dataTransfer: {
          files: [model],
          types: ["Files"],
        },
      },
    );

    await waitFor(() => {
      expect(converterApi.uploadModelSurface).toHaveBeenCalledWith(model);
    });
    expect(useConverterStore.getState().modelSurfaceFile).toBe(model);
    expect(useConverterStore.getState().heightmapFile).toBeNull();
    expect(useConverterStore.getState().imageFile).toBeNull();
  });

  it("routes model and image files dropped together from a folder into the full surface workflow", async () => {
    const modelFile = new File(["solid"], "pegboard.obj", {
      type: "application/octet-stream",
    });
    const imageFile = new File(["img"], "artwork.png", { type: "image/png" });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:artwork");

    render(<BasicSettings />);
    fireEvent.drop(window, {
      dataTransfer: {
        files: [modelFile, imageFile],
        types: ["Files"],
      },
    });

    await waitFor(() => {
      expect(converterApi.uploadModelSurface).toHaveBeenCalledWith(modelFile);
      expect(useConverterStore.getState().imageFile).toBe(imageFile);
    });
    const state = useConverterStore.getState();
    expect(state.modelSurfaceEnabled).toBe(true);
    expect(state.modelSurfaceFile).toBe(modelFile);
  });

  it("lets users drop a model directly onto the model surface upload zone", async () => {
    const file = new File(["solid"], "pegboard.stl", {
      type: "application/octet-stream",
    });

    render(<BasicSettings />);
    fireEvent.click(screen.getByText("模型覆面").closest("label")!);

    const modelDropZone = await screen.findByRole("button", {
      name: "拖拽 STL/OBJ 模型到此处或点击上传",
    });
    fireEvent.drop(modelDropZone, {
      dataTransfer: {
        files: [file],
        types: ["Files"],
      },
    });

    await waitFor(() => {
      expect(converterApi.uploadModelSurface).toHaveBeenCalledWith(file);
    });
    const state = useConverterStore.getState();
    expect(state.modelSurfaceEnabled).toBe(true);
    expect(state.modelSurfaceFile).toBe(file);
    expect(state.imageFile).toBeNull();
  });

  it("forces single-sided structure and hides the irrelevant selector in model surface mode", () => {
    useConverterStore.setState({
      structure_mode: StructureModeEnum.DOUBLE_SIDED,
    } as never);

    render(<BasicSettings />);
    fireEvent.click(screen.getByText("模型覆面").closest("label")!);

    expect(useConverterStore.getState().structure_mode).toBe(
      StructureModeEnum.SINGLE_SIDED,
    );
    expect(screen.queryByText("结构模式")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "双面" })).not.toBeInTheDocument();
  });

  it("shows a global drop hint while dragging model and image files over the converter", () => {
    const modelFile = new File(["solid"], "pegboard.stl", {
      type: "application/octet-stream",
    });
    const imageFile = new File(["img"], "artwork.png", { type: "image/png" });

    render(<BasicSettings />);

    fireEvent.dragOver(window, {
      dataTransfer: {
        files: [modelFile],
        types: ["Files"],
      },
    });

    expect(screen.getByRole("status", { name: "拖拽导入文件" })).toHaveTextContent("导入模型");

    fireEvent.dragOver(window, {
      dataTransfer: {
        files: [imageFile],
        types: ["Files"],
      },
    });

    expect(screen.getByRole("status", { name: "拖拽导入文件" })).toHaveTextContent("导入图片");
  });

  it("lets users append one more image after a single image has a preview", async () => {
    const existingFile = new File(["existing"], "existing.jpg", { type: "image/jpeg" });
    const newFile = new File(["new"], "new.jpg", { type: "image/jpeg" });
    useConverterStore.setState({
      imageFile: existingFile,
      imagePreviewUrl: "data:image/jpeg;base64,fake",
      previewImageUrl: "/api/files/preview.png",
      batchMode: false,
      batchFiles: [],
    });

    render(<BasicSettings />);

    await waitFor(() => {
      expect(screen.getByText("点击更换或追加")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("点击更换或追加").closest("button")!);
    fireEvent.click(screen.getByText("添加更多图片"));

    const input = Array.from(
      document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
    ).find((candidate) => candidate.multiple);
    expect(input).toBeTruthy();
    fireEvent.change(input!, { target: { files: [newFile] } });

    await waitFor(() => {
      const state = useConverterStore.getState();
      expect(state.imageFile).toBeNull();
      expect(state.batchMode).toBe(true);
      expect(state.batchFiles).toEqual([existingFile, newFile]);
    });
    expect(screen.getByText("existing.jpg")).toBeInTheDocument();
    expect(screen.getByText("new.jpg")).toBeInTheDocument();
  });

  it("localizes large-format fallback warnings and shows the reason", () => {
    useConverterStore.setState({
      largeFormatEnabled: false,
      previewWarnings: [
        "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling. Unsupported features: text.",
      ],
      largeFormatWarnings: [
        "Raster fallback was used for this large-format SVG request.",
        "Native vector generation failed; raster fallback was used for this large-format SVG request.",
      ],
    });

    render(<BasicSettings />);

    expect(
      screen.getByText("此 SVG 含有原生大画幅暂不支持的特性（text），已改用栅格切片。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("本次大画幅 SVG 已改用栅格切片。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("原生矢量切片生成失败，已自动改用栅格切片。"),
    ).toBeInTheDocument();
  });

  it("localizes embedded wipe-tower warnings returned by large-format generation", () => {
    useConverterStore.setState({
      largeFormatWarnings: ["wipe_tower_manual_adjustment_required"],
    });

    render(<BasicSettings />);

    expect(
      screen.getByText(/文件已继续生成，但当前模型和擦料塔无法在所选热床上同时安全摆放/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("wipe_tower_manual_adjustment_required"),
    ).not.toBeInTheDocument();
  });

  it("renders the source version selector and legacy LUT database panel in old mode", () => {
    render(<BasicSettings />);

    expect(screen.getByText("来源类型")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "传统 LUT" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "反推LUT" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "LUT 品牌" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "LUT" })).not.toBeInTheDocument();
  });

  it("keeps a Snapmaker LUT independent from the configured Bambu printer", async () => {
    const snapmakerGroup: LutDetailsCatalogGroup = {
      manufacturer: "snapmaker",
      items: [
        {
          name: "快造&4色PLA&RYBW",
          path: "lut-ref/snapmaker-rybw.npy",
          fingerprint: "fp-snapmaker-rybw",
          color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
          compatibility_key: "sig-snapmaker-rybw",
          source_kind: "legacy_lookup",
          manufacturer: "snapmaker",
          material_type: "PLA",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["snapmaker", "rybw"],
        },
      ],
    };
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({
      groups: [snapmakerGroup],
    });
    vi.mocked(converterApi.fetchLutList).mockResolvedValue({
      luts: [
        {
          name: "snapmaker - 快造&4色PLA&RYBW",
          color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
          path: "lut-ref/snapmaker-rybw.npy",
          fingerprint: "fp-snapmaker-rybw",
        },
      ],
    });
    useConverterStore.setState({
      legacyCatalogGroups: [snapmakerGroup],
      selectedLegacyManufacturer: "",
      bed_label: "Bambu Lab P1S",
      bedSizes: [
        {
          label: "Bambu Lab P1S",
          width_mm: 256,
          height_mm: 256,
          is_default: false,
          printer_id: "bambu-p1s",
        },
      ],
    });
    useSettingsStore.setState({ printerModel: "bambu-p1s" });

    render(
      <>
        <BasicSettings />
        <BedSizeSelector />
      </>,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "LUT 品牌" }));
    fireEvent.click(screen.getByRole("option", { name: "snapmaker" }));

    await waitFor(() => {
      expect(useConverterStore.getState().selectedLegacyManufacturer)
        .toBe("snapmaker");
    });
    expect(useSettingsStore.getState().printerModel).toBe("bambu-p1s");
    expect(useConverterStore.getState().bed_label).toBe("Bambu Lab P1S");
    expect(screen.getByText("LUT 品牌")).toBeInTheDocument();
    expect(screen.getByText("打印机热床")).toBeInTheDocument();
    expect(
      screen.getByText("Bambu Lab P1S · 256×256 毫米"),
    ).toBeInTheDocument();
  });

  it("shows the inferred white material as the base plate when no backing is persisted", async () => {
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValueOnce({
      status: "success",
      message: "ok",
      materials: [
        makeMaterial("brand/pla-green", "Green PLA"),
        makeMaterial("brand/pla-yellow", "Yellow PLA"),
        makeMaterial("brand/pla-white", "White PLA"),
      ],
    });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [
        "brand/pla-green",
        "brand/pla-yellow",
        "brand/pla-white",
      ],
      materialBackingMaterialDirName: null,
    });

    render(<BasicSettings />);

    const backingDropdown = screen.getByRole("combobox", { name: "底板耗材" });
    await waitFor(() => {
      expect(backingDropdown).toHaveTextContent("3. White PLA");
    });
  });

  it("shows fixed material layers by default and swaps to the dynamic range controls", () => {
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: ["brand/pla-white"],
      materialLayerCount: 7,
      materialDynamicLayerCountEnabled: false,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 10,
    } as never);

    render(<BasicSettings />);

    const dynamicToggle = screen.getByRole("checkbox", {
      name: /动态调整有效叠层数/,
    });
    expect(dynamicToggle).not.toBeChecked();
    expect(screen.getByRole("slider", { name: "叠色层数" })).toHaveValue("7");
    expect(
      screen.queryByRole("slider", { name: "最小有效叠层数" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "穷举缓存…" })).toBeInTheDocument();

    fireEvent.click(dynamicToggle);

    expect(useConverterStore.getState().materialDynamicLayerCountEnabled).toBe(
      true,
    );
    expect(
      screen.queryByRole("slider", { name: "叠色层数" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("slider", { name: "最小有效叠层数" }),
    ).toHaveAttribute("step", "1");
    expect(
      screen.getByRole("slider", { name: "最大有效叠层数" }),
    ).toHaveAttribute("max", "10");
    expect(screen.getByText(/范围内自动加载/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "穷举缓存…" }),
    ).not.toBeInTheDocument();
  });

  it("couples dynamic material range controls in both edit directions", () => {
    useConverterStore.setState({
      source_version: "material",
      materialDynamicLayerCountEnabled: true,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 7,
    } as never);

    render(<BasicSettings />);

    fireEvent.change(
      screen.getByRole("slider", { name: "最小有效叠层数" }),
      { target: { value: "9" } },
    );
    expect(useConverterStore.getState()).toMatchObject({
      materialMinLayerCount: 9,
      materialMaxLayerCount: 9,
    });

    fireEvent.change(
      screen.getByRole("slider", { name: "最大有效叠层数" }),
      { target: { value: "6" } },
    );
    expect(useConverterStore.getState()).toMatchObject({
      materialMinLayerCount: 6,
      materialMaxLayerCount: 6,
    });
  });

  it("does not expose dynamic material controls for non-material sources", () => {
    useConverterStore.setState({
      source_version: "legacy",
      materialDynamicLayerCountEnabled: true,
    } as never);

    render(<BasicSettings />);

    expect(
      screen.queryByRole("checkbox", { name: "动态调整有效叠层数" }),
    ).not.toBeInTheDocument();
  });

  it("lets users retry a failed material-library load from the picker", async () => {
    vi.mocked(extractorApi.listGradientCardMaterials)
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({
        status: "success",
        message: "ok",
        materials: [makeMaterial("JAYO/red-pla", "Red PLA")],
      });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [],
      materialBackingMaterialDirName: null,
    });

    render(<BasicSettings />);

    await waitFor(() => {
      expect(extractorApi.listGradientCardMaterials).toHaveBeenCalledOnce();
    });
    fireEvent.click(screen.getByTestId("material-picker-trigger"));
    expect(
      await screen.findByTestId("material-picker-load-error"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => {
      expect(extractorApi.listGradientCardMaterials).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Red PLA")).toBeInTheDocument();
  });

  it("reconciles renamed material selections imported after the library loads", async () => {
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValueOnce({
      status: "success",
      message: "ok",
      materials: [makeMaterial("Karvax/Karvax PLA 耀石黑", "Karvax PLA 耀石黑")],
    });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [],
      materialBackingMaterialDirName: null,
    });

    render(<BasicSettings />);

    fireEvent.click(screen.getByTestId("material-picker-trigger"));
    await screen.findByText("Karvax PLA 耀石黑");

    act(() => {
      useConverterStore.getState().importRecipeState(
        {
          source_version: "material",
          selectedMaterialDirNames: ["无境新材/无境新材 PLA 耀石黑"],
          materialBackingMaterialDirName: "无境新材/无境新材 PLA 耀石黑",
        },
        new File(["recipe"], "recipe.png", { type: "image/png" }),
      );
    });

    await waitFor(() => {
      expect(useConverterStore.getState().selectedMaterialDirNames).toEqual([
        "Karvax/Karvax PLA 耀石黑",
      ]);
      expect(useConverterStore.getState().materialBackingMaterialDirName).toBe(
        "Karvax/Karvax PLA 耀石黑",
      );
    });
  });

  it("shows brand options from the loaded legacy details catalog", () => {
    render(<BasicSettings />);

    fireEvent.click(screen.getByRole("combobox", { name: "LUT 品牌" }));

    expect(screen.getByRole("option", { name: "Brand A" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Brand B" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "个人" })).toBeInTheDocument();
  });

  it("enables grouped LUT choices after selecting a legacy brand", async () => {
    render(<BasicSettings />);

    fireEvent.click(screen.getByRole("combobox", { name: "LUT 品牌" }));
    fireEvent.click(screen.getByRole("option", { name: "Brand A" }));

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "LUT 品牌" }))
        .toHaveTextContent("Brand A");
      expect(screen.getByText(/品牌信息/)).toBeInTheDocument();
    });
    expect(useConverterStore.getState().selectedLegacyManufacturer)
      .toBe("Brand A");
    expect(useConverterStore.getState().legacyCatalogGroups).toHaveLength(3);

    await waitFor(() => {
      expect(screen.getByText(/品牌信息/)).toBeInTheDocument();
      expect(screen.getAllByText(/数据库/).length).toBeGreaterThan(0);
    });
    const fourColor = screen.getByRole("checkbox", { name: "A 4C" });
    const alternateFourColor = screen.getByRole("checkbox", {
      name: "A 4C Alt",
    });
    const eightColor = screen.getByRole("checkbox", { name: "A 8C" });
    expect(fourColor).toBeEnabled();
    expect(alternateFourColor).toBeEnabled();
    expect(eightColor).toBeEnabled();

    fireEvent.click(fourColor);
    fireEvent.click(eightColor);

    await waitFor(() => {
      expect(useConverterStore.getState().lut_names).toEqual([
        "Brand A - A4",
        "Brand A - A8",
      ]);
    });
  });

  it("submits the LUTManager name when a catalog LUT path maps to a shorter legacy LUT name", async () => {
    render(<BasicSettings />);

    fireEvent.click(screen.getByRole("combobox", { name: "LUT 品牌" }));
    fireEvent.click(screen.getByRole("option", { name: "Brand A" }));

    const fourColor = await screen.findByRole("checkbox", { name: "A 4C" });
    fireEvent.click(fourColor);

    await waitFor(() => {
      expect(useConverterStore.getState().lut_name).toBe("Brand A - A4");
    });
    expect(fourColor).toBeChecked();
    expect(screen.getByText(/数据库/).parentElement).toHaveTextContent("A 4C");
  });

  it("hides LUT choices until LUTManager names are mapped", () => {
    useConverterStore.setState({
      selectedLegacyManufacturer: "Brand A",
      lutListFull: [],
      lutListLoading: true,
      lut_name: "",
    } as never);

    render(<BasicSettings />);

    expect(screen.queryByRole("checkbox", { name: "A 4C" })).not.toBeInTheDocument();
    expect(screen.getByText("品牌目录加载中…")).toBeInTheDocument();
    expect(useConverterStore.getState().lut_name).toBe("");
  });

  it("syncs the legacy brand after a hydrated lut_name catalog fetch", async () => {
    useConverterStore.setState({
      legacyCatalogGroups: [],
      selectedLegacyManufacturer: "",
      lut_name: "Brand B - BW",
    } as never);

    render(<BasicSettings />);

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "LUT 品牌" }))
        .toHaveTextContent("Brand B");
    });
  });

  it("renders only the BambuLab native brand in native mode", async () => {
    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "bambulab_pla",
      selectedNativeDbNames: ["DB-B", "DB-C"],
    } as never);

    render(<BasicSettings />);

    expect(screen.getByRole("combobox", { name: "品牌" })).toBeInTheDocument();
    expect(screen.getByText(/品牌信息/)).toBeInTheDocument();
    expect(screen.getAllByText("Bambu PLA")).not.toHaveLength(0);
    expect(screen.getByText("材质类型: PLA")).toBeInTheDocument();
    expect(screen.getByText("供应商: Bambu Lab")).toBeInTheDocument();
    expect(screen.getByText(/数据库/)).toBeInTheDocument();
    expect(screen.getByText("DB-A")).toBeInTheDocument();
    expect(screen.getByText("DB-B")).toBeInTheDocument();
    expect(screen.getByText("DB-C")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("combobox", { name: "品牌" }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Bambu PLA" })).toBeInTheDocument();
  });

  it("renders a native layer-count slider instead of the mode dropdown", () => {
    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "bambulab_pla",
      selectedNativeDbNames: ["DB-B", "DB-C"],
      color_layers: 5,
      layer_height_mm: 0.08,
    } as never);

    render(<BasicSettings />);

    expect(screen.getByRole("slider", { name: "层数" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "层数" })).toHaveAttribute("min", "1");
    expect(screen.getByRole("slider", { name: "层数" })).toHaveAttribute("max", "15");
    expect(screen.getByRole("slider", { name: "层数" })).toHaveAttribute("step", "1");
    expect(screen.queryByRole("combobox", { name: "动态层模式" })).not.toBeInTheDocument();
  });

  it("renders object-shaped native DB options without React key or child warnings", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [
        {
          brand_key: "bambulab_pla",
          material_type: "PLA",
          vendor: "Bambu Lab",
          display_name: "Bambu PLA",
          db_options: [makeDbOption("DB-A"), makeDbOption("DB-B")],
          default_db_names: ["DB-A"],
          supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
        },
      ],
      selectedNativeBrandKey: "bambulab_pla",
      selectedNativeDbNames: ["DB-A"],
    } as never);

    render(<BasicSettings />);

    const errorMessages = consoleErrorSpy.mock.calls
      .flatMap((call) => call)
      .map((value) => String(value));

    expect(errorMessages).not.toEqual(
      expect.arrayContaining([
        expect.stringContaining("Objects are not valid as a React child"),
      ]),
    );
    expect(errorMessages).not.toEqual(
      expect.arrayContaining([
        expect.stringContaining("Encountered two children with the same key"),
      ]),
    );
  });

  it("renders the predictive model controls for predictive native sources", () => {
    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "bambulab_pla",
      selectedNativeDbNames: ["DB-B", "DB-C"],
      color_layers: 5,
      layer_height_mm: 0.08,
    } as never);

    render(<BasicSettings />);

    expect(screen.getByRole("checkbox", { name: "模型辅助匹配" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "仅模型匹配" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "模型阈值" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "模型边距" })).not.toBeInTheDocument();
  });

  it("shows dynamic layer controls for predictive sources", () => {
    useConverterStore.setState({
      lut_name: "ReferencePack - bambulab_pla",
      selectedLutInfo: {
        name: "ReferencePack - bambulab_pla",
        color_mode: "8-Color Max",
        color_count: 64,
        max_color_layers: 10,
        layer_height_mm: 0.08,
        supports_predictive_match: true,
        supports_dynamic_layer_count: true,
        supports_custom_recipe: true,
        source_kind: "predictive_package",
        supported_modes: [
          { color_layers: 5, layer_height_mm: 0.08 },
          { color_layers: 10, layer_height_mm: 0.08 },
        ],
      },
      color_layers: 5,
      layer_height_mm: 0.08,
    } as never);

    render(<BasicSettings />);

    expect(screen.getByText("叠色层数")).toBeInTheDocument();
    expect(screen.getByText("叠色层高")).toBeInTheDocument();
    expect(screen.getByText(/支持模式/)).toBeInTheDocument();
  });

  it("does not render predictive model controls in legacy mode", () => {
    render(<BasicSettings />);

    expect(screen.queryByRole("checkbox", { name: "模型辅助匹配" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "仅模型匹配" })).not.toBeInTheDocument();
  });

  it("does not render predictive model controls for non-predictive native brands", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [{
        brand_key: "plain-pla",
        material_type: "PLA",
        vendor: "Vendor B",
        display_name: "Vendor B PLA",
        db_options: [makeDbOption("DB-X")],
        default_db_names: ["DB-X"],
        supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
      }],
      selectedNativeBrandKey: "plain-pla",
      selectedNativeDbNames: ["DB-X"],
      color_layers: 5,
      layer_height_mm: 0.08,
    } as never);

    render(<BasicSettings />);

    expect(screen.queryByRole("checkbox", { name: "模型辅助匹配" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "仅模型匹配" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "模型阈值" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "模型边距" })).not.toBeInTheDocument();
  });

  it("anchors the thickness slider to the 0.08mm layer grid", () => {
    render(<BasicSettings />);

    const slider = screen.getByRole("slider", { name: "厚度" }) as HTMLInputElement;
    const min = Number(slider.min);
    const max = Number(slider.max);
    const step = Number(slider.step);

    expect(step).toBeCloseTo(0.08, 10);
    expect(isMultipleOfStep(min, step)).toBe(true);
    expect(isMultipleOfStep(max, step)).toBe(true);

    for (let value = min; value <= max + 1e-9; value = Number((value + step).toFixed(10))) {
      expect(isMultipleOfStep(value, step)).toBe(true);
    }
  });

  it("snaps manually entered thickness to the exported 0.08mm layer grid", async () => {
    render(<BasicSettings />);

    const input = screen.getByRole("textbox", { name: "厚度 value" });
    fireEvent.change(input, { target: { value: "0.3" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(useConverterStore.getState().spacer_thick).toBeCloseTo(0.32, 10);
    expect(useConverterStore.getState().base_spacer_thick).toBeCloseTo(0.32, 10);
    await waitFor(() => expect(input).toHaveValue("0.32"));

    fireEvent.change(input, { target: { value: "0.36" } });
    fireEvent.blur(input);

    expect(useConverterStore.getState().spacer_thick).toBeCloseTo(0.32, 10);
    expect(useConverterStore.getState().base_spacer_thick).toBeCloseTo(0.32, 10);
    await waitFor(() => expect(input).toHaveValue("0.32"));

    fireEvent.change(input, { target: { value: "1.88" } });
    fireEvent.blur(input);

    expect(useConverterStore.getState().spacer_thick).toBeCloseTo(1.84, 10);
    expect(useConverterStore.getState().base_spacer_thick).toBeCloseTo(1.84, 10);
    await waitFor(() => expect(input).toHaveValue("1.84"));

    fireEvent.change(input, { target: { value: "2.36" } });
    fireEvent.blur(input);

    expect(useConverterStore.getState().spacer_thick).toBeCloseTo(2.32, 10);
    expect(useConverterStore.getState().base_spacer_thick).toBeCloseTo(2.32, 10);
    await waitFor(() => expect(input).toHaveValue("2.32"));
  });

  it("disables structure and large-format controls while fridge mode is enabled", () => {
    useConverterStore.setState({
      enable_fridge_magnet: true,
      largeFormatEnabled: false,
      structure_mode: StructureModeEnum.SINGLE_SIDED,
    } as never);

    render(<BasicSettings />);

    expect(
      screen.getByRole("checkbox", { name: /大画幅模式/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("radio", { name: "单面" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("radio", { name: "双面" }),
    ).toBeDisabled();
  });
});
