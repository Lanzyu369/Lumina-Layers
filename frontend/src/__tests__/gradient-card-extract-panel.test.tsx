import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import GradientCardExtractPanel from "../components/GradientCardExtractPanel";
import { useSingleStageStore } from "../stores/singleStageStore";

vi.mock("../api/extractor", () => ({
  extractGradientCardStageA: vi.fn(),
  rotateExtractorImage: vi.fn(),
  saveGradientCardMaterial: vi.fn(),
}));

vi.mock("../components/GradientCardCanvasPreview", () => ({
  default: (props: {
    dataTestId: string;
    imageUrl?: string | null;
    sampleBoxes?: Array<unknown>;
  }) => (
    <div data-testid={props.dataTestId} data-image-url={props.imageUrl ?? ""}>
      {(props.sampleBoxes ?? []).map((_, index) => (
        <span key={`${props.dataTestId}-${index}`} data-testid={`${props.dataTestId}-sample-box`} />
      ))}
    </div>
  ),
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
    verificationTargetDirectoryName: null,
    verificationTargetCount: 0,
    isSaving: false,
    saveError: null,
    saveSuccess: null,
    materialFileUrl: null,
    savedStageAParamsUrl: null,
    orientationRanking: null,
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
        warp_width_px: 1240,
        warp_height_px: 620,
        thickness_layers: [25, 16, 15],
        sample_boxes: [
          { row: 0, col: 0, x: 40, y: 40, width: 120, height: 120, thickness_layers: 0 },
          { row: 0, col: 1, x: 180, y: 40, width: 120, height: 120, thickness_layers: 1 },
        ],
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
        overall_validation: {
          mean_delta_e: 4.514124395715932,
          max_delta_e: 15.165750888103101,
          rmse_linear: 0.01402580194010753,
          channel_rmse: [0.02322185575513894, 0.004913006223800963, 0.005174663788284788],
        },
        warnings: [],
      },
      orientationRanking: {
        orientation_reliable: true,
        delta_e_gap: 2.3456,
        top_candidates: [
          { white_orientation: "flip_horizontal", black_orientation: "identity", mean_delta_e: 4.5141, rmse_linear: 0.014, max_delta_e: 15.1658 },
          { white_orientation: "identity", black_orientation: "identity", mean_delta_e: 6.8597, rmse_linear: 0.021, max_delta_e: 18.2 },
        ],
      },
      materialFileUrl: "/api/files/material.json",
      savedStageAParamsUrl: "/api/files/saved-stage-a.json",
      savedMaterialSummary: {
        material_name: "Test Material",
        directory_name: "test-material",
        archive_path: "materials/test-material/material.json",
        stage_a_params_path: "materials/test-material/stage_A_parameters.json",
        verification_count: 2,
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
      "data-image-url",
      "/api/files/white-warp.png",
    );
    expect(screen.getByTestId("black-warp-preview")).toHaveAttribute(
      "data-image-url",
      "/api/files/black-warp.png",
    );
    expect(screen.getByTestId("estimated-material-color-rgb")).toHaveTextContent(
      "100, 120, 140",
    );
    expect(screen.getByTestId("estimated-material-color-hex")).toHaveTextContent(
      "#64788C",
    );
    expect(screen.getByTestId("estimated-material-fit-mean-delta-e")).toHaveTextContent(
      "4.514",
    );
    expect(screen.getByTestId("estimated-material-fit-max-delta-e")).toHaveTextContent(
      "15.166",
    );
    expect(screen.getByTestId("estimated-material-fit-rmse-linear")).toHaveTextContent(
      "0.0140",
    );
    expect(screen.getByTestId("estimated-material-fit-channel-rmse")).toHaveTextContent(
      "0.0232",
    );
    expect(screen.getByTestId("estimated-material-fit-channel-rmse")).toHaveTextContent(
      "0.0049",
    );
    expect(screen.getByTestId("estimated-material-fit-channel-rmse")).toHaveTextContent(
      "0.0052",
    );
    expect(screen.getAllByTestId("white-warp-preview-sample-box")).toHaveLength(2);
    expect(screen.getAllByTestId("black-warp-preview-sample-box")).toHaveLength(2);
    expect(screen.getByText("warning 1")).toBeInTheDocument();
    expect(screen.getAllByText(/dataset\.zip/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId("orientation-white")).toHaveTextContent("flip_horizontal");
    expect(screen.getByTestId("orientation-black")).toHaveTextContent("identity");
    expect(screen.getByTestId("orientation-delta-e-gap")).toHaveTextContent("2.3456");
    expect(screen.getByTestId("orientation-reliability-badge")).toHaveTextContent(/可靠|reliable/i);
  });

  it("shows unreliable orientation badge when delta_e_gap is below threshold", () => {
    useSingleStageStore.setState({
      materialSummary: {
        sample_count: 36,
        per_substrate_sample_count: 18,
        grid_rows: 3,
        grid_cols: 6,
        layer_height_mm: 0.04,
        thickness_layers: [],
        sample_boxes: [],
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
        overall_validation: { mean_delta_e: 6.61, max_delta_e: 18.0, rmse_linear: 0.04 },
        warnings: [],
      },
      orientationRanking: {
        orientation_reliable: false,
        delta_e_gap: 0.12,
        top_candidates: [
          { white_orientation: "rotate_180", black_orientation: "flip_vertical", mean_delta_e: 6.61, rmse_linear: 0.04, max_delta_e: 18.0 },
          { white_orientation: "identity", black_orientation: "identity", mean_delta_e: 6.73, rmse_linear: 0.042, max_delta_e: 18.5 },
        ],
      },
    });

    render(<GradientCardExtractPanel />);

    expect(screen.getByTestId("orientation-reliability-badge")).toHaveTextContent(/置信度低|low confidence/i);
    expect(screen.getByTestId("orientation-white")).toHaveTextContent("rotate_180");
    expect(screen.getByTestId("orientation-black")).toHaveTextContent("flip_vertical");
    expect(screen.getByTestId("orientation-delta-e-gap")).toHaveTextContent("0.1200");
  });

  it("shows verification mode when re-validating an existing material", () => {
    useSingleStageStore.setState({
      materialName: "PLA Basic",
      verificationTargetDirectoryName: "pla-basic",
      verificationTargetCount: 3,
    });

    render(<GradientCardExtractPanel />);

    expect(
      screen.getByTestId("gradient-card-verification-mode-banner"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /保存验证结果|save verification result/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /取消复验|cancel re-verification/i }),
    ).toBeInTheDocument();
  });
});
