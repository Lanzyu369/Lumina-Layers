import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  colorcheckerConfirm,
  colorcheckerRelease,
  extractGradientCardStageA,
  rotateExtractorImage,
} from "../api/extractor";
import { uploadImagePreview } from "../api/system";
import apiClient from "../api/client";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useSettingsStore } from "../stores/settingsStore";

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
const heicUnsupportedDetail =
  "当前环境暂不支持 HEIC/HEIF 图片，请先转换为 PNG/JPEG 后再上传。";

const mockedExtractGradientCardStageA = vi.mocked(extractGradientCardStageA);
const mockedColorcheckerConfirm = vi.mocked(colorcheckerConfirm);
const mockedColorcheckerRelease = vi.mocked(colorcheckerRelease);
const mockedRotateExtractorImage = vi.mocked(rotateExtractorImage);

async function buildNormalizedApiError(detail: string, status = 500): Promise<unknown> {
  const previousLanguage = useSettingsStore.getState().language;
  useSettingsStore.setState({ language: "en" });
  const error = new Error(`Request failed with status code ${status}`);
  Object.assign(error, {
    config: { method: "post", url: "/gradient-card/extract" },
    response: { status, data: { detail } },
  });
  apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);
  try {
    await apiClient.post("/gradient-card/extract", {});
  } catch (err) {
    return err;
  } finally {
    apiClient.defaults.adapter = undefined;
    useSettingsStore.setState({ language: previousLanguage });
  }
  throw new Error("Expected apiClient to reject");
}

function buildApiDetailError(detail: string): unknown {
  return Object.assign(new Error("Request failed with status code 422"), {
    response: { status: 422, data: { detail } },
  });
}

type MockImageHandle = {
  onload: (() => void) | null;
  onerror: (() => void) | null;
  naturalWidth: number;
  naturalHeight: number;
  src: string;
};

const resolvePending = <T,>(resolver: ((value: T) => void) | null, value: T) => {
  if (!resolver) {
    throw new Error("Expected a pending mocked request resolver");
  }
  resolver(value);
};

const requireCreatedImage = (image: MockImageHandle | null): MockImageHandle => {
  if (!image) {
    throw new Error("Expected the store to create a preview Image");
  }
  return image;
};

const triggerImageLoad = (image: MockImageHandle | null) => {
  image?.onload?.();
};

