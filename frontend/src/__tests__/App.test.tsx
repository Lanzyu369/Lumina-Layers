import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

vi.mock("../api/extractor", () => ({
  colorcheckerConfirm: vi.fn(),
  colorcheckerRelease: vi.fn(),
  colorcheckerTouch: vi.fn(() => Promise.resolve()),
  extractColors: vi.fn(),
  manualFixCell: vi.fn(),
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
vi.mock("../components/CalibrationPanel", () => ({ default: () => null }));
vi.mock("../components/ExtractorPanel", () => ({ default: () => null }));
vi.mock("../components/ExtractorCanvas", () => ({ default: () => null }));
vi.mock("../components/GradientCardGeneratePanel", () => ({ default: () => null }));
vi.mock("../components/GradientCardExtractPanel", () => ({ default: () => null }));
vi.mock("../components/MaterialLibraryPanel", () => ({ default: () => null }));
vi.mock("../components/MaterialRecipeQueryPanel", () => ({ default: () => null }));
vi.mock("../components/LutManagerPanel", () => ({ default: () => null }));
vi.mock("../components/LutDetailsPanel", () => ({ default: () => null }));
vi.mock("../components/LutComparePanel", () => ({ default: () => null }));
vi.mock("../components/FiveColorQueryPanel", () => ({ default: () => null }));
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
import { colorcheckerTouch } from "../api/extractor";
import { useExtractorStore } from "../stores/extractorStore";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";

describe("App component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Restore default rejection for unmocked calls
    vi.mocked(apiClient.get).mockRejectedValue(new Error("unmocked"));
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    useExtractorStore.setState({
      colorchecker_enabled: false,
      colorchecker_phase: null,
      imageFile: null,
      calibratedFullFileId: null,
      previousCalibratedFullFileId: null,
      imagePreviewUrl: null,
      calibratedPreviewUrl: null,
      originalPreviewUrl: null,
    });
    useSingleStageStore.setState({
      colorchecker_phase: null,
      colorchecker_target: null,
      whiteColorcheckerFileId: null,
      blackColorcheckerFileId: null,
      whiteImagePreviewUrl: null,
      blackImagePreviewUrl: null,
      originalWhitePreviewUrl: null,
      originalBlackPreviewUrl: null,
      calibratedPreviewUrl: null,
    });
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

  it('renders header with "Lumina Studio 2"', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });

    render(<App />);

    expect(screen.getByText("Lumina Studio 2")).toBeInTheDocument();
  });

  it("renews the previous extractor ColorChecker id while replacement confirmation is open", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });
    useExtractorStore.setState({
      colorchecker_enabled: true,
      colorchecker_phase: "confirming",
      imageFile: new File(["raw"], "checker.png", { type: "image/png" }),
      calibratedFullFileId: "new-pending-id",
      previousCalibratedFullFileId: "old-confirmed-id",
    });

    render(<App />);

    await waitFor(() => {
      expect(colorcheckerTouch).toHaveBeenCalledWith("old-confirmed-id");
    });
  });

  it("renews active ColorChecker preview URLs while confirmed sources are mounted", async () => {
    const originalFetch = globalThis.fetch;
    const fetchMock = vi.fn(() => Promise.resolve(new Response()));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });
    useExtractorStore.setState({
      colorchecker_enabled: true,
      colorchecker_phase: "done",
      imageFile: new File(["raw"], "checker.png", { type: "image/png" }),
      calibratedFullFileId: "extractor-full-id",
      imagePreviewUrl: "/api/files/extractor-confirmed-preview.jpg",
      calibratedPreviewUrl: "/api/files/extractor-confirmed-preview.jpg",
      originalPreviewUrl: "/api/files/extractor-original-preview.jpg",
    });
    useSingleStageStore.setState({
      whiteColorcheckerFileId: "white-full-id",
      blackColorcheckerFileId: "black-full-id",
      whiteImagePreviewUrl: "/api/files/white-confirmed-preview.jpg",
      blackImagePreviewUrl: "/api/files/black-confirmed-preview.jpg",
      originalWhitePreviewUrl: "/api/files/white-original-preview.jpg",
      originalBlackPreviewUrl: "/api/files/black-original-preview.jpg",
    });

    try {
      render(<App />);

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith(
          "/api/files/extractor-confirmed-preview.jpg",
          { cache: "no-store" },
        );
      });
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/files/white-confirmed-preview.jpg",
        { cache: "no-store" },
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/files/black-confirmed-preview.jpg",
        { cache: "no-store" },
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/files/extractor-original-preview.jpg",
        { cache: "no-store" },
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/files/white-original-preview.jpg",
        { cache: "no-store" },
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/files/black-original-preview.jpg",
        { cache: "no-store" },
      );
      expect(colorcheckerTouch).toHaveBeenCalledWith("extractor-full-id");
      expect(colorcheckerTouch).toHaveBeenCalledWith("white-full-id");
      expect(colorcheckerTouch).toHaveBeenCalledWith("black-full-id");
    } finally {
      if (originalFetch) {
        globalThis.fetch = originalFetch;
      } else {
        Reflect.deleteProperty(globalThis, "fetch");
      }
    }
  });
});
