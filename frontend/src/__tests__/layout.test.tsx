import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import App from "../App";
import { useWidgetStore } from "../stores/widgetStore";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
  },
  apiErrorToVisibleMessage: (_error: unknown, fallback: string) => fallback,
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
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 2400 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 1200 });
    Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: 1 });
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

  it("renders the full main-app top-level navigation", () => {
    render(<App />);
    expect(screen.getByTestId("tab-converter")).toBeInTheDocument();
    expect(screen.getByTestId("tab-lut-management")).toBeInTheDocument();
    expect(screen.getByTestId("tab-material-management")).toBeInTheDocument();
    expect(screen.getByTestId("tab-vectorizer")).toBeInTheDocument();
    expect(screen.getByTestId("tab-settings")).toBeInTheDocument();
  });

  it("keeps the top-level navigation in the legacy centered header column", () => {
    render(<App />);

    const converterTab = screen.getByTestId("tab-converter");
    const nav = converterTab.closest("nav");
    const header = nav?.closest("header");
    const tabWrapper = nav?.parentElement;

    expect(header).toHaveClass("lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]");
    expect(header).not.toHaveClass("lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]");
    expect(tabWrapper).not.toHaveClass("w-full");
  });

  it("renders local LUT and material secondary tabs in the main app", () => {
    render(<App />);

    fireEvent.click(screen.getByTestId("tab-lut-management"));
    expect(screen.getByTestId("subtab-lut-library")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-calibration")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-extractor")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-lut-cloud-sync")).toBeInTheDocument();
    expect(screen.queryByTestId("subtab-lut-manager")).not.toBeInTheDocument();
    expect(screen.getByTestId("subtab-five-color")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("tab-material-management"));
    expect(screen.getByTestId("subtab-material-library")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-material-cloud-sync")).toBeInTheDocument();
    expect(screen.queryByTestId("subtab-lut-cloud-sync")).not.toBeInTheDocument();
    expect(screen.getByTestId("subtab-material-recipe")).toBeInTheDocument();

    expect(screen.queryByTestId("tab-calibration")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-extractor")).not.toBeInTheDocument();
  });
});
