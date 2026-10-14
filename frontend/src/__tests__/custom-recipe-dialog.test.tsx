import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  RecipeHistoryItem,
  RecipeOverrideApplyResponse,
} from "../api/types";
import CustomRecipeDialog from "../components/ui/CustomRecipeDialog";

const applyRecipeOverrideMock = vi.hoisted(() => vi.fn());
const predictCustomRecipeMock = vi.hoisted(() => vi.fn());
const fetchRegionRecipeMock = vi.hoisted(() => vi.fn());
const converterStoreState = vi.hoisted(() => ({
  customRecipeHistory: [] as RecipeHistoryItem[],
  pushCustomRecipeHistory: vi.fn(),
  source_version: "legacy",
  selectedLutInfo: null as {
    supports_predictive_match?: boolean;
  } | null,
  materialDynamicLayerCountEnabled: false,
  selectedMaterialDirNames: [] as string[],
  materialSuggestions: null,
  materialSuggestionsLoading: false,
  materialSuggestionsError: null,
  fetchMaterialSuggestions: vi.fn(),
  applyCustomRecipeFromHistory: vi.fn(),
}));

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    applyRecipeOverride: applyRecipeOverrideMock,
    predictCustomRecipe: predictCustomRecipeMock,
    fetchRegionRecipe: fetchRegionRecipeMock,
  };
});

vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}));

vi.mock("../stores/converter", () => {
  const useConverterStore = (
    selector?: (state: typeof converterStoreState) => unknown,
  ) => (selector ? selector(converterStoreState) : converterStoreState);
  useConverterStore.getState = () => converterStoreState;
  return {
    useConverterStore,
    // The dialog also imports this pure predicate from the barrel. Mirror it
    // here instead of spreading the real module, which would load the network
    // clients this suite deliberately mocks out.
    isMaterialArchiveSourceVersion: (value: string | null | undefined) =>
      value === "material" || value === "lumina_box",
  };
});

const baseProps = {
  open: true,
  sessionId: "session-1",
  palette: [
    { color: "W", material: "white", hex: "ffffff" },
    { color: "R", material: "red", hex: "ff0000" },
  ],
  regionIds: ["region-1"],
  colorLayers: 2,
  layerHeightMm: 0.08,
  layerOrder: "Top2Bottom",
  baseChannelIdx: 0,
  currentRegionColorHex: null as string | null,
  onClose: vi.fn(),
  onApplied: vi.fn(),
};

function applyResponse(): RecipeOverrideApplyResponse {
  return {
    status: "ok",
    message: "ok",
    rgb: [255, 255, 255],
    lab: [100, 0, 0],
    source: "model",
    runtime_mode_key: "mode-a",
    preview_url: "/api/files/preview.png",
    preview_glb_url: null,
    override_count: 1,
  };
}

function renderDialog(
  overrides: Partial<typeof baseProps> = {},
): ReturnType<typeof render> {
  return render(<CustomRecipeDialog {...baseProps} {...overrides} />);
}

