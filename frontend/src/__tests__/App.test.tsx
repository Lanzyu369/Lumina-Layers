import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Mock the API client module — default to rejecting so unexpected calls don't crash
vi.mock("../api/client", () => ({
  default: {
    get: vi.fn().mockRejectedValue(new Error("unmocked")),
    post: vi.fn().mockRejectedValue(new Error("unmocked")),
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

import App from "../App";
import apiClient from "../api/client";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";

describe("App component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Restore default rejection for unmocked calls
    vi.mocked(apiClient.get).mockRejectedValue(new Error("unmocked"));
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    localStorage.clear();
  });

  it('renders green badge when API returns status "ok"', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("health-badge-ok")).toBeInTheDocument();
    });
  });

  it("renders red badge when API request fails", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Network Error"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("health-badge-fail")).toBeInTheDocument();
    });
  });

  it('renders header with "Lumina Studio 2.0"', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });

    render(<App />);

    expect(screen.getByText("Lumina Studio 2.0")).toBeInTheDocument();
  });
});
