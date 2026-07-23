import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../api/system", () => ({
  clearCache: vi.fn(),
  getMachineRegistryAssetUrl: (path: string) => `/api/system/machine-registry/assets/${path}`,
  getPrinters: vi.fn(),
  getSlicers: vi.fn(),
  saveSettings: vi.fn(),
}));

import { I18nProvider } from "../../i18n/context";
import * as i18nContext from "../../i18n/context";
import { translations } from "../../i18n/translations";
import SettingsPanel from "../SettingsPanel";
import { DEFAULT_SETTINGS, useSettingsStore } from "../../stores/settingsStore";
import { useSlicerStore } from "../../stores/slicerStore";
import type { PrinterInfo, SlicerOption } from "../../api/types";
import * as systemApi from "../../api/system";

const SLICERS: SlicerOption[] = [
  { id: "BambuStudio", display_name: "Bambu Studio" },
  { id: "PrusaSlicer", display_name: "PrusaSlicer" },
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
  },
  {
    id: "prusamk4",
    display_name: "Prusa MK4",
    brand: "Prusa",
    bed_width: 250,
    bed_depth: 210,
    bed_height: 220,
    supported_nozzle_sizes: ["0.4"],
    supported_slicers: ["PrusaSlicer"],
  },
];

function renderPanel() {
  return render(
    <I18nProvider>
      <SettingsPanel />
    </I18nProvider>,
  );
}

describe("SettingsPanel base-layer-height modifier", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      enableBaseLayerHeightModifier: true,
      printerModel: "bambu-h2d",
      slicerSoftware: "BambuStudio",
      nozzleSize: "0.4",
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

  it("renders switch when slicerSoftware is BambuStudio", async () => {
    renderPanel();

    await waitFor(() => {
      expect(
        screen.getByTestId("base-layer-height-modifier-row"),
      ).toBeInTheDocument();
    });
  });

  it("hides switch when slicerSoftware is PrusaSlicer", async () => {
    useSettingsStore.setState({
      slicerSoftware: "PrusaSlicer",
      printerModel: "prusamk4",
    });

    renderPanel();

    await waitFor(() => {
      expect(systemApi.getSlicers).toHaveBeenCalled();
    });
    expect(
      screen.queryByTestId("base-layer-height-modifier-row"),
    ).toBeNull();
  });

  it("default switch is on", async () => {
    renderPanel();

    const toggle = await screen.findByRole("switch", {
      name: "底板层高修改器",
    });
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("renders manual slicer app path controls", async () => {
    renderPanel();

    expect(
      await screen.findByLabelText("手动切片软件路径"),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("/Applications/Bambu Studio.app"),
    ).toBeInTheDocument();
    expect(screen.getByText("校验并保存")).toBeInTheDocument();
    expect(screen.getByText("清除")).toBeInTheDocument();
  });

  it("toggling switch updates store and triggers syncToBackend", async () => {
    renderPanel();

    const toggle = await screen.findByRole("switch", {
      name: "底板层高修改器",
    });
    fireEvent.click(toggle);

    expect(
      useSettingsStore.getState().enableBaseLayerHeightModifier,
    ).toBe(false);
    await waitFor(() => {
      expect(systemApi.saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          enable_base_layer_height_modifier: false,
        }),
      );
    });
  });

  it("displays translated label in Chinese locale", async () => {
    useSettingsStore.setState({ language: "zh" });
    renderPanel();

    expect(
      await screen.findByText("底板层高修改器"),
    ).toBeInTheDocument();
  });

  it("describes compatible slicers without merging Orca and Bambu settings", () => {
    const description = translations["settings.base_layer_height_modifier_desc"];

    expect(description.zh).not.toContain("Bambu 系");
    expect(description.zh).toContain("当前设置中选择的兼容切片软件");
    expect(description.zh).toContain("各自的机器配置");
    expect(description.en).not.toContain("Bambu-family");
    expect(description.en).toContain("compatible slicer selected in Settings");
    expect(description.en).toContain("own machine profile");
  });

  it("displays translated label in English locale", async () => {
    const useI18nSpy = vi.spyOn(i18nContext, "useI18n").mockReturnValue({
      lang: "en",
      t: (key: string) => translations[key]?.en ?? key,
    });

    renderPanel();

    expect(
      await screen.findByText("Base-plate layer-height modifier"),
    ).toBeInTheDocument();

    useI18nSpy.mockRestore();
  });

  it("describes fixed-first-layer boundary alignment in both locales", () => {
    const description = translations["settings.base_layer_height_modifier_desc"];

    expect(description.zh).toContain("计入固定首层");
    expect(description.zh).toContain("准确落在底板边界");
    expect(description.zh).toContain("浮雕");
    expect(description.zh).toContain("双面");
    expect(description.zh).toContain("没有安全可选值");
    expect(description.zh).not.toContain("整除底板厚度");

    expect(description.en).toContain("accounts for the fixed first layer");
    expect(description.en).toContain("lands exactly on the backing boundary");
    expect(description.en).toContain("relief");
    expect(description.en).toContain("double-sided");
    expect(description.en).toContain("no safe value exists");
    expect(description.en).not.toContain("divides the base-plate thickness exactly");
  });
});
