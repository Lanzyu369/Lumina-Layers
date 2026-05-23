import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  colorcheckerConfirm,
  colorcheckerRelease,
  extractGradientCardStageA,
  rotateExtractorImage,
} from "../api/extractor";
import { uploadImagePreview } from "../api/system";
import { useSingleStageStore } from "../stores/singleStageStore";

vi.mock("../api/extractor", () => ({
  colorcheckerConfirm: vi.fn(),
  colorcheckerRelease: vi.fn(),
  colorcheckerTouch: vi.fn(() => Promise.resolve()),
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
const mockedColorcheckerConfirm = vi.mocked(colorcheckerConfirm);
const mockedColorcheckerRelease = vi.mocked(colorcheckerRelease);
const mockedRotateExtractorImage = vi.mocked(rotateExtractorImage);

describe("useSingleStageStore ColorChecker flow", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    mockedColorcheckerConfirm.mockResolvedValue(undefined);
    mockedColorcheckerRelease.mockResolvedValue(undefined);
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

  it("marks confirmed ColorChecker images as restored source", async () => {
    const OriginalImage = globalThis.Image;
    let createdImage:
      | {
          onload: (() => void) | null;
          onerror: (() => void) | null;
          naturalWidth: number;
          naturalHeight: number;
          src: string;
        }
      | null = null;
    class MockImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      naturalWidth = 400;
      naturalHeight = 300;
      src = "";

      constructor() {
        createdImage = this;
      }
    }
    globalThis.Image = MockImage as unknown as typeof Image;

    try {
      useSingleStageStore.setState({
        colorchecker_phase: "confirming",
        colorchecker_target: "white",
        pendingColorcheckerFileId: "full-id",
        calibratedPreviewUrl: "/api/files/calibrated-preview.jpg",
        imageSource: "raw",
      });

      useSingleStageStore.getState().confirmCalibrated();
      await vi.waitFor(() => expect(mockedColorcheckerConfirm).toHaveBeenCalledWith("full-id"));
      createdImage?.onload?.();

      const state = useSingleStageStore.getState();
      expect(state.imageSource).toBe("restored");
    } finally {
      globalThis.Image = OriginalImage;
    }
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

  it.each(["calibrating", "confirming"] as const)(
    "does not compute Stage A while ColorChecker is %s",
    async (phase) => {
      useSingleStageStore.setState({
        datasetFile: new File([new Uint8Array([1])], "kit.zip", {
          type: "application/zip",
        }),
        whiteImageFile: buildPngFile("white.png"),
        blackImageFile: buildPngFile("black.png"),
        whiteCornerPoints: [[0, 0], [10, 0], [10, 10], [0, 10]],
        blackCornerPoints: [[0, 0], [20, 0], [20, 20], [0, 20]],
        colorchecker_enabled: true,
        colorchecker_phase: phase,
        colorchecker_target: "white",
        pendingColorcheckerFileId:
          phase === "confirming" ? "pending-full-id" : null,
      });

      await useSingleStageStore.getState().submitExtract();

      expect(mockedExtractGradientCardStageA).not.toHaveBeenCalled();
    },
  );

  it("releases stale ColorChecker responses for the wrong target image", () => {
    const oldWhiteFile = buildPngFile("old-white.png");
    const currentWhiteFile = buildPngFile("current-white.png");

    useSingleStageStore.setState({
      colorchecker_enabled: true,
      colorchecker_phase: "calibrating",
      colorchecker_target: "white",
      whiteImageFile: currentWhiteFile,
    });

    useSingleStageStore.getState().receiveCalibratedFromCC(
      "/api/files/stale-preview.jpg",
      "stale-full-id",
      null,
      {
        fullWidth: 800,
        fullHeight: 600,
        previewWidth: 400,
        previewHeight: 300,
      },
      { imageFile: oldWhiteFile, target: "white" },
    );

    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("stale-full-id");
    expect(useSingleStageStore.getState().pendingColorcheckerFileId).toBeNull();
    expect(useSingleStageStore.getState().colorchecker_phase).toBe("calibrating");
  });

  it("clears released white ColorChecker id when white rotation fails", async () => {
    mockedRotateExtractorImage.mockRejectedValueOnce(new Error("rotate failed"));

    useSingleStageStore.setState({
      whiteImageFile: buildPngFile("white.png"),
      whiteColorcheckerFileId: "released-white-id",
      colorchecker_phase: "done",
      imageSource: "restored",
    });

    await useSingleStageStore.getState().rotateWhiteImage("cw");

    const state = useSingleStageStore.getState();
    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("released-white-id");
    expect(state.whiteColorcheckerFileId).toBeNull();
    expect(state.pendingColorcheckerFileId).toBeNull();
    expect(state.colorchecker_phase).toBeNull();
    expect(state.imageSource).toBe("raw");
  });

  it("clears released black ColorChecker id when black rotation fails", async () => {
    mockedRotateExtractorImage.mockRejectedValueOnce(new Error("rotate failed"));

    useSingleStageStore.setState({
      blackImageFile: buildPngFile("black.png"),
      blackColorcheckerFileId: "released-black-id",
      colorchecker_phase: "done",
      imageSource: "restored",
    });

    await useSingleStageStore.getState().rotateBlackImage("ccw");

    const state = useSingleStageStore.getState();
    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("released-black-id");
    expect(state.blackColorcheckerFileId).toBeNull();
    expect(state.pendingColorcheckerFileId).toBeNull();
    expect(state.colorchecker_phase).toBeNull();
    expect(state.imageSource).toBe("raw");
  });

  it("clears restored corner points when disabling ColorChecker", () => {
    useSingleStageStore.setState({
      colorchecker_enabled: true,
      imageSource: "restored",
      whiteImageFile: buildPngFile("white.png"),
      blackImageFile: buildPngFile("black.png"),
      whiteColorcheckerFileId: "white-full-id",
      blackColorcheckerFileId: "black-full-id",
      whiteCornerPoints: [[0, 0], [10, 0], [10, 10], [0, 10]],
      blackCornerPoints: [[0, 0], [20, 0], [20, 20], [0, 20]],
      activeCanvas: "white",
      activeCornerIndex: 2,
    });

    useSingleStageStore.getState().setColorcheckerEnabled(false);

    const state = useSingleStageStore.getState();
    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("white-full-id");
    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("black-full-id");
    expect(state.whiteCornerPoints).toEqual([]);
    expect(state.blackCornerPoints).toEqual([]);
    expect(state.activeCanvas).toBeNull();
    expect(state.activeCornerIndex).toBeNull();
    expect(state.imageSource).toBe("raw");
  });

  it("releases calibration responses that arrive during rotation", async () => {
    const whiteFile = buildPngFile("white.png");
    let resolveRotate:
      | ((value: Awaited<ReturnType<typeof rotateExtractorImage>>) => void)
      | null = null;
    mockedRotateExtractorImage.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRotate = resolve;
      }),
    );
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue({ blob: () => Promise.resolve(new Blob([""])) }) as unknown as typeof fetch;

    useSingleStageStore.setState({
      colorchecker_enabled: true,
      colorchecker_phase: "calibrating",
      colorchecker_target: "white",
      whiteImageFile: whiteFile,
    });

    const rotation = useSingleStageStore.getState().rotateWhiteImage("cw");
    expect(useSingleStageStore.getState().colorchecker_phase).toBeNull();
    expect(useSingleStageStore.getState().isRotatingWhite).toBe(true);

    useSingleStageStore.getState().receiveCalibratedFromCC(
      "/api/files/stale-preview.jpg",
      "stale-full-id",
      null,
      {
        fullWidth: 800,
        fullHeight: 600,
        previewWidth: 400,
        previewHeight: 300,
      },
      { imageFile: whiteFile, target: "white" },
    );

    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("stale-full-id");

    resolveRotate?.({
      preview_url: "/api/files/rotated.png",
      width: 100,
      height: 100,
    });
    await rotation;
    globalThis.fetch = originalFetch;
  });

  it("does not reattach a pending full id after accept preview loads late", () => {
    const OriginalImage = globalThis.Image;
    let createdImage:
      | {
          onload: (() => void) | null;
          onerror: (() => void) | null;
          naturalWidth: number;
          naturalHeight: number;
          src: string;
        }
      | null = null;
    class MockImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      naturalWidth = 400;
      naturalHeight = 300;
      src = "";

      constructor() {
        createdImage = this;
      }
    }
    globalThis.Image = MockImage as unknown as typeof Image;

    try {
      useSingleStageStore.setState({
        colorchecker_enabled: true,
        colorchecker_phase: "confirming",
        colorchecker_target: "white",
        calibratedPreviewUrl: "/api/files/calibrated-preview.jpg",
        pendingColorcheckerFileId: "pending-full-id",
        whiteImageFile: buildPngFile("white.png"),
      });

      useSingleStageStore.getState().confirmCalibrated();
      useSingleStageStore.getState().setColorcheckerEnabled(false);
      createdImage?.onload?.();

      const state = useSingleStageStore.getState();
      expect(mockedColorcheckerRelease).toHaveBeenCalledWith("pending-full-id");
      expect(state.whiteColorcheckerFileId).toBeNull();
      expect(state.pendingColorcheckerFileId).toBeNull();
      expect(state.colorchecker_phase).toBeNull();
      expect(state.imageSource).toBe("raw");
    } finally {
      globalThis.Image = OriginalImage;
    }
  });

  it("resets restored image source when replacing one ColorChecker image", async () => {
    useSingleStageStore.setState({
      colorchecker_enabled: true,
      imageSource: "restored",
      whiteImageFile: buildPngFile("white.png"),
      blackImageFile: buildPngFile("black.png"),
      whiteColorcheckerFileId: "white-full-id",
      blackColorcheckerFileId: "black-full-id",
      whiteCornerPoints: [[0, 0], [10, 0], [10, 10], [0, 10]],
      blackCornerPoints: [[0, 0], [20, 0], [20, 20], [0, 20]],
    });

    await useSingleStageStore.getState().setWhiteImageFile(buildPngFile("white-new.png"));
    useSingleStageStore.getState().closeColorcheckerDialog();

    const state = useSingleStageStore.getState();
    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("white-full-id");
    expect(state.whiteColorcheckerFileId).toBeNull();
    expect(state.blackColorcheckerFileId).toBe("black-full-id");
    expect(state.imageSource).toBe("raw");
  });

  it("does not submit Stage A with only one ColorChecker full id", async () => {
    useSingleStageStore.setState({
      datasetFile: new File([new Uint8Array([1])], "kit.zip", {
        type: "application/zip",
      }),
      whiteImageFile: buildPngFile("white.png"),
      blackImageFile: buildPngFile("black.png"),
      whiteCornerPoints: [[0, 0], [10, 0], [10, 10], [0, 10]],
      blackCornerPoints: [[0, 0], [20, 0], [20, 20], [0, 20]],
      blackColorcheckerFileId: "black-full-id",
      imageSource: "restored",
    });

    await useSingleStageStore.getState().submitExtract();

    expect(mockedExtractGradientCardStageA).not.toHaveBeenCalled();
    expect(useSingleStageStore.getState().extractError).toContain("ColorChecker");
  });
});
