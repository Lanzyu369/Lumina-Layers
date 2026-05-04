import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import BasicSettings from "../components/sections/BasicSettings";
import { useConverterStore } from "../stores/converter";
import * as lutApi from "../api/lut";
import {
  ColorMode as ColorModeEnum,
  StructureMode as StructureModeEnum,
  ModelingMode as ModelingModeEnum,
} from "../api/types";
import type { LutDetailsCatalogGroup } from "../api/types";

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

function makeLegacyCatalogGroups(): LutDetailsCatalogGroup[] {
  return [
    {
      manufacturer: "Brand A",
      items: [
        {
          name: "A 4C",
          path: "/a4.npy",
          fingerprint: "fp-a4",
          color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
          source_kind: "legacy_lookup",
          manufacturer: "Brand A",
          material_type: "",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["brand", "a", "4c"],
        },
        {
          name: "A 8C",
          path: "/a8.npy",
          fingerprint: "fp-a8",
          color_mode: ColorModeEnum.EIGHT_COLOR,
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
          path: "/bbw.npy",
          fingerprint: "fp-bbw",
          color_mode: ColorModeEnum.BW,
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
          path: "/loose.npy",
          fingerprint: "fp-loose",
          color_mode: ColorModeEnum.MERGED,
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
        path: "/a4.npy",
        fingerprint: "fp-a4",
      },
      {
        name: "Brand A - A8",
        color_mode: ColorModeEnum.EIGHT_COLOR,
        path: "/a8.npy",
        fingerprint: "fp-a8",
      },
      {
        name: "Brand B - BW",
        color_mode: ColorModeEnum.BW,
        path: "/bbw.npy",
        fingerprint: "fp-bbw",
      },
      {
        name: "Loose Merged",
        color_mode: ColorModeEnum.MERGED,
        path: "/loose.npy",
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
    previewWarnings: [],
    largeFormatWarnings: [],
  });
});

afterEach(() => {
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

function isMultipleOfStep(value: number, step: number): boolean {
  const ratio = value / step;
  return Math.abs(ratio - Math.round(ratio)) < 1e-9;
}

describe("BasicSettings", () => {
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
    expect(screen.getByText("拖拽图片或点击上传（支持多选）")).toBeInTheDocument();
  });

  it("renders large-format warnings when present", () => {
    useConverterStore.setState({
      largeFormatEnabled: false,
      previewWarnings: [
        "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling. Unsupported features: text.",
      ],
      largeFormatWarnings: [
        "Raster fallback was used for this large-format SVG request.",
      ],
    });

    render(<BasicSettings />);

    expect(
      screen.getByText(/Native vector large-format is unavailable/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Raster fallback was used/i),
    ).toBeInTheDocument();
  });

  it("renders the source version selector and legacy LUT dropdown in old mode", () => {
    render(<BasicSettings />);

    expect(screen.getByText("来源类型")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "传统 LUT" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "反推LUT" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "品牌" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "LUT" })).toBeInTheDocument();
  });

  it("shows brand options from the loaded legacy details catalog", () => {
    render(<BasicSettings />);

    fireEvent.click(screen.getByRole("combobox", { name: "品牌" }));

    expect(screen.getByRole("option", { name: "Brand A" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Brand B" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "个人" })).toBeInTheDocument();
  });

  it("enables grouped LUT choices after selecting a legacy brand", async () => {
    render(<BasicSettings />);

    fireEvent.click(screen.getByRole("combobox", { name: "品牌" }));
    fireEvent.click(screen.getByRole("option", { name: "Brand A" }));

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "品牌" }))
        .toHaveTextContent("Brand A");
      expect(screen.getByRole("combobox", { name: "LUT" }))
        .not.toBeDisabled();
    });
    expect(useConverterStore.getState().selectedLegacyManufacturer)
      .toBe("Brand A");
    expect(useConverterStore.getState().legacyCatalogGroups).toHaveLength(3);

    const lutDropdown = screen.getByRole("combobox", { name: "LUT" });
    fireEvent.click(lutDropdown);
    await waitFor(() => expect(screen.getByRole("listbox")).toBeInTheDocument());

    await waitFor(() => {
      expect(lutDropdown).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByText("4 色")).toBeInTheDocument();
    });
    expect(screen.getByText("8 色")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "A 4C" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "A 8C" })).toBeInTheDocument();
  });

  it("submits the LUTManager name when a catalog LUT path maps to a shorter legacy LUT name", async () => {
    render(<BasicSettings />);

    fireEvent.click(screen.getByRole("combobox", { name: "品牌" }));
    fireEvent.click(screen.getByRole("option", { name: "Brand A" }));

    const lutDropdown = screen.getByRole("combobox", { name: "LUT" });
    await waitFor(() => expect(lutDropdown).not.toBeDisabled());
    fireEvent.click(lutDropdown);
    fireEvent.click(screen.getByRole("option", { name: "A 4C" }));

    await waitFor(() => {
      expect(useConverterStore.getState().lut_name).toBe("Brand A - A4");
    });
    expect(lutDropdown).toHaveTextContent("A 4C");
  });

  it("keeps the LUT dropdown disabled until LUTManager names are mapped", () => {
    useConverterStore.setState({
      selectedLegacyManufacturer: "Brand A",
      lutListFull: [],
      lutListLoading: true,
      lut_name: "",
    } as never);

    render(<BasicSettings />);

    const lutDropdown = screen.getByRole("combobox", { name: "LUT" });
    expect(lutDropdown).toBeDisabled();
    expect(screen.queryByRole("option", { name: "A 4C" })).not.toBeInTheDocument();
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
      expect(screen.getByRole("combobox", { name: "品牌" }))
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
