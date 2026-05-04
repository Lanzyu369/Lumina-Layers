import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";

import GradientCardExtractPanel from "../components/GradientCardExtractPanel";
import {
  extractGradientCardStageA,
  listGradientCardMaterials,
  rotateExtractorImage,
  saveGradientCardMaterial,
} from "../api/extractor";
import { uploadImagePreview } from "../api/system";
import { useSingleStageStore } from "../stores/singleStageStore";

vi.mock("../api/extractor", () => ({
  extractGradientCardStageA: vi.fn(),
  listGradientCardMaterials: vi.fn(),
  rotateExtractorImage: vi.fn(),
  saveGradientCardMaterial: vi.fn(),
}));

vi.mock("../api/system", () => ({
  uploadImagePreview: vi.fn(),
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
  vi.clearAllMocks();
  vi.mocked(uploadImagePreview).mockReset();
  vi.mocked(listGradientCardMaterials).mockImplementation(
    () => new Promise(() => {}),
  );
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
    materialBrand: "",
    verificationTargetDirectoryName: null,
    verificationTargetCount: 0,
    isSaving: false,
    saveError: null,
    saveSuccess: null,
    materialFileUrl: null,
    savedStageAParamsUrl: null,
    orientationRanking: null,
    manualWhiteAnchor: null,
    manualBlackAnchor: null,
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
    const extractButton = screen.getByRole("button", {
      name: /提取耗材|extract material/i,
    });
    expect(extractButton).toBeDisabled();
    const blackCornerSelector = screen.getByTestId("black-corner-selector-preview");
    expect(
      blackCornerSelector.compareDocumentPosition(extractButton) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
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
          { white_orientation: "flip_horizontal", black_orientation: "identity", anchor_penalty: 0.001, mean_delta_e: 4.5141, rmse_linear: 0.014, max_delta_e: 15.1658 },
          { white_orientation: "identity", black_orientation: "identity", anchor_penalty: 0.35, mean_delta_e: 6.8597, rmse_linear: 0.021, max_delta_e: 18.2 },
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
    expect(screen.queryByTestId("stage-a-link")).not.toBeInTheDocument();
    expect(screen.queryByTestId("material-summary-json")).not.toBeInTheDocument();
    expect(screen.queryByTestId("fit-summary-json")).not.toBeInTheDocument();
    expect(screen.queryByTestId("saved-material-summary-json")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /查看详细信息|view details/i }));

    expect(screen.getByTestId("gradient-card-details-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("stage-a-link")).toHaveAttribute(
      "href",
      "/api/files/stage-a.json",
    );
    expect(screen.getByTestId("material-summary-json")).toHaveTextContent("estimated_rgb");
    expect(screen.getByTestId("fit-summary-json")).toHaveTextContent("overall_validation");
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
          { white_orientation: "rotate_180", black_orientation: "flip_vertical", anchor_penalty: 0.12, mean_delta_e: 6.61, rmse_linear: 0.04, max_delta_e: 18.0 },
          { white_orientation: "identity", black_orientation: "identity", anchor_penalty: 0.13, mean_delta_e: 6.73, rmse_linear: 0.042, max_delta_e: 18.5 },
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
      screen.getByRole("button", { name: /合并结果|merge result/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /覆盖结果|override/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /取消复验|cancel re-verification/i }),
    ).toBeInTheDocument();
  });

  it("renders verification save actions next to extracted results", () => {
    useSingleStageStore.setState({
      materialName: "PLA Basic",
      verificationTargetDirectoryName: "pla-basic",
      verificationTargetCount: 3,
      sessionId: "sess-verify",
      materialSummary: {
        sample_count: 36,
        per_substrate_sample_count: 18,
        grid_rows: 3,
        grid_cols: 6,
        layer_height_mm: 0.04,
        warp_width_px: 1240,
        warp_height_px: 620,
        thickness_layers: [],
        sample_boxes: [],
        white_zero_rgb: [255, 255, 255],
        black_zero_rgb: [24, 24, 24],
        estimated_rgb: [100, 120, 140],
        estimated_k: [1.2, 1.3, 1.4],
      },
    });

    render(<GradientCardExtractPanel />);

    const resultActions = screen.getByTestId("gradient-card-verification-result-actions");
    expect(
      within(resultActions).getByRole("button", { name: /合并结果|merge result/i }),
    ).toBeEnabled();
    expect(
      within(resultActions).getByRole("button", { name: /覆盖结果|override/i }),
    ).toBeEnabled();
    expect(
      screen.getByTestId("estimated-material-color").compareDocumentPosition(resultActions) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("saves merged verification results from the result-area actions", async () => {
    const saveMock = vi.mocked(saveGradientCardMaterial);
    saveMock.mockResolvedValueOnce({
      status: "ok",
      message: "",
      material_file_url: "/api/files/material.json",
      stage_a_params_url: "/api/files/stage-a.json",
      material_summary: {
        material_name: "PLA Basic",
        directory_name: "pla-basic",
        archive_path: "materials/pla-basic/material.json",
        stage_a_params_path: "materials/pla-basic/stage_A_parameters.json",
        verification_count: 4,
      },
    });
    useSingleStageStore.setState({
      materialName: "PLA Basic",
      verificationTargetDirectoryName: "pla-basic",
      verificationTargetCount: 3,
      sessionId: "sess-verify",
      materialSummary: {
        sample_count: 36,
        per_substrate_sample_count: 18,
        grid_rows: 3,
        grid_cols: 6,
        layer_height_mm: 0.04,
        warp_width_px: 1240,
        warp_height_px: 620,
        thickness_layers: [],
        sample_boxes: [],
        white_zero_rgb: [255, 255, 255],
        black_zero_rgb: [24, 24, 24],
        estimated_rgb: [100, 120, 140],
        estimated_k: [1.2, 1.3, 1.4],
      },
    });

    render(<GradientCardExtractPanel />);

    const resultActions = screen.getByTestId("gradient-card-verification-result-actions");
    await act(async () => {
      fireEvent.click(
        within(resultActions).getByRole("button", { name: /合并结果|merge result/i }),
      );
    });

    expect(saveMock).toHaveBeenCalledWith({
      sessionId: "sess-verify",
      materialName: "PLA Basic",
      targetDirectoryName: "pla-basic",
      saveMode: "merge",
      brand: null,
    });
  });

  it("defaults the anchor-corner dropdowns to auto-detection", () => {
    render(<GradientCardExtractPanel />);

    const whiteWrapper = screen.getByTestId("manual-white-anchor-select");
    const whiteCombobox = within(whiteWrapper).getByRole("combobox");
    expect(whiteCombobox).toHaveTextContent("自动检测");

    const blackWrapper = screen.getByTestId("manual-black-anchor-select");
    const blackCombobox = within(blackWrapper).getByRole("combobox");
    expect(blackCombobox).toHaveTextContent("自动检测");
  });

  it("forwards the chosen rotation direction to the extractor API for both substrates", async () => {
    const rotateMock = vi.mocked(rotateExtractorImage);
    rotateMock.mockResolvedValue({
      preview_url: "/api/files/rotated.png",
      width: 100,
      height: 100,
    });
    // Stub fetch so the rotation flow can construct a File from the preview.
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue({ blob: () => Promise.resolve(new Blob([""])) }) as unknown as typeof fetch;

    useSingleStageStore.setState({
      whiteImageFile: new File(["white"], "white.png", { type: "image/png" }),
      blackImageFile: new File(["black"], "black.png", { type: "image/png" }),
    });

    await act(async () => {
      await useSingleStageStore.getState().rotateWhiteImage("cw");
    });
    await act(async () => {
      await useSingleStageStore.getState().rotateBlackImage("ccw");
    });

    const cwCall = rotateMock.mock.calls.find((call) => call[2] === "cw");
    const ccwCall = rotateMock.mock.calls.find((call) => call[2] === "ccw");
    expect(cwCall?.[1]).toBe("white.png");
    expect(ccwCall?.[1]).toBe("black.png");

    globalThis.fetch = originalFetch;
  });

  it("uses backend PNG previews for HEIC and HEIF gradient card uploads", async () => {
    const previewMock = vi.mocked(uploadImagePreview);
    const whiteFile = new File(["white"], "white.HEIC", { type: "image/heic" });
    const blackFile = new File(["black"], "black.heif", { type: "" });
    previewMock
      .mockResolvedValueOnce({
        preview_url: "/api/files/white-preview.png",
        width: 1200,
        height: 900,
      })
      .mockResolvedValueOnce({
        preview_url: "http://localhost:8000/api/files/black-preview.png",
        width: 1000,
        height: 800,
      });

    await act(async () => {
      await useSingleStageStore.getState().setWhiteImageFile(whiteFile);
      await useSingleStageStore.getState().setBlackImageFile(blackFile);
    });

    const state = useSingleStageStore.getState();
    expect(previewMock).toHaveBeenNthCalledWith(1, whiteFile);
    expect(previewMock).toHaveBeenNthCalledWith(2, blackFile);
    expect(state.whiteImagePreviewUrl).toBe("/api/files/white-preview.png");
    expect(state.whiteImageNaturalWidth).toBe(1200);
    expect(state.whiteImageNaturalHeight).toBe(900);
    expect(state.blackImagePreviewUrl).toBe("/api/files/black-preview.png");
    expect(state.blackImageNaturalWidth).toBe(1000);
    expect(state.blackImageNaturalHeight).toBe(800);
  });

  it("lets you pick an existing saved brand from the brand selector", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 2 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "bambu-lab/pla-basic",
          brand: "Bambu Lab",
          archive_path: "materials/bambu-lab/pla-basic/material.json",
          stage_a_params_path: "materials/bambu-lab/pla-basic/stage_A_parameters.json",
          material_file_url: "/api/files/material-1.json",
          stage_a_params_url: "/api/files/stage-a-1.json",
          estimated_rgb: [100, 120, 140],
        },
        {
          material_name: "PLA Matte",
          directory_name: "polymaker/pla-matte",
          brand: "Polymaker",
          archive_path: "materials/polymaker/pla-matte/material.json",
          stage_a_params_path: "materials/polymaker/pla-matte/stage_A_parameters.json",
          material_file_url: "/api/files/material-2.json",
          stage_a_params_url: "/api/files/stage-a-2.json",
          estimated_rgb: [120, 120, 120],
        },
      ],
    });

    render(<GradientCardExtractPanel />);

    fireEvent.click(screen.getByTestId("gradient-card-material-brand-toggle"));

    const option = await screen.findByRole("option", { name: "Bambu Lab" });
    fireEvent.click(option);

    const input = screen.getByTestId("gradient-card-material-brand-input") as HTMLInputElement;
    expect(input.value).toBe("Bambu Lab");
    expect(useSingleStageStore.getState().materialBrand).toBe("Bambu Lab");
  });

  it("lets you create a new brand from typed input when it does not already exist", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "bambu-lab/pla-basic",
          brand: "Bambu Lab",
          archive_path: "materials/bambu-lab/pla-basic/material.json",
          stage_a_params_path: "materials/bambu-lab/pla-basic/stage_A_parameters.json",
          material_file_url: "/api/files/material-1.json",
          stage_a_params_url: "/api/files/stage-a-1.json",
          estimated_rgb: [100, 120, 140],
        },
      ],
    });

    render(<GradientCardExtractPanel />);

    const input = screen.getByTestId("gradient-card-material-brand-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "My New Brand" } });

    const createOption = await screen.findByTestId("gradient-card-material-brand-create-option");
    fireEvent.click(createOption);

    expect(input.value).toBe("My New Brand");
    expect(useSingleStageStore.getState().materialBrand).toBe("My New Brand");
  });

  it("shows a friendly error when the uploaded gradient card ZIP is invalid", async () => {
    const extractMock = vi.mocked(extractGradientCardStageA);
    const axiosLikeError = new Error("Request failed with status code 422") as Error & {
      response?: {
        status: number;
        data: {
          detail: string;
        };
      };
    };
    axiosLikeError.response = {
      status: 422,
      data: {
        detail: "Gradient card kit zip must contain manifest.json",
      },
    };
    extractMock.mockRejectedValueOnce(axiosLikeError);

    useSingleStageStore.setState({
      datasetFile: new File(["zip"], "wrong.zip", { type: "application/zip" }),
      whiteImageFile: new File(["white"], "white.png", { type: "image/png" }),
      blackImageFile: new File(["black"], "black.png", { type: "image/png" }),
      whiteCornerPoints: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
      blackCornerPoints: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
    });

    render(<GradientCardExtractPanel />);

    await act(async () => {
      await useSingleStageStore.getState().submitExtract();
    });

    expect(screen.getByTestId("extract-error")).toHaveTextContent(
      /ZIP 不是正确的梯度卡 Kit ZIP|uploaded ZIP is not a valid gradient card kit/i,
    );
  });

  it("shows a friendly error when an uploaded gradient card image cannot be decoded", async () => {
    const extractMock = vi.mocked(extractGradientCardStageA);
    const axiosLikeError = new Error("Request failed with status code 422") as Error & {
      response?: {
        status: number;
        data: {
          detail: string;
        };
      };
    };
    axiosLikeError.response = {
      status: 422,
      data: {
        detail: "无法解码图像文件: cannot identify image file",
      },
    };
    extractMock.mockRejectedValueOnce(axiosLikeError);

    useSingleStageStore.setState({
      datasetFile: new File(["zip"], "dataset.zip", { type: "application/zip" }),
      whiteImageFile: new File(["white"], "white.png", { type: "image/png" }),
      blackImageFile: new File(["black"], "black.png", { type: "image/png" }),
      whiteCornerPoints: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
      blackCornerPoints: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
    });

    render(<GradientCardExtractPanel />);

    await act(async () => {
      await useSingleStageStore.getState().submitExtract();
    });

    expect(screen.getByTestId("extract-error")).toHaveTextContent(
      /上传的图片无法识别|uploaded image could not be read/i,
    );
  });

  it("shows a friendly save error when the extraction session has expired", async () => {
    const saveMock = vi.mocked(saveGradientCardMaterial);
    const axiosLikeError = new Error("Request failed with status code 404") as Error & {
      response?: {
        status: number;
        data: {
          detail: string;
        };
      };
    };
    axiosLikeError.response = {
      status: 404,
      data: {
        detail: "Session sess-expired not found",
      },
    };
    saveMock.mockRejectedValueOnce(axiosLikeError);

    useSingleStageStore.setState({
      sessionId: "sess-expired",
      materialName: "PLA Basic",
    });

    render(<GradientCardExtractPanel />);

    await act(async () => {
      await useSingleStageStore.getState().submitSave();
    });

    expect(screen.getByTestId("save-error")).toHaveTextContent(
      /提取结果已失效|extraction result has expired/i,
    );
  });

  it("propagates the manual white anchor-corner selection to the extractor API call", async () => {
    const extractMock = vi.mocked(extractGradientCardStageA);
    extractMock.mockResolvedValue({
      session_id: "sess-1",
      status: "ok",
      message: "",
      stage_a_params_url: "/api/files/stage-a.json",
      white_warp_preview_url: "/api/files/white-warp.png",
      black_warp_preview_url: "/api/files/black-warp.png",
      fit_summary: {
        substrate_count: 2,
        channel_count: 1,
        substrates: ["black", "white"],
        colors: ["PLA Basic"],
        overall_validation: { mean_delta_e: 0.5, max_delta_e: 1.0, rmse_linear: 0.01 },
        warnings: [],
      },
      material_summary: {
        sample_count: 36,
        per_substrate_sample_count: 18,
        grid_rows: 3,
        grid_cols: 6,
        layer_height_mm: 0.04,
        warp_width_px: 1240,
        warp_height_px: 620,
        thickness_layers: [],
        sample_boxes: [],
        white_zero_rgb: [255, 255, 255],
        black_zero_rgb: [24, 24, 24],
        estimated_rgb: [200, 200, 200],
        estimated_k: [1.2, 1.3, 1.4],
      },
      warnings: [],
    });

    useSingleStageStore.setState({
      datasetFile: new File(["zip"], "dataset.zip", { type: "application/zip" }),
      whiteImageFile: new File(["white"], "white.png", { type: "image/png" }),
      blackImageFile: new File(["black"], "black.png", { type: "image/png" }),
      whiteCornerPoints: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
      blackCornerPoints: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
    });

    render(<GradientCardExtractPanel />);

    // User picks a manual anchor-corner for the white capture; bottom-right
    // anchor maps to the backend orientation label "rotate_180".
    const whiteWrapper = screen.getByTestId("manual-white-anchor-select");
    const whiteCombobox = within(whiteWrapper).getByRole("combobox");
    fireEvent.click(whiteCombobox);

    // The option uses the translated label
    const option = await screen.findByRole("option", { name: /右下角|Bottom-right/i });
    fireEvent.click(option);

    // Fire the extract action directly via the store to avoid pulling in
    // the image upload flow, then assert the API client received the
    // manually selected orientation. Wrap in act(...) because submitExtract
    // triggers multiple React state updates (isExtracting, response fields).
    await act(async () => {
      await useSingleStageStore.getState().submitExtract();
    });

    expect(extractMock).toHaveBeenCalledTimes(1);
    expect(extractMock).toHaveBeenCalledWith(
      expect.objectContaining({
        manualWhiteOrientation: "rotate_180",
        manualBlackOrientation: null,
      }),
    );
  });

  it("shows per-substrate signal cards and the flat hint when the white substrate is flagged flat", () => {
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
        estimated_rgb: [240, 240, 240],
        estimated_k: [2.5, 2.7, 3.0],
      },
      fitSummary: {
        substrate_count: 2,
        channel_count: 1,
        substrates: ["black", "white"],
        colors: ["PLA Basic"],
        overall_validation: { mean_delta_e: 3.2, max_delta_e: 8.0, rmse_linear: 0.08 },
        warnings: [],
      },
      orientationRanking: {
        orientation_reliable: true,
        delta_e_gap: 1.5,
        top_candidates: [
          {
            white_orientation: "identity",
            black_orientation: "identity",
            anchor_penalty: 0.01,
            mean_delta_e: 3.2,
            rmse_linear: 0.08,
            max_delta_e: 8.0,
          },
        ],
        white_signal_strength: 0.005,
        black_signal_strength: 0.12,
        white_orientation_info: {
          signal_strength: 0.005,
          flat: true,
          manual_override: null,
          locked_to: null,
        },
        black_orientation_info: {
          signal_strength: 0.12,
          flat: false,
          manual_override: null,
          locked_to: null,
        },
      },
    });

    render(<GradientCardExtractPanel />);

    // Signal cards render for both substrates with the correct rounded values.
    expect(screen.getByTestId("white-orientation-signal")).toHaveTextContent("0.0050");
    expect(screen.getByTestId("black-orientation-signal")).toHaveTextContent("0.1200");
    // Flat badge only appears on the white card.
    expect(screen.getByTestId("white-orientation-signal-flat-badge")).toBeInTheDocument();
    expect(screen.queryByTestId("black-orientation-signal-flat-badge")).not.toBeInTheDocument();
    // The recovery hint banner is shown, steering the user to manual override.
    expect(screen.getByTestId("orientation-flat-substrate-hint")).toBeInTheDocument();
  });

  it("does not render the image-source selector UI and pins imageSource to raw", () => {
    // Stage A no longer exposes the raw/restored toggle: restored
    // captures break the Beer-Lambert C0_white anchor and are caught
    // post-hoc by the bias filter. The store retains the field for
    // backend contract compatibility but the UI must stay hidden so
    // every extract call goes out as ``raw``.
    render(<GradientCardExtractPanel />);

    // None of the legacy testids should resolve.
    expect(
      screen.queryByTestId("gradient-card-image-source-section"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("gradient-card-image-source-raw"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("gradient-card-image-source-restored"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("gradient-card-image-source-restored-warning"),
    ).not.toBeInTheDocument();

    // Store still defaults to raw so submitExtract sends raw.
    expect(useSingleStageStore.getState().imageSource).toBe("raw");
  });

  it("propagates the store's imageSource value to the extractGradientCardStageA call", async () => {
    const extractMock = vi.mocked(extractGradientCardStageA);
    extractMock.mockResolvedValue({
      session_id: "sess-img-source",
      status: "ok",
      message: "",
      stage_a_params_url: "/api/files/stage-a.json",
      white_warp_preview_url: "/api/files/white-warp.png",
      black_warp_preview_url: "/api/files/black-warp.png",
      fit_summary: {
        substrate_count: 2,
        channel_count: 1,
        substrates: ["black", "white"],
        colors: ["PLA Basic"],
        overall_validation: { mean_delta_e: 0.5, max_delta_e: 1.0, rmse_linear: 0.01 },
        warnings: [],
      },
      material_summary: {
        sample_count: 36,
        per_substrate_sample_count: 18,
        grid_rows: 3,
        grid_cols: 6,
        layer_height_mm: 0.04,
        warp_width_px: 1240,
        warp_height_px: 620,
        thickness_layers: [],
        sample_boxes: [],
        white_zero_rgb: [255, 255, 255],
        black_zero_rgb: [24, 24, 24],
        estimated_rgb: [200, 200, 200],
        estimated_k: [1.2, 1.3, 1.4],
      },
      warnings: [],
    });

    useSingleStageStore.setState({
      datasetFile: new File(["zip"], "dataset.zip", { type: "application/zip" }),
      whiteImageFile: new File(["white"], "white.png", { type: "image/png" }),
      blackImageFile: new File(["black"], "black.png", { type: "image/png" }),
      whiteCornerPoints: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
      blackCornerPoints: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
    });

    render(<GradientCardExtractPanel />);

    // The UI radio is intentionally hidden (raw is the only supported
    // source). We still exercise the contract by mutating the store
    // directly to confirm submitExtract forwards whatever imageSource
    // is set, so the wire format stays stable for power-users / tests
    // that flip the field programmatically.
    await act(async () => {
      useSingleStageStore.getState().setImageSource("restored");
    });

    await act(async () => {
      await useSingleStageStore.getState().submitExtract();
    });

    expect(extractMock).toHaveBeenCalledTimes(1);
    expect(extractMock).toHaveBeenCalledWith(
      expect.objectContaining({ imageSource: "restored" }),
    );
  });

  it("shows the manual badge and suppresses the flat hint once a manual override is in effect", () => {
    useSingleStageStore.setState({
      manualWhiteAnchor: "tr",
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
        estimated_rgb: [240, 240, 240],
        estimated_k: [2.5, 2.7, 3.0],
      },
      fitSummary: {
        substrate_count: 2,
        channel_count: 1,
        substrates: ["black", "white"],
        colors: ["PLA Basic"],
        overall_validation: { mean_delta_e: 0.3, max_delta_e: 0.8, rmse_linear: 0.02 },
        warnings: [],
      },
      orientationRanking: {
        orientation_reliable: true,
        delta_e_gap: 0.0,
        top_candidates: [
          {
            white_orientation: "flip_horizontal",
            black_orientation: "identity",
            anchor_penalty: 0.01,
            mean_delta_e: 0.3,
            rmse_linear: 0.02,
            max_delta_e: 0.8,
          },
        ],
        white_signal_strength: 0.005,
        black_signal_strength: 0.12,
        white_orientation_info: {
          signal_strength: 0.005,
          flat: true,
          manual_override: "flip_horizontal",
          locked_to: "flip_horizontal",
        },
        black_orientation_info: {
          signal_strength: 0.12,
          flat: false,
          manual_override: null,
          locked_to: null,
        },
      },
    });

    render(<GradientCardExtractPanel />);

    // Manual badge visible; flat badge still visible (substrate IS flat), but
    // the recovery hint is suppressed because the user already overrode.
    expect(screen.getByTestId("white-orientation-signal-flat-badge")).toBeInTheDocument();
    expect(screen.getByTestId("white-orientation-signal-manual-badge")).toBeInTheDocument();
    expect(
      screen.queryByTestId("orientation-flat-substrate-hint"),
    ).not.toBeInTheDocument();
  });

  // ----- Merge diagnostics section -----------------------------------
  // The "merge diagnostics" card is only rendered when the saved
  // material summary carries a populated ``aggregation_selection``
  // block. These tests pin down the three states the user actually
  // sees: hidden when missing, "no exclusions" message after a clean
  // single-run save, and a per-run breakdown with badges & flag
  // labels after a multi-run merge that excluded a biased run.

  it("does not render the merge diagnostics section when no aggregation_selection is present", () => {
    useSingleStageStore.setState({
      savedMaterialSummary: {
        material_name: "Test",
        directory_name: "test",
        archive_path: "/m/test/material.json",
        stage_a_params_path: "/m/test/stage_A_parameters.json",
        verification_count: 1,
      },
    });

    render(<GradientCardExtractPanel />);

    expect(
      screen.queryByTestId("merge-diagnostics-section"),
    ).not.toBeInTheDocument();
  });

  it("renders the merge diagnostics section with included badges and 'no excluded' message after a clean single-run save", () => {
    useSingleStageStore.setState({
      savedMaterialSummary: {
        material_name: "Test",
        directory_name: "test",
        archive_path: "/m/test/material.json",
        stage_a_params_path: "/m/test/stage_A_parameters.json",
        verification_count: 1,
        aggregation_method: "refit_combined_samples",
        aggregation_selection: {
          selected_indices: [0],
          excluded_runs: [],
          selection_strategy: "bias_filter_v1",
          fresh_index: 0,
          run_scores: [
            {
              index: 0,
              is_fresh: true,
              bias_flag_count: 0,
              bias_flags: [],
              structural_flag_count: 0,
              structural_flags: [],
              white_c0_avg: 0.88,
              image_source: "raw",
              cross_val_rmse: null,
            },
          ],
        },
      },
    });

    render(<GradientCardExtractPanel />);

    expect(screen.getByTestId("merge-diagnostics-section")).toBeInTheDocument();
    expect(screen.getByTestId("merge-diagnostics-runs-used")).toHaveTextContent(
      /1.*1|1\s*\/\s*1/,
    );
    expect(screen.getByTestId("merge-diagnostics-method")).toHaveTextContent(
      /合并样本重拟合|Refit on combined samples/i,
    );
    expect(screen.getByTestId("merge-diagnostics-strategy")).toHaveTextContent(
      /偏置硬过滤|Bias filter/i,
    );
    expect(
      screen.getByTestId("merge-diagnostics-run-0-fresh-badge"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("merge-diagnostics-run-0-included-badge"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("merge-diagnostics-run-0-excluded-badge"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("merge-diagnostics-no-excluded"),
    ).toBeInTheDocument();
  });

  it("renders excluded badges and the matching bias-flag label when a historical run is dropped by the bias filter", () => {
    useSingleStageStore.setState({
      savedMaterialSummary: {
        material_name: "Test",
        directory_name: "test",
        archive_path: "/m/test/material.json",
        stage_a_params_path: "/m/test/stage_A_parameters.json",
        verification_count: 2,
        aggregation_method: "refit_combined_samples",
        aggregation_selection: {
          selected_indices: [1],
          excluded_runs: [
            {
              index: 0,
              reason: "bias_filter",
              bias_flags: ["c0_white_avg_gt_0_95"],
              structural_flags: ["c0_white_avg_gt_0_95"],
              cross_val_rmse: null,
            },
          ],
          selection_strategy: "bias_filter_v1",
          fresh_index: 1,
          run_scores: [
            {
              index: 0,
              is_fresh: false,
              bias_flag_count: 1,
              bias_flags: ["c0_white_avg_gt_0_95"],
              structural_flag_count: 1,
              structural_flags: ["c0_white_avg_gt_0_95"],
              white_c0_avg: 0.97,
              image_source: "raw",
              cross_val_rmse: null,
            },
            {
              index: 1,
              is_fresh: true,
              bias_flag_count: 0,
              bias_flags: [],
              structural_flag_count: 0,
              structural_flags: [],
              white_c0_avg: 0.88,
              image_source: "raw",
              cross_val_rmse: null,
            },
          ],
        },
      },
    });

    render(<GradientCardExtractPanel />);

    // Top-level summary line shows "1 of 2".
    expect(screen.getByTestId("merge-diagnostics-runs-used")).toHaveTextContent(
      /1.*2|1\s*\/\s*2/,
    );
    // Excluded run gets the excluded badge and the c0_white bias label.
    expect(
      screen.getByTestId("merge-diagnostics-run-0-excluded-badge"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId(
        "merge-diagnostics-run-0-flag-c0_white_avg_gt_0_95",
      ),
    ).toBeInTheDocument();
    // The fresh run keeps included + fresh badges.
    expect(
      screen.getByTestId("merge-diagnostics-run-1-fresh-badge"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("merge-diagnostics-run-1-included-badge"),
    ).toBeInTheDocument();
    // Because at least one run is excluded the "no excluded" hint is hidden.
    expect(
      screen.queryByTestId("merge-diagnostics-no-excluded"),
    ).not.toBeInTheDocument();
  });
});
