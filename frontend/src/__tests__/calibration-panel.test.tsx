import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import CalibrationPanel from "../components/CalibrationPanel";
import { CalibrationColorMode, BackingColor } from "../api/types";
import { useCalibrationStore } from "../stores/calibrationStore";

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
  generateSingleStageKit: vi.fn(),
}));

beforeEach(() => {
  useCalibrationStore.setState({
    workflow: "legacy",
    color_mode: CalibrationColorMode.FOUR_COLOR_RYBW,
    block_size: 5,
    gap: 0.82,
    backing: BackingColor.WHITE,
    substrateId: "white",
    substrateDisplayName: "White",
    materialDefault: "PLA Basic",
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

describe("CalibrationPanel", () => {
  it("renders workflow selector and legacy controls by default", () => {
    render(<CalibrationPanel />);

    expect(screen.getByTestId("calibration-panel")).toBeInTheDocument();
    expect(screen.getAllByRole("combobox").length).toBeGreaterThanOrEqual(2);
  });

  it("renders single-stage fields when workflow is single-stage", () => {
    useCalibrationStore.setState({ workflow: "single-stage" });
    render(<CalibrationPanel />);

    expect(screen.getByTestId("single-stage-config")).toBeInTheDocument();
    expect(screen.getByDisplayValue("white")).toBeInTheDocument();
    expect(screen.getByDisplayValue("White")).toBeInTheDocument();
    expect(screen.getByDisplayValue("PLA Basic")).toBeInTheDocument();
  });

  it("shows manifest link when single-stage output exists", () => {
    useCalibrationStore.setState({
      workflow: "single-stage",
      downloadUrl: "/api/files/kit.zip",
      manifestUrl: "/api/files/manifest.json",
      singleStageJobs: [
        {
          color: "White",
          color_name: "White",
          material: "PLA Basic",
          substrate_id: "white",
          substrate_display_name: "White",
          filename: "single_stage_white_white.3mf",
        },
      ],
    });
    render(<CalibrationPanel />);

    expect(screen.getByTestId("download-link")).toHaveAttribute(
      "href",
      "/api/files/kit.zip",
    );
    expect(screen.getByTestId("manifest-link")).toHaveAttribute(
      "href",
      "/api/files/manifest.json",
    );
    expect(screen.getByTestId("single-stage-jobs")).toBeInTheDocument();
  });

  it("shows preview image when previewImageUrl is set", () => {
    useCalibrationStore.setState({ previewImageUrl: "/api/files/preview.png" });
    render(<CalibrationPanel />);

    const img = screen.getByTestId("preview-image");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "/api/files/preview.png");
  });
});
