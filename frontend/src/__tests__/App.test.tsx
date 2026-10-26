import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
vi.mock("../components/Scene3D", () => ({ default: ({ suspended }: { suspended?: boolean }) => <div data-testid="scene-stub" data-suspended={String(suspended ?? false)} /> }));
vi.mock("../components/SettingsPanel", () => ({ default: () => null }));
vi.mock("../components/VectorizerPanel", () => ({ default: () => <input aria-label="Vector draft" defaultValue="" /> }));
const menuCommands = vi.hoisted(() => new Map<string, () => void>());
vi.mock("../integrations/applicationMenu", () => ({
  useApplicationMenuLanguage: vi.fn(),
  useApplicationMenuCommand: (command: string, handler: () => void) => { menuCommands.set(command, handler); },
}));
vi.mock("../credits/AboutDialog", () => ({ default: ({ page, onNavigate, onClose }: {
  page: "about" | "credits"; onNavigate: (page: "about" | "credits") => void; onClose: () => void;
}) => <div role="dialog" aria-label={page === "about" ? "关于 Lumina Studio" : "致谢"}>
  {page === "about" && <button onClick={() => onNavigate("credits")}>致谢</button>}
  <button onClick={page === "credits" ? () => onNavigate("about") : onClose}>{page === "credits" ? "返回关于" : "Close about"}</button>
</div> }));
vi.mock("../components/ThemeToggle", () => ({ ThemeToggle: () => null }));
vi.mock("../components/BugReportButton", () => ({ BugReportButton: () => null }));
vi.mock("../components/BugReportModal", () => ({
  BugReportModal: ({ open, presetDescription }: { open: boolean; presetDescription?: string }) =>
    open ? <div data-testid="bug-report-modal-stub">{presetDescription}</div> : null,
}));
vi.mock("../components/tutorial/TutorialHost", () => ({ TutorialHost: () => null }));
vi.mock("../components/tutorial/TutorialLauncherButton", () => ({
  TutorialLauncherButton: () => null,
}));
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
import { useErrorTicketPromptStore } from "../stores/errorTicketPromptStore";
import { translations } from "../i18n/translations";
import { useWidgetStore } from "../stores/widgetStore";

// Backend status lives inside the header's more-options menu.
function openHeaderMenu() {
  fireEvent.click(screen.getByTestId("header-menu-button"));
}

