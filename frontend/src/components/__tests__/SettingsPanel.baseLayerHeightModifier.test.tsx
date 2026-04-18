import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../api/system", () => ({
  clearCache: vi.fn(),
  getPrinters: vi.fn(),
  getSlicers: vi.fn(),
  saveSettings: vi.fn(),
}));

import { I18nProvider } from "../../i18n/context";
import * as i18nContext from "../../i18n/context";
import { translations } from "../../i18n/translations";
import SettingsPanel from "../SettingsPanel";
import { DEFAULT_SETTINGS, useSettingsStore } from "../../stores/settingsStore";
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
});
