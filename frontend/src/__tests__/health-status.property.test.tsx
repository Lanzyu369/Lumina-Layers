import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, cleanup } from "@testing-library/react";
import fc from "fast-check";
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
  colorcheckerConfirm: vi.fn(),
  colorcheckerRelease: vi.fn(),
  colorcheckerTouch: vi.fn(() => Promise.resolve()),
  extractColors: vi.fn(),
  manualFixCell: vi.fn(),
}));

vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
  I18nProvider: ({ children }: { children: ReactNode }) => children,
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
vi.mock("../components/LutManagerPanel", () => ({ default: () => null }));
vi.mock("../components/LutDetailsPanel", () => ({ default: () => null }));
vi.mock("../components/LutComparePanel", () => ({ default: () => null }));
vi.mock("../components/MaterialLibraryPanel", () => ({ default: () => null }));
vi.mock("../components/MaterialRecipeQueryPanel", () => ({ default: () => null }));
vi.mock("../components/FiveColorQueryPanel", () => ({ default: () => null }));
vi.mock("../components/SettingsPanel", () => ({ default: () => null }));
vi.mock("../components/VectorizerPanel", () => ({ default: () => null }));
vi.mock("../components/LoadingSpinner", () => ({ default: () => null }));
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

describe("Feature: frontend-scaffold, Property 2: 非 'ok' 状态显示失败徽章", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    cleanup();
    // Restore default rejection for unmocked calls
    vi.mocked(apiClient.get).mockRejectedValue(new Error("unmocked"));
  });

  /**
   * Validates: Requirements 5.3
   * For any non-"ok" status string, the App should render a red (fail) badge.
   */
  it("renders a red badge for any non-ok status after the workspace connected", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string().filter((s) => s !== "ok"),
        async (status) => {
          vi.clearAllMocks();
          cleanup();
          // Restore default rejection for unmocked calls
          vi.mocked(apiClient.get).mockRejectedValue(new Error("unmocked"));

          let healthStatus = "ok";
          vi.mocked(apiClient.get).mockImplementation(async (url) => {
            if (url !== "/health") throw new Error(`Unmocked request: ${url}`);
            return { data: { status: healthStatus, version: "2.0", uptime_seconds: 0 } };
          });
          vi.useFakeTimers();
          try {
            await act(async () => { render(<App />); });
            expect(screen.getByTestId("health-badge-ok")).toBeInTheDocument();

            healthStatus = status;
            await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
            expect(screen.getByTestId("health-badge-fail")).toBeInTheDocument();
            expect(screen.queryByTestId("health-badge-ok")).not.toBeInTheDocument();
          } finally {
            cleanup();
            vi.useRealTimers();
          }
        }
      ),
      { numRuns: 20 }
    );
  }, 30000);
});
