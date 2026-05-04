import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

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

describe("App settings bootstrap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    localStorage.clear();
  });

  it("hydrates missing device settings from backend settings on startup", async () => {
    const apiClient = (await import("../api/client")).default;
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });

    const systemApi = await import("../api/system");
    vi.mocked(systemApi.getSettings).mockResolvedValueOnce({
      status: "success",
      settings: {
        printer_model: "bambu-p1s",
        slicer_software: "BambuStudio",
        nozzle_size: "0.2",
      },
    } as never);

    const settingsStore = await import("../stores/settingsStore");
    settingsStore.useSettingsStore.setState({ ...settingsStore.DEFAULT_SETTINGS });
    localStorage.clear();

    const { default: App } = await import("../App");
    render(<App />);

    await waitFor(() => {
      expect(systemApi.getSettings).toHaveBeenCalled();
      expect(settingsStore.useSettingsStore.getState().printerModel).toBe("bambu-p1s");
      expect(settingsStore.useSettingsStore.getState().slicerSoftware).toBe("BambuStudio");
      expect(settingsStore.useSettingsStore.getState().nozzleSize).toBe("0.2");
    });
  });
});
