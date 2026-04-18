import { describe, expect, it } from "vitest";
import { deriveBackendDeviceSettingsPatch } from "../stores/settingsStore";

describe("deriveBackendDeviceSettingsPatch", () => {
  it("backfills device settings when persisted snapshot is missing fields", () => {
    const patch = deriveBackendDeviceSettingsPatch(
      {
        printer_model: "bambu-p1s",
        slicer_software: "BambuStudio",
        nozzle_size: "0.2",
      },
      null,
    );

    expect(patch).toEqual({
      printerModel: "bambu-p1s",
      slicerSoftware: "BambuStudio",
      nozzleSize: "0.2",
    });
  });

  it("preserves explicit persisted device settings over backend values", () => {
    const patch = deriveBackendDeviceSettingsPatch(
      {
        printer_model: "bambu-p1s",
        slicer_software: "BambuStudio",
        nozzle_size: "0.2",
      },
      {
        printerModel: "bambu-h2d",
        slicerSoftware: "BambuStudio",
        nozzleSize: "0.4",
      },
    );

    expect(patch).toEqual({});
  });

  it("backfills only newly added nozzle size when older persisted snapshot lacks it", () => {
    const patch = deriveBackendDeviceSettingsPatch(
      {
        printer_model: "bambu-p1s",
        slicer_software: "BambuStudio",
        nozzle_size: "0.2",
      },
      {
        printerModel: "bambu-p1s",
        slicerSoftware: "BambuStudio",
      },
    );

    expect(patch).toEqual({
      nozzleSize: "0.2",
    });
  });
});
