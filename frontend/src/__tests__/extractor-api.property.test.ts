import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useExtractorStore } from "../stores/extractorStore";
import { ExtractorColorMode, ExtractorPage } from "../api/types";
import type { ExtractResponse } from "../api/types";

// ========== Mock API module ==========

vi.mock("../api/extractor", () => ({
  colorcheckerConfirm: vi.fn(),
  colorcheckerRelease: vi.fn(),
  colorcheckerTouch: vi.fn(() => Promise.resolve()),
  confirmPalette: vi.fn(),
  extractColors: vi.fn(),
  manualFixCell: vi.fn(),
  rotateExtractorImage: vi.fn(),
}));

import {
  colorcheckerConfirm,
  colorcheckerRelease,
  confirmPalette,
  extractColors,
  rotateExtractorImage,
} from "../api/extractor";

const mockedExtractColors = vi.mocked(extractColors);
const mockedConfirmPalette = vi.mocked(confirmPalette);
const mockedColorcheckerConfirm = vi.mocked(colorcheckerConfirm);
const mockedColorcheckerRelease = vi.mocked(colorcheckerRelease);
const mockedRotateExtractorImage = vi.mocked(rotateExtractorImage);

// ========== Mock browser APIs ==========

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  }),
);

// ========== Helpers ==========

function resetExtractorStore(): void {
  useExtractorStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    imageNaturalWidth: null,
    imageNaturalHeight: null,
    color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
    page: ExtractorPage.PAGE_1,
    eight_color_full_export: false,
    corner_points: [],
    offset_x: 0,
    offset_y: 0,
    zoom: 1.0,
    distortion: 0.0,
    vignette_correction: false,
    isLoading: false,
    error: null,
    session_id: null,
    lut_download_url: null,
    warp_view_url: null,
    lut_preview_url: null,
    manualFixLoading: false,
    manualFixError: null,
    page1Extracted: false,
    page2Extracted: false,
    extractedEightColorFullPages: [],
    mergeLoading: false,
    mergeError: null,
    page1Extracted_5c: false,
    page2Extracted_5c: false,
    manufacturer: "",
    type: "",
    defaultPalette: [],
    paletteConfirmed: false,
    paletteConfirmLoading: false,
    paletteConfirmError: null,
    colorchecker_enabled: false,
    colorchecker_phase: null,
    calibratedPreviewUrl: null,
    calibratedFullFileId: null,
    previousCalibratedFullFileId: null,
    calibratedFullWidth: null,
    calibratedFullHeight: null,
    calibratedPreviewWidth: null,
    calibratedPreviewHeight: null,
    originalPreviewUrl: null,
    originalPreviewWidth: null,
    originalPreviewHeight: null,
    colorcheckerSummary: null,
  });
}

// ========== Generators ==========

const arbCornerPoint = fc.tuple(
  fc.integer({ min: 0, max: 10000 }),
  fc.integer({ min: 0, max: 10000 }),
) as fc.Arbitrary<[number, number]>;

const arbFourCorners = fc.array(arbCornerPoint, {
  minLength: 4,
  maxLength: 4,
});

const arbExtractorColorMode = fc.constantFrom(
  ExtractorColorMode.BW,
  ExtractorColorMode.FOUR_COLOR_RYBW,
  ExtractorColorMode.SIX_COLOR,
  ExtractorColorMode.EIGHT_COLOR,
);

/** Generate a valid store state for submitExtract (imageFile non-null, 4 corner points). */
const arbValidExtractState = fc.record({
  color_mode: arbExtractorColorMode,
  eight_color_full_export: fc.boolean(),
  corner_points: arbFourCorners,
  offset_x: fc.integer({ min: -30, max: 30 }),
  offset_y: fc.integer({ min: -30, max: 30 }),
  zoom: fc.double({ min: 0.8, max: 1.2, noNaN: true, noDefaultInfinity: true }),
  distortion: fc.double({
    min: -0.2,
    max: 0.2,
    noNaN: true,
    noDefaultInfinity: true,
  }),
  vignette_correction: fc.boolean(),
});

