import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import type { TabId } from "../types/widget";
import App from "../App";
import { useWidgetStore } from "../stores/widgetStore";
const indicatorCompletions = vi.hoisted(() => [] as Array<(tab: TabId) => void>);

vi.mock("../components/widget/TabNavBar", async (original) => {
  const actual = await original<typeof import("../components/widget/TabNavBar")>();
  return {
    ...actual,
    default: (props: ComponentProps<typeof actual.default>) => {
      if (props.onIndicatorAnimationComplete) indicatorCompletions.push(props.onIndicatorAnimationComplete);
      // Control animation completion explicitly in jsdom, which has no layout.
      return <actual.default {...props} onIndicatorAnimationComplete={undefined} />;
    },
  };
});

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
  default: ({ modelUrl, deferInitialization }: { modelUrl?: string; deferInitialization?: boolean }) => (
    <div data-testid="scene3d-mock" data-deferred={String(deferInitialization ?? false)}>{modelUrl ?? "no-model"}</div>
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
  indicatorCompletions.length = 0;
  // Reset widget store to default layout before each test
  useWidgetStore.getState().resetLayout();
  useWidgetStore.getState().setActiveTab("converter");
});

describe("App Widget Toggles", () => {
  it("defers only converter re-entry until the indicator finishes and keeps the page shell visible", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    expect(screen.getByTestId("scene3d-mock")).toHaveAttribute("data-deferred", "false");
    fireEvent.click(screen.getByTestId("tab-vectorizer"));
    expect(screen.queryByTestId("scene3d-mock")).toBeNull();
    fireEvent.click(screen.getByTestId("tab-converter"));
    expect(screen.getByTestId("scene3d-mock")).toHaveAttribute("data-deferred", "true");
    expect(screen.getByTestId("panel-controls-toggle")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tab-converter"));
    expect(screen.getByTestId("scene3d-mock")).toHaveAttribute("data-deferred", "true");
    act(() => indicatorCompletions.at(-1)!("converter"));
    expect(screen.getByTestId("scene3d-mock")).toHaveAttribute("data-deferred", "false");
  });

  it("ignores completion from a converter entry interrupted by another tab", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    fireEvent.click(screen.getByTestId("tab-vectorizer"));
    fireEvent.click(screen.getByTestId("tab-converter"));
    const previousCompletion = indicatorCompletions.at(-1)!;
    fireEvent.click(screen.getByTestId("tab-vectorizer"));
    expect(screen.queryByTestId("scene3d-mock")).toBeNull();
    fireEvent.click(screen.getByTestId("tab-converter"));
    const currentCompletion = indicatorCompletions.at(-1)!;
    act(() => previousCompletion("converter"));
    expect(screen.getByTestId("scene3d-mock")).toHaveAttribute("data-deferred", "true");
    act(() => currentCompletion("converter"));
    expect(screen.getByTestId("scene3d-mock")).toHaveAttribute("data-deferred", "false");
  });

  it("clears a pending initialization when navigation is changed outside the header", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    fireEvent.click(screen.getByTestId("tab-vectorizer"));
    fireEvent.click(screen.getByTestId("tab-converter"));
    act(() => useWidgetStore.getState().setActiveTab("vectorizer"));
    expect(screen.queryByTestId("scene3d-mock")).toBeNull();
    act(() => useWidgetStore.getState().setActiveTab("converter"));
    expect(screen.getByTestId("scene3d-mock")).toHaveAttribute("data-deferred", "false");
  });

  function openWidgetMenu() {
    fireEvent.click(screen.getByTestId("panel-controls-toggle"));
  }

  it("renders widget toggle buttons only for current tab (converter by default)", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
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

  it("shows the model texture panel toggle only under the Creative Center sub-tab", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");

    // Core sub-tab (核心设置) must not offer the model texture panel.
    // 核心设置子页签不得提供模型贴图面板。
    openWidgetMenu();
    expect(
      screen.queryByTestId("widget-toggle-model-surface-settings"),
    ).not.toBeInTheDocument();

    // Switch to the Creative Center (创意中心) sub-tab and reopen the menu.
    fireEvent.click(screen.getByTestId("subtab-converter-advanced"));
    openWidgetMenu();

    const modelSurfaceToggle = screen.getByTestId("widget-toggle-model-surface-settings");
    expect(modelSurfaceToggle).toBeInTheDocument();
    expect(modelSurfaceToggle.className).toContain("bg-blue-50");
  });

  it("does not show widget toggles on LUT pages rendered as full panels", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");

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
    await screen.findByTestId("tab-converter");
    await waitFor(() => {
      expect(screen.getByTestId("header-menu-button")).toHaveAttribute(
        "data-backend-status",
        "ok",
      );
    });

    fireEvent.click(screen.getByTestId("tab-workshop"));

    await screen.findByRole("heading", { name: "创意工坊" });
    expect(
      screen.getByTestId("panel-controls-toggle").parentElement,
    ).toHaveClass("invisible");
    expect(
      screen.queryByTestId("widget-toggle-basic-settings"),
    ).not.toBeInTheDocument();
  });

  it("converter tab widgets are visible by default", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    openWidgetMenu();

    const basicToggle = screen.getByTestId("widget-toggle-basic-settings");
    const actionBarToggle = screen.getByTestId("widget-toggle-action-bar");

    expect(basicToggle.className).toContain("bg-blue-50");
    expect(actionBarToggle.className).toContain("bg-blue-50");
  });

  it("toggles widget visibility when toggle button is clicked", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    openWidgetMenu();

    const basicToggle = screen.getByTestId("widget-toggle-basic-settings");

    expect(basicToggle.className).toContain("bg-blue-50");

    // Click to hide
    fireEvent.click(basicToggle);

    expect(basicToggle.className).not.toContain("bg-blue-50");
    expect(basicToggle.className).toContain("bg-transparent");
  });

  it("toggles widget back to visible when clicked again", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    openWidgetMenu();

    const basicToggle = screen.getByTestId("widget-toggle-basic-settings");

    // Click to hide
    fireEvent.click(basicToggle);
    expect(basicToggle.className).toContain("bg-transparent");

    // Click to show again
    fireEvent.click(basicToggle);
    expect(basicToggle.className).toContain("bg-blue-50");
  });

  it("renders reset layout button", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    openWidgetMenu();

    const resetButton = screen.getByTestId("widget-reset-layout");
    expect(resetButton).toBeInTheDocument();
    expect(resetButton.textContent).toContain("重置布局");
  });
});
