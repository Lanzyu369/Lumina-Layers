import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

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
    expect(screen.getByDisplayValue("white")).not.toBeVisible();
    expect(screen.getByDisplayValue("White")).not.toBeVisible();
    // Default material is rendered as a dropdown, not a free-text input, so
    // there is no `<input value="PLA Basic">`. Assert instead that the
    // dropdown exists and displays the selected preset label.
    // 默认耗材以下拉框形式呈现，不是自由文本输入，因此没有
    // `<input value="PLA Basic">`。改为断言下拉框存在且当前显示所选预设。
    expect(screen.queryByDisplayValue("PLA Basic")).not.toBeInTheDocument();
    const materialCombobox = screen.queryByRole("combobox", {
      name: /default material|默认材料/i,
    });
    expect(materialCombobox).not.toBeInTheDocument();
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

    const materialCombobox = screen.queryByRole("combobox", {
      name: /default material|默认材料/i,
    });
    expect(materialCombobox).not.toBeInTheDocument();
    expect(useCalibrationStore.getState().materialDefault).toBe("PLA Basic");
    expect(MATERIAL_PRESETS.map((p) => p.value)).toContain("PLA Basic");
  });

  it("renders the gradient card notice and MakerWorld links", () => {
    render(<GradientCardGeneratePanel />);

    expect(
      screen.getByText(/需要打印两张|requires printing two/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/MakerWorld/i),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: /梯度卡在线模型|gradient card online model/i }),
    ).toHaveAttribute(
      "href",
      "https://makerworld.com.cn/zh/models/2394753-lumina2-0-ti-xing-xiao-se-se-qia-0-08ceng-gao-15ce#profileId-2721317",
    );
    expect(
      screen.getByRole("link", { name: /梯度卡收纳盒在线模型|Gradient Card Parametric Storage Box/i }),
    ).toHaveAttribute(
      "href",
      "https://makerworld.com.cn/zh/models/2400920-can-shu-hua-lumina-2-0ti-du-se-qia-zi-ding-yi-shou#profileId-2729620",
    );
  });

  it("selecting a dropdown option updates the store with the chosen preset", () => {
    useCalibrationStore.getState().setMaterialDefault("PLA Silk");

    expect(useCalibrationStore.getState().materialDefault).toBe("PLA Silk");
  });

  it("renders only the kit download while hiding manifest and preview output", () => {
    useCalibrationStore.setState({
      lastSubmittedWorkflow: "single-stage",
      downloadUrl: "/api/files/kit.zip",
      manifestUrl: "/api/files/manifest.json",
      previewImageUrl: "/api/files/preview.png",
      singleStageJobs: [],
    });

    render(<GradientCardGeneratePanel />);

    expect(screen.getByTestId("download-link")).toHaveAttribute(
      "href",
      "/api/files/kit.zip",
    );
    expect(screen.queryByTestId("manifest-link")).not.toBeInTheDocument();
    expect(screen.queryByTestId("preview-image")).not.toBeInTheDocument();
  });
});
