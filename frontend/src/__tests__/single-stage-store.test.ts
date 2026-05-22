import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSingleStageStore } from "../stores/singleStageStore";

vi.mock("../api/extractor", () => ({
  extractGradientCardStageA: vi.fn(),
  rotateExtractorImage: vi.fn(),
  saveGradientCardMaterial: vi.fn(),
}));

vi.mock("../api/system", () => ({
  uploadImagePreview: vi.fn(),
}));

const buildPngFile = (name: string) =>
  new File([new Uint8Array([1, 2, 3])], name, { type: "image/png" });

describe("useSingleStageStore ColorChecker flow", () => {
  beforeEach(() => {
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
      calibratedImageFile: null,
      calibratedPreviewUrl: null,
      originalWhitePreviewUrl: null,
      colorcheckerSummary: null,
      imageSource: "raw",
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:gradient-card-source");
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
    expect(state.originalWhitePreviewUrl).toBe("blob:gradient-card-source");
  });

  it("marks confirmed ColorChecker images as restored source", () => {
    const calibratedFile = buildPngFile("calibrated.png");

    useSingleStageStore.setState({
      colorchecker_phase: "confirming",
      colorchecker_target: "white",
      calibratedImageFile: calibratedFile,
      calibratedPreviewUrl: "blob:calibrated",
      imageSource: "raw",
    });

    useSingleStageStore.getState().confirmCalibrated();

    const state = useSingleStageStore.getState();
    expect(state.imageSource).toBe("restored");
  });
});
