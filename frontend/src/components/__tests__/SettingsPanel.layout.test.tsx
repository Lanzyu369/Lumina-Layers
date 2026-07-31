import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api/system", () => ({
  clearCache: vi.fn(),
  getMachineRegistryAssetUrl: (path?: string) =>
    path ? `/api/system/machine-registry/assets/${path}` : null,
  getPrinters: vi.fn(),
  getSlicers: vi.fn(),
  saveSettings: vi.fn(),
}));

vi.mock("../../utils/retryAsync", () => ({
  retryAsync: vi.fn((operation: () => Promise<unknown>) => operation()),
}));

import type { PrinterInfo, SlicerOption } from "../../api/types";
import * as systemApi from "../../api/system";
import { I18nProvider } from "../../i18n/context";
import { DEFAULT_SETTINGS, useSettingsStore } from "../../stores/settingsStore";
import { useSlicerStore } from "../../stores/slicerStore";
import SettingsPanel from "../SettingsPanel";

const SLICERS: SlicerOption[] = [
  { id: "BambuStudio", display_name: "Bambu Studio" },
];

const PRINTERS: PrinterInfo[] = [
  {
    id: "bambu-h2d",
    display_name: "Bambu Lab H2D",
    brand: "Bambu Lab",
    bed_width: 350,
    bed_depth: 320,
    bed_height: 325,
    supported_nozzle_sizes: ["0.2", "0.4"],
    supported_slicers: ["BambuStudio"],
    thumbnail: "slicers/BambuStudio/h2d.png",
    device_profiles: [
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
        slicer_id: "BambuStudio",
        nozzle_size: "0.4",
        source_profile_name: "Bambu Lab H2D 0.4 nozzle",
        revision: "sha256:h2d",
        supported: true,
      },
    ],
  },
  {
    id: "bambu-p1s",
    display_name: "Bambu Lab P1S",
    brand: "Bambu Lab",
    bed_width: 256,
    bed_depth: 256,
    bed_height: 250,
    supported_nozzle_sizes: ["0.4"],
    supported_slicers: ["BambuStudio"],
    thumbnail: "slicers/BambuStudio/p1s.png",
    device_profiles: [
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-p1s:0.4",
        slicer_id: "BambuStudio",
        nozzle_size: "0.4",
        source_profile_name: "Bambu Lab P1S 0.4 nozzle",
        revision: "sha256:p1s",
        supported: true,
      },
    ],
  },
];

function renderPanel() {
  return render(
    <I18nProvider>
      <SettingsPanel />
    </I18nProvider>,
  );
}

