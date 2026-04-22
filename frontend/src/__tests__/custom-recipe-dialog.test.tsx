import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RecipeOverrideApplyResponse } from "../api/types";
import CustomRecipeDialog from "../components/ui/CustomRecipeDialog";

const applyRecipeOverrideMock = vi.hoisted(() => vi.fn());
const predictCustomRecipeMock = vi.hoisted(() => vi.fn());
const fetchRegionRecipeMock = vi.hoisted(() => vi.fn());
const converterStoreState = vi.hoisted(() => ({
  customRecipeHistory: [],
  pushCustomRecipeHistory: vi.fn(),
  source_version: "legacy",
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
  return { useConverterStore };
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

describe("CustomRecipeDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    converterStoreState.customRecipeHistory = [];
    converterStoreState.source_version = "legacy";
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

  it("renders no-forward-model prediction failures as a warning", async () => {
    predictCustomRecipeMock.mockRejectedValueOnce(
      new Error("No predictive runtime available for this source"),
    );
    renderDialog();

    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_predict" }),
    );

    const banner = await screen.findByTestId("recipe-error-banner");
    expect(banner).toHaveTextContent("recipe_custom_predict_no_forward_model");
    expect(banner.className).toContain("amber");
    expect(banner.className).not.toContain("red");
  });

  it("renders generic prediction failures as an error", async () => {
    predictCustomRecipeMock.mockRejectedValueOnce(new Error("network boom"));
    renderDialog();

    fireEvent.click(
      screen.getByRole("button", { name: "recipe_custom_predict" }),
    );

    const banner = await screen.findByTestId("recipe-error-banner");
    expect(banner).toHaveTextContent("network boom");
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
});
