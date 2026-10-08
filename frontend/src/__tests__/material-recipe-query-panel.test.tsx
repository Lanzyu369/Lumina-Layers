import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import MaterialRecipeQueryPanel from "../components/MaterialRecipeQueryPanel";
import apiClient, { downloadResourceBlob } from "../api/client";
import {
  generateMaterialRecipeSwatch,
  listGradientCardMaterials,
  previewMaterialRecipe,
} from "../api/extractor";
import { invalidateGeneratedArtifacts } from "../stores/generatedArtifactInvalidation";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

vi.mock("../api/extractor", () => ({
  colorcheckerConfirm: vi.fn(),
  colorcheckerRelease: vi.fn(),
  colorcheckerTouch: vi.fn(() => Promise.resolve()),
  generateMaterialRecipeSwatch: vi.fn(),
  listGradientCardMaterials: vi.fn(),
  previewMaterialRecipe: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    downloadResourceBlob: vi.fn(),
  };
});

const buildLibraryResponse = (
  count: number,
  profileKind: "stage_a" | "lumina_box" = "stage_a",
) => ({
  status: "ok",
  message: `Loaded ${count} saved materials`,
  materials: Array.from({ length: count }, (_, idx) => ({
    material_name: `Material-${idx}`,
    directory_name: `mat-${idx}`,
    created_at: "2026-04-16T10:00:00Z",
    updated_at: "2026-04-16T11:00:00Z",
    material_file_url: `/api/files/material-${idx}`,
    stage_a_params_url: `/api/files/stage-a-${idx}`,
    estimated_rgb: [100 + idx * 10, 120, 140] as [number, number, number],
    layer_height_mm: 0.04,
    mean_delta_e: 1.0,
    verification_count: 1,
    verification_history: [],
    profile_kind: profileKind,
    optical_model_id: profileKind === "lumina_box" ? "backed_gradient_spectral_four_flux_smooth/v3" : undefined,
  })),
});

function apiValidationFailure(loc: Array<string | number>, msg: string) {
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
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function prepareRecipeForSwatchDownload(): Promise<void> {
  vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(1));
  vi.mocked(previewMaterialRecipe).mockResolvedValue({
    status: "ok",
    material_profile_kind: "stage_a",
    layer_count: 1,
    layer_height_mm: 0.08,
    substrate: "white",
    predicted_rgb: [180, 60, 90],
    predicted_hex: "#B43C5A",
    layers: [],
  });

  render(<MaterialRecipeQueryPanel />);
  await waitFor(() => {
    expect(screen.getAllByTestId("material-recipe-palette-item")).toHaveLength(1);
  });
  fireEvent.click(screen.getByTestId("material-recipe-palette-item"));
  fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));
  await screen.findByRole("button", { name: /添加到队列|Add to queue/ });
  fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
  fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));
  await screen.findByRole("button", { name: /下载 3MF|Download 3MF/ });
}

