import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api/system", () => ({
  clearCache: vi.fn(),
  getMachineRegistryAssetUrl: (path: string) => `/api/system/machine-registry/assets/${path}`,
  getPrinters: vi.fn(),
  getSlicers: vi.fn(),
  saveSettings: vi.fn(),
}));

vi.mock("../../utils/retryAsync", () => ({
  retryAsync: vi.fn((operation: () => Promise<unknown>) => operation()),
}));

import { I18nProvider } from "../../i18n/context";
import SettingsPanel from "../SettingsPanel";
import { DEFAULT_SETTINGS, useSettingsStore } from "../../stores/settingsStore";
import { useSlicerStore } from "../../stores/slicerStore";
import type { PrinterInfo, SlicerOption } from "../../api/types";
import * as systemApi from "../../api/system";
import { translations } from "../../i18n/translations";

const SLICERS: SlicerOption[] = [
  { id: "BambuStudio", display_name: "Bambu Studio" },
  { id: "OrcaSlicer", display_name: "OrcaSlicer" },
];

const PRINTERS: PrinterInfo[] = [
  {
    id: "bambu-h2d",
    display_name: "Bambu Lab H2D",
    brand: "Bambu Lab",
    bed_width: 350,
    bed_depth: 320,
    bed_height: 325,
    supported_nozzle_sizes: ["0.2", "0.4", "0.6", "0.8"],
    supported_slicers: ["BambuStudio", "OrcaSlicer"],
    thumbnail: "slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d_cover.png",
    device_profiles: [
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.2",
        slicer_id: "BambuStudio",
        nozzle_size: "0.2",
        source_profile_name: "Bambu Lab H2D 0.2 nozzle",
        revision: "sha256:bambu-02",
        supported: true,
      },
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
        slicer_id: "BambuStudio",
        nozzle_size: "0.4",
        source_profile_name: "Bambu Lab H2D 0.4 nozzle",
        revision: "sha256:bambu",
        supported: true,
      },
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.6",
        slicer_id: "BambuStudio",
        nozzle_size: "0.6",
        source_profile_name: "Bambu Lab H2D 0.6 nozzle",
        revision: "sha256:bambu-06",
        supported: true,
      },
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.8",
        slicer_id: "BambuStudio",
        nozzle_size: "0.8",
        source_profile_name: "Bambu Lab H2D 0.8 nozzle",
        revision: "sha256:bambu-08",
        supported: true,
      },
      {
        device_profile_id: "OrcaSlicer:bbl:bambu-lab-h2d:0.2",
        slicer_id: "OrcaSlicer",
        nozzle_size: "0.2",
        source_profile_name: "Bambu Lab H2D 0.2 nozzle",
        revision: "sha256:orca",
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
    thumbnail: "slicers/BambuStudio/02.07.01.57/assets/bambu-lab-p1s_cover.png",
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

describe("SettingsPanel machine adapter registry UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      printerModel: "bambu-h2d",
      slicerSoftware: "BambuStudio",
      nozzleSize: "0.4",
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-h2d:0.2",
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

  it("renders registry thumbnail and normalizes selected device profile", async () => {
    renderPanel();

    const h2dCard = await screen.findByTestId("machine-adapter-card-bambu-h2d");
    const image = within(h2dCard).getByAltText("Bambu Lab H2D");
    expect(image).toHaveAttribute(
      "src",
      "/api/system/machine-registry/assets/slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d_cover.png",
    );
    expect(await screen.findByText(/Bambu Lab H2D 0\.4 nozzle/)).toBeInTheDocument();

    await waitFor(() => {
      expect(useSettingsStore.getState().deviceProfileId).toBe(
        "BambuStudio:bbl:bambu-lab-h2d:0.4",
      );
    });
  });

  it("renders visual printer cards and selecting one updates the active machine", async () => {
    renderPanel();

    const h2dCard = await screen.findByTestId("machine-adapter-card-bambu-h2d");
    const p1sCard = await screen.findByTestId("machine-adapter-card-bambu-p1s");

    expect(h2dCard).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByAltText("Bambu Lab P1S"),
    ).toHaveAttribute(
      "src",
      "/api/system/machine-registry/assets/slicers/BambuStudio/02.07.01.57/assets/bambu-lab-p1s_cover.png",
    );

    fireEvent.click(p1sCard);

    await waitFor(() => {
      expect(useSettingsStore.getState().printerModel).toBe("bambu-p1s");
      expect(useSettingsStore.getState().deviceProfileId).toBe(
        "BambuStudio:bbl:bambu-lab-p1s:0.4",
      );
    });
    expect(p1sCard).toHaveAttribute("aria-pressed", "true");
  });

  it("lets users pick supported nozzles inside machine cards without showing 0.6 or 0.8", async () => {
    renderPanel();

    await screen.findByTestId("machine-adapter-card-bambu-h2d");

    const h2dNozzle02 = await screen.findByTestId("machine-adapter-nozzle-bambu-h2d-0_2");
    const h2dNozzle04 = await screen.findByTestId("machine-adapter-nozzle-bambu-h2d-0_4");
    expect(h2dNozzle02).toHaveTextContent(/0\.2\s*(mm|毫米)/);
    expect(h2dNozzle04).toHaveTextContent(/0\.4\s*(mm|毫米)/);
    expect(screen.queryByTestId("machine-adapter-nozzle-bambu-h2d-0_6")).not.toBeInTheDocument();
    expect(screen.queryByTestId("machine-adapter-nozzle-bambu-h2d-0_8")).not.toBeInTheDocument();

    fireEvent.click(h2dNozzle02);

    await waitFor(() => {
      expect(useSettingsStore.getState().printerModel).toBe("bambu-h2d");
      expect(useSettingsStore.getState().nozzleSize).toBe("0.2");
      expect(useSettingsStore.getState().deviceProfileId).toBe(
        "BambuStudio:bbl:bambu-lab-h2d:0.2",
      );
    });
    expect(h2dNozzle02).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("combobox", { name: "喷嘴尺寸" })).not.toBeInTheDocument();
  });

  it("shows a visible error when printer options fail to load", async () => {
    vi.mocked(systemApi.getPrinters).mockRejectedValueOnce(
      new Error("Printer registry unavailable"),
    );

    renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      translations["settings.printer_options_load_failed"].zh.replace("{error}", ""),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Printer registry unavailable",
    );
    expect(await screen.findByText("Bambu Studio")).toBeInTheDocument();
  });

  it("retries printer options from the visible error banner", async () => {
    vi.mocked(systemApi.getPrinters)
      .mockRejectedValueOnce(new Error("Printer registry unavailable"))
      .mockResolvedValueOnce(PRINTERS);

    renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Printer registry unavailable",
    );

    fireEvent.click(screen.getByRole("button", { name: translations.widget_retry.zh }));

    expect(await screen.findByTestId("machine-adapter-card-bambu-h2d")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(systemApi.getPrinters).toHaveBeenCalledTimes(2);
  });

  it("shows a visible error when slicer options fail to load", async () => {
    vi.mocked(systemApi.getSlicers).mockRejectedValueOnce(
      new Error("Slicer registry unavailable"),
    );

    renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      translations["settings.slicer_options_load_failed"].zh.replace("{error}", ""),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Slicer registry unavailable",
    );
    expect(await screen.findByTestId("machine-adapter-card-bambu-h2d")).toBeInTheDocument();
  });
});