const triggerImageError = (image: MockImageHandle | null) => {
  image?.onerror?.();
};

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
      isRotatingWhite: false,
      isRotatingBlack: false,
      isExtracting: false,
      extractError: null,
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
    expect(state.originalWhitePreviewUrl).toBeNull();
    expect(uploadImagePreview).not.toHaveBeenCalled();
  });

  it("does not request system previews for ColorChecker substrate targets", async () => {
    const blackFile = buildPngFile("black.png");
    const whiteFile = buildPngFile("white.png");

    useSingleStageStore.getState().setColorcheckerEnabled(true);
    await useSingleStageStore.getState().setBlackImageFile(blackFile);
    await useSingleStageStore.getState().setWhiteImageFile(whiteFile);

    const state = useSingleStageStore.getState();
    expect(state.colorchecker_target).toBe("white");
    expect(state.originalWhitePreviewUrl).toBeNull();
    expect(uploadImagePreview).not.toHaveBeenCalled();
  });

  it("clears the previous substrate preview when starting another ColorChecker upload", async () => {
    const blackFile = buildPngFile("black.png");
    const whiteFile = buildPngFile("white.png");

    useSingleStageStore.getState().setColorcheckerEnabled(true);
    await useSingleStageStore.getState().setBlackImageFile(blackFile);

    await useSingleStageStore.getState().setWhiteImageFile(whiteFile);

    const state = useSingleStageStore.getState();
    expect(state.colorchecker_target).toBe("white");
    expect(state.originalWhitePreviewUrl).toBeNull();
    expect(uploadImagePreview).not.toHaveBeenCalled();
  });

  it("restores substrate previews when ColorChecker is disabled before acceptance", async () => {
    const blackFile = buildPngFile("black.png");
    const whiteFile = buildPngFile("white.png");

    useSingleStageStore.getState().setColorcheckerEnabled(true);
    await useSingleStageStore.getState().setBlackImageFile(blackFile);
    await useSingleStageStore.getState().setWhiteImageFile(whiteFile);

    useSingleStageStore.getState().setColorcheckerEnabled(false);

    const state = useSingleStageStore.getState();
    expect(state.colorchecker_enabled).toBe(false);
    expect(state.colorchecker_phase).toBeNull();
    expect(state.whiteImagePreviewUrl).toBe("blob:gradient-card-source");
    expect(state.blackImagePreviewUrl).toBe("blob:gradient-card-source");
    expect(state.whiteColorcheckerFileId).toBeNull();
    expect(state.blackColorcheckerFileId).toBeNull();
    expect(uploadImagePreview).not.toHaveBeenCalled();
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
        // eslint-disable-next-line @typescript-eslint/no-this-alias
        createdImage = this;
      }
    }
    globalThis.Image = MockImage as unknown as typeof Image;

    try {
      mockedColorcheckerConfirm.mockResolvedValueOnce({
        status: "ok",
        confirmed: true,
        calibrated_preview_url: "/api/files/fresh-stage-a-preview.jpg",
        preview_width: 640,
        preview_height: 480,
        source_preview_url: "/api/files/preserved-white-source.jpg",
        source_preview_width: 1600,
        source_preview_height: 1200,
      });
      useSingleStageStore.setState({
        colorchecker_enabled: true,
        colorchecker_phase: "confirming",
        colorchecker_target: "white",
        pendingColorcheckerFileId: "full-id",
        calibratedPreviewUrl: "/api/files/calibrated-preview.jpg",
        originalWhitePreviewUrl: "/api/files/source-owned-white.jpg",
        originalWhitePreviewWidth: 800,
        originalWhitePreviewHeight: 600,
        imageSource: "raw",
      });

      useSingleStageStore.getState().confirmCalibrated({
        sourceFileId: "white-source-id",
        sourcePreviewUrl: "/api/files/source-owned-white.jpg",
      });
      await vi.waitFor(() =>
        expect(mockedColorcheckerConfirm).toHaveBeenCalledWith(
          "full-id",
          "/api/files/calibrated-preview.jpg",
          {
            sourceFileId: "white-source-id",
            sourcePreviewUrl: "/api/files/source-owned-white.jpg",
          },
        ),
      );
      const acceptedImage = requireCreatedImage(createdImage);
      expect(acceptedImage.src).toBe("/api/files/fresh-stage-a-preview.jpg");
      acceptedImage.onload?.();

      const state = useSingleStageStore.getState();
      expect(state.imageSource).toBe("restored");
      expect(state.whiteImagePreviewUrl).toBe("/api/files/fresh-stage-a-preview.jpg");
      expect(state.whiteImageNaturalWidth).toBe(640);
      expect(state.whiteImageNaturalHeight).toBe(480);
      expect(state.originalWhitePreviewUrl).toBe("/api/files/preserved-white-source.jpg");
      expect(state.originalWhitePreviewWidth).toBe(1600);
      expect(state.originalWhitePreviewHeight).toBe(1200);

      mockedColorcheckerRelease.mockClear();
      useSingleStageStore.getState().setColorcheckerEnabled(false);
      const restoredState = useSingleStageStore.getState();
      expect(mockedColorcheckerRelease).toHaveBeenCalledWith("full-id");
      expect(restoredState.whiteImagePreviewUrl).toBe("/api/files/preserved-white-source.jpg");
      expect(restoredState.whiteImageNaturalWidth).toBe(1600);
      expect(restoredState.whiteImageNaturalHeight).toBe(1200);
    } finally {
      globalThis.Image = OriginalImage;
    }
  });

  it("preserves the black source preview returned by confirm", async () => {
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
        // eslint-disable-next-line @typescript-eslint/no-this-alias
        createdImage = this;
      }
    }
    globalThis.Image = MockImage as unknown as typeof Image;

    try {
      mockedColorcheckerConfirm.mockResolvedValueOnce({
        status: "ok",
        confirmed: true,
        calibrated_preview_url: "/api/files/fresh-black-preview.jpg",
        preview_width: 640,
        preview_height: 480,
        source_preview_url: "/api/files/preserved-black-source.jpg",
        source_preview_width: 1200,
        source_preview_height: 900,
      });
      useSingleStageStore.setState({
        colorchecker_enabled: true,
        colorchecker_phase: "confirming",
        colorchecker_target: "black",
        pendingColorcheckerFileId: "black-full-id",
        calibratedPreviewUrl: "/api/files/black-calibrated-preview.jpg",
        originalBlackPreviewUrl: "/api/files/source-owned-black.jpg",
        originalBlackPreviewWidth: 600,
        originalBlackPreviewHeight: 450,
        imageSource: "raw",
      });

      useSingleStageStore.getState().confirmCalibrated({
        sourceFileId: "black-source-id",
        sourcePreviewUrl: "/api/files/source-owned-black.jpg",
      });
      await vi.waitFor(() =>
        expect(mockedColorcheckerConfirm).toHaveBeenCalledWith(
          "black-full-id",
          "/api/files/black-calibrated-preview.jpg",
          {
            sourceFileId: "black-source-id",
            sourcePreviewUrl: "/api/files/source-owned-black.jpg",
          },
        ),
      );
      triggerImageLoad(createdImage);

      const state = useSingleStageStore.getState();
      expect(state.blackImagePreviewUrl).toBe("/api/files/fresh-black-preview.jpg");
      expect(state.blackColorcheckerFileId).toBe("black-full-id");
      expect(state.originalBlackPreviewUrl).toBe("/api/files/preserved-black-source.jpg");
      expect(state.originalBlackPreviewWidth).toBe(1200);
      expect(state.originalBlackPreviewHeight).toBe(900);

      mockedColorcheckerRelease.mockClear();
      useSingleStageStore.getState().setColorcheckerEnabled(false);
      const restoredState = useSingleStageStore.getState();
      expect(mockedColorcheckerRelease).toHaveBeenCalledWith("black-full-id");
      expect(restoredState.blackImagePreviewUrl).toBe("/api/files/preserved-black-source.jpg");
      expect(restoredState.blackImageNaturalWidth).toBe(1200);
      expect(restoredState.blackImageNaturalHeight).toBe(900);
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

  it("does not disable confirmed Stage A ColorChecker images while extracting", () => {
    useSingleStageStore.setState({
      isExtracting: true,
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      whiteColorcheckerFileId: "white-full-id",
      blackColorcheckerFileId: "black-full-id",
      imageSource: "restored",
    });

    useSingleStageStore.getState().setColorcheckerEnabled(false);

    const state = useSingleStageStore.getState();
    expect(state.colorchecker_enabled).toBe(true);
    expect(state.whiteColorcheckerFileId).toBe("white-full-id");
    expect(state.blackColorcheckerFileId).toBe("black-full-id");
    expect(state.imageSource).toBe("restored");
    expect(mockedColorcheckerRelease).not.toHaveBeenCalled();
  });

  it("does not replace confirmed Stage A ColorChecker images while extracting", async () => {
    const whiteFile = buildPngFile("white.png");
    const blackFile = buildPngFile("black.png");
    useSingleStageStore.setState({
      isExtracting: true,
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      whiteImageFile: whiteFile,
      blackImageFile: blackFile,
      whiteImagePreviewUrl: "/api/files/white-preview.jpg",
      blackImagePreviewUrl: "/api/files/black-preview.jpg",
      whiteColorcheckerFileId: "white-full-id",
      blackColorcheckerFileId: "black-full-id",
      imageSource: "restored",
    });

    await useSingleStageStore.getState().setWhiteImageFile(buildPngFile("white-new.png"));
    await useSingleStageStore.getState().setBlackImageFile(buildPngFile("black-new.png"));

    const state = useSingleStageStore.getState();
    expect(state.whiteImageFile).toBe(whiteFile);
    expect(state.blackImageFile).toBe(blackFile);
    expect(state.whiteColorcheckerFileId).toBe("white-full-id");
    expect(state.blackColorcheckerFileId).toBe("black-full-id");
    expect(mockedColorcheckerRelease).not.toHaveBeenCalled();
    expect(uploadImagePreview).not.toHaveBeenCalled();
  });

  it("does not rotate confirmed Stage A ColorChecker images while extracting", async () => {
    const whiteFile = buildPngFile("white.png");
    const blackFile = buildPngFile("black.png");
    useSingleStageStore.setState({
      isExtracting: true,
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      whiteImageFile: whiteFile,
      blackImageFile: blackFile,
      whiteColorcheckerFileId: "white-full-id",
      blackColorcheckerFileId: "black-full-id",
      imageSource: "restored",
    });

    await useSingleStageStore.getState().rotateWhiteImage("cw");
    await useSingleStageStore.getState().rotateBlackImage("ccw");

    const state = useSingleStageStore.getState();
    expect(mockedRotateExtractorImage).not.toHaveBeenCalled();
    expect(mockedColorcheckerRelease).not.toHaveBeenCalled();
    expect(state.whiteColorcheckerFileId).toBe("white-full-id");
    expect(state.blackColorcheckerFileId).toBe("black-full-id");
    expect(state.isExtracting).toBe(true);
  });

  it("does not treat failed white rotation preview downloads as image files", async () => {
    const originalFetch = globalThis.fetch;
    const whiteFile = buildPngFile("white.png");
    mockedRotateExtractorImage.mockResolvedValueOnce({
      preview_url: "/api/files/expired-white-rotation.png",
      width: 100,
      height: 100,
    });
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ detail: "Not Found" }),
    }) as unknown as typeof fetch;

    try {
      useSingleStageStore.setState({
        whiteImageFile: whiteFile,
        whiteImagePreviewUrl: "/api/files/original-white.png",
      });

      await useSingleStageStore.getState().rotateWhiteImage("cw");

      const state = useSingleStageStore.getState();
      expect(state.whiteImageFile).toBe(whiteFile);
      expect(state.whiteImagePreviewUrl).toBe("/api/files/original-white.png");
      expect(state.isRotatingWhite).toBe(false);
      expect(state.extractError).toMatch(/requested resource|请求的资源/);
      expect(state.extractError).not.toContain("404");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("does not treat failed black rotation preview downloads as image files", async () => {
    const originalFetch = globalThis.fetch;
    const blackFile = buildPngFile("black.png");
    mockedRotateExtractorImage.mockResolvedValueOnce({
      preview_url: "/api/files/expired-black-rotation.png",
      width: 100,
      height: 100,
    });
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ detail: "Not Found" }),
    }) as unknown as typeof fetch;

    try {
      useSingleStageStore.setState({
        blackImageFile: blackFile,
        blackImagePreviewUrl: "/api/files/original-black.png",
      });

      await useSingleStageStore.getState().rotateBlackImage("ccw");

      const state = useSingleStageStore.getState();
      expect(state.blackImageFile).toBe(blackFile);
      expect(state.blackImagePreviewUrl).toBe("/api/files/original-black.png");
      expect(state.isRotatingBlack).toBe(false);
      expect(state.extractError).toMatch(/requested resource|请求的资源/);
      expect(state.extractError).not.toContain("404");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("uses readable API fallbacks for numeric gradient card extraction failures", async () => {
    const normalizedError = await buildNormalizedApiError("500", 500);
    mockedExtractGradientCardStageA.mockRejectedValueOnce(normalizedError);

    useSingleStageStore.setState({
      datasetFile: new File(["zip"], "kit.zip", { type: "application/zip" }),
      whiteImageFile: buildPngFile("white.png"),
      blackImageFile: buildPngFile("black.png"),
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
      whiteImageNaturalWidth: 100,
      whiteImageNaturalHeight: 100,
      blackImageNaturalWidth: 100,
      blackImageNaturalHeight: 100,
    });

    await useSingleStageStore.getState().submitExtract();

    expect(useSingleStageStore.getState().extractError).toBe(
      "The server hit an internal error. Check the log for the request ID.",
    );
  });

  it("maps safe HEIC unsupported details to the gradient-card upload guidance", async () => {
    const previousLanguage = useSettingsStore.getState().language;
    useSettingsStore.setState({ language: "en" });
    mockedExtractGradientCardStageA.mockRejectedValueOnce(
      buildApiDetailError(heicUnsupportedDetail),
    );

    try {
      useSingleStageStore.setState({
        datasetFile: new File(["zip"], "kit.zip", { type: "application/zip" }),
        whiteImageFile: buildPngFile("white.heic"),
        blackImageFile: buildPngFile("black.png"),
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
        whiteImageNaturalWidth: 100,
        whiteImageNaturalHeight: 100,
        blackImageNaturalWidth: 100,
        blackImageNaturalHeight: 100,
      });

      await useSingleStageStore.getState().submitExtract();

      expect(useSingleStageStore.getState().extractError).toBe(
        "HEIC/HEIF images are not supported in the current environment. Please convert them to PNG or JPG before uploading.",
      );
    } finally {
      useSettingsStore.setState({ language: previousLanguage });
    }
  });

  it("ignores stale Stage A extraction responses after ColorChecker state changes", async () => {
    let resolveExtract:
      | ((value: Awaited<ReturnType<typeof extractGradientCardStageA>>) => void)
      | null = null;
    mockedExtractGradientCardStageA.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveExtract = resolve;
      }),
    );

    useSingleStageStore.setState({
      datasetFile: new File([new Uint8Array([1])], "kit.zip", {
        type: "application/zip",
      }),
      whiteImageFile: buildPngFile("white.png"),
      blackImageFile: buildPngFile("black.png"),
      whiteCornerPoints: [[0, 0], [10, 0], [10, 10], [0, 10]],
      blackCornerPoints: [[0, 0], [20, 0], [20, 20], [0, 20]],
      whiteColorcheckerFileId: "white-full-id",
      blackColorcheckerFileId: "black-full-id",
      imageSource: "restored",
      sessionId: null,
      stageAParamsUrl: null,
    });

    const submit = useSingleStageStore.getState().submitExtract();
    await vi.waitFor(() => {
      expect(mockedExtractGradientCardStageA).toHaveBeenCalled();
    });

    useSingleStageStore.setState({
      colorchecker_enabled: false,
      whiteColorcheckerFileId: null,
      blackColorcheckerFileId: null,
      imageSource: "raw",
    });
    resolvePending(resolveExtract, {
      session_id: "stale-stage-a-session",
      status: "success",
      message: "ok",
      stage_a_params_url: "/api/files/stale-stage-a.json",
      white_warp_preview_url: "/api/files/stale-white-warp.png",
      black_warp_preview_url: "/api/files/stale-black-warp.png",
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
    await submit;

    const state = useSingleStageStore.getState();
    expect(state.sessionId).toBeNull();
    expect(state.stageAParamsUrl).toBeNull();
    expect(state.isExtracting).toBe(false);
  });

  it("ignores stale Stage A extraction responses after corner or orientation changes", async () => {
    let resolveExtract:
      | ((value: Awaited<ReturnType<typeof extractGradientCardStageA>>) => void)
      | null = null;
    mockedExtractGradientCardStageA.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveExtract = resolve;
      }),
    );

    useSingleStageStore.setState({
      datasetFile: new File([new Uint8Array([1])], "kit.zip", {
        type: "application/zip",
      }),
      whiteImageFile: buildPngFile("white.png"),
      blackImageFile: buildPngFile("black.png"),
      whiteImageNaturalWidth: 640,
      whiteImageNaturalHeight: 480,
      blackImageNaturalWidth: 320,
      blackImageNaturalHeight: 240,
      whiteCornerPoints: [[0, 0], [10, 0], [10, 10], [0, 10]],
      blackCornerPoints: [[0, 0], [20, 0], [20, 20], [0, 20]],
      manualWhiteAnchor: null,
      manualBlackAnchor: null,
      sessionId: null,
      stageAParamsUrl: null,
    });

    const submit = useSingleStageStore.getState().submitExtract();
    await vi.waitFor(() => {
      expect(mockedExtractGradientCardStageA).toHaveBeenCalled();
    });

    useSingleStageStore.getState().setManualWhiteAnchor("tr");
    useSingleStageStore.getState().clearWhiteCornerPoints();
    resolvePending(resolveExtract, {
      session_id: "stale-stage-a-session",
      status: "success",
      message: "ok",
      stage_a_params_url: "/api/files/stale-stage-a.json",
      white_warp_preview_url: "/api/files/stale-white-warp.png",
      black_warp_preview_url: "/api/files/stale-black-warp.png",
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
    await submit;

    const state = useSingleStageStore.getState();
    expect(state.manualWhiteAnchor).toBe("tr");
    expect(state.whiteCornerPoints).toEqual([]);
    expect(state.sessionId).toBeNull();
    expect(state.stageAParamsUrl).toBeNull();
    expect(state.isExtracting).toBe(false);
  });

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

    resolvePending(resolveRotate, {
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
        // eslint-disable-next-line @typescript-eslint/no-this-alias
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
      triggerImageLoad(createdImage);

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

  it("keeps the previous Stage A ColorChecker id when rejecting after confirm but before preview load", async () => {
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
        // eslint-disable-next-line @typescript-eslint/no-this-alias
        createdImage = this;
      }
    }
    globalThis.Image = MockImage as unknown as typeof Image;

    try {
      useSingleStageStore.setState({
        colorchecker_enabled: true,
        colorchecker_phase: "confirming",
        colorchecker_target: "white",
        calibratedPreviewUrl: "/api/files/new-calibrated-preview.jpg",
        pendingColorcheckerFileId: "new-full-id",
        whiteColorcheckerFileId: "old-full-id",
        imageSource: "restored",
      });

      useSingleStageStore.getState().confirmCalibrated();
      await vi.waitFor(() =>
        expect(mockedColorcheckerConfirm).toHaveBeenCalledWith(
          "new-full-id",
          "/api/files/new-calibrated-preview.jpg",
        ),
      );
      useSingleStageStore.getState().rejectCalibrated();
      triggerImageLoad(createdImage);

      const state = useSingleStageStore.getState();
      expect(mockedColorcheckerRelease).toHaveBeenCalledWith("new-full-id");
      expect(mockedColorcheckerRelease).not.toHaveBeenCalledWith("old-full-id");
      expect(state.whiteColorcheckerFileId).toBe("old-full-id");
      expect(state.pendingColorcheckerFileId).toBeNull();
      expect(state.colorchecker_phase).toBe("calibrating");
    } finally {
      globalThis.Image = OriginalImage;
    }
  });

  it("does not replace a Stage A ColorChecker id when preview loading fails", async () => {
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
        // eslint-disable-next-line @typescript-eslint/no-this-alias
        createdImage = this;
      }
    }
    globalThis.Image = MockImage as unknown as typeof Image;

    try {
      useSingleStageStore.setState({
        colorchecker_enabled: true,
        colorchecker_phase: "confirming",
        colorchecker_target: "white",
        calibratedPreviewUrl: "/api/files/new-calibrated-preview.jpg",
        pendingColorcheckerFileId: "new-full-id",
        whiteColorcheckerFileId: "old-full-id",
        imageSource: "restored",
      });

      useSingleStageStore.getState().confirmCalibrated();
      await vi.waitFor(() =>
        expect(mockedColorcheckerConfirm).toHaveBeenCalledWith(
          "new-full-id",
          "/api/files/new-calibrated-preview.jpg",
        ),
      );
      triggerImageError(createdImage);

      const state = useSingleStageStore.getState();
      expect(mockedColorcheckerRelease).not.toHaveBeenCalledWith("old-full-id");
      expect(state.colorchecker_phase).toBe("confirming");
      expect(state.whiteColorcheckerFileId).toBe("old-full-id");
      expect(state.pendingColorcheckerFileId).toBe("new-full-id");
      expect(state.imageSource).toBe("restored");
      expect(state.extractError).toBeTruthy();
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
