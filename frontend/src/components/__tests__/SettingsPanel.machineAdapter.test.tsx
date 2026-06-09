import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("../../api/system", () => ({
  clearCache: vi.fn(),
  getMachineRegistryAssetUrl: (path: string) => `/api/system/machine-registry/assets/${path}`,
  getPrinters: vi.fn(),
  getSlicers: vi.fn(),
  saveSettings: vi.fn(),
}));

import { I18nProvider } from "../../i18n/context";
import SettingsPanel from "../SettingsPanel";
import { DEFAULT_SETTINGS, useSettingsStore } from "../../stores/settingsStore";
import { useSlicerStore } from "../../stores/slicerStore";
import type { PrinterInfo, SlicerOption } from "../../api/types";
import * as systemApi from "../../api/system";

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
    supported_nozzle_sizes: ["0.2", "0.4"],
    supported_slicers: ["BambuStudio", "OrcaSlicer"],
    thumbnail: "slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d_cover.png",
    device_profiles: [
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
        slicer_id: "BambuStudio",
        nozzle_size: "0.4",
        source_profile_name: "Bambu Lab H2D 0.4 nozzle",
        revision: "sha256:bambu",
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

    const image = await screen.findByAltText("Bambu Lab H2D");
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
});
