import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

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
  validateCustomSlicerPath: vi.fn(),
}));

vi.mock("../api/lut", () => ({
  fetchLutInfo: vi.fn(),
  mergeLuts: vi.fn(),
  compareLuts: vi.fn(),
}));

vi.mock("../api/system", () => ({
  clearCache: vi.fn(),
  getSettings: vi.fn().mockResolvedValue({}),
  saveSettings: vi.fn(),
  getStats: vi.fn().mockResolvedValue({}),
}));

vi.mock("../hooks/useAutoPreview", () => ({ useAutoPreview: vi.fn() }));
vi.mock("../hooks/usePuzzleLayoutPreview", () => ({ usePuzzleLayoutPreview: vi.fn() }));
vi.mock("../hooks/useSessionLease", () => ({ useSessionLease: vi.fn() }));
vi.mock("../hooks/useAnnouncement", () => ({
  useAnnouncement: () => ({
    visible: false,
    entries: [],
    entry: null,
    version: "",
    close: vi.fn(),
    dismissThisVersion: vi.fn(),
  }),
}));
vi.mock("../hooks/useWorkspaceMode", () => ({
  useWorkspaceMode: () => ({
    width: 1440,
    height: 900,
    dpr: 1,
    mode: "standard",
    isCompact: false,
    isStandard: true,
    isWide: false,
  }),
}));
vi.mock("../components/Scene3D", () => ({ default: () => null }));
vi.mock("../components/SettingsPanel", () => ({ default: () => null }));
vi.mock("../components/VectorizerPanel", () => ({ default: () => null }));
vi.mock("../components/LanguageToggle", () => ({ LanguageToggle: () => null }));
vi.mock("../components/ThemeToggle", () => ({ ThemeToggle: () => null }));
vi.mock("../components/BugReportButton", () => ({ BugReportButton: () => null }));
vi.mock("../components/BugReportModal", () => ({ BugReportModal: () => null }));
vi.mock("../components/ui/AnnouncementDialog", () => ({ default: () => null }));
vi.mock("../components/widget/WidgetWorkspace", () => ({
  WidgetWorkspace: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock("../components/widget/TabNavBar", () => ({
  default: () => null,
  hasSubTabs: () => false,
}));
vi.mock("../components/widget/SubTabBar", () => ({ default: () => null }));

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
    expect(apiClient.get).toHaveBeenCalledWith("/health", {
      suppressClientLog: true,
    });
  });

  it("renders red badge when API request fails", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Network Error"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("health-badge-fail")).toBeInTheDocument();
    });
    expect(apiClient.get).toHaveBeenCalledWith("/health", {
      suppressClientLog: true,
    });
  });

  it("rechecks health after a failed request and recovers the badge", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValue({
        data: { status: "ok", version: "2.0", uptime_seconds: 120 },
      });

    try {
      render(<App />);

      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByTestId("health-badge-fail")).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
        await Promise.resolve();
      });

      expect(apiClient.get).toHaveBeenCalledTimes(2);
      expect(apiClient.get).toHaveBeenNthCalledWith(1, "/health", {
        suppressClientLog: true,
      });
      expect(apiClient.get).toHaveBeenNthCalledWith(2, "/health", {
        suppressClientLog: true,
      });
      expect(screen.getByTestId("health-badge-ok")).toBeInTheDocument();
      expect(screen.queryByTestId("health-badge-fail")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('renders header with "Lumina Studio 2"', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });

    render(<App />);

    expect(screen.getByText("Lumina Studio 2")).toBeInTheDocument();
  });
});