describe("App component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    menuCommands.clear();
    // Unrelated workspace checks start after the backend readiness gate opens.
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    useErrorTicketPromptStore.getState()._resetForTests();
    useWidgetStore.setState({ activeTab: "converter" });
    localStorage.clear();
  });

  it("offers a ticket after a server error and pre-fills the bug report", async () => {
    render(<App />);
    await screen.findByText("Lumina Studio 2");

    act(() => {
      useErrorTicketPromptStore.getState().reportApiError({
        statusCode: 500,
        path: "/api/convert/preview",
        requestId: "req-9",
        message: "preview exploded",
      });
    });

    expect(await screen.findByTestId("error-ticket-prompt")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "提交工单" }));

    const modal = await screen.findByTestId("bug-report-modal-stub");
    expect(modal).toHaveTextContent("/api/convert/preview");
    expect(modal).toHaveTextContent("req-9");
    expect(modal).toHaveTextContent("preview exploded");
    expect(screen.queryByTestId("error-ticket-prompt")).toBeNull();
    expect(useErrorTicketPromptStore.getState().pending).toBeNull();
  });

  it('renders green badge when API returns status "ok"', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });

    render(<App />);
    await screen.findByTestId("header-menu-button");
    openHeaderMenu();

    await waitFor(() => {
      expect(screen.getByTestId("health-badge-ok")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("header-menu-alert")).not.toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/health", {
      suppressClientLog: true,
      timeout: 4_000,
      signal: expect.any(AbortSignal),
    });
  });

  it("waits for the backend before mounting the workspace after an initial failure", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Network Error"));

    render(<App />);

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalled();
    });
    expect(screen.getByRole("status")).toHaveTextContent(translations.app_starting.zh);
    expect(screen.queryByText("Lumina Studio 2")).not.toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/health", {
      suppressClientLog: true,
      timeout: 4_000,
      signal: expect.any(AbortSignal),
    });
  });

  it("rechecks health and preserves the workspace through later disconnects", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValueOnce({
        data: { status: "ok", version: "2.0", uptime_seconds: 120 },
      })
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValue({
        data: { status: "ok", version: "2.0", uptime_seconds: 120 },
      });

    try {
      render(<App />);

      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByRole("status")).toHaveTextContent(translations.app_starting.zh);
      expect(screen.queryByText("Lumina Studio 2")).not.toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
        await Promise.resolve();
      });

      expect(apiClient.get).toHaveBeenCalledTimes(2);
      expect(apiClient.get).toHaveBeenNthCalledWith(1, "/health", {
        suppressClientLog: true,
        timeout: 4_000,
        signal: expect.any(AbortSignal),
      });
      expect(apiClient.get).toHaveBeenNthCalledWith(2, "/health", {
        suppressClientLog: true,
        timeout: 4_000,
        signal: expect.any(AbortSignal),
      });
      openHeaderMenu();
      expect(screen.getByTestId("health-badge-ok")).toBeInTheDocument();
      expect(screen.queryByTestId("health-badge-fail")).not.toBeInTheDocument();
      const workspaceHeader = screen.getByText("Lumina Studio 2");

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(screen.getByTestId("health-badge-fail")).toBeInTheDocument();
      expect(screen.getByText("Lumina Studio 2")).toBe(workspaceHeader);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(screen.getByTestId("health-badge-ok")).toBeInTheDocument();
      expect(screen.getByText("Lumina Studio 2")).toBe(workspaceHeader);
      expect(apiClient.get).toHaveBeenCalledTimes(4);
    } finally {
      vi.useRealTimers();
    }
  });

  it('renders header with "Lumina Studio 2"', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });

    render(<App />);

    expect(await screen.findByText("Lumina Studio 2")).toBeInTheDocument();
  });

  it("preserves the active workspace and its draft while credits opens and closes", async () => {
    useWidgetStore.setState({ activeTab: "vectorizer" });
    render(<App />);
    const draft = await screen.findByLabelText("Vector draft");
    fireEvent.change(draft, { target: { value: "unsaved artwork" } });
    openHeaderMenu();
    fireEvent.click(screen.getByRole("button", { name: "关于 Lumina Studio" }));
    await screen.findByRole("dialog", { name: "关于 Lumina Studio" });
    fireEvent.click(screen.getByRole("button", { name: "致谢" }));
    expect(screen.getByLabelText("Vector draft")).toBe(draft);
    expect(draft.closest("main")).toHaveAttribute("inert");
    fireEvent.click(screen.getByRole("button", { name: "返回关于" }));
    fireEvent.click(screen.getByRole("button", { name: "Close about" }));
    expect(screen.getByLabelText("Vector draft")).toBe(draft);
    expect(draft).toHaveValue("unsaved artwork");
    expect(draft.closest("main")).not.toHaveAttribute("inert");
  });

  it("suspends background 3D rendering without unmounting the scene", async () => {
    render(<App />);
    const scene = await screen.findByTestId("scene-stub");
    openHeaderMenu();
    fireEvent.click(screen.getByRole("button", { name: "关于 Lumina Studio" }));
    await screen.findByRole("dialog", { name: "关于 Lumina Studio" });
    expect(screen.getByTestId("scene-stub")).toBe(scene);
    expect(scene).toHaveAttribute("data-suspended", "true");
    document.body.setAttribute("tabindex", "-1");
    document.body.focus();
    document.body.removeAttribute("tabindex");
    fireEvent.click(screen.getByRole("button", { name: "致谢" }));
    fireEvent.click(screen.getByRole("button", { name: "返回关于" }));
    expect(scene).toHaveAttribute("data-suspended", "true");
    fireEvent.click(screen.getByRole("button", { name: "Close about" }));
    expect(scene).toHaveAttribute("data-suspended", "false");
    expect(screen.getByTestId("header-menu-button")).toHaveFocus();
  });

  it("routes the native About command to the same page even while viewing credits", async () => {
    render(<App />);
    await screen.findByText("Lumina Studio 2");
    act(() => menuCommands.get("about")!());
    await screen.findByRole("dialog", { name: "关于 Lumina Studio" });
    fireEvent.click(screen.getByRole("button", { name: "致谢" }));
    expect(screen.getByRole("dialog", { name: "致谢" })).toBeInTheDocument();
    act(() => menuCommands.get("about")!());
    expect(screen.getByRole("dialog", { name: "关于 Lumina Studio" })).toBeInTheDocument();
  });
});