/** Generate a valid ExtractResponse. */
const arbExtractResponse = fc.record({
  session_id: fc.string({ minLength: 1, maxLength: 40 }),
  status: fc.constant("success"),
  message: fc.string({ minLength: 0, maxLength: 50 }),
  lut_download_url: fc.string({ minLength: 1, maxLength: 80 }),
  warp_view_url: fc.string({ minLength: 1, maxLength: 80 }),
  lut_preview_url: fc.string({ minLength: 1, maxLength: 80 }),
  default_palette: fc.constant([] as ExtractResponse["default_palette"]),
});

const arbPaletteEntry = fc.record({
  color: fc.string({ minLength: 1, maxLength: 16 }),
  material: fc.string({ minLength: 1, maxLength: 16 }),
  hex_color: fc.option(fc.constantFrom("#FFFFFF", "#000000", "#FF0000"), {
    nil: null,
  }),
  color_name: fc.option(fc.string({ minLength: 1, maxLength: 20 }), {
    nil: null,
  }),
});

// ========== Tests ==========

beforeEach(() => {
  resetExtractorStore();
  vi.clearAllMocks();
  mockedColorcheckerConfirm.mockResolvedValue(undefined);
  mockedColorcheckerRelease.mockResolvedValue(undefined);
});

// **Feature: extractor-calibration-tab, Property 7: API 请求载荷与 Store 状态一致性**
// **Validates: Requirements 6.3**
describe("Feature: extractor-calibration-tab, Property 7: API 请求载荷与 Store 状态一致性", () => {
  it("For any valid ExtractorStore state, submitExtract sends API params matching the store state", async () => {
    await fc.assert(
      fc.asyncProperty(arbValidExtractState, async (stateInput) => {
        resetExtractorStore();
        vi.clearAllMocks();

        // Set up a mock File as imageFile
        const file = new File(["test-data"], "calibration.png", {
          type: "image/png",
        });

        // Set store state
        useExtractorStore.setState({
          imageFile: file,
          corner_points: stateInput.corner_points,
          color_mode: stateInput.color_mode,
          eight_color_full_export: stateInput.eight_color_full_export,
          offset_x: stateInput.offset_x,
          offset_y: stateInput.offset_y,
          zoom: stateInput.zoom,
          distortion: stateInput.distortion,
          vignette_correction: stateInput.vignette_correction,
        });

        // Mock extractColors to resolve with a dummy response
        mockedExtractColors.mockResolvedValueOnce({
          session_id: "dummy",
          status: "success",
          message: "ok",
          lut_download_url: "/dummy.npy",
          warp_view_url: "/dummy_warp.png",
          lut_preview_url: "/dummy_preview.png",
          default_palette: [],
        });

        // Call submitExtract
        await useExtractorStore.getState().submitExtract();

        // Verify extractColors was called exactly once
        expect(mockedExtractColors).toHaveBeenCalledTimes(1);

        // Verify the parameters match the store state
        const [calledImage, calledParams] = mockedExtractColors.mock.calls[0];

        expect(calledImage).toBe(file);
        expect(calledParams.corner_points).toEqual(stateInput.corner_points);
        expect(calledParams.color_mode).toBe(stateInput.color_mode);
        expect(calledParams.eight_color_full_export).toBe(
          stateInput.eight_color_full_export,
        );
        expect(calledParams.offset_x).toBe(stateInput.offset_x);
        expect(calledParams.offset_y).toBe(stateInput.offset_y);
        expect(calledParams.zoom).toBe(stateInput.zoom);
        expect(calledParams.distortion).toBe(stateInput.distortion);
        expect(calledParams.vignette_correction).toBe(
          stateInput.vignette_correction,
        );
      }),
      { numRuns: 100 },
    );
  });

  it("When ColorChecker is confirmed, submitExtract sends the private id without an image file", async () => {
    const file = new File(["test-data"], "calibration.png", {
      type: "image/png",
    });

    useExtractorStore.setState({
      imageFile: file,
      imageNaturalWidth: 1600,
      imageNaturalHeight: 1200,
      corner_points: [[0, 0], [100, 0], [100, 100], [0, 100]],
      auto_wb: true,
      colorchecker_phase: "done",
      calibratedFullFileId: "full-id",
    });

    mockedExtractColors.mockResolvedValueOnce({
      session_id: "dummy",
      status: "success",
      message: "ok",
      lut_download_url: "/dummy.npy",
      warp_view_url: "/dummy_warp.png",
      lut_preview_url: "/dummy_preview.png",
      default_palette: [],
    });

    await useExtractorStore.getState().submitExtract();

    expect(mockedExtractColors).toHaveBeenCalledTimes(1);
    const [calledImage, calledParams] = mockedExtractColors.mock.calls[0];
    expect(calledImage).toBeNull();
    expect(calledParams.colorcheckerCalibratedFileId).toBe("full-id");
    expect(calledParams.auto_wb).toBe(false);
    expect(calledParams.cornerPointsWidth).toBe(1600);
    expect(calledParams.cornerPointsHeight).toBe(1200);
  });

  it.each(["calibrating", "confirming"] as const)(
    "does not submit while ColorChecker is %s",
    async (phase) => {
      const file = new File(["test-data"], "calibration.png", {
        type: "image/png",
      });

      useExtractorStore.setState({
        imageFile: file,
        corner_points: [[0, 0], [100, 0], [100, 100], [0, 100]],
        colorchecker_enabled: true,
        colorchecker_phase: phase,
        calibratedFullFileId: phase === "confirming" ? "pending-full-id" : null,
      });

      await useExtractorStore.getState().submitExtract();

      expect(mockedExtractColors).not.toHaveBeenCalled();
    },
  );

  it("does not disable a confirmed ColorChecker image while extraction is in flight", () => {
    useExtractorStore.setState({
      isLoading: true,
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      calibratedFullFileId: "full-id",
    });

    useExtractorStore.getState().setColorcheckerEnabled(false);

    const state = useExtractorStore.getState();
    expect(state.colorchecker_enabled).toBe(true);
    expect(state.colorchecker_phase).toBe("done");
    expect(state.calibratedFullFileId).toBe("full-id");
    expect(mockedColorcheckerRelease).not.toHaveBeenCalled();
  });

  it("does not replace a confirmed ColorChecker image while extraction is in flight", () => {
    const existingFile = new File(["old"], "old.png", { type: "image/png" });
    const nextFile = new File(["new"], "new.png", { type: "image/png" });
    useExtractorStore.setState({
      imageFile: existingFile,
      imagePreviewUrl: "/api/files/confirmed-preview.jpg",
      isLoading: true,
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      calibratedFullFileId: "full-id",
    });

    useExtractorStore.getState().setImageFile(nextFile);

    const state = useExtractorStore.getState();
    expect(state.imageFile).toBe(existingFile);
    expect(state.imagePreviewUrl).toBe("/api/files/confirmed-preview.jpg");
    expect(state.calibratedFullFileId).toBe("full-id");
    expect(mockedColorcheckerRelease).not.toHaveBeenCalled();
  });

  it("does not rotate a confirmed ColorChecker image while extraction is in flight", async () => {
    const file = new File(["raw"], "calibration.png", { type: "image/png" });
    useExtractorStore.setState({
      imageFile: file,
      imagePreviewUrl: "/api/files/confirmed-preview.jpg",
      isLoading: true,
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      calibratedFullFileId: "full-id",
    });

    await useExtractorStore.getState().rotateImage();

    const state = useExtractorStore.getState();
    expect(mockedRotateExtractorImage).not.toHaveBeenCalled();
    expect(mockedColorcheckerRelease).not.toHaveBeenCalled();
    expect(state.imageFile).toBe(file);
    expect(state.calibratedFullFileId).toBe("full-id");
    expect(state.isLoading).toBe(true);
  });

  it("ignores stale extractor responses after ColorChecker state changes", async () => {
    const file = new File(["test-data"], "calibration.png", {
      type: "image/png",
    });
    let resolveExtract: ((value: ExtractResponse) => void) | null = null;
    mockedExtractColors.mockReturnValueOnce(
      new Promise<ExtractResponse>((resolve) => {
        resolveExtract = resolve;
      }),
    );

    useExtractorStore.setState({
      imageFile: file,
      imageNaturalWidth: 1600,
      imageNaturalHeight: 1200,
      corner_points: [[0, 0], [100, 0], [100, 100], [0, 100]],
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      calibratedFullFileId: "full-id",
    });

    const submit = useExtractorStore.getState().submitExtract();
    await vi.waitFor(() => expect(mockedExtractColors).toHaveBeenCalled());

    useExtractorStore.setState({
      colorchecker_enabled: false,
      colorchecker_phase: null,
      calibratedFullFileId: null,
    });
    resolveExtract?.({
      session_id: "stale-session",
      status: "success",
      message: "ok",
      lut_download_url: "/stale.npy",
      warp_view_url: "/stale_warp.png",
      lut_preview_url: "/stale_preview.png",
      default_palette: [],
    });
    await submit;

    const state = useExtractorStore.getState();
    expect(state.session_id).toBeNull();
    expect(state.lut_download_url).toBeNull();
    expect(state.isLoading).toBe(false);
  });

  it("ignores stale extractor responses after extraction parameters change", async () => {
    const file = new File(["test-data"], "calibration.png", {
      type: "image/png",
    });
    let resolveExtract: ((value: ExtractResponse) => void) | null = null;
    mockedExtractColors.mockReturnValueOnce(
      new Promise<ExtractResponse>((resolve) => {
        resolveExtract = resolve;
      }),
    );

    useExtractorStore.setState({
      imageFile: file,
      imageNaturalWidth: 1600,
      imageNaturalHeight: 1200,
      corner_points: [[0, 0], [100, 0], [100, 100], [0, 100]],
      color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
      page: ExtractorPage.PAGE_1,
      offset_x: 0,
      offset_y: 0,
      zoom: 1,
      distortion: 0,
      vignette_correction: false,
    });

    const submit = useExtractorStore.getState().submitExtract();
    await vi.waitFor(() => expect(mockedExtractColors).toHaveBeenCalled());

    useExtractorStore.getState().setColorMode(ExtractorColorMode.SIX_COLOR);
    resolveExtract?.({
      session_id: "stale-session",
      status: "success",
      message: "ok",
      lut_download_url: "/stale.npy",
      warp_view_url: "/stale_warp.png",
      lut_preview_url: "/stale_preview.png",
      default_palette: [],
    });
    await submit;

    const state = useExtractorStore.getState();
    expect(state.color_mode).toBe(ExtractorColorMode.SIX_COLOR);
    expect(state.session_id).toBeNull();
    expect(state.lut_download_url).toBeNull();
    expect(state.isLoading).toBe(false);
  });

  it("releases stale ColorChecker calibration responses", () => {
    const oldFile = new File(["old"], "old.png", { type: "image/png" });
    const newFile = new File(["new"], "new.png", { type: "image/png" });

    useExtractorStore.setState({
      imageFile: newFile,
      colorchecker_enabled: true,
      colorchecker_phase: "calibrating",
    });

    useExtractorStore.getState().receiveCalibratedFromCC(
      "/api/files/stale-preview.jpg",
      "stale-full-id",
      null,
      {
        fullWidth: 800,
        fullHeight: 600,
        previewWidth: 400,
        previewHeight: 300,
      },
      { imageFile: oldFile },
    );

    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("stale-full-id");
    expect(useExtractorStore.getState().calibratedFullFileId).toBeNull();
    expect(useExtractorStore.getState().colorchecker_phase).toBe("calibrating");
  });

  it("keeps the previous confirmed ColorChecker id when rejecting a replacement", () => {
    const file = new File(["raw"], "calibration.png", { type: "image/png" });
    useExtractorStore.setState({
      imageFile: file,
      imagePreviewUrl: "/api/files/old-calibrated.jpg",
      colorchecker_enabled: true,
      colorchecker_phase: "calibrating",
      calibratedFullFileId: "old-full-id",
    });

    useExtractorStore.getState().receiveCalibratedFromCC(
      "/api/files/new-calibrated.jpg",
      "new-full-id",
      null,
      {
        fullWidth: 800,
        fullHeight: 600,
        previewWidth: 400,
        previewHeight: 300,
      },
      { imageFile: file },
    );

    expect(mockedColorcheckerRelease).not.toHaveBeenCalledWith("old-full-id");
    expect(useExtractorStore.getState().previousCalibratedFullFileId).toBe("old-full-id");

    useExtractorStore.getState().rejectCalibrated();

    const state = useExtractorStore.getState();
    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("new-full-id");
    expect(mockedColorcheckerRelease).not.toHaveBeenCalledWith("old-full-id");
    expect(state.colorchecker_phase).toBe("done");
    expect(state.calibratedFullFileId).toBe("old-full-id");
    expect(state.previousCalibratedFullFileId).toBeNull();
    expect(state.imagePreviewUrl).toBe("/api/files/old-calibrated.jpg");
  });

  it("confirms a replacement ColorChecker id before releasing the previous one", async () => {
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
        calibrated_preview_url: "/api/files/fresh-calibrated.jpg",
        preview_width: 640,
        preview_height: 480,
      });
      useExtractorStore.setState({
        colorchecker_enabled: true,
        colorchecker_phase: "confirming",
        calibratedPreviewUrl: "/api/files/new-calibrated.jpg",
        calibratedFullFileId: "new-full-id",
        previousCalibratedFullFileId: "old-full-id",
      });

      useExtractorStore.getState().confirmCalibrated();
      await vi.waitFor(() =>
        expect(mockedColorcheckerConfirm).toHaveBeenCalledWith(
          "new-full-id",
          "/api/files/new-calibrated.jpg",
        ),
      );
      expect(mockedColorcheckerRelease).not.toHaveBeenCalledWith("old-full-id");
      expect(createdImage?.src).toBe("/api/files/fresh-calibrated.jpg");
      createdImage?.onload?.();

      const state = useExtractorStore.getState();
      expect(mockedColorcheckerRelease).toHaveBeenCalledWith("old-full-id");
      expect(state.colorchecker_phase).toBe("done");
      expect(state.calibratedFullFileId).toBe("new-full-id");
      expect(state.previousCalibratedFullFileId).toBeNull();
      expect(state.imagePreviewUrl).toBe("/api/files/fresh-calibrated.jpg");
      expect(state.imageNaturalWidth).toBe(640);
      expect(state.imageNaturalHeight).toBe(480);
    } finally {
      globalThis.Image = OriginalImage;
    }
  });

  it("does not accept or release the previous ColorChecker id when preview loading fails", async () => {
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
      useExtractorStore.setState({
        colorchecker_enabled: true,
        colorchecker_phase: "confirming",
        imagePreviewUrl: "/api/files/old-calibrated.jpg",
        calibratedPreviewUrl: "/api/files/new-calibrated.jpg",
        calibratedFullFileId: "new-full-id",
        previousCalibratedFullFileId: "old-full-id",
      });

      useExtractorStore.getState().confirmCalibrated();
      await vi.waitFor(() =>
        expect(mockedColorcheckerConfirm).toHaveBeenCalledWith(
          "new-full-id",
          "/api/files/new-calibrated.jpg",
        ),
      );
      createdImage?.onerror?.();

      const state = useExtractorStore.getState();
      expect(mockedColorcheckerRelease).not.toHaveBeenCalledWith("old-full-id");
      expect(state.colorchecker_phase).toBe("confirming");
      expect(state.calibratedFullFileId).toBe("new-full-id");
      expect(state.previousCalibratedFullFileId).toBe("old-full-id");
      expect(state.imagePreviewUrl).toBe("/api/files/old-calibrated.jpg");
      expect(state.error).toBeTruthy();
    } finally {
      globalThis.Image = OriginalImage;
    }
  });

  it("keeps the previous ColorChecker id when rejecting after confirm but before preview load", async () => {
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
      useExtractorStore.setState({
        colorchecker_enabled: true,
        colorchecker_phase: "confirming",
        calibratedPreviewUrl: "/api/files/new-calibrated.jpg",
        calibratedFullFileId: "new-full-id",
        previousCalibratedFullFileId: "old-full-id",
      });

      useExtractorStore.getState().confirmCalibrated();
      await vi.waitFor(() =>
        expect(mockedColorcheckerConfirm).toHaveBeenCalledWith(
          "new-full-id",
          "/api/files/new-calibrated.jpg",
        ),
      );
      useExtractorStore.getState().rejectCalibrated();
      createdImage?.onload?.();

      const state = useExtractorStore.getState();
      expect(mockedColorcheckerRelease).toHaveBeenCalledWith("new-full-id");
      expect(mockedColorcheckerRelease).not.toHaveBeenCalledWith("old-full-id");
      expect(state.colorchecker_phase).toBe("done");
      expect(state.calibratedFullFileId).toBe("old-full-id");
      expect(state.previousCalibratedFullFileId).toBeNull();
    } finally {
      globalThis.Image = OriginalImage;
    }
  });

  it("clears released ColorChecker id when image rotation fails", async () => {
    mockedRotateExtractorImage.mockRejectedValueOnce(new Error("rotate failed"));

    useExtractorStore.setState({
      imageFile: new File(["raw"], "calibration.png", { type: "image/png" }),
      imagePreviewUrl: "/api/files/calibrated-preview.jpg",
      originalPreviewUrl: "/api/files/original-preview.jpg",
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      calibratedPreviewUrl: "/api/files/calibrated-preview.jpg",
      calibratedFullFileId: "released-full-id",
    });

    await useExtractorStore.getState().rotateImage();

    const state = useExtractorStore.getState();
    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("released-full-id");
    expect(state.calibratedFullFileId).toBeNull();
    expect(state.colorchecker_phase).toBeNull();
    expect(state.colorchecker_enabled).toBe(false);
    expect(state.imagePreviewUrl).toBe("/api/files/original-preview.jpg");
  });

  it("keeps original image dimensions when disabling ColorChecker to an existing preview", () => {
    const file = new File(["image"], "calibration.png", { type: "image/png" });
    useExtractorStore.setState({
      imageFile: file,
      imagePreviewUrl: "/api/files/calibrated-preview.jpg",
      imageNaturalWidth: 1600,
      imageNaturalHeight: 1200,
      originalPreviewUrl: "/api/files/original-preview.jpg",
      originalPreviewWidth: 2400,
      originalPreviewHeight: 1800,
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      calibratedPreviewUrl: "/api/files/calibrated-preview.jpg",
      calibratedFullFileId: "released-full-id",
      corner_points: [[0, 0], [1, 0], [1, 1], [0, 1]],
      active_corner_index: 2,
    });

    useExtractorStore.getState().setColorcheckerEnabled(false);

    const state = useExtractorStore.getState();
    expect(mockedColorcheckerRelease).toHaveBeenCalledWith("released-full-id");
    expect(state.imagePreviewUrl).toBe("/api/files/original-preview.jpg");
    expect(state.imageNaturalWidth).toBe(2400);
    expect(state.imageNaturalHeight).toBe(1800);
    expect(state.corner_points).toEqual([]);
    expect(state.active_corner_index).toBeNull();
  });

  it("releases calibration responses that arrive during image rotation", async () => {
    const file = new File(["raw"], "calibration.png", { type: "image/png" });
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
      .mockResolvedValue({ blob: () => Promise.resolve(new Blob(["rotated"])) }) as unknown as typeof fetch;

    useExtractorStore.setState({
      imageFile: file,
      imagePreviewUrl: "/api/files/original-preview.jpg",
      colorchecker_enabled: true,
      colorchecker_phase: "calibrating",
    });

    const rotation = useExtractorStore.getState().rotateImage();
    expect(useExtractorStore.getState().colorchecker_phase).toBeNull();

    useExtractorStore.getState().receiveCalibratedFromCC(
      "/api/files/stale-preview.jpg",
      "stale-full-id",
      null,
      {
        fullWidth: 800,
        fullHeight: 600,
        previewWidth: 400,
        previewHeight: 300,
      },
      { imageFile: file },
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
});

describe("Feature: extractor-calibration-tab, Property 11: confirm-palette 请求载荷与 Store 状态一致性", () => {
  it("For any valid metadata and palette, submitConfirmPalette sends confirmPalette payload matching the store state", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ maxLength: 20 }),
        fc.string({ maxLength: 20 }),
        fc.array(arbPaletteEntry, { minLength: 1, maxLength: 4 }),
        async (manufacturer, type, palette) => {
          resetExtractorStore();
          vi.clearAllMocks();

          useExtractorStore.setState({
            session_id: "session-1",
            manufacturer,
            type,
            defaultPalette: palette,
          });

          mockedConfirmPalette.mockResolvedValueOnce({
            status: "ok",
            message: "confirmed",
          });

          await useExtractorStore.getState().submitConfirmPalette();

          expect(mockedConfirmPalette).toHaveBeenCalledTimes(1);
          expect(mockedConfirmPalette).toHaveBeenCalledWith({
            session_id: "session-1",
            manufacturer: manufacturer.trim(),
            type: type.trim(),
            palette: palette.map((entry) => ({
              ...entry,
              color_name: entry.color_name?.trim() || null,
            })),
          });

          const state = useExtractorStore.getState();
          expect(state.paletteConfirmed).toBe(true);
          expect(state.paletteConfirmLoading).toBe(false);
          expect(state.paletteConfirmError).toBeNull();
        },
      ),
      { numRuns: 50 },
    );
  });
});

