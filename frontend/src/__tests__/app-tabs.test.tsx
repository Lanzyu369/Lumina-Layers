import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import App from "../App";
import { useWidgetStore } from "../stores/widgetStore";

// Mock apiClient to prevent real HTTP calls (health check)
vi.mock("../api/client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { status: "ok" } }),
    post: vi.fn(),
  },
  apiErrorToVisibleMessage: vi.fn(
    (_error: unknown, fallback = "Request failed") => fallback,
  ),
}));

// Mock Scene3D to avoid Three.js rendering in jsdom
vi.mock("../components/Scene3D", () => ({
  default: ({ modelUrl }: { modelUrl?: string }) => (
    <div data-testid="scene3d-mock">{modelUrl ?? "no-model"}</div>
  ),
}));

// Mock calibration API to prevent CalibrationPanel network calls
vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
  generateSingleStageKit: vi.fn(),
}));

// Mock converter API to prevent fetchLutList call during data init
vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn().mockResolvedValue({ luts: [] }),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  getFileUrl: vi.fn((id: string) => `/api/files/${id}`),
}));

beforeEach(() => {
  vi.clearAllMocks();
  // Reset widget store to default layout before each test
  useWidgetStore.getState().resetLayout();
  useWidgetStore.getState().setActiveTab("converter");
});

describe("App Widget Toggles", () => {
  function openWidgetMenu() {
    fireEvent.click(screen.getByTestId("panel-controls-toggle"));
  }

  it("renders widget toggle buttons only for current tab (converter by default)", () => {
    render(<App />);
    openWidgetMenu();

    // Converter page widgets (default active tab) should be visible
    expect(screen.getByTestId("widget-toggle-basic-settings")).toBeInTheDocument();
    expect(screen.getByTestId("widget-toggle-advanced-settings")).toBeInTheDocument();
    expect(screen.getByTestId("widget-toggle-action-bar")).toBeInTheDocument();
    // Other page widgets should NOT be visible on converter tab
    expect(screen.queryByTestId("widget-toggle-calibration")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-toggle-extractor")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-toggle-lut-manager")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-toggle-five-color")).not.toBeInTheDocument();
  });

  it("does not show widget toggles on LUT pages rendered as full panels", () => {
    render(<App />);

    fireEvent.click(screen.getByTestId("tab-lut-management"));
    openWidgetMenu();

    expect(screen.queryByTestId("widget-toggle-calibration")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-toggle-extractor")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-toggle-lut-manager")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-toggle-five-color")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-reset-layout")).not.toBeInTheDocument();
  });

  it("opens Creative Workshop without exposing converter widget controls", async () => {
    render(<App />);
    await screen.findByTestId("health-badge-ok");

    fireEvent.click(screen.getByTestId("tab-workshop"));

    await screen.findByRole("heading", { name: "创意工坊" });
    expect(
      screen.getByTestId("panel-controls-toggle").parentElement,
    ).toHaveClass("invisible");
    expect(
      screen.queryByTestId("widget-toggle-basic-settings"),
    ).not.toBeInTheDocument();
  });

  it("converter tab widgets are visible by default", () => {
    render(<App />);
    openWidgetMenu();

    const basicToggle = screen.getByTestId("widget-toggle-basic-settings");
    const actionBarToggle = screen.getByTestId("widget-toggle-action-bar");

    expect(basicToggle.className).toContain("bg-blue-50");
    expect(actionBarToggle.className).toContain("bg-blue-50");
  });

  it("toggles widget visibility when toggle button is clicked", () => {
    render(<App />);
    openWidgetMenu();

    const basicToggle = screen.getByTestId("widget-toggle-basic-settings");

    expect(basicToggle.className).toContain("bg-blue-50");

    // Click to hide
    fireEvent.click(basicToggle);

    expect(basicToggle.className).not.toContain("bg-blue-50");
    expect(basicToggle.className).toContain("bg-transparent");
  });

  it("toggles widget back to visible when clicked again", () => {
    render(<App />);
    openWidgetMenu();

    const basicToggle = screen.getByTestId("widget-toggle-basic-settings");

    // Click to hide
    fireEvent.click(basicToggle);
    expect(basicToggle.className).toContain("bg-transparent");

    // Click to show again
    fireEvent.click(basicToggle);
    expect(basicToggle.className).toContain("bg-blue-50");
  });

  it("renders reset layout button", () => {
    render(<App />);
    openWidgetMenu();

    const resetButton = screen.getByTestId("widget-reset-layout");
    expect(resetButton).toBeInTheDocument();
    expect(resetButton.textContent).toContain("重置布局");
  });
});
