import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import GradientCardGeneratePanel from "../components/GradientCardGeneratePanel";
import { useCalibrationStore } from "../stores/calibrationStore";
import { MATERIAL_PRESETS } from "../constants/materialPresets";

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
    // Default material is rendered as a dropdown, not a free-text input, so
    // there is no `<input value="PLA Basic">`. Assert instead that the
    // dropdown exists and displays the selected preset label.
    // 默认耗材以下拉框形式呈现，不是自由文本输入，因此没有
    // `<input value="PLA Basic">`。改为断言下拉框存在且当前显示所选预设。
    expect(screen.queryByDisplayValue("PLA Basic")).not.toBeInTheDocument();
    const materialCombobox = screen.getByRole("combobox", {
      name: /default material|默认材料/i,
    });
    expect(materialCombobox).toHaveTextContent("PLA Basic");
  });

  it("renders default material as a curated dropdown rather than a free-text input", () => {
    // Regression: the default material used to be a free-text input, which
    // let users type non-standard values (typos, internal codes) that then
    // flowed into the kit manifest and downstream 3MF metadata. It must be
    // a constrained dropdown backed by `MATERIAL_PRESETS`.
    // 回归测试：默认耗材此前是自由文本输入，用户可以输入拼写错误或内部编号
    // 等非标准值并流入 manifest 与 3MF 元数据。必须改为由 `MATERIAL_PRESETS`
    // 限定的下拉框。
    render(<GradientCardGeneratePanel />);

    const materialCombobox = screen.getByRole("combobox", {
      name: /default material|默认材料/i,
    });
    expect(materialCombobox.tagName).toBe("BUTTON");
    expect(materialCombobox).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(materialCombobox);

    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");
    const optionValues = options.map((el) => el.textContent?.trim() ?? "");

    expect(optionValues).toEqual(MATERIAL_PRESETS.map((p) => p.value));
    expect(optionValues).toContain("PLA Basic");
    expect(optionValues).toContain("PETG HF");
    expect(optionValues.length).toBeGreaterThanOrEqual(10);
  });

  it("selecting a dropdown option updates the store with the chosen preset", () => {
    render(<GradientCardGeneratePanel />);

    const materialCombobox = screen.getByRole("combobox", {
      name: /default material|默认材料/i,
    });
    fireEvent.click(materialCombobox);

    const listbox = screen.getByRole("listbox");
    const target = within(listbox).getByRole("option", { name: "PLA Silk" });
    fireEvent.click(target);

    expect(useCalibrationStore.getState().materialDefault).toBe("PLA Silk");
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
