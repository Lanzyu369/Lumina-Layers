import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import CalibrationPanel from "../components/CalibrationPanel";
import { CalibrationColorMode } from "../api/types";
import { useCalibrationStore } from "../stores/calibrationStore";

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
  generateSingleStageKit: vi.fn(),
}));

vi.mock("../components/sections/SlicerSelector", () => ({
  default: ({
    threemfDiskPath,
    downloadUrl,
    canSubmit,
    largeFormat,
  }: {
    threemfDiskPath: string | null;
    downloadUrl: string | null;
    canSubmit: boolean;
    largeFormat?: boolean;
  }) => (
    <div
      data-testid="calibration-slicer-selector"
      data-threemf-path={threemfDiskPath ?? ""}
      data-download-url={downloadUrl ?? ""}
      data-can-submit={canSubmit ? "true" : "false"}
      data-large-format={largeFormat ? "true" : "false"}
    />
  ),
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
    threemfDiskPath: null,
    previewImageUrl: null,
    modelUrl: null,
    statusMessage: null,
    warnings: [],
    manifestUrl: null,
    singleStageJobs: [],
  });
});

describe("CalibrationPanel", () => {
  it("keeps a precise backing-thickness editor and unit below the external heading", () => {
    render(<CalibrationPanel />);
    const slider = screen.getByTestId("backing-thickness-slider");
    const control = slider.parentElement!.parentElement!;
    const input = within(control).getByRole("textbox");
    expect(input).toHaveValue("1.20");
    expect(within(control).getByText("mm")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "1.48" } });
    fireEvent.blur(input);
    expect(useCalibrationStore.getState().backing_thickness).toBe(1.48);
  });

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

  it("passes loading state to the slicer selector action", () => {
    useCalibrationStore.setState({ isLoading: true });
    render(<CalibrationPanel />);

    expect(screen.getByTestId("calibration-slicer-selector")).toHaveAttribute(
      "data-can-submit",
      "false",
    );
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

  it("passes a generated 3MF disk path to the slicer selector", () => {
    useCalibrationStore.setState({
      downloadUrl: "/api/files/test.3mf",
      threemfDiskPath: "/tmp/test.3mf",
    });
    render(<CalibrationPanel />);

    const selector = screen.getByTestId("calibration-slicer-selector");
    expect(selector).toHaveAttribute("data-threemf-path", "/tmp/test.3mf");
    expect(selector).toHaveAttribute("data-download-url", "/api/files/test.3mf");
    expect(selector).toHaveAttribute("data-large-format", "false");
    expect(screen.queryByTestId("download-link")).not.toBeInTheDocument();
  });

  it("keeps an explicit download link for ZIP calibration packages", () => {
    useCalibrationStore.setState({
      color_mode: CalibrationColorMode.FIVE_COLOR_EXT,
      downloadUrl: "/api/files/test.zip",
    });
    render(<CalibrationPanel />);

    const link = screen.getByTestId("download-link");
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/api/files/test.zip");
    expect(link).toHaveAttribute("download");
    expect(screen.getByTestId("calibration-slicer-selector")).toHaveAttribute(
      "data-large-format",
      "true",
    );
  });

  it("shows the manual layout warning with a generated ZIP download", () => {
    useCalibrationStore.setState({
      color_mode: CalibrationColorMode.FIVE_COLOR_EXT,
      downloadUrl: "/api/files/test.zip",
      statusMessage: "5-Color Extended Kit (Page 1 & 2) Generated!",
      warnings: ["wipe_tower_manual_adjustment_required"],
    });
    render(<CalibrationPanel />);

    const warning = screen.getByTestId("calibration-placement-warning");
    expect(warning).toHaveAttribute("data-tone", "warning");
    expect(warning).toHaveTextContent(
      /Check the layout before printing|打印前请手动检查摆放/,
    );
    expect(warning).toHaveTextContent(
      /Check each project in a ZIP separately|ZIP 中的每个工程都需要分别检查/,
    );
    expect(screen.getByTestId("download-link")).toHaveAttribute(
      "href",
      "/api/files/test.zip",
    );
  });

  it("keeps the warning next to a retained ZIP after a failed retry", () => {
    useCalibrationStore.setState({
      color_mode: CalibrationColorMode.FIVE_COLOR_EXT,
      downloadUrl: "/api/files/test.zip",
      warnings: ["wipe_tower_manual_adjustment_required"],
      error: "Calibration board could not be generated.",
    });
    render(<CalibrationPanel />);

    expect(screen.getByTestId("error-message")).toBeInTheDocument();
    expect(
      screen.getByTestId("calibration-placement-warning"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("download-link")).toHaveAttribute(
      "href",
      "/api/files/test.zip",
    );
  });

  it("does not show a placement warning when the result has none", () => {
    useCalibrationStore.setState({
      color_mode: CalibrationColorMode.FIVE_COLOR_EXT,
      downloadUrl: "/api/files/test.zip",
      warnings: [],
    });
    render(<CalibrationPanel />);

    expect(
      screen.queryByTestId("calibration-placement-warning"),
    ).not.toBeInTheDocument();
  });

  it("shows preview image when previewImageUrl is set", () => {
    useCalibrationStore.setState({ previewImageUrl: "/api/files/preview.png" });
    render(<CalibrationPanel />);

    const img = screen.getByTestId("preview-image");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "/api/files/preview.png");
  });
});
