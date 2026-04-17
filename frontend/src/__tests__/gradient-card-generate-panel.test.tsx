import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import GradientCardGeneratePanel from "../components/GradientCardGeneratePanel";
import { useCalibrationStore } from "../stores/calibrationStore";

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
  generateSingleStageKit: vi.fn(),
}));

beforeEach(() => {
  useCalibrationStore.setState({
    workflow: "legacy",
    lastSubmittedWorkflow: null,
    substrateId: "white",
    substrateDisplayName: "White",
    materialDefault: "PLA Basic",
    singleStageLayerHeightMm: 0.04,
    isLoading: false,
    error: null,
    downloadUrl: null,
    previewImageUrl: null,
    modelUrl: null,
    statusMessage: null,
    manifestUrl: null,
    singleStageJobs: [],
  });
});

describe("GradientCardGeneratePanel", () => {
  it("renders gradient-card generation fields and hides LUT color mode", () => {
    render(<GradientCardGeneratePanel />);

    expect(screen.getByTestId("gradient-card-generate-panel")).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: /layer height|层高/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: /color mode|颜色模式/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("white")).toBeInTheDocument();
    expect(screen.getByDisplayValue("White")).toBeInTheDocument();
    expect(screen.getByDisplayValue("PLA Basic")).toBeInTheDocument();
  });

  it("renders kit and manifest links when generation output exists", () => {
    useCalibrationStore.setState({
      lastSubmittedWorkflow: "single-stage",
      downloadUrl: "/api/files/kit.zip",
      manifestUrl: "/api/files/manifest.json",
      singleStageJobs: [],
    });

    render(<GradientCardGeneratePanel />);

    expect(screen.getByTestId("download-link")).toHaveAttribute(
      "href",
      "/api/files/kit.zip",
    );
    expect(screen.getByTestId("manifest-link")).toHaveAttribute(
      "href",
      "/api/files/manifest.json",
    );
  });
});
