import { beforeEach, describe, expect, it, vi } from "vitest";

import { extractGradientCardStageA } from "../api/extractor";
import { uploadImagePreview } from "../api/system";
import { useSingleStageStore } from "../stores/singleStageStore";

vi.mock("../api/extractor", () => ({
  colorcheckerRelease: vi.fn(),
  extractGradientCardStageA: vi.fn(),
  rotateExtractorImage: vi.fn(),
  saveGradientCardMaterial: vi.fn(),
}));

vi.mock("../api/system", () => ({
  uploadImagePreview: vi.fn(),
}));

const buildPngFile = (name: string) =>
  new File([new Uint8Array([1, 2, 3])], name, { type: "image/png" });

const mockedExtractGradientCardStageA = vi.mocked(extractGradientCardStageA);

describe("useSingleStageStore ColorChecker flow", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useSingleStageStore.setState({
      colorchecker_enabled: false,
      colorchecker_phase: null,
      colorchecker_target: null,
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
      calibratedPreviewUrl: null,
      pendingColorcheckerFileId: null,
      pendingColorcheckerFullWidth: null,
      pendingColorcheckerFullHeight: null,
      pendingColorcheckerPreviewWidth: null,
      pendingColorcheckerPreviewHeight: null,
      whiteColorcheckerFileId: null,
      blackColorcheckerFileId: null,
      originalWhitePreviewUrl: null,
      colorcheckerSummary: null,
      imageSource: "raw",
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:gradient-card-source");
    vi.mocked(uploadImagePreview).mockResolvedValue({
      preview_url: "/api/files/gradient-card-preview.png",
      width: 640,
      height: 480,
    });
  });

  it("starts ColorChecker calibration for the black substrate upload", async () => {
    const blackFile = buildPngFile("black.png");

    useSingleStageStore.getState().setColorcheckerEnabled(true);
    await useSingleStageStore.getState().setBlackImageFile(blackFile);

    const state = useSingleStageStore.getState();
    expect(state.colorchecker_phase).toBe("calibrating");
    expect(state.colorchecker_target).toBe("black");
    expect(state.blackImageFile).toBe(blackFile);
    expect(state.blackImagePreviewUrl).toBeNull();
    expect(state.originalWhitePreviewUrl).toBe("/api/files/gradient-card-preview.png");
    expect(uploadImagePreview).toHaveBeenCalledWith(blackFile);
  });

  it("marks confirmed ColorChecker images as restored source", () => {
    useSingleStageStore.setState({
      colorchecker_phase: "confirming",
      colorchecker_target: "white",
      pendingColorcheckerFileId: "full-id",
      calibratedPreviewUrl: "/api/files/calibrated-preview.jpg",
      imageSource: "raw",
    });

    useSingleStageStore.getState().confirmCalibrated();

    const state = useSingleStageStore.getState();
    expect(state.imageSource).toBe("restored");
  });

  it("submits private ColorChecker ids without image files", async () => {
    mockedExtractGradientCardStageA.mockResolvedValueOnce({
      session_id: "stage-a-session",
      status: "success",
      message: "ok",
      stage_a_params_url: "/api/files/stage-a.json",
      white_warp_preview_url: "/api/files/white-warp.png",
      black_warp_preview_url: "/api/files/black-warp.png",
      fit_summary: {
        substrate_count: 2,
        channel_count: 4,
        substrates: [],
        colors: [],
        overall_validation: {},
        warnings: [],
      },
      material_summary: {
        sample_count: 0,
        per_substrate_sample_count: 0,
        grid_rows: 0,
        grid_cols: 0,
        layer_height_mm: 0.2,
        thickness_layers: [],
        sample_boxes: [],
        white_zero_rgb: [],
        black_zero_rgb: [],
        estimated_rgb: [],
        estimated_k: [],
      },
      warnings: [],
    });

    useSingleStageStore.setState({
      datasetFile: new File([new Uint8Array([1])], "kit.zip", {
        type: "application/zip",
      }),
      whiteImageFile: buildPngFile("white.png"),
      blackImageFile: buildPngFile("black.png"),
      whiteCornerPoints: [[0, 0], [10, 0], [10, 10], [0, 10]],
      blackCornerPoints: [[0, 0], [20, 0], [20, 20], [0, 20]],
      whiteImageNaturalWidth: 640,
      whiteImageNaturalHeight: 480,
      blackImageNaturalWidth: 320,
      blackImageNaturalHeight: 240,
      whiteColorcheckerFileId: "white-full-id",
      blackColorcheckerFileId: "black-full-id",
      imageSource: "restored",
    });

    await useSingleStageStore.getState().submitExtract();

    expect(mockedExtractGradientCardStageA).toHaveBeenCalledWith(
      expect.objectContaining({
        whiteImage: null,
        blackImage: null,
        whiteColorcheckerFileId: "white-full-id",
        blackColorcheckerFileId: "black-full-id",
        whiteCornerPointsWidth: 640,
        whiteCornerPointsHeight: 480,
        blackCornerPointsWidth: 320,
        blackCornerPointsHeight: 240,
        imageSource: "restored",
      }),
    );
  });
});
