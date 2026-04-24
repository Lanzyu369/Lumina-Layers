import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useWidgetStore } from "../stores/widgetStore";
import App from "../App";

const lutDetailsModuleState = vi.hoisted(() => ({
  evaluationCount: 0,
}));

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { status: "ok" } }),
    post: vi.fn(),
  },
}));

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn().mockResolvedValue({ luts: [] }),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  getFileUrl: vi.fn(),
  fetchBedSizes: vi.fn().mockResolvedValue({ bed_sizes: [] }),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
  convertBatch: vi.fn(),
  replaceColor: vi.fn(),
}));

vi.mock("../api/slicer", () => ({
  detectSlicers: vi.fn().mockResolvedValue({ slicers: [] }),
  launchSlicer: vi.fn(),
}));

vi.mock("../api/lut", () => ({
  fetchLutInfo: vi.fn(),
  mergeLuts: vi.fn(),
  compareLuts: vi.fn(),
}));

vi.mock("../api/extractor", () => ({
  extractColors: vi.fn(),
  manualFixCell: vi.fn(),
}));

vi.mock("../api/system", () => ({
  clearCache: vi.fn(),
  getSettings: vi.fn().mockResolvedValue({}),
  saveSettings: vi.fn(),
  getStats: vi.fn().mockResolvedValue({}),
}));

vi.mock("../components/Scene3D", () => ({ default: () => null }));

vi.mock("../components/LutDetailsPanel", () => {
  lutDetailsModuleState.evaluationCount += 1;
  return {
    default: () => <div data-testid="lut-details-panel" />,
  };
});

describe("App LUT details loading", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWidgetStore.getState().resetLayout();
    useWidgetStore.getState().setActiveTab("converter");
  });

  it("does not evaluate the LUT details module until the tab is opened", async () => {
    render(<App />);

    expect(lutDetailsModuleState.evaluationCount).toBe(0);

    act(() => {
      useWidgetStore.getState().setActiveTab("lut-details");
    });

    await waitFor(() => {
      expect(lutDetailsModuleState.evaluationCount).toBe(1);
      expect(screen.getByTestId("lut-details-panel")).toBeInTheDocument();
    });
  });
});
