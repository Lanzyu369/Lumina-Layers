import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  calibrationGenerate,
  generateSingleStageKit,
} from "../api/calibration";
import { CalibrationColorMode } from "../api/types";
import {
  BACKING_THICKNESS_DEFAULT_MM,
  useCalibrationStore,
} from "../stores/calibrationStore";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
  generateSingleStageKit: vi.fn(),
}));

const mockCalibrationGenerate = vi.mocked(calibrationGenerate);
const mockGenerateSingleStageKit = vi.mocked(generateSingleStageKit);
const RAW_HTTP_STATUS_PATTERN =
  /Request failed with status code|status code\s+\d{3}/i;

function resetCalibrationState(): void {
  useSettingsStore.setState({
    ...DEFAULT_SETTINGS,
    printerModel: "bambu-p1s",
    slicerSoftware: "OrcaSlicer",
    nozzleSize: "0.2",
    deviceProfileId: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
  });
  useCalibrationStore.setState({
    workflow: "legacy",
    lastSubmittedWorkflow: null,
    color_mode: CalibrationColorMode.FOUR_COLOR_RYBW,
    block_size: 5,
    gap: 0.84,
    backing_thickness: BACKING_THICKNESS_DEFAULT_MM,
    eight_color_full_export: false,
    substrateId: "white",
    substrateDisplayName: "White",
    materialDefault: "PLA Basic",
    singleStageLayerHeightMm: 0.08,
    isLoading: false,
    error: null,
    downloadUrl: null,
    threemfDiskPath: null,
    previewImageUrl: null,
    layerImageUrls: null,
    modelUrl: null,
    statusMessage: null,
    manifestUrl: null,
    singleStageJobs: [],
  });
}

describe("calibration visible error language", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetCalibrationState();
  });

  it("normalizes raw HTTP status text from legacy calibration generation", async () => {
    mockCalibrationGenerate.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useCalibrationStore.getState().submitLegacyGenerate();

    const error = useCalibrationStore.getState().error;
    expect(error).toBeTruthy();
    expect(error).not.toMatch(RAW_HTTP_STATUS_PATTERN);
    expect(error).toBe("服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。");
    expect(useCalibrationStore.getState().isLoading).toBe(false);
  });

  it("normalizes raw HTTP status text from single-stage kit generation", async () => {
    useCalibrationStore.setState({ workflow: "single-stage" });
    mockGenerateSingleStageKit.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useCalibrationStore.getState().submitSingleStageGenerate();

    const error = useCalibrationStore.getState().error;
    expect(error).toBeTruthy();
    expect(error).not.toMatch(RAW_HTTP_STATUS_PATTERN);
    expect(error).toBe("服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。");
    expect(useCalibrationStore.getState().isLoading).toBe(false);
  });

  it("uses a localized fallback for non-Error calibration failures", async () => {
    mockCalibrationGenerate.mockRejectedValueOnce("unknown");

    await useCalibrationStore.getState().submitLegacyGenerate();

    expect(useCalibrationStore.getState().error).toBe("校准板生成失败，请稍后重试。");
  });
});