// **Feature: extractor-calibration-tab, Property 8: API 响应字段正确存储**
// **Validates: Requirements 6.5**
describe("Feature: extractor-calibration-tab, Property 8: API 响应字段正确存储", () => {
  it("For any valid ExtractResponse, submitExtract stores session_id, lut_download_url, warp_view_url, lut_preview_url correctly", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbExtractResponse,
        async (response: ExtractResponse) => {
          resetExtractorStore();
          vi.clearAllMocks();

          // Set up valid preconditions for submitExtract
          const file = new File(["test-data"], "calibration.png", {
            type: "image/png",
          });
          useExtractorStore.setState({
            imageFile: file,
            corner_points: [
              [0, 0],
              [100, 0],
              [100, 100],
              [0, 100],
            ],
          });

          // Mock extractColors to return the random response
          mockedExtractColors.mockResolvedValueOnce(response);

          // Call submitExtract
          await useExtractorStore.getState().submitExtract();

          // Verify store fields match the response (relative URL contract)
          const state = useExtractorStore.getState();
          expect(state.session_id).toBe(response.session_id);
          expect(state.lut_download_url).toBe(
            response.lut_download_url ?? null,
          );
          expect(state.warp_view_url).toBe(response.warp_view_url ?? null);
          expect(state.lut_preview_url).toBe(response.lut_preview_url ?? null);
          expect(state.isLoading).toBe(false);
          expect(state.error).toBeNull();
        },
      ),
      { numRuns: 100 },
    );
  });
});