describe("SettingsPanel information architecture", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      printerModel: "bambu-h2d",
      slicerSoftware: "BambuStudio",
      nozzleSize: "0.4",
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
      language: "zh",
    });
    useSlicerStore.setState({
      slicers: [],
      selectedSlicerId: null,
      isDetecting: false,
      isLaunching: false,
      isValidatingCustomPath: false,
      launchMessage: null,
      customPathMessage: null,
      customPathError: null,
      error: null,
    });
    vi.mocked(systemApi.getPrinters).mockResolvedValue(PRINTERS);
    vi.mocked(systemApi.getSlicers).mockResolvedValue(SLICERS);
    vi.mocked(systemApi.clearCache).mockResolvedValue({
      status: "success",
      message: "ok",
      deleted_files: 0,
      freed_bytes: 0,
      details: {
        registry_cleaned: 0,
        sessions_cleaned: 0,
        output_files_cleaned: 0,
      },
    });
    vi.mocked(systemApi.saveSettings).mockResolvedValue({
      status: "success",
      message: "Settings saved",
    });
  });

  it("shows one settings category at a time", async () => {
    renderPanel();

    const navigation = screen.getByRole("navigation", { name: "设置分类" });
    const deviceButton = within(navigation).getByRole("button", {
      name: /打印与切片/,
    });

    expect(deviceButton).toHaveAttribute("aria-current", "page");
    expect(
      await screen.findByRole("heading", { name: "当前设备", level: 3 }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "完成通知" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(navigation).getByRole("button", { name: /常规/ }),
    );
    expect(
      screen.getByRole("heading", { name: "完成通知", level: 3 }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "当前设备" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(navigation).getByRole("button", { name: /转换与精度/ }),
    );
    expect(screen.getByRole("region", { name: /转换与精度/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "转换与精度" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "SVG 清晰度",
        level: 3,
      }),
    ).toBeInTheDocument();

    fireEvent.click(
      within(navigation).getByRole("button", { name: /存储与维护/ }),
    );
    expect(screen.getByRole("region", { name: /存储与维护/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "存储与维护" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "缓存管理", level: 3 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清除缓存" })).toBeInTheDocument();
  });

  it("uses one concise label for each toggle setting", async () => {
    renderPanel();

    const navigation = screen.getByRole("navigation", { name: "设置分类" });
    fireEvent.click(
      within(navigation).getByRole("button", { name: /常规/ }),
    );

    expect(screen.getAllByText("完成通知")).toHaveLength(1);
    expect(
      screen.getByRole("switch", { name: "完成通知" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("启用浏览器完成通知")).not.toBeInTheDocument();
    expect(screen.getAllByText("加载趣味消息")).toHaveLength(1);

    fireEvent.click(
      within(navigation).getByRole("button", { name: /转换与精度/ }),
    );

    expect(screen.getAllByText("颜色计算精度")).toHaveLength(1);
    expect(
      screen.getByRole("switch", { name: "颜色计算精度" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("自动清理渐变条纹")).toHaveLength(1);
    expect(
      screen.getByRole("switch", { name: "自动清理渐变条纹" }),
    ).toBeInTheDocument();
  });

  it("keeps the machine registry out of the page until the chooser opens", async () => {
    renderPanel();

    await screen.findByRole("heading", { name: "当前设备", level: 3 });
    expect(
      screen.queryByTestId("machine-adapter-card-bambu-h2d"),
    ).not.toBeInTheDocument();

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    fireEvent.click(changeDeviceButton);

    const dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    expect(
      within(dialog).getByTestId("machine-adapter-card-bambu-h2d"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByTestId("machine-adapter-card-bambu-p1s"),
    ).toBeInTheDocument();

    fireEvent.change(
      within(dialog).getByRole("searchbox", { name: "搜索打印机" }),
      { target: { value: "P1S" } },
    );

    expect(
      within(dialog).queryByTestId("machine-adapter-card-bambu-h2d"),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByTestId("machine-adapter-card-bambu-p1s"),
    ).toBeInTheDocument();
  });

  it("shows normalized transparent printer artwork without a decorative stage", async () => {
    renderPanel();

    const summaryImage = await screen.findByRole("img", {
      name: "Bambu Lab H2D",
    });
    expect(summaryImage.parentElement).toHaveClass(
      "rounded-none",
      "bg-transparent",
    );
    expect(summaryImage).toHaveClass("p-0");

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    fireEvent.click(changeDeviceButton);

    const dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    const h2dCard = within(dialog).getByTestId("machine-adapter-card-bambu-h2d");
    const chooserImage = within(h2dCard).getByRole("img", {
      name: "Bambu Lab H2D",
    });

    expect(chooserImage.parentElement).toHaveClass(
      "aspect-square",
      "rounded-none",
      "bg-transparent",
    );
    expect(chooserImage).toHaveClass("p-0");
  });

  it("keeps manual slicer setup collapsed until requested", async () => {
    renderPanel();

    await waitFor(() => {
      expect(systemApi.getSlicers).toHaveBeenCalled();
    });
    expect(screen.queryByLabelText("手动切片软件路径")).not.toBeInTheDocument();

    const disclosure = screen.getByRole("button", { name: /手动设置/ });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(disclosure);

    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("手动切片软件路径")).toBeInTheDocument();
  });

  it("closes the machine chooser with Escape", async () => {
    renderPanel();

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    changeDeviceButton.focus();
    fireEvent.click(changeDeviceButton);
    expect(
      await screen.findByRole("dialog", { name: "选择打印设备" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "选择打印设备" }),
      ).not.toBeInTheDocument();
    });
    expect(changeDeviceButton).toHaveFocus();
  });

  it("keeps Tab and Shift+Tab focus inside the machine chooser", async () => {
    renderPanel();

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    changeDeviceButton.focus();
    fireEvent.click(changeDeviceButton);

    const dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    const searchInput = within(dialog).getByRole("searchbox", {
      name: "搜索打印机",
    });
    const closeButton = within(dialog).getByRole("button", { name: "关闭" });
    const doneButton = within(dialog).getByRole("button", { name: "完成" });

    expect(searchInput).toHaveFocus();

    doneButton.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(closeButton).toHaveFocus();

    closeButton.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(doneButton).toHaveFocus();
  });

  it("restores focus after closing the machine chooser with its buttons", async () => {
    renderPanel();

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    changeDeviceButton.focus();
    fireEvent.click(changeDeviceButton);

    let dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    fireEvent.click(within(dialog).getByRole("button", { name: "完成" }));
    expect(changeDeviceButton).toHaveFocus();

    fireEvent.click(changeDeviceButton);
    dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
    expect(changeDeviceButton).toHaveFocus();
  });
});
