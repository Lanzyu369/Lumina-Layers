import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App";
import { useWidgetStore } from "../stores/widgetStore";

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

  it('preserves "Lumina Studio 2" header', () => {
    render(<App />);
    expect(screen.getByText("Lumina Studio 2")).toBeInTheDocument();
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

  it("renders only converter / vectorizer / settings top-level tabs", () => {
    render(<App />);
    expect(screen.getByTestId("tab-converter")).toBeInTheDocument();
    expect(screen.getByTestId("tab-vectorizer")).toBeInTheDocument();
    expect(screen.getByTestId("tab-settings")).toBeInTheDocument();

    // Material/LUT workflows moved to the standalone MLS service (Route B):
    // their tabs/sub-tabs must be gone from the main app.
    // 耗材/LUT 流程已迁移到独立 MLS 服务，其标签/子标签不应再出现在主应用。
    expect(screen.queryByTestId("tab-lut-management")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-material-management")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-calibration")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-extractor")).not.toBeInTheDocument();
    expect(screen.queryByTestId("subtab-calibration")).not.toBeInTheDocument();
    expect(screen.queryByTestId("subtab-extractor")).not.toBeInTheDocument();
    expect(screen.queryByTestId("subtab-lut-manager")).not.toBeInTheDocument();
    expect(screen.queryByTestId("subtab-five-color")).not.toBeInTheDocument();
  });

  it("exposes a jump entry that opens the standalone Material-LUT Studio", () => {
    render(<App />);
    expect(screen.getByTestId("tab-open-mls")).toBeInTheDocument();
  });
});
