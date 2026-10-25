import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n/context";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import CreditsDialog from "./CreditsDialog";
import { loadCreditsCatalog } from "./catalog";
import type { CreditsCatalog } from "./types";

const { desktop } = vi.hoisted(() => ({ desktop: { platform: undefined as string | undefined } }));
vi.mock("../integrations/electron", () => ({ electronAPI: desktop }));
vi.mock("./catalog", () => ({ loadCreditsCatalog: vi.fn() }));
vi.mock("./CreditsGarden", () => ({ default: ({ catalog }: { catalog: CreditsCatalog }) => <div data-testid="loaded-garden">{catalog.records[0].name}</div> }));

const catalog: CreditsCatalog = {
  records: [{ id: "real-1", name: "真实昵称", source: "GitHub", tier: 0, dev: true, brand: false }],
  assetsBase: "https://lumina-studio-credits.pages.dev/", stale: false,
};

beforeEach(() => {
  desktop.platform = undefined;
  vi.mocked(loadCreditsCatalog).mockReset();
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
});

describe("CreditsDialog", () => {
  it.each([
    ["darwin", "paddingLeft"],
    ["win32", "paddingRight"],
  ] as const)("keeps %s native window controls clear and the close button clickable", async (platform, padding) => {
    desktop.platform = platform;
    vi.mocked(loadCreditsCatalog).mockResolvedValue(catalog);
    const onClose = vi.fn();
    render(<I18nProvider><CreditsDialog onClose={onClose} /></I18nProvider>);
    await screen.findByText("真实昵称");
    const header = screen.getByRole("dialog").querySelector("header")!;
    expect(header).toHaveClass("desktop-titlebar");
    expect(header.style[padding]).toContain("titlebar-area");
    const close = screen.getByRole("button", { name: "返回工作区" });
    expect(close.closest(".desktop-titlebar-controls")).not.toBeNull();
    fireEvent.click(close);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows loading and then hands the real catalog to the garden", async () => {
    let resolve!: (value: CreditsCatalog) => void;
    vi.mocked(loadCreditsCatalog).mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<I18nProvider><CreditsDialog onClose={vi.fn()} /></I18nProvider>);
    expect(screen.getByRole("dialog", { name: "致谢" })).toBeInTheDocument();
    expect(screen.getByText("正在加载名单…")).toBeInTheDocument();
    resolve(catalog);
    expect(await screen.findByText("真实昵称")).toBeInTheDocument();
  });

  it("retries a failed first load without showing fake records", async () => {
    vi.mocked(loadCreditsCatalog).mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce(catalog);
    render(<I18nProvider><CreditsDialog onClose={vi.fn()} /></I18nProvider>);
    expect(await screen.findByText("暂时无法加载名单")).toBeInTheDocument();
    expect(screen.queryByTestId("loaded-garden")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("真实昵称")).toBeInTheDocument();
  });

  it("returns focus to the launch control after Escape closes the dialog", async () => {
    vi.mocked(loadCreditsCatalog).mockResolvedValue(catalog);
    function Host() {
      const [open, setOpen] = useState(false);
      return <I18nProvider><button onClick={() => setOpen(true)}>Open</button>{open && <CreditsDialog onClose={() => setOpen(false)} />}</I18nProvider>;
    }
    render(<Host />);
    const launch = screen.getByRole("button", { name: "Open" });
    launch.focus();
    fireEvent.click(launch);
    expect(await screen.findByText("真实昵称")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(launch).toHaveFocus();
  });

  it("does not close when the garden already handled Escape", async () => {
    vi.mocked(loadCreditsCatalog).mockResolvedValue(catalog);
    const onClose = vi.fn();
    render(<I18nProvider><CreditsDialog onClose={onClose} /></I18nProvider>);
    await screen.findByText("真实昵称");
    const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    event.preventDefault();
    document.dispatchEvent(event);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps a cached catalog visible when the refresh is unavailable", async () => {
    vi.mocked(loadCreditsCatalog).mockResolvedValue({ ...catalog, stale: true });
    render(<I18nProvider><CreditsDialog onClose={vi.fn()} /></I18nProvider>);
    expect(await screen.findByText("真实昵称")).toBeInTheDocument();
    expect(screen.getByText("已载入上次保存的名单")).toBeInTheDocument();
  });

  it("keeps keyboard events away from the suspended workspace", async () => {
    vi.mocked(loadCreditsCatalog).mockResolvedValue(catalog);
    const backgroundNudge = vi.fn();
    window.addEventListener("keydown", backgroundNudge);
    try {
      render(<I18nProvider><CreditsDialog onClose={vi.fn()} /></I18nProvider>);
      await screen.findByText("真实昵称");
      fireEvent.keyDown(screen.getByRole("button", { name: "返回工作区" }), { key: "ArrowDown" });
      fireEvent.keyDown(document.body, { key: "ArrowDown" });
      expect(backgroundNudge).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("keydown", backgroundNudge);
    }
  });
});