describe("MaterialRecipeQueryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      printerModel: "bambu-h2d",
      slicerSoftware: "BambuStudio",
      nozzleSize: "0.2",
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.2",
    });
    vi.mocked(generateMaterialRecipeSwatch).mockResolvedValue({
      status: "ok",
      message: "Generated",
      download_url: "/api/files/material-swatch",
      preview_url: "/api/files/material-swatch-preview",
      recipe_count: 1,
    });
    vi.mocked(downloadResourceBlob).mockResolvedValue(new Blob(["3mf"], { type: "model/3mf" }));
  });

  it("renders the empty palette hint when the library has no materials", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 0 saved materials",
      materials: [],
    });

    render(<MaterialRecipeQueryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-recipe-query-panel")).toBeInTheDocument();
    });

    expect(
      screen.getByText(
        /耗材库为空|Material library is empty/i,
      ),
    ).toBeInTheDocument();
  });

  it("appends materials as recipe layers when palette tiles are clicked", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(3));

    render(<MaterialRecipeQueryPanel />);

    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(3);
    });

    const tiles = screen.getAllByTestId("material-recipe-palette-item");
    fireEvent.click(tiles[0]);
    fireEvent.click(tiles[1]);
    fireEvent.click(tiles[0]);

    expect(screen.getAllByTestId("material-recipe-layer-item")).toHaveLength(3);
  });

  it("calls the preview API with the recipe converted from viewing-face order to stacking order", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(2));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 2,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [180, 60, 90],
      predicted_hex: "#B43C5A",
      layers: [
        {
          layer_index: 0,
          directory_name: "mat-0",
          material_name: "Material-0",
          estimated_rgb: [100, 120, 140],
          estimated_hex: "#64788C",
        },
        {
          layer_index: 1,
          directory_name: "mat-1",
          material_name: "Material-1",
          estimated_rgb: [110, 120, 140],
          estimated_hex: "#6E788C",
        },
      ],
    });

    render(<MaterialRecipeQueryPanel />);

    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(2);
    });

    const tiles = screen.getAllByTestId("material-recipe-palette-item");
    fireEvent.click(tiles[0]);
    fireEvent.click(tiles[1]);

    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(screen.getByTestId("material-recipe-result-hex")).toHaveTextContent("#B43C5A");
    });

    expect(previewMaterialRecipe).toHaveBeenCalledWith({
      directory_names: ["mat-1", "mat-0"],
      material_profile_kind: "stage_a",
      layer_height_mm: 0.08,
      substrate: "white",
    });
    expect(screen.getByTestId("material-recipe-result-swatch")).toBeInTheDocument();
    expect(screen.getByTestId("material-recipe-result-layers")).toBeInTheDocument();
  });

  it("switches profile families, clears the active recipe, and sends Lumina Box requests", async () => {
    const stageAResponse = {
      ...buildLibraryResponse(1, "stage_a"),
      materials: [
        {
          ...buildLibraryResponse(1, "stage_a").materials[0],
          material_name: "Stage A Red",
          directory_name: "stage-a-red",
        },
      ],
    };
    const luminaBoxResponse = {
      ...buildLibraryResponse(1, "lumina_box"),
      materials: [
        {
          ...buildLibraryResponse(1, "lumina_box").materials[0],
          material_name: "Lumina Blue",
          directory_name: "lumina-blue",
        },
      ],
    };
    vi.mocked(listGradientCardMaterials).mockImplementation(async ({ profileKind } = {}) => (
      profileKind === "lumina_box" ? luminaBoxResponse : stageAResponse
    ));
    vi.mocked(previewMaterialRecipe).mockImplementation(async (request) => ({
      status: "ok",
      material_profile_kind: request.material_profile_kind,
      layer_count: request.directory_names.length,
      layer_height_mm: request.layer_height_mm,
      substrate: request.substrate,
      predicted_rgb: [50, 90, 190],
      predicted_hex: "#325ABE",
      layers: [],
    }));

    render(<MaterialRecipeQueryPanel />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Stage A Red" })).toBeInTheDocument();
      expect(listGradientCardMaterials).toHaveBeenLastCalledWith({ profileKind: "stage_a" });
    });
    fireEvent.click(screen.getByRole("button", { name: "Stage A Red" }));
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));
    await waitFor(() => {
      expect(screen.getByTestId("material-recipe-result-hex")).toHaveTextContent("#325ABE");
    });

    fireEvent.click(screen.getByTestId("material-recipe-profile-lumina_box"));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Lumina Blue" })).toBeInTheDocument();
      expect(listGradientCardMaterials).toHaveBeenLastCalledWith({ profileKind: "lumina_box" });
    });
    expect(screen.queryByRole("button", { name: "Stage A Red" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("material-recipe-layer-item")).not.toBeInTheDocument();
    expect(screen.queryByTestId("material-recipe-result-hex")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Lumina Blue" }));
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));
    await waitFor(() => {
      expect(vi.mocked(previewMaterialRecipe).mock.calls.at(-1)?.[0]).toMatchObject({
        directory_names: ["lumina-blue"],
        material_profile_kind: "lumina_box",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
    fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));
    await waitFor(() => {
      expect(vi.mocked(generateMaterialRecipeSwatch).mock.calls.at(-1)?.[0]).toMatchObject({
        material_profile_kind: "lumina_box",
        recipes: [
          expect.objectContaining({
            directory_names: ["lumina-blue"],
            result_hex: "#325ABE",
          }),
        ],
      });
    });
  });

  it("permits more than five layers (no 5-layer hard cap)", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(2));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 7,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [10, 20, 30],
      predicted_hex: "#0A141E",
      layers: Array.from({ length: 7 }, (_, idx) => ({
        layer_index: idx,
        directory_name: `mat-${idx % 2}`,
        material_name: `Material-${idx % 2}`,
        estimated_rgb: [100, 120, 140] as [number, number, number],
        estimated_hex: "#64788C",
      })),
    });

    render(<MaterialRecipeQueryPanel />);

    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(2);
    });

    const tiles = screen.getAllByTestId("material-recipe-palette-item");
    for (let i = 0; i < 7; i += 1) {
      fireEvent.click(tiles[i % 2]);
    }
    expect(screen.getAllByTestId("material-recipe-layer-item")).toHaveLength(7);

    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(previewMaterialRecipe).toHaveBeenCalled();
    });
    const callArgs = vi.mocked(previewMaterialRecipe).mock.calls[0][0];
    expect(callArgs.directory_names).toHaveLength(7);
  });

  it("renders a readable error banner when the preview API rejects with a generic server error", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(1));
    vi.mocked(previewMaterialRecipe).mockRejectedValue(new Error("Request failed with status code 500"));

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(1);
    });
    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(
        screen.getByText(/The server hit an internal error|服务器发生内部错误/),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText("Request failed with status code 500"),
    ).not.toBeInTheDocument();
  });

  it("renders a readable palette error when material loading rejects with a generic client error", async () => {
    vi.mocked(listGradientCardMaterials).mockRejectedValue(
      new Error("Request failed with status code 422"),
    );

    render(<MaterialRecipeQueryPanel />);

    await waitFor(() => {
      expect(
        screen.getByText(/missing required data|缺少必填数据|invalid values|无效值/),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText("Request failed with status code 422"),
    ).not.toBeInTheDocument();
  });

  it("preserves actionable validation details from the preview API", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(1));
    const validationError = new Error(
      "Request failed with status code 422",
    ) as Error & {
      response: {
        status: number;
        data: { detail: string };
        headers: Record<string, string>;
      };
    };
    validationError.response = {
      status: 422,
      data: { detail: "Layer height must be 0.04, 0.08, or 0.1 mm" },
      headers: {},
    };
    vi.mocked(previewMaterialRecipe).mockRejectedValue(validationError);

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(1);
    });
    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(
        screen.getByText("Layer height must be 0.04, 0.08, or 0.1 mm"),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText("Request failed with status code 422"),
    ).not.toBeInTheDocument();
  });

  it("hides backend validation paths from the preview API", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(1));
    vi.mocked(previewMaterialRecipe).mockRejectedValue(
      apiValidationFailure(["body", "directory_names"], "Field required"),
    );

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(1);
    });
    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(
        screen.getByText(/配方计算失败|Recipe computation failed/),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/body\.directory_names/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/directory_names/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText("Request failed with status code 422"),
    ).not.toBeInTheDocument();
  });

  it("keeps non-path material validation details from the preview API", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(1));
    vi.mocked(previewMaterialRecipe).mockRejectedValue(
      apiValidationFailure(
        ["body", "layer_height_mm"],
        "Layer height must be 0.04, 0.08, or 0.1 mm",
      ),
    );

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(1);
    });
    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(
        screen.getByText(
          "body.layer_height_mm: Layer height must be 0.04, 0.08, or 0.1 mm",
        ),
      ).toBeInTheDocument();
    });
  });

  it("renders a readable swatch error when generation rejects with a generic server error", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(1));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 1,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [180, 60, 90],
      predicted_hex: "#B43C5A",
      layers: [],
    });
    vi.mocked(generateMaterialRecipeSwatch).mockRejectedValue(
      new Error("Request failed with status code 500"),
    );

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(1);
    });
    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /添加到队列|Add to queue/ }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
    fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));

    await waitFor(() => {
      expect(
        screen.getByText(/The server hit an internal error|服务器发生内部错误/),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText("Request failed with status code 500"),
    ).not.toBeInTheDocument();
  });

  it("hides backend validation paths from swatch generation errors", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(1));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 1,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [180, 60, 90],
      predicted_hex: "#B43C5A",
      layers: [],
    });
    vi.mocked(generateMaterialRecipeSwatch).mockRejectedValue(
      apiValidationFailure(
        ["body", "recipes", 0, "directory_names"],
        "Recipe must include material directories",
      ),
    );

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(1);
    });
    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /添加到队列|Add to queue/ }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
    fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));

    await waitFor(() => {
      expect(
        screen.getByText(/色块生成失败|Swatch generation failed/),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/body\.recipes\.0\.directory_names/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/directory_names/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText("Request failed with status code 422"),
    ).not.toBeInTheDocument();
  });

  it("reverses the visible recipe layer order when the reverse button is pressed", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(3));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 3,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [10, 20, 30],
      predicted_hex: "#0A141E",
      layers: [],
    });

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(3);
    });

    const tiles = screen.getAllByTestId("material-recipe-palette-item");
    fireEvent.click(tiles[0]); // mat-0 (visible face)
    fireEvent.click(tiles[1]); // mat-1
    fireEvent.click(tiles[2]); // mat-2 (substrate side)

    fireEvent.click(screen.getByRole("button", { name: /反序|^Reverse$/ }));
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(previewMaterialRecipe).toHaveBeenCalled();
    });
    const callArgs = vi.mocked(previewMaterialRecipe).mock.calls[0][0];
    expect(callArgs.directory_names).toEqual(["mat-0", "mat-1", "mat-2"]);
  });

  it("sends collected swatch recipes in backend stacking order", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(2));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 2,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [180, 60, 90],
      predicted_hex: "#B43C5A",
      layers: [],
    });

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(2);
    });

    const tiles = screen.getAllByTestId("material-recipe-palette-item");
    fireEvent.click(tiles[0]);
    fireEvent.click(tiles[1]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /添加到队列|Add to queue/ })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
    fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));

    await waitFor(() => {
      expect(generateMaterialRecipeSwatch).toHaveBeenCalled();
    });
    const callArgs = vi.mocked(generateMaterialRecipeSwatch).mock.calls[0][0];
    expect(callArgs.recipes[0].directory_names).toEqual(["mat-1", "mat-0"]);
    expect(callArgs.material_profile_kind).toBe("stage_a");
    expect(callArgs.device_profile_id).toBe("BambuStudio:bbl:bambu-lab-h2d:0.2");
  });

  it("renders the swatch preview without double-prefixing API file URLs", async () => {
    const originalBaseUrl = apiClient.defaults.baseURL;
    vi.stubEnv("VITE_API_BASE_URL", "/api");
    apiClient.defaults.baseURL = "/api";

    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(2));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 2,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [180, 60, 90],
      predicted_hex: "#B43C5A",
      layers: [],
    });

    try {
      render(<MaterialRecipeQueryPanel />);
      await waitFor(() => {
        expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(2);
      });

      const tiles = screen.getAllByTestId("material-recipe-palette-item");
      fireEvent.click(tiles[0]);
      fireEvent.click(tiles[1]);
      fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /添加到队列|Add to queue/ })).toBeInTheDocument();
      });
      fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
      fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));

      const preview = await screen.findByAltText(/色块图例|Swatch legend/);
      expect(preview).toHaveAttribute(
        "src",
        "/api/files/material-swatch-preview",
      );
      expect(preview.getAttribute("src")).not.toContain("/api/api/files");
    } finally {
      apiClient.defaults.baseURL = originalBaseUrl;
      vi.unstubAllEnvs();
    }
  });

  it("keeps a newer material swatch active when an old plate response resolves", async () => {
    const stale = deferred<
      Awaited<ReturnType<typeof generateMaterialRecipeSwatch>>
    >();
    const fresh = deferred<
      Awaited<ReturnType<typeof generateMaterialRecipeSwatch>>
    >();
    vi.mocked(generateMaterialRecipeSwatch)
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    useSettingsStore.setState({ buildPlateId: "engineering-plate" });
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(2));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 2,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [180, 60, 90],
      predicted_hex: "#B43C5A",
      layers: [],
    });

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item")).toHaveLength(2);
    });
    const tiles = screen.getAllByTestId("material-recipe-palette-item");
    fireEvent.click(tiles[0]);
    fireEvent.click(tiles[1]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /添加到队列|Add to queue/ })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
    const generateButton = screen.getByRole("button", {
      name: /生成验证色块|Generate swatch/,
    });
    fireEvent.click(generateButton);

    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "BambuStudio:bbl:bambu-lab-h2d",
        "textured-pei-plate",
      );
    await waitFor(() => {
      expect(generateButton).toBeEnabled();
    });

    fireEvent.click(generateButton);
    expect(vi.mocked(generateMaterialRecipeSwatch).mock.calls[0][0].build_plate_id).toBe(
      "engineering-plate",
    );
    expect(vi.mocked(generateMaterialRecipeSwatch).mock.calls[1][0].build_plate_id).toBe(
      "textured-pei-plate",
    );

    await act(async () => {
      stale.resolve({
        status: "ok",
        message: "stale",
        download_url: "/api/files/stale-material-swatch.3mf",
        preview_url: "/api/files/stale-material-swatch.png",
        recipe_count: 1,
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(generateButton).toBeDisabled();
    });
    expect(screen.queryByAltText(/色块图例|Swatch legend/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /下载 3MF|Download swatch/ }),
    ).not.toBeInTheDocument();

    await act(async () => {
      fresh.resolve({
        status: "ok",
        message: "fresh",
        download_url: "/api/files/fresh-material-swatch.3mf",
        preview_url: "/api/files/fresh-material-swatch.png",
        recipe_count: 1,
      });
      await Promise.resolve();
    });

    expect(await screen.findByAltText(/色块图例|Swatch legend/)).toHaveAttribute(
      "src",
      "/api/files/fresh-material-swatch.png",
    );
    expect(
      screen.getByRole("button", { name: /下载 3MF|Download swatch/ }),
    ).toBeEnabled();

    act(() => {
      useSettingsStore
        .getState()
        .setBuildPlateForMachine(
          "BambuStudio:bbl:bambu-lab-h2d",
          "smooth-pei-plate",
        );
    });
    await waitFor(() => {
      expect(screen.getByAltText(/色块图例|Swatch legend/)).toHaveAttribute(
        "src",
        "/api/files/fresh-material-swatch.png",
      );
      expect(
        screen.queryByRole("button", { name: /下载 3MF|Download swatch/ }),
      ).not.toBeInTheDocument();
    });
  });

  it("keeps swatch download failures in the panel with visible language", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    vi.mocked(downloadResourceBlob).mockRejectedValueOnce(
      new Error("Request failed with status code 404"),
    );
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(2));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 2,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [180, 60, 90],
      predicted_hex: "#B43C5A",
      layers: [],
    });

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(2);
    });

    const tiles = screen.getAllByTestId("material-recipe-palette-item");
    fireEvent.click(tiles[0]);
    fireEvent.click(tiles[1]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /添加到队列|Add to queue/ })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
    fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /下载 3MF|Download 3MF/ })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /下载 3MF|Download 3MF/ }));

    await waitFor(() => {
      expect(downloadResourceBlob).toHaveBeenCalledWith("/api/files/material-swatch");
    });
    expect(openSpy).not.toHaveBeenCalled();
    expect(screen.getByText(/请求的资源不存在或已过期|not found or has expired/i)).toBeInTheDocument();
    expect(screen.queryByText("Request failed with status code 404")).not.toBeInTheDocument();

    openSpy.mockRestore();
  });

  it("downloads the material recipe swatch through a blob URL", async () => {
    const clickSpy = vi.fn();
    const removeSpy = vi.fn();
    const anchor = document.createElement("a");
    anchor.click = clickSpy;
    anchor.remove = removeSpy;
    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string, options?: ElementCreationOptions) => {
        if (tagName.toLowerCase() === "a") {
          return anchor;
        }
        return Document.prototype.createElement.call(document, tagName, options);
      });
    const appendSpy = vi.spyOn(document.body, "appendChild");
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:material-swatch"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(2));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      layer_count: 2,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [180, 60, 90],
      predicted_hex: "#B43C5A",
      layers: [],
    });

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(2);
    });

    const tiles = screen.getAllByTestId("material-recipe-palette-item");
    fireEvent.click(tiles[0]);
    fireEvent.click(tiles[1]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /添加到队列|Add to queue/ })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
    fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /下载 3MF|Download 3MF/ })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /下载 3MF|Download 3MF/ }));

    await waitFor(() => {
      expect(clickSpy).toHaveBeenCalledOnce();
    });
    expect(downloadResourceBlob).toHaveBeenCalledWith("/api/files/material-swatch");
    expect(anchor.href).toBe("blob:material-swatch");
    expect(anchor.download).toBe("material-recipe-swatch.3mf");
    expect(appendSpy).toHaveBeenCalledWith(anchor);
    expect(removeSpy).toHaveBeenCalledOnce();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:material-swatch");

    createElementSpy.mockRestore();
    appendSpy.mockRestore();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: originalCreateObjectURL,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectURL,
    });
  });

  it("does not download a stale Stage A swatch blob after switching to Lumina Box", async () => {
    const pendingDownload = deferred<Blob>();
    const luminaBoxResponse = {
      ...buildLibraryResponse(1, "lumina_box"),
      materials: [
        {
          ...buildLibraryResponse(1, "lumina_box").materials[0],
          material_name: "Lumina Blue",
          directory_name: "lumina-blue",
        },
      ],
    };
    vi.mocked(listGradientCardMaterials).mockImplementation(async ({ profileKind } = {}) => (
      profileKind === "lumina_box" ? luminaBoxResponse : buildLibraryResponse(1)
    ));
    vi.mocked(previewMaterialRecipe).mockResolvedValue({
      status: "ok",
      material_profile_kind: "stage_a",
      layer_count: 1,
      layer_height_mm: 0.08,
      substrate: "white",
      predicted_rgb: [180, 60, 90],
      predicted_hex: "#B43C5A",
      layers: [],
    });
    vi.mocked(downloadResourceBlob).mockReturnValue(pendingDownload.promise);
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    try {
      render(<MaterialRecipeQueryPanel />);
      await waitFor(() => {
        expect(screen.getAllByTestId("material-recipe-palette-item")).toHaveLength(1);
      });
      fireEvent.click(screen.getByTestId("material-recipe-palette-item"));
      fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));
      await screen.findByRole("button", { name: /添加到队列|Add to queue/ });
      fireEvent.click(screen.getByRole("button", { name: /添加到队列|Add to queue/ }));
      fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));
      const downloadButton = await screen.findByRole("button", {
        name: /下载 3MF|Download 3MF/,
      });
      fireEvent.click(downloadButton);
      await waitFor(() => {
        expect(downloadResourceBlob).toHaveBeenCalledWith("/api/files/material-swatch");
      });

      fireEvent.click(screen.getByTestId("material-recipe-profile-lumina_box"));
      await screen.findByRole("button", { name: "Lumina Blue" });

      await act(async () => {
        pendingDownload.resolve(new Blob(["3mf"], { type: "model/3mf" }));
        await Promise.resolve();
      });

      expect(anchorClickSpy).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("button", { name: /下载 3MF|Download 3MF/ }),
      ).not.toBeInTheDocument();
    } finally {
      anchorClickSpy.mockRestore();
    }
  });

  it("drops a resolved stale swatch blob after global artifact invalidation and allows a fresh download", async () => {
    const pendingDownload = deferred<Blob>();
    vi.mocked(downloadResourceBlob)
      .mockReturnValueOnce(pendingDownload.promise)
      .mockResolvedValueOnce(new Blob(["current"], { type: "model/3mf" }));
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:current-material-swatch"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });

    try {
      await prepareRecipeForSwatchDownload();
      fireEvent.click(screen.getByRole("button", { name: /下载 3MF|Download 3MF/ }));
      await waitFor(() => {
        expect(downloadResourceBlob).toHaveBeenCalledTimes(1);
      });

      act(() => {
        invalidateGeneratedArtifacts();
      });
      expect(
        screen.queryByRole("button", { name: /下载 3MF|Download 3MF/ }),
      ).not.toBeInTheDocument();

      await act(async () => {
        pendingDownload.resolve(new Blob(["stale"], { type: "model/3mf" }));
        await Promise.resolve();
      });

      expect(anchorClickSpy).not.toHaveBeenCalled();
      expect(screen.queryByText(/Swatch download failed|色块下载失败/)).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));
      const freshDownloadButton = await screen.findByRole("button", {
        name: /下载 3MF|Download 3MF/,
      });
      expect(freshDownloadButton).toBeEnabled();
      fireEvent.click(freshDownloadButton);

      await waitFor(() => {
        expect(downloadResourceBlob).toHaveBeenCalledTimes(2);
        expect(anchorClickSpy).toHaveBeenCalledOnce();
      });
    } finally {
      anchorClickSpy.mockRestore();
      Object.defineProperty(URL, "createObjectURL", {
        configurable: true,
        value: originalCreateObjectURL,
      });
      Object.defineProperty(URL, "revokeObjectURL", {
        configurable: true,
        value: originalRevokeObjectURL,
      });
    }
  });

  it("drops a rejected stale swatch blob after global artifact invalidation and allows a fresh download", async () => {
    const pendingDownload = deferred<Blob>();
    vi.mocked(downloadResourceBlob)
      .mockReturnValueOnce(pendingDownload.promise)
      .mockResolvedValueOnce(new Blob(["current"], { type: "model/3mf" }));
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:current-material-swatch"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });

    try {
      await prepareRecipeForSwatchDownload();
      fireEvent.click(screen.getByRole("button", { name: /下载 3MF|Download 3MF/ }));
      await waitFor(() => {
        expect(downloadResourceBlob).toHaveBeenCalledTimes(1);
      });

      act(() => {
        invalidateGeneratedArtifacts();
      });
      expect(
        screen.queryByRole("button", { name: /下载 3MF|Download 3MF/ }),
      ).not.toBeInTheDocument();

      const staleError = Object.assign(
        new Error("Request failed with status code 422"),
        {
          response: {
            status: 422,
            data: { detail: "stale swatch download failure" },
            headers: {},
          },
        },
      );
      await act(async () => {
        pendingDownload.reject(staleError);
        await Promise.resolve();
      });

      expect(anchorClickSpy).not.toHaveBeenCalled();
      expect(screen.queryByText("stale swatch download failure")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /生成验证色块|Generate swatch/ }));
      const freshDownloadButton = await screen.findByRole("button", {
        name: /下载 3MF|Download 3MF/,
      });
      expect(freshDownloadButton).toBeEnabled();
      fireEvent.click(freshDownloadButton);

      await waitFor(() => {
        expect(downloadResourceBlob).toHaveBeenCalledTimes(2);
        expect(anchorClickSpy).toHaveBeenCalledOnce();
      });
    } finally {
      anchorClickSpy.mockRestore();
      Object.defineProperty(URL, "createObjectURL", {
        configurable: true,
        value: originalCreateObjectURL,
      });
      Object.defineProperty(URL, "revokeObjectURL", {
        configurable: true,
        value: originalRevokeObjectURL,
      });
    }
  });

  it("disables reverse button when fewer than two layers are present", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(3));

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(3);
    });

    const reverseButton = screen.getByRole("button", { name: /反序|^Reverse$/ });
    expect(reverseButton).toBeDisabled();

    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[0]);
    expect(reverseButton).toBeDisabled(); // 1 layer still disabled

    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[1]);
    expect(reverseButton).not.toBeDisabled();
  });

  it("filters palette tiles by material name via the search input", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(4));

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(4);
    });

    const searchInput = screen.getByTestId("material-recipe-search-input") as HTMLInputElement;
    fireEvent.change(searchInput, { target: { value: "Material-2" } });

    const tiles = screen.getAllByTestId("material-recipe-palette-item");
    expect(tiles).toHaveLength(1);
    expect(tiles[0]).toHaveAttribute("aria-label", "Material-2");
  });

  it("shows the no-match hint when the search query has no results", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(2));

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(2);
    });

    const searchInput = screen.getByTestId("material-recipe-search-input") as HTMLInputElement;
    fireEvent.change(searchInput, { target: { value: "nonexistent" } });

    expect(screen.queryByTestId("material-recipe-palette-item")).not.toBeInTheDocument();
    expect(
      screen.getByText(/未找到匹配的耗材|No materials match the search/i),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("material-recipe-search-clear"));
    expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(2);
  });

  it("clears layers and result when the clear button is pressed", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(2));

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(2);
    });

    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[0]);
    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[1]);
    expect(screen.getAllByTestId("material-recipe-layer-item")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: /清空|^Clear$/ }));
    expect(screen.queryByTestId("material-recipe-layer-item")).not.toBeInTheDocument();
  });
});
