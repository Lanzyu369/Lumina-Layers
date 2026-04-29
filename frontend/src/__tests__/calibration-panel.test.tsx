import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import CalibrationPanel from "../components/CalibrationPanel";
import { CalibrationColorMode } from "../api/types";
import { useCalibrationStore } from "../stores/calibrationStore";

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
  generateSingleStageKit: vi.fn(),
}));

beforeEach(() => {
  useCalibrationStore.setState({
    workflow: "legacy",
    lastSubmittedWorkflow: "legacy",
    color_mode: CalibrationColorMode.FOUR_COLOR_RYBW,
    block_size: 5,
    gap: 0.84,
    backing_thickness: 1.2,
    eight_color_full_export: false,
    substrateId: "white",
    substrateDisplayName: "White",
    materialDefault: "PLA Basic",
    singleStageLayerHeightMm: 0.08,
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
  it("renders legacy LUT controls and no gradient-card workflow selector", () => {
    render(<CalibrationPanel />);

    expect(screen.getByTestId("calibration-panel")).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: /color mode|颜色模式/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: /layer height|层高/i }),
    ).not.toBeInTheDocument();
  });

  it("hides the exhaustive export switch outside 8-Color Max mode", () => {
    render(<CalibrationPanel />);

    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("reflects the exhaustive export switch state in 8-Color Max mode", () => {
    useCalibrationStore.setState({
      color_mode: CalibrationColorMode.EIGHT_COLOR,
      eight_color_full_export: true,
    });
    render(<CalibrationPanel />);

    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("导出全部 8 色配方")).toBeInTheDocument();
  });

  it("enables all controls in 6-Color mode", () => {
    useCalibrationStore.setState({ color_mode: CalibrationColorMode.SIX_COLOR });
    render(<CalibrationPanel />);

    const sliders = screen.getAllByRole("slider");
    const selects = screen.getAllByRole("combobox");

    expect(sliders).toHaveLength(3);
    sliders.forEach((slider) => expect(slider).not.toBeDisabled());
    expect(selects).toHaveLength(1);
    expect(selects[0]).not.toBeDisabled();
  });

  it("enables all controls in BW mode", () => {
    useCalibrationStore.setState({ color_mode: CalibrationColorMode.BW });
    render(<CalibrationPanel />);

    const sliders = screen.getAllByRole("slider");
    const selects = screen.getAllByRole("combobox");

    expect(sliders).toHaveLength(3);
    sliders.forEach((slider) => expect(slider).not.toBeDisabled());
    expect(selects).toHaveLength(1);
    expect(selects[0]).not.toBeDisabled();
  });

  it("enables all controls in 4-Color mode", () => {
    render(<CalibrationPanel />);

    const sliders = screen.getAllByRole("slider");
    const selects = screen.getAllByRole("combobox");

    expect(sliders).toHaveLength(3);
    sliders.forEach((slider) => expect(slider).not.toBeDisabled());
    expect(selects).toHaveLength(1);
    expect(selects[0]).not.toBeDisabled();
  });

  it("reflects backing thickness slider value from the store", () => {
    useCalibrationStore.setState({ backing_thickness: 2.4 });
    render(<CalibrationPanel />);

    const slider = screen.getByTestId("backing-thickness-slider");
    expect(slider).toHaveValue("2.4");
  });

  it("disables generate button when isLoading is true", () => {
    useCalibrationStore.setState({ isLoading: true });
    render(<CalibrationPanel />);

    expect(screen.getByRole("button", { name: "生成校准板" })).toBeDisabled();
  });

  it("shows error message when error is set", () => {
    useCalibrationStore.setState({ error: "网络连接失败" });
    render(<CalibrationPanel />);

    const errorEl = screen.getByTestId("error-message");
    expect(errorEl).toBeInTheDocument();
    expect(errorEl).toHaveTextContent("网络连接失败");
  });

  it("shows status message when statusMessage is set", () => {
    useCalibrationStore.setState({ statusMessage: "校准板生成成功" });
    render(<CalibrationPanel />);

    const statusEl = screen.getByTestId("status-message");
    expect(statusEl).toBeInTheDocument();
    expect(statusEl).toHaveTextContent("校准板生成成功");
  });

  it("shows download link when downloadUrl is set", () => {
    useCalibrationStore.setState({ downloadUrl: "/api/files/test.3mf" });
    render(<CalibrationPanel />);

    const link = screen.getByTestId("download-link");
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/api/files/test.3mf");
    expect(link).toHaveAttribute("download");
  });

  it("shows preview image when previewImageUrl is set", () => {
    useCalibrationStore.setState({ previewImageUrl: "/api/files/preview.png" });
    render(<CalibrationPanel />);

    const img = screen.getByTestId("preview-image");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "/api/files/preview.png");
  });
});
