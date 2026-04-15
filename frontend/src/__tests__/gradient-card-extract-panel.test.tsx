import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import GradientCardExtractPanel from "../components/GradientCardExtractPanel";
import { useSingleStageStore } from "../stores/singleStageStore";

vi.mock("../api/extractor", () => ({
  extractGradientCardStageA: vi.fn(),
  rotateExtractorImage: vi.fn(),
  saveGradientCardMaterial: vi.fn(),
}));

beforeEach(() => {
  useSingleStageStore.setState({
    workflow: "single-stage",
    datasetFile: null,
    whiteImageFile: null,
    whiteImagePreviewUrl: null,
    whiteImageNaturalWidth: null,
    whiteImageNaturalHeight: null,
    whiteCornerPoints: [],
    blackImageFile: null,
    blackImagePreviewUrl: null,
    blackImageNaturalWidth: null,
    blackImageNaturalHeight: null,
    blackCornerPoints: [],
    isRotatingWhite: false,
    isRotatingBlack: false,
    isExtracting: false,
    extractError: null,
    sessionId: null,
    warnings: [],
    stageAParamsUrl: null,
    whiteWarpPreviewUrl: null,
    blackWarpPreviewUrl: null,
    fitSummary: null,
    materialSummary: null,
    materialName: "",
    isSaving: false,
    saveError: null,
    saveSuccess: null,
    materialFileUrl: null,
    savedStageAParamsUrl: null,
    savedMaterialSummary: null,
  });
});

describe("GradientCardExtractPanel", () => {
  it("renders the new upload workflow and keeps extract/save actions disabled before inputs are ready", () => {
    render(<GradientCardExtractPanel />);

    expect(screen.getByTestId("gradient-card-extract-panel")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /选择数据集 zip|choose dataset zip/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /提取 stage a 耗材参数|extract stage a material parameters/i }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /保存耗材档案|save material archive/i }),
    ).toBeDisabled();
  });

  it("renders Stage A, saved material, warp previews, and warnings when results are available", () => {
    useSingleStageStore.setState({
      datasetFile: new File(["zip"], "dataset.zip", { type: "application/zip" }),
      whiteImageFile: new File(["white"], "white.png", { type: "image/png" }),
      whiteImagePreviewUrl: "blob:white-preview",
      whiteImageNaturalWidth: 800,
      whiteImageNaturalHeight: 600,
      whiteCornerPoints: [
        [10, 10],
        [790, 10],
        [790, 590],
        [10, 590],
      ],
      blackImageFile: new File(["black"], "black.png", { type: "image/png" }),
      blackImagePreviewUrl: "blob:black-preview",
      blackImageNaturalWidth: 800,
      blackImageNaturalHeight: 600,
      blackCornerPoints: [
        [10, 10],
        [790, 10],
        [790, 590],
        [10, 590],
      ],
      stageAParamsUrl: "/api/files/stage-a.json",
      whiteWarpPreviewUrl: "/api/files/white-warp.png",
      blackWarpPreviewUrl: "/api/files/black-warp.png",
      warnings: ["warning 1"],
      materialSummary: {
        sample_count: 36,
        per_substrate_sample_count: 18,
        grid_rows: 3,
        grid_cols: 6,
        layer_height_mm: 0.04,
        thickness_layers: [25, 16, 15],
        white_zero_rgb: [255, 255, 255],
        black_zero_rgb: [24, 24, 24],
        estimated_rgb: [100, 120, 140],
        estimated_k: [1.2, 1.3, 1.4],
      },
      fitSummary: {
        substrate_count: 2,
        channel_count: 1,
        substrates: ["black", "white"],
        colors: ["PLA Basic"],
        overall_validation: {},
        warnings: [],
      },
      materialFileUrl: "/api/files/material.json",
      savedStageAParamsUrl: "/api/files/saved-stage-a.json",
      savedMaterialSummary: {
        material_name: "Test Material",
        directory_name: "test-material",
        archive_path: "materials/test-material/material.json",
        stage_a_params_path: "materials/test-material/stage_A_parameters.json",
      },
    });

    render(<GradientCardExtractPanel />);

    expect(screen.getByTestId("stage-a-link")).toHaveAttribute(
      "href",
      "/api/files/stage-a.json",
    );
    expect(screen.getByTestId("material-link")).toHaveAttribute(
      "href",
      "/api/files/material.json",
    );
    expect(screen.getByTestId("white-warp-preview")).toHaveAttribute(
      "src",
      "/api/files/white-warp.png",
    );
    expect(screen.getByTestId("black-warp-preview")).toHaveAttribute(
      "src",
      "/api/files/black-warp.png",
    );
    expect(screen.getByText("warning 1")).toBeInTheDocument();
    expect(screen.getAllByText(/dataset\.zip/i).length).toBeGreaterThan(0);
  });
});
