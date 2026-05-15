import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import MaterialRecipeQueryPanel from "../components/MaterialRecipeQueryPanel";
import {
  generateMaterialRecipeSwatch,
  listGradientCardMaterials,
  previewMaterialRecipe,
} from "../api/extractor";

vi.mock("../api/extractor", () => ({
  generateMaterialRecipeSwatch: vi.fn(),
  listGradientCardMaterials: vi.fn(),
  previewMaterialRecipe: vi.fn(),
}));

const buildLibraryResponse = (count: number) => ({
  status: "ok",
  message: `Loaded ${count} saved materials`,
  materials: Array.from({ length: count }, (_, idx) => ({
    material_name: `Material-${idx}`,
    directory_name: `mat-${idx}`,
    created_at: "2026-04-16T10:00:00Z",
    updated_at: "2026-04-16T11:00:00Z",
    archive_path: `materials/mat-${idx}/material.json`,
    stage_a_params_path: `materials/mat-${idx}/stage_A_parameters.json`,
    material_file_url: `/api/files/material-${idx}`,
    stage_a_params_url: `/api/files/stage-a-${idx}`,
    estimated_rgb: [100 + idx * 10, 120, 140] as [number, number, number],
    layer_height_mm: 0.04,
    mean_delta_e: 1.0,
    verification_count: 1,
    verification_history: [],
  })),
});

describe("MaterialRecipeQueryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(generateMaterialRecipeSwatch).mockResolvedValue({
      status: "ok",
      message: "Generated",
      download_url: "/api/files/material-swatch",
      preview_url: "/api/files/material-swatch-preview",
      recipe_count: 1,
    });
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
      layer_height_mm: 0.08,
      substrate: "white",
    });
    expect(screen.getByTestId("material-recipe-result-swatch")).toBeInTheDocument();
    expect(screen.getByTestId("material-recipe-result-layers")).toBeInTheDocument();
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

  it("renders an error banner when the preview API rejects", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue(buildLibraryResponse(1));
    vi.mocked(previewMaterialRecipe).mockRejectedValue(new Error("backend boom"));

    render(<MaterialRecipeQueryPanel />);
    await waitFor(() => {
      expect(screen.getAllByTestId("material-recipe-palette-item").length).toBe(1);
    });
    fireEvent.click(screen.getAllByTestId("material-recipe-palette-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /计算混色|Compute color/ }));

    await waitFor(() => {
      expect(screen.getByText("backend boom")).toBeInTheDocument();
    });
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