function apiValidationFailure(
  loc: Array<string | number>,
  msg = "Field required",
) {
  return Object.assign(new Error("Request failed with status code 422"), {
    response: {
      status: 422,
      data: {
        detail: [{ loc, msg }],
      },
      headers: {},
    },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

describe("CustomRecipeDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    converterStoreState.customRecipeHistory = [];
    converterStoreState.source_version = "legacy";
    converterStoreState.selectedLutInfo = null;
    converterStoreState.materialDynamicLayerCountEnabled = false;
    converterStoreState.selectedMaterialDirNames = [];
    converterStoreState.materialSuggestions = null;
    converterStoreState.materialSuggestionsLoading = false;
    converterStoreState.materialSuggestionsError = null;
    // Default: empty recipes so legacy tests keep their all-White / base-channel
    // synchronous default instead of racing with an async override. Tests that
    // exercise the "seed from real recipe" path override this with a custom
    // mockResolvedValue.
    // 默认返回空 recipes，让老测试保持"同步 base channel 默认"的行为不变；
    // 需要验证"用真实 recipe 作默认"的用例在自己里面显式覆盖 mock。
    fetchRegionRecipeMock.mockResolvedValue({
      status: "ok",
      message: "ok",
      recipes: [],
    });
  });

  it("renders each layer swatch from the palette hex", () => {
    renderDialog();

    fireEvent.change(
      screen.getByPlaceholderText("recipe_custom_pattern_placeholder"),
      { target: { value: "WR" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_pattern_apply" }),
    );

    // Swatches render the canonical primary hex (not the LUT-stored hex) so
    // the 8-primary visual stays consistent across LUT flavours.
    // 色块使用规范原色 hex（非 LUT 里的具体色值），保证 8 原色视觉在不同 LUT 间一致。
    expect(screen.getByTestId("recipe-layer-swatch-0")).toHaveStyle({
      backgroundColor: "rgb(245, 245, 245)",
    });
    expect(screen.getByTestId("recipe-layer-swatch-1")).toHaveStyle({
      backgroundColor: "rgb(229, 57, 53)",
    });
  });

  it("requires a second apply click before upgrading the layer count", async () => {
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    renderDialog({ colorLayers: 5 });

    const addLayerButton = screen.getByRole("button", {
      name: "recipe_custom_add_layer",
    });
    fireEvent.click(addLayerButton);
    fireEvent.click(addLayerButton);

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    expect(applyRecipeOverrideMock).not.toHaveBeenCalled();
    expect(
      screen.getByText("recipe_custom_layer_upgrade_warning"),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "recipe_custom_layer_upgrade_confirm",
      }),
    );

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    expect(applyRecipeOverrideMock.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        recipe: expect.arrayContaining([0]),
        color_layers: 7,
      }),
    );
    expect(applyRecipeOverrideMock.mock.calls[0]?.[0].recipe).toHaveLength(7);
  });

  it("disables prediction for LUT sources without a forward model", () => {
    renderDialog();

    expect(
      screen.getByRole("button", { name: "recipe_custom_predict" }),
    ).toBeDisabled();
    const notice = screen.getByText("recipe_custom_predict_no_forward_model");
    expect(notice).toBeInTheDocument();
    expect(notice.className).toContain("slate");
    expect(predictCustomRecipeMock).not.toHaveBeenCalled();
  });

  it("enables prediction for LUT sources that carry a forward model", () => {
    converterStoreState.selectedLutInfo = { supports_predictive_match: true };
    renderDialog();

    expect(
      screen.getByRole("button", { name: "recipe_custom_predict" }),
    ).not.toBeDisabled();
    expect(
      screen.queryByText("recipe_custom_predict_no_forward_model"),
    ).not.toBeInTheDocument();
  });

  it("allows applying when LUT prediction is unavailable", async () => {
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    const onApplied = vi.fn();
    renderDialog({ onApplied });

    const applyButton = screen.getByRole("button", {
      name: "recipe_custom_apply",
    });
    expect(applyButton).not.toBeDisabled();
    fireEvent.click(applyButton);

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce());
  });

  it("renders no-forward-model prediction failures as a neutral notice for material sources", async () => {
    converterStoreState.source_version = "material";
    predictCustomRecipeMock.mockRejectedValueOnce(
      new Error("No predictive runtime available for this source"),
    );
    renderDialog();

    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_predict" }),
    );

    const banner = await screen.findByTestId("recipe-error-banner");
    expect(banner).toHaveTextContent("recipe_custom_predict_no_forward_model");
    expect(banner.className).toContain("slate");
    expect(banner.className).not.toContain("red");
  });

  it("allows applying after a package-only prediction warning", async () => {
    converterStoreState.source_version = "material";
    predictCustomRecipeMock.mockRejectedValueOnce(
      new Error(
        "Recipe is not present in the runtime package; exact prediction unavailable for package-only source",
      ),
    );
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    const onApplied = vi.fn();
    renderDialog({ onApplied });

    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_predict" }),
    );

    const banner = await screen.findByTestId("recipe-error-banner");
    expect(banner).toHaveTextContent("recipe_custom_predict_no_forward_model");
    expect(banner.className).toContain("slate");

    const applyButton = screen.getByRole("button", {
      name: "recipe_custom_apply",
    });
    expect(applyButton).not.toBeDisabled();
    fireEvent.click(applyButton);

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce());
  });

  it("renders generic prediction failures as an error", async () => {
    converterStoreState.source_version = "material";
    predictCustomRecipeMock.mockRejectedValueOnce(new Error("network boom"));
    renderDialog();

    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_predict" }),
    );

    const banner = await screen.findByTestId("recipe-error-banner");
    expect(banner).toHaveTextContent("network boom");
    expect(banner.className).toContain("red");
    expect(banner.className).not.toContain("slate");
  });

  it("hides backend validation paths from prediction failures", async () => {
    converterStoreState.selectedLutInfo = { supports_predictive_match: true };
    predictCustomRecipeMock.mockRejectedValueOnce(
      apiValidationFailure(["body", "recipe"], "Recipe is required"),
    );
    renderDialog();

    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_predict" }),
    );

    const banner = await screen.findByTestId("recipe-error-banner");
    expect(banner).toHaveTextContent("recipe_custom_predict_failed");
    expect(banner).not.toHaveTextContent("body.recipe");
    expect(banner).not.toHaveTextContent("recipe: Recipe is required");
    expect(banner).not.toHaveTextContent("Request failed with status code 422");
    expect(banner.className).toContain("red");
    expect(banner.className).not.toContain("amber");
  });

  it("keeps non-target prediction validation details visible", async () => {
    converterStoreState.selectedLutInfo = { supports_predictive_match: true };
    predictCustomRecipeMock.mockRejectedValueOnce(
      apiValidationFailure(["body", "layer_order"], "Layer order is invalid"),
    );
    renderDialog();

    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_predict" }),
    );

    const banner = await screen.findByTestId("recipe-error-banner");
    expect(banner).toHaveTextContent("body.layer_order: Layer order is invalid");
    expect(banner).not.toHaveTextContent("recipe_custom_predict_failed");
    expect(banner.className).toContain("red");
    expect(banner.className).not.toContain("amber");
  });

  it("stays open after a successful apply and shows the applied banner", async () => {
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    const onClose = vi.fn();
    renderDialog({ onClose });

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    const banner = await screen.findByTestId("recipe-applied-banner");
    expect(banner).toHaveTextContent("recipe_custom_applied_toast");
    // Dialog must stay open so the user can keep tweaking / switch regions.
    expect(onClose).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "recipe_custom_apply" }),
    ).toBeInTheDocument();
  });

  it("normalizes generic apply API failures in the visible error banner", async () => {
    applyRecipeOverrideMock.mockRejectedValueOnce(
      Object.assign(new Error("Request failed with status code 500"), {
        response: {
          status: 500,
          data: {},
          headers: {},
        },
      }),
    );
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    const banner = await screen.findByTestId("recipe-error-banner");
    expect(banner).toHaveTextContent("服务器发生内部错误");
    expect(banner).not.toHaveTextContent("Request failed with status code 500");
  });

  it("hides backend validation paths from apply failures", async () => {
    applyRecipeOverrideMock.mockRejectedValueOnce(
      apiValidationFailure(
        ["body", "virtual_materials", 0, "hex"],
        "String should match pattern",
      ),
    );
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    const banner = await screen.findByTestId("recipe-error-banner");
    expect(banner).toHaveTextContent("recipe_custom_apply_failed");
    expect(banner).not.toHaveTextContent("body.virtual_materials.0.hex");
    expect(banner).not.toHaveTextContent("virtual_materials");
    expect(banner).not.toHaveTextContent("Request failed with status code 422");
  });

  it("restores the prior recipe when the undo button is clicked", () => {
    renderDialog({ colorLayers: 2 });

    // Undo is empty initially.
    const undoButton = screen.getByRole("button", {
      name: "recipe_custom_undo",
    });
    expect(undoButton).toBeDisabled();

    // Mutate the recipe: add a layer then remove index 0.
    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_add_layer" }),
    );
    // Now undo should be enabled; clicking it reverts to 2 layers.
    expect(undoButton).not.toBeDisabled();
    expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(3);

    fireEvent.click(undoButton);
    expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(2);
    expect(undoButton).toBeDisabled();
  });

  it("renders sortable drag handles without changing recipe payload shape", async () => {
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    renderDialog({
      palette: [
        { color: "White", material: "white", hex: "F5F5F5" },
        { color: "Red", material: "red", hex: "E53935" },
      ],
      colorLayers: 2,
    });

    fireEvent.change(
      screen.getByPlaceholderText("recipe_custom_pattern_placeholder"),
      { target: { value: "RW" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_pattern_apply" }),
    );

    expect(screen.getByTestId("recipe-layer-swatch-0")).toHaveStyle({
      backgroundColor: "rgb(229, 57, 53)",
    });
    expect(screen.getByTestId("recipe-layer-swatch-1")).toHaveStyle({
      backgroundColor: "rgb(245, 245, 245)",
    });

    const firstHandle = screen.getByTestId("recipe-layer-drag-handle-0");
    expect(firstHandle).toHaveAttribute("role", "button");
    expect(firstHandle).toHaveAttribute("aria-roledescription", "sortable");

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));
    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    expect(applyRecipeOverrideMock.mock.calls[0]?.[0].recipe).toEqual([1, 0]);
  });

  it("renders the current region swatch when a hex is provided", () => {
    renderDialog({ currentRegionColorHex: "#123456" });

    const swatch = screen.getByTestId("recipe-current-region-swatch");
    expect(swatch).toHaveStyle({ backgroundColor: "rgb(18, 52, 86)" });
    expect(swatch).toHaveAttribute("title", "#123456");
  });

  it("sends user-picked non-native primaries as virtual_materials on apply", async () => {
    // Simulate a CMYW LUT (no native Red / Green / Blue / Black). Picking
    // Red must ship a virtual_materials entry plus a recipe index at
    // palette.length + k rather than silently substituting Magenta.
    // 模拟 CMYW LUT：选 Red 应该发 virtual_materials + recipe 索引 = palette.length+k，
    // 而不是被悄悄代用成 Magenta。
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    renderDialog({
      palette: [
        { color: "White", material: "", hex: "F5F5F5" },
        { color: "Cyan", material: "", hex: "00B7EB" },
        { color: "Magenta", material: "", hex: "E6007E" },
        { color: "Yellow", material: "", hex: "FFD400" },
      ],
      colorLayers: 2,
    });

    // Use the pattern input to drive both layers to Red; "RR" maps through
    // the display palette and lands on the non-native Red primary.
    // pattern 输入 "RR" 把两层都设成非原生 Red。
    fireEvent.change(
      screen.getByPlaceholderText("recipe_custom_pattern_placeholder"),
      { target: { value: "RR" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_pattern_apply" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    const payload = applyRecipeOverrideMock.mock.calls[0]?.[0];
    expect(payload).toEqual(
      expect.objectContaining({
        color_layers: 2,
        virtual_materials: [
          { name: "Red", hex: "#E53935" },
        ],
      }),
    );
    // Every layer points at the virtual tail (palette.length + 0 == 4).
    expect(payload.recipe).toEqual([4, 4]);
  });

  it("uses selected material count for virtual primaries while material archive session palette is loading", async () => {
    // Material-archive mode now shows materials in original order without
    // canonical-primary grouping. When palette is empty, effectivePalette
    // falls back to selectedMaterialDirNames, and every entry is native.
    // 耗材档案模式现在直接按原始顺序显示材料，不做标准原色归类。
    // palette 为空时回退到 selectedMaterialDirNames，所有条目都是原生的。
    converterStoreState.source_version = "material";
    converterStoreState.selectedMaterialDirNames = [
      "brand/red-pla",
      "brand/green-pla",
      "brand/blue-pla",
      "brand/yellow-pla",
      "brand/cyan-pla",
    ];
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    renderDialog({ palette: [], colorLayers: 2 });

    // In material-archive mode with empty palette, the dropdown shows
    // selectedMaterialDirNames directly (e.g. "red-pla", "green-pla", ...).
    // Pattern "GG" selects index 1 (green-pla) for both layers by first letter.
    fireEvent.change(
      screen.getByPlaceholderText("recipe_custom_pattern_placeholder"),
      { target: { value: "GG" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_pattern_apply" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    const payload = applyRecipeOverrideMock.mock.calls[0]?.[0];
    expect(payload).toEqual(
      expect.objectContaining({
        recipe: [1, 1],
        color_layers: 2,
      }),
    );
    expect(payload).not.toHaveProperty("virtual_materials");
  });

  it("defaults material archive recipes to the native white channel when white is not slot zero", async () => {
    converterStoreState.source_version = "material";
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    renderDialog({
      palette: [
        {
          color: "瑞贝思 PLA 绿",
          material: "瑞贝思/瑞贝思 PLA 绿",
          hex: "43A047",
        },
        {
          color: "瑞贝思 PLA 黄",
          material: "瑞贝思/瑞贝思 PLA 黄",
          hex: "FFD400",
        },
        {
          color: "瑞贝思 PLA 白",
          material: "瑞贝思/瑞贝思 PLA 白",
          hex: "F5F5F5",
        },
      ],
      colorLayers: 3,
      baseChannelIdx: 0,
    });

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    const payload = applyRecipeOverrideMock.mock.calls[0]?.[0];
    expect(payload.recipe).toEqual([2, 2, 2]);
    expect(payload).not.toHaveProperty("virtual_materials");
  });

  it("maps material archive color names to native channels instead of virtual primaries", async () => {
    // Material-archive mode now shows materials in original order without
    // canonical-primary grouping. Recipe indices map directly to palette order.
    // 耗材档案模式现在直接按原始顺序显示材料，配方索引直接对应 palette 顺序。
    converterStoreState.source_version = "material";
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    renderDialog({
      palette: [
        {
          color: "Magenta PETG",
          material: "alice/Magenta PETG",
          hex: "E6007E",
        },
        {
          color: "Cyan PLA",
          material: "bob/Cyan PLA",
          hex: "00B7EB",
        },
        {
          color: "Yellow PETG",
          material: "alice/Yellow PETG",
          hex: "FFD400",
        },
        {
          color: "Red PETG",
          material: "alice/Red PETG",
          hex: "E53935",
        },
        {
          color: "White PETG",
          material: "alice/White PETG",
          hex: "F5F5F5",
        },
        {
          color: "Green PETG",
          material: "alice/Green PETG",
          hex: "43A047",
        },
      ],
      colorLayers: 3,
    });

    // Pattern uses first-letter mapping. "C" maps to index 1 (Cyan PLA),
    // "G" maps to index 5 (Green PETG). We use "?" to keep layer 1 as default.
    fireEvent.change(
      screen.getByPlaceholderText("recipe_custom_pattern_placeholder"),
      { target: { value: "C?G" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_pattern_apply" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    const payload = applyRecipeOverrideMock.mock.calls[0]?.[0];
    // Default recipe is all base channel (index 4 = white).
    // Pattern "C?G" sets layer 0 → 1 (Cyan), layer 1 stays default (4),
    // layer 2 → 5 (Green).
    expect(payload.recipe).toEqual([1, 4, 5]);
    expect(payload).not.toHaveProperty("virtual_materials");
  });

  it("omits virtual_materials when every picked primary is LUT-native", async () => {
    // Bare-bones palette already exposes W (native). Clicking apply without
    // touching the default recipe must NOT attach virtual_materials so the
    // legacy non-virtual payload shape is preserved for old bundles.
    // 全原生 palette 下默认配方应用，请求不得带 virtual_materials，保持
    // 旧 bundle 的负载形态不变。
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    const payload = applyRecipeOverrideMock.mock.calls[0]?.[0];
    expect(payload).not.toHaveProperty("virtual_materials");
  });

  it("pushes a recipe history entry after a successful apply", async () => {
    applyRecipeOverrideMock.mockResolvedValueOnce({
      ...applyResponse(),
      rgb: [10, 20, 30],
      lab: [40, 50, 60],
      source: "apply",
    });
    renderDialog({ colorLayers: 3, layerOrder: "Bottom2Top" });

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    await waitFor(() =>
      expect(converterStoreState.pushCustomRecipeHistory).toHaveBeenCalledOnce(),
    );
    expect(converterStoreState.pushCustomRecipeHistory).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "0-0-0@Bottom2Top",
        recipe: [0, 0, 0],
        layerOrder: "Bottom2Top",
        predictedRgb: [10, 20, 30],
        predictedLab: [40, 50, 60],
        hex: "#0A141E",
        fromModel: false,
      }),
    );
  });

  it("forwards virtual_materials to onApplied and persists them in history", async () => {
    // Regression for the generate-path virtual-material loss: apply must
    // hand the parent component the exact ``virtualMaterials`` list the
    // dialog computed so PalettePanel can persist them in
    // ``state.recipe_overrides``; history replay must carry them too so
    // ``applyCustomRecipeFromHistory`` does not regress into 422s / 3MF
    // missing objects on sparse LUTs.
    // generate 路径丢虚拟耗材的回归：apply 必须把 dialog 算出的
    // virtualMaterials 原样交给父组件存进 recipe_overrides；历史条目也必须
    // 带上 virtuals，不然在稀疏 LUT 上重放会 422 / 3MF 缺对象。
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    const onApplied = vi.fn();
    renderDialog({
      palette: [
        { color: "White", material: "", hex: "F5F5F5" },
        { color: "Cyan", material: "", hex: "00B7EB" },
        { color: "Magenta", material: "", hex: "E6007E" },
        { color: "Yellow", material: "", hex: "FFD400" },
      ],
      colorLayers: 2,
      onApplied,
    });

    fireEvent.change(
      screen.getByPlaceholderText("recipe_custom_pattern_placeholder"),
      { target: { value: "RR" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_pattern_apply" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce());
    const onAppliedArgs = onApplied.mock.calls[0] ?? [];
    // onApplied signature: (response, recipe, colorLayers, layerHeightMm, virtuals)
    expect(onAppliedArgs).toHaveLength(5);
    expect(onAppliedArgs[4]).toEqual([{ name: "Red", hex: "#E53935" }]);

    // History entry must carry virtuals too so replay can round-trip them.
    await waitFor(() =>
      expect(converterStoreState.pushCustomRecipeHistory).toHaveBeenCalledOnce(),
    );
    expect(converterStoreState.pushCustomRecipeHistory).toHaveBeenCalledWith(
      expect.objectContaining({
        virtualMaterials: [{ name: "Red", hex: "#E53935" }],
      }),
    );
  });

  // Canonical-name palette: "White" / "Red" match ``DISPLAY_PRIMARY_ORDER``
  // entries case-insensitively, so ``buildDisplayPalette`` marks them
  // ``native`` in-place at indices 0 (White) and 5 (Red) with canonical
  // primary hex ``#F5F5F5`` / ``#E53935``. ``baseProps`` uses short labels
  // "W" / "R" which would instead land the native copies at the 8+ tail
  // (``ffffff`` / ``ff0000``) — good for legacy LUT coverage but not what
  // these seed-from-real-recipe tests want to assert on.
  // 用规范名的 palette：White / Red 在 buildDisplayPalette 的主循环里就
  // 被标为 native（索引 0 / 5），hex 走规范色 #F5F5F5 / #E53935。baseProps
  // 的短名 "W" / "R" 会把 native 条目追加到 8+ 位（hex 是 LUT 原值
  // ffffff / ff0000），适合老 LUT 兼容，但这几条新测试想断言规范色。
  const canonicalNamePalette = [
    { color: "White", material: "white", hex: "F5F5F5" },
    { color: "Red", material: "red", hex: "E53935" },
  ];

  it("seeds the per-layer recipe from the region's real matched stack on open", async () => {
    // Regression for "自定义配方编辑器每一层永远默认全白". Before the fix
    // the dialog unconditionally initialised ``recipe`` to White / base
    // channel via ``buildDefaultRecipe``, so clicking Apply after opening
    // silently overwrote the region's real matched recipe. After the fix
    // the dialog fetches ``/region-recipe`` on open and pre-populates the
    // per-layer dropdowns with the backend's LUT-channel indices,
    // translated to ``displayPalette`` indices so the canonical-primary
    // swatches echo the actual recipe. 打开对话框时要用该区域真实匹配
    // 的配方作为默认，而不是全白；下方的 layer swatch 颜色锁定了
    // LUT → displayPalette 索引翻译路径。
    fetchRegionRecipeMock.mockResolvedValueOnce({
      status: "ok",
      message: "ok",
      recipes: [
        {
          region_id: "region-1",
          // LUT channels: 0=White, 1=Red. Top2Bottom so index 0 = top.
          // 期望下拉翻译：layer 0 → Red swatch、layer 1 → White swatch。
          recipe: [1, 0],
          color_layers: 2,
          layer_height_mm: 0.08,
          layer_order: "Top2Bottom",
        },
      ],
    });

    renderDialog({ palette: canonicalNamePalette });

    // Endpoint called with the dialog's session / region / layer-order
    // props — this is the contract PalettePanel relies on.
    await waitFor(() => expect(fetchRegionRecipeMock).toHaveBeenCalledOnce());
    expect(fetchRegionRecipeMock).toHaveBeenCalledWith({
      session_id: "session-1",
      region_ids: ["region-1"],
      layer_order: "Top2Bottom",
    });

    // Swatches echo the fetched recipe: Red on top, White underneath.
    // If the fetch path regressed and the dialog kept the synchronous
    // default both layers would render White — this is the exact bug
    // report ("永远默认全白").
    await waitFor(() =>
      expect(screen.getByTestId("recipe-layer-swatch-0")).toHaveStyle({
        backgroundColor: "rgb(229, 57, 53)",
      }),
    );
    expect(screen.getByTestId("recipe-layer-swatch-1")).toHaveStyle({
      backgroundColor: "rgb(245, 245, 245)",
    });
  });

  it("keeps the fetched actual layer count in dynamic material mode", async () => {
    converterStoreState.source_version = "material";
    converterStoreState.materialDynamicLayerCountEnabled = true;
    converterStoreState.selectedMaterialDirNames = ["white", "red"];
    fetchRegionRecipeMock.mockResolvedValueOnce({
      status: "ok",
      message: "ok",
      recipes: [
        {
          region_id: "region-1",
          recipe: [1, 0, 1, 0, 1, 0],
          color_layers: 6,
          layer_height_mm: 0.08,
          layer_order: "Top2Bottom",
        },
      ],
    });
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());

    renderDialog({ palette: canonicalNamePalette, colorLayers: 9 });

    await waitFor(() =>
      expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(6),
    );
    fireEvent.change(
      screen.getByPlaceholderText("recipe_custom_pattern_placeholder"),
      { target: { value: "RWRWRW" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_pattern_apply" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    expect(applyRecipeOverrideMock.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        recipe: expect.any(Array),
        color_layers: 6,
      }),
    );
    expect(applyRecipeOverrideMock.mock.calls[0]?.[0].recipe).toHaveLength(6);
  });

  it("falls back to the synchronous default recipe when the region-recipe fetch fails", async () => {
    // The dialog must remain usable when the backend sampling errors —
    // otherwise a transient 500 / 409 would leave the dropdowns in an
    // unrecoverable state. After the failure we must see the legacy
    // all-White / base-channel default (the apply-time safety net that
    // predates this fix). 请求失败时退回全白默认，保证对话框依旧可用。
    fetchRegionRecipeMock.mockRejectedValueOnce(new Error("boom"));

    renderDialog({ palette: canonicalNamePalette });

    await waitFor(() => expect(fetchRegionRecipeMock).toHaveBeenCalledOnce());
    // Both layers stay on the base-channel (White, canonical primary) default;
    // the failed fetch must NOT surface as a visible error banner in the
    // dialog because the user hasn't done anything yet. 请求失败后两层
    // 都保持 White 默认且不冒 error banner，用户未交互不该看到错误。
    expect(screen.getByTestId("recipe-layer-swatch-0")).toHaveStyle({
      backgroundColor: "rgb(245, 245, 245)",
    });
    expect(screen.getByTestId("recipe-layer-swatch-1")).toHaveStyle({
      backgroundColor: "rgb(245, 245, 245)",
    });
    expect(screen.queryByTestId("recipe-error-banner")).toBeNull();
  });

  it("does not fetch the region recipe when the dialog opens without a session", () => {
    // Recipe-history replay can open the dialog before a session is wired
    // up (e.g. in Storybook / local dev without a backend). The fetch is
    // pointless in that case and an attempted POST would noise up the
    // devtools; the dialog falls back to its synchronous default.
    // 没有 session 时不发请求（用于 Storybook / 本地无后端场景），让
    // 对话框安静地退回同步默认值。
    renderDialog({ sessionId: "", palette: canonicalNamePalette });
    expect(fetchRegionRecipeMock).not.toHaveBeenCalled();
  });

  it("reverses the fetched recipe when the LUT uses Bottom2Top layer order", async () => {
    // Bottom2Top LUTs ship ``layerOrder: "Bottom2Top"`` through
    // PalettePanel; the backend honours this and returns the recipe
    // already flipped so the dropdown row 0 consistently represents the
    // bottom-most layer. This test locks the end-to-end axis contract:
    // a Bottom2Top fetch result [0, 1] (bottom=White, top=Red) renders
    // layer swatch 0 = White and layer swatch 1 = Red. 若 axis 契约
    // 回归，这里的断言会立即发现。
    fetchRegionRecipeMock.mockResolvedValueOnce({
      status: "ok",
      message: "ok",
      recipes: [
        {
          region_id: "region-1",
          // Bottom2Top: index 0 = bottom (White), index 1 = top (Red).
          recipe: [0, 1],
          color_layers: 2,
          layer_height_mm: 0.08,
          layer_order: "Bottom2Top",
        },
      ],
    });

    renderDialog({ palette: canonicalNamePalette, layerOrder: "Bottom2Top" });

    await waitFor(() => expect(fetchRegionRecipeMock).toHaveBeenCalledOnce());
    expect(fetchRegionRecipeMock).toHaveBeenCalledWith({
      session_id: "session-1",
      region_ids: ["region-1"],
      layer_order: "Bottom2Top",
    });

    await waitFor(() =>
      expect(screen.getByTestId("recipe-layer-swatch-0")).toHaveStyle({
        backgroundColor: "rgb(245, 245, 245)",
      }),
    );
    expect(screen.getByTestId("recipe-layer-swatch-1")).toHaveStyle({
      backgroundColor: "rgb(229, 57, 53)",
    });
  });

  it("does not attach virtualMaterials on history entries when no virtual primary is used", async () => {
    // All-native recipes must keep the legacy history shape (no
    // ``virtualMaterials`` key) so old exports / tests that spread the
    // entry keep binary-compatible behaviour.
    // 全原生配方时历史条目不带 virtualMaterials，保持老格式二进制兼容。
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    await waitFor(() =>
      expect(converterStoreState.pushCustomRecipeHistory).toHaveBeenCalledOnce(),
    );
    const entry = converterStoreState.pushCustomRecipeHistory.mock.calls[0]?.[0];
    expect(entry).not.toHaveProperty("virtualMaterials");
  });

  it("keeps a clicked history recipe when the parent rerenders with the same regions", async () => {
    // PalettePanel builds ``regionIds`` inline, so store updates caused by
    // history replay can rerender the parent with a fresh array instance even
    // when the selected regions did not actually change. The dialog must key
    // its open/fetch effect by region contents, not array identity, otherwise
    // clicking a history row immediately resets all per-layer pickers back to
    // the fetched/default recipe ("历史配方一点，每层颜色乱跳").
    // PalettePanel 会内联构造 regionIds；历史重放触发 store 更新后，父组件
    // 可能传进一个内容相同但引用全新的数组。Dialog 的初始化 effect 必须
    // 按 region 内容判断是否变化，不能按数组引用，否则点历史后每层颜色会
    // 立刻被重置，看起来像乱跳。
    const historyEntry: RecipeHistoryItem = {
      id: "1-1@Top2Bottom",
      recipe: [1, 1],
      layerOrder: "Top2Bottom",
      predictedRgb: [229, 57, 53],
      predictedLab: [50, 60, 70],
      hex: "#E53935",
      fromModel: false,
      createdAtMs: 1,
      displayHexes: ["#E53935", "#E53935"],
      displayLabels: ["Red", "Red"],
    };
    converterStoreState.customRecipeHistory = [historyEntry];

    const { rerender } = renderDialog({
      palette: canonicalNamePalette,
      regionIds: ["region-1"],
    });

    fireEvent.click(
      screen.getByTestId("recipe-history-row-1-1@Top2Bottom"),
    );

    await waitFor(() =>
      expect(screen.getByTestId("recipe-layer-swatch-0")).toHaveStyle({
        backgroundColor: "rgb(229, 57, 53)",
      }),
    );

    rerender(
      <CustomRecipeDialog
        {...baseProps}
        palette={canonicalNamePalette.map((entry) => ({ ...entry }))}
        regionIds={["region-1"]}
      />,
    );

    await waitFor(() => expect(fetchRegionRecipeMock).toHaveBeenCalledOnce());
    expect(screen.getByTestId("recipe-layer-swatch-0")).toHaveStyle({
      backgroundColor: "rgb(229, 57, 53)",
    });
    expect(screen.getByTestId("recipe-layer-swatch-1")).toHaveStyle({
      backgroundColor: "rgb(229, 57, 53)",
    });
  });

  it("keeps a longer history recipe through the color layer count update", async () => {
    // Applying a history recipe can also update store.color_layers. That makes
    // PalettePanel pass a larger ``colorLayers`` prop on the next render. The
    // dialog should keep the history recipe the user just chose instead of
    // treating the layer-count change as a reason to fetch/reset every layer.
    // 历史配方可能比当前模式层数更多，应用后 store.color_layers 会变大，
    // 父组件也会把更大的 colorLayers 传回来。这里锁住：不能因为层数 prop
    // 变化就把刚点的历史配方重置掉。
    const historyEntry: RecipeHistoryItem = {
      id: "1-1-1@Top2Bottom",
      recipe: [1, 1, 1],
      layerOrder: "Top2Bottom",
      predictedRgb: [229, 57, 53],
      predictedLab: [50, 60, 70],
      hex: "#E53935",
      fromModel: false,
      createdAtMs: 1,
      displayHexes: ["#E53935", "#E53935", "#E53935"],
      displayLabels: ["Red", "Red", "Red"],
    };
    converterStoreState.customRecipeHistory = [historyEntry];

    const { rerender } = renderDialog({
      palette: canonicalNamePalette,
      regionIds: ["region-1"],
      colorLayers: 2,
    });

    fireEvent.click(
      screen.getByTestId("recipe-history-row-1-1-1@Top2Bottom"),
    );

    await waitFor(() =>
      expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(3),
    );
    expect(screen.getByTestId("recipe-layer-swatch-2")).toHaveStyle({
      backgroundColor: "rgb(229, 57, 53)",
    });

    rerender(
      <CustomRecipeDialog
        {...baseProps}
        palette={canonicalNamePalette.map((entry) => ({ ...entry }))}
        regionIds={["region-1"]}
        colorLayers={3}
      />,
    );

    await waitFor(() => expect(fetchRegionRecipeMock).toHaveBeenCalledOnce());
    expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(3);
    expect(screen.getByTestId("recipe-layer-swatch-0")).toHaveStyle({
      backgroundColor: "rgb(229, 57, 53)",
    });
    expect(screen.getByTestId("recipe-layer-swatch-1")).toHaveStyle({
      backgroundColor: "rgb(229, 57, 53)",
    });
    expect(screen.getByTestId("recipe-layer-swatch-2")).toHaveStyle({
      backgroundColor: "rgb(229, 57, 53)",
    });
  });

  it("keeps locally added layers when a delayed region recipe returns", async () => {
    const pendingFetch = deferred<Awaited<ReturnType<typeof fetchRegionRecipeMock>>>();
    fetchRegionRecipeMock.mockReturnValueOnce(pendingFetch.promise);
    renderDialog({
      palette: canonicalNamePalette,
      colorLayers: 5,
      regionIds: ["region-1"],
    });

    const addLayerButton = screen.getByRole("button", {
      name: "recipe_custom_add_layer",
    });
    for (let i = 0; i < 5; i += 1) {
      fireEvent.click(addLayerButton);
    }
    expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(10);

    await act(async () => {
      pendingFetch.resolve({
        status: "ok",
        message: "ok",
        recipes: [
          {
            region_id: "region-1",
            recipe: [0, 0, 0, 0, 0],
            color_layers: 5,
            layer_height_mm: 0.08,
            layer_order: "Top2Bottom",
          },
        ],
      });
      await pendingFetch.promise;
    });

    expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(10);
  });

  it("keeps locally added layers when the parent rerenders with equivalent props", async () => {
    const { rerender } = renderDialog({
      palette: canonicalNamePalette,
      colorLayers: 5,
      regionIds: ["region-1"],
    });
    await waitFor(() => expect(fetchRegionRecipeMock).toHaveBeenCalledOnce());

    const addLayerButton = screen.getByRole("button", {
      name: "recipe_custom_add_layer",
    });
    for (let i = 0; i < 5; i += 1) {
      fireEvent.click(addLayerButton);
    }
    expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(10);

    rerender(
      <CustomRecipeDialog
        {...baseProps}
        palette={canonicalNamePalette.map((entry) => ({ ...entry }))}
        colorLayers={5}
        regionIds={["region-1"]}
      />,
    );

    expect(fetchRegionRecipeMock).toHaveBeenCalledOnce();
    expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(10);
  });

  it("reinitializes from the fetched recipe after switching to different regions", async () => {
    fetchRegionRecipeMock
      .mockResolvedValueOnce({
        status: "ok",
        message: "ok",
        recipes: [],
      })
      .mockResolvedValueOnce({
        status: "ok",
        message: "ok",
        recipes: [
          {
            region_id: "region-2",
            recipe: [1, 1, 1, 1, 1],
            color_layers: 5,
            layer_height_mm: 0.08,
            layer_order: "Top2Bottom",
          },
        ],
      });
    const { rerender } = renderDialog({
      palette: canonicalNamePalette,
      colorLayers: 5,
      regionIds: ["region-1"],
    });
    await waitFor(() => expect(fetchRegionRecipeMock).toHaveBeenCalledOnce());

    const addLayerButton = screen.getByRole("button", {
      name: "recipe_custom_add_layer",
    });
    for (let i = 0; i < 5; i += 1) {
      fireEvent.click(addLayerButton);
    }
    expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(10);

    rerender(
      <CustomRecipeDialog
        {...baseProps}
        palette={canonicalNamePalette.map((entry) => ({ ...entry }))}
        colorLayers={5}
        regionIds={["region-2"]}
      />,
    );

    await waitFor(() => expect(fetchRegionRecipeMock).toHaveBeenCalledTimes(2));
    expect(screen.getAllByTestId(/recipe-layer-swatch-/)).toHaveLength(5);
    await waitFor(() =>
      expect(screen.getByTestId("recipe-layer-swatch-0")).toHaveStyle({
        backgroundColor: "rgb(229, 57, 53)",
      }),
    );
  });

  it("confirms before applying a ten-layer recipe upgrade", async () => {
    applyRecipeOverrideMock.mockResolvedValueOnce(applyResponse());
    renderDialog({
      palette: canonicalNamePalette,
      colorLayers: 5,
      regionIds: ["region-1"],
    });

    const addLayerButton = screen.getByRole("button", {
      name: "recipe_custom_add_layer",
    });
    for (let i = 0; i < 5; i += 1) {
      fireEvent.click(addLayerButton);
    }

    fireEvent.click(screen.getByRole("button", { name: "recipe_custom_apply" }));

    expect(applyRecipeOverrideMock).not.toHaveBeenCalled();
    expect(
      screen.getByText("recipe_custom_layer_upgrade_warning"),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "recipe_custom_layer_upgrade_confirm",
      }),
    );

    await waitFor(() => expect(applyRecipeOverrideMock).toHaveBeenCalledOnce());
    const payload = applyRecipeOverrideMock.mock.calls[0]?.[0];
    expect(payload).toEqual(expect.objectContaining({ color_layers: 10 }));
    expect(payload.recipe).toHaveLength(10);
  });
});
