import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import App from "../App";
import { useWidgetStore } from "../stores/widgetStore";
import { useSingleStageStore } from "../stores/singleStageStore";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
  },
}));

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn().mockResolvedValue({ luts: [] }),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  getFileUrl: vi.fn(),
}));

// Mock Scene3D to avoid Three.js rendering in jsdom
vi.mock("../components/Scene3D", () => ({
  default: () => <div data-testid="scene3d-mock">scene</div>,
}));

import apiClient from "../api/client";

describe("Widget Workspace Layout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });
    useWidgetStore.getState().resetLayout();
  });

  it('preserves "Lumina Studio 2.0" header', () => {
    render(<App />);
    expect(screen.getByText("Lumina Studio 2.0")).toBeInTheDocument();
  });

  it("renders widget workspace with Scene3D", () => {
    render(<App />);
    expect(screen.getByTestId("scene3d-mock")).toBeInTheDocument();
  });

  it("renders panel controls toggle button in header", () => {
    render(<App />);
    // Widget toggles are now inside a dropdown menu
    expect(screen.getByTestId("panel-controls-toggle")).toBeInTheDocument();
  });

  it("renders grouped top-level tabs in TabNavBar", () => {
    render(<App />);
    expect(screen.getByTestId("tab-converter")).toBeInTheDocument();
    expect(screen.getByTestId("tab-lut-management")).toBeInTheDocument();
    expect(screen.getByTestId("tab-material-management")).toBeInTheDocument();
    expect(screen.getByTestId("tab-vectorizer")).toBeInTheDocument();
    expect(screen.getByTestId("tab-settings")).toBeInTheDocument();

    expect(screen.queryByTestId("tab-calibration")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-extractor")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-lut-manager")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-five-color")).not.toBeInTheDocument();
  });

  it("shows LUT sub-tabs and switches to original target tabs", () => {
    render(<App />);

    fireEvent.click(screen.getByTestId("tab-lut-management"));
    expect(screen.getByRole("tab", { name: "Calibration Board" })).toBeInTheDocument();
    expect(screen.getByTestId("subtab-extractor")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-lut-manager")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-lut-details")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-lut-compare")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-five-color")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("subtab-extractor"));
    expect(useWidgetStore.getState().activeTab).toBe("extractor");

    fireEvent.click(screen.getByTestId("subtab-lut-manager"));
    expect(useWidgetStore.getState().activeTab).toBe("lut-manager");

    fireEvent.click(screen.getByTestId("subtab-lut-details"));
    expect(useWidgetStore.getState().activeTab).toBe("lut-details");

    fireEvent.click(screen.getByTestId("subtab-lut-compare"));
    expect(useWidgetStore.getState().activeTab).toBe("lut-compare");

    fireEvent.click(screen.getByTestId("subtab-five-color"));
    expect(useWidgetStore.getState().activeTab).toBe("five-color");
  });

  it("shows Material Management sub-tabs and switches to gradient-card pages", () => {
    render(<App />);

    fireEvent.click(screen.getByTestId("tab-material-management"));
    expect(screen.getByTestId("subtab-gradient-card-generate")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-gradient-card-extract")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("subtab-gradient-card-extract"));
    expect(useWidgetStore.getState().activeTab).toBe("gradient-card-extract");

    fireEvent.click(screen.getByTestId("subtab-gradient-card-generate"));
    expect(useWidgetStore.getState().activeTab).toBe("gradient-card-generate");
  });

  it("clears material-verification state when the user clicks the gradient-card-extract sub-tab", () => {
    // Repro: user clicks "再次校验" in the Material Library (which sets
    // verification state and switches tabs via the store), then navigates
    // away and clicks the "提取耗材" sub-tab expecting a fresh extraction.
    // The verification state must be dropped on this explicit nav click,
    // otherwise the panel keeps rendering 覆盖/合并 buttons in extract mode.
    // 复现：用户在耗材库点「再次校验」后切换 tab，再点「提取耗材」子页期望
    // 全新提取，必须清掉验证状态，否则面板还会显示覆盖/合并按钮。
    useSingleStageStore.setState({
      verificationTargetDirectoryName: "pla-basic",
      verificationTargetCount: 3,
      materialName: "PLA Basic",
    });

    render(<App />);

    fireEvent.click(screen.getByTestId("tab-material-management"));
    fireEvent.click(screen.getByTestId("subtab-gradient-card-extract"));

    expect(useWidgetStore.getState().activeTab).toBe("gradient-card-extract");
    const state = useSingleStageStore.getState();
    expect(state.verificationTargetDirectoryName).toBeNull();
    expect(state.verificationTargetCount).toBe(0);
  });

  it("preserves material-verification state when entering via store.setActiveTab (re-verify path)", () => {
    // Reverse-direction guard: the Material Library re-verify entry calls
    // setActiveTab directly via the store, NOT through the TabNavBar's
    // onTabChange handler. The verification state seeded by
    // startMaterialVerification must survive that programmatic switch.
    // 反向哨兵：「再次校验」走 store.setActiveTab 而非 TabNavBar 的 onTabChange，
    // 不能被错误清除。
    render(<App />);

    useSingleStageStore.setState({
      verificationTargetDirectoryName: "pla-basic",
      verificationTargetCount: 3,
      materialName: "PLA Basic",
    });
    useWidgetStore.getState().setActiveTab("gradient-card-extract");

    expect(useWidgetStore.getState().activeTab).toBe("gradient-card-extract");
    const state = useSingleStageStore.getState();
    expect(state.verificationTargetDirectoryName).toBe("pla-basic");
    expect(state.verificationTargetCount).toBe(3);
  });
});
