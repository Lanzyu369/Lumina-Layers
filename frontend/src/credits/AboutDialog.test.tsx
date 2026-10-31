import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { version as webVersion } from "../../package.json";
import { I18nProvider } from "../i18n/context";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import AboutDialog from "./AboutDialog";
import type { AboutPage } from "./AboutDialog";
import { loadCreditsCatalog } from "./catalog";
import type { CreditsCatalog } from "./types";

const { desktop } = vi.hoisted(() => ({ desktop: { platform: undefined as string | undefined, getAppVersion: vi.fn() } }));
vi.mock("../integrations/electron", () => ({ electronAPI: desktop }));
vi.mock("./catalog", () => ({ loadCreditsCatalog: vi.fn() }));
vi.mock("./CreditsGarden", () => ({ default: ({ catalog }: { catalog: CreditsCatalog }) => <div data-testid="loaded-garden">{catalog.records[0].name}</div> }));

const catalog: CreditsCatalog = {
  records: [{ id: "real-1", name: "真实昵称", source: "GitHub", tier: 0, dev: true, brand: false }],
  assetsBase: "https://lumina-studio-credits.pages.dev/", stale: false,
};

beforeEach(() => {
  desktop.platform = undefined;
  desktop.getAppVersion.mockReset().mockResolvedValue("2.0.0");
  vi.mocked(loadCreditsCatalog).mockReset();
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
});

function PageHost({ onClose, initialPage = "credits" }: { onClose: () => void; initialPage?: AboutPage }) {
  const [page, setPage] = useState(initialPage);
  return <I18nProvider><AboutDialog page={page} onNavigate={setPage} onClose={onClose} /></I18nProvider>;
}

describe("AboutDialog", () => {
  it("opens About first and loads credits only after choosing Credits", async () => {
    vi.mocked(loadCreditsCatalog).mockResolvedValue(catalog);
    render(<PageHost initialPage="about" onClose={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "关于 Lumina Studio" })).toBeInTheDocument();
    expect(loadCreditsCatalog).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "致谢" }));
    expect(await screen.findByText("真实昵称")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回关于" }));
    expect(screen.getByRole("dialog", { name: "关于 Lumina Studio" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "致谢" })).toHaveFocus();
    expect(loadCreditsCatalog).toHaveBeenCalledTimes(1);
  });

  it("shows the desktop version and official project links without loading the catalog", async () => {
    desktop.getAppVersion.mockResolvedValue("2.3.4");
    render(<PageHost initialPage="about" onClose={vi.fn()} />);
    expect(await screen.findByText("版本 2.3.4")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "官网" })).toHaveAttribute("href", "https://luminastudio.com.cn/");
    expect(screen.getByRole("link", { name: "GitHub" })).toHaveAttribute("href", "https://github.com/lumina-layer-studio/Lumina-studio");
    expect(loadCreditsCatalog).not.toHaveBeenCalled();
  });

  it("keeps the web build version when the desktop version lookup fails", async () => {
    desktop.getAppVersion.mockRejectedValue(new Error("Host unavailable"));
    render(<PageHost initialPage="about" onClose={vi.fn()} />);
    expect(await screen.findByText(`版本 ${webVersion}`)).toBeInTheDocument();
  });

  it.each([
    ["darwin", "paddingLeft"],
    ["win32", "paddingRight"],
  ] as const)("keeps %s native window controls clear and the close button clickable", async (platform, padding) => {
    desktop.platform = platform;
    const onClose = vi.fn();
    render(<PageHost initialPage="about" onClose={onClose} />);
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
    render(<PageHost onClose={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "致谢" })).toBeInTheDocument();
    expect(screen.getByText("正在加载名单…")).toBeInTheDocument();
    resolve(catalog);
    expect(await screen.findByText("真实昵称")).toBeInTheDocument();
  });

  it("retries a failed first load without showing fake records", async () => {
    vi.mocked(loadCreditsCatalog).mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce(catalog);
    render(<PageHost onClose={vi.fn()} />);
    expect(await screen.findByText("暂时无法加载名单")).toBeInTheDocument();
    expect(screen.queryByTestId("loaded-garden")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("真实昵称")).toBeInTheDocument();
  });

  it("returns focus to the launch control after Escape closes the dialog", async () => {
    vi.mocked(loadCreditsCatalog).mockResolvedValue(catalog);
    function Host() {
      const [open, setOpen] = useState(false);
      return <><button onClick={() => setOpen(true)}>Open</button>{open && <PageHost onClose={() => setOpen(false)} />}</>;
    }
    render(<Host />);
    const launch = screen.getByRole("button", { name: "Open" });
    launch.focus();
    fireEvent.click(launch);
    expect(await screen.findByText("真实昵称")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "关于 Lumina Studio" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "致谢" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(launch).toHaveFocus();
  });

  it("does not close when the garden already handled Escape", async () => {
    vi.mocked(loadCreditsCatalog).mockResolvedValue(catalog);
    const onClose = vi.fn();
    render(<PageHost onClose={onClose} />);
    await screen.findByText("真实昵称");
    const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    event.preventDefault();
    document.dispatchEvent(event);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps a cached catalog visible when the refresh is unavailable", async () => {
    vi.mocked(loadCreditsCatalog).mockResolvedValue({ ...catalog, stale: true });
    render(<PageHost onClose={vi.fn()} />);
    expect(await screen.findByText("真实昵称")).toBeInTheDocument();
    expect(screen.getByText("已载入上次保存的名单")).toBeInTheDocument();
  });

  it("keeps keyboard events away from the suspended workspace", async () => {
    vi.mocked(loadCreditsCatalog).mockResolvedValue(catalog);
    const backgroundNudge = vi.fn();
    window.addEventListener("keydown", backgroundNudge);
    try {
      render(<PageHost onClose={vi.fn()} />);
      await screen.findByText("真实昵称");
      fireEvent.keyDown(screen.getByRole("button", { name: "返回关于" }), { key: "ArrowDown" });
      fireEvent.keyDown(document.body, { key: "ArrowDown" });
      expect(backgroundNudge).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("keydown", backgroundNudge);
    }
  });
});
