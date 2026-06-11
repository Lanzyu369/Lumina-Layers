import { describe, expect, it } from "vitest";

import {
  filterCompatiblePrinters,
  getDetectedSlicerIdForSoftware,
  getSlicerSoftwareDisplayName,
  getPrinterNozzleSizeOptions,
  isBambuFamilySlicer,
  normalizePrinterOptionId,
  normalizeSlicerOptionId,
  resolveDeviceProfileOptionId,
  resolveNozzleSizeOption,
  resolvePrinterOptionId,
  resolveSlicerOptionId,
} from "../utils/settingsOptionIds";
import type { PrinterInfo, SlicerOption } from "../api/types";

const SLICERS: SlicerOption[] = [
  { id: "BambuStudio", display_name: "BambuStudio" },
  { id: "OrcaSlicer", display_name: "OrcaSlicer" },
  { id: "AnycubicSlicerNext", display_name: "Anycubic Slicer Next" },
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
    id: "elegoo-cc2",
    display_name: "Elegoo Centauri Carbon 2",
    brand: "Elegoo",
    bed_width: 256,
    bed_depth: 256,
    bed_height: 256,
    supported_nozzle_sizes: ["0.4"],
    supported_slicers: ["ElegooSlicer"],
  },
  {
    id: "anycubic-kobra-s1",
    display_name: "Anycubic Kobra S1",
    brand: "Anycubic",
    bed_width: 250,
    bed_depth: 250,
    bed_height: 250,
    supported_nozzle_sizes: ["0.4"],
    supported_slicers: ["AnycubicSlicerNext"],
  },
  {
    id: "anycubic-kobra-x",
    display_name: "Anycubic Kobra X",
    brand: "Anycubic",
    bed_width: 260,
    bed_depth: 260,
    bed_height: 260,
    supported_nozzle_sizes: ["0.25", "0.4", "0.6", "0.8"],
    supported_slicers: ["AnycubicSlicerNext"],
    device_profiles: [
      {
        device_profile_id: "AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.25",
        slicer_id: "AnycubicSlicerNext",
        nozzle_size: "0.25",
        source_profile_name: "Anycubic Kobra X 0.25 nozzle",
        revision: "sha256:ac-kx-025",
        supported: true,
      },
      {
        device_profile_id: "AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.4",
        slicer_id: "AnycubicSlicerNext",
        nozzle_size: "0.4",
        source_profile_name: "Anycubic Kobra X 0.4 nozzle",
        revision: "sha256:ac-kx-04",
        supported: true,
      },
      {
        device_profile_id: "AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.8",
        slicer_id: "AnycubicSlicerNext",
        nozzle_size: "0.8",
        source_profile_name: "Anycubic Kobra X 0.8 nozzle",
        revision: "sha256:ac-kx-08",
        supported: true,
      },
    ],
  },
];

const MULTI_SOURCE_ELEGOO_CC2: PrinterInfo = {
  id: "elegoo-cc2",
  display_name: "Elegoo Centauri Carbon 2",
  brand: "Elegoo",
  bed_width: 256,
  bed_depth: 256,
  bed_height: 256,
  supported_nozzle_sizes: ["0.2", "0.4", "0.6", "0.8"],
  supported_slicers: ["OrcaSlicer", "ElegooSlicer"],
  device_profiles: [
    {
      device_profile_id: "OrcaSlicer:elegoo:elegoo-centauri-carbon-2:0.4",
      slicer_id: "OrcaSlicer",
      nozzle_size: "0.4",
      source_profile_name: "Elegoo Centauri Carbon 2 0.4 nozzle",
      revision: "sha256:orca-cc2",
      supported: true,
    },
    {
      device_profile_id: "ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.2",
      slicer_id: "ElegooSlicer",
      nozzle_size: "0.2",
      source_profile_name: "Elegoo Centauri Carbon 2 0.2 nozzle",
      revision: "sha256:elegoo-cc2-02",
      supported: true,
    },
    {
      device_profile_id: "ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.4",
      slicer_id: "ElegooSlicer",
      nozzle_size: "0.4",
      source_profile_name: "Elegoo Centauri Carbon 2 0.4 nozzle",
      revision: "sha256:elegoo-cc2",
      supported: true,
    },
    {
      device_profile_id: "ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.8",
      slicer_id: "ElegooSlicer",
      nozzle_size: "0.8",
      source_profile_name: "Elegoo Centauri Carbon 2 0.8 nozzle",
      revision: "sha256:elegoo-cc2-08",
      supported: true,
    },
  ],
};

describe("settingsOptionIds", () => {
  it("normalizes legacy slicer ids", () => {
    expect(normalizeSlicerOptionId("orca_slicer")).toBe("OrcaSlicer");
    expect(normalizeSlicerOptionId("anycubic_slicer_next")).toBe("AnycubicSlicerNext");
    expect(normalizeSlicerOptionId("prusa_slicer")).toBe("PrusaSlicer");
    expect(normalizeSlicerOptionId("ultimaker-cura")).toBe("Cura");
    expect(normalizeSlicerOptionId("BambuStudio")).toBe("BambuStudio");
  });

  it("maps canonical slicer software ids to detected slicer ids", () => {
    expect(getDetectedSlicerIdForSoftware("AnycubicSlicerNext")).toBe("anycubic_slicer_next");
    expect(getDetectedSlicerIdForSoftware("anycubic_slicer")).toBe("anycubic_slicer_next");
    expect(getDetectedSlicerIdForSoftware("OrcaSlicer")).toBe("orca_slicer");
    expect(getDetectedSlicerIdForSoftware("prusa_slicer")).toBe("prusa_slicer");
    expect(getDetectedSlicerIdForSoftware("ultimaker cura")).toBe("cura");
  });

  it("returns readable slicer software display names", () => {
    expect(getSlicerSoftwareDisplayName("AnycubicSlicerNext")).toBe("Anycubic Slicer Next");
    expect(getSlicerSoftwareDisplayName("prusa_slicer")).toBe("PrusaSlicer");
    expect(getSlicerSoftwareDisplayName("ultimaker-cura")).toBe("Ultimaker Cura");
  });

  it("normalizes legacy printer ids", () => {
    expect(normalizePrinterOptionId("BAMBU_H2D")).toBe("bambu-h2d");
  });

  it("resolves invalid slicer selection to a canonical option", () => {
    expect(resolveSlicerOptionId("orca_slicer", SLICERS)).toBe("OrcaSlicer");
    expect(resolveSlicerOptionId("anycubic_slicer", SLICERS)).toBe("AnycubicSlicerNext");
  });

  it("resolves invalid printer selection to a compatible option", () => {
    expect(resolvePrinterOptionId("BAMBU_H2D", PRINTERS, "OrcaSlicer")).toBe("bambu-h2d");
  });

  it("filters printers by canonical slicer id", () => {
    expect(filterCompatiblePrinters(PRINTERS, "OrcaSlicer")).toHaveLength(1);
    expect(filterCompatiblePrinters(PRINTERS, "OrcaSlicer")[0]?.id).toBe("bambu-h2d");
    expect(filterCompatiblePrinters(PRINTERS, "AnycubicSlicerNext").map((printer) => printer.id)).toEqual([
      "anycubic-kobra-s1",
      "anycubic-kobra-x",
    ]);
  });

  it("resolves unsupported nozzle size to the first supported option", () => {
    expect(resolveNozzleSizeOption("0.2", PRINTERS[1])).toBe("0.4");
    expect(resolveNozzleSizeOption("0.2", PRINTERS[0])).toBe("0.2");
    expect(resolveNozzleSizeOption("0.8", PRINTERS[0], "BambuStudio")).toBe("0.4");
    expect(resolveNozzleSizeOption("", undefined)).toBe("0.4");
  });

  it("derives only Lumina-supported nozzle sizes from slicer-scoped registry device profiles", () => {
    expect(getPrinterNozzleSizeOptions(PRINTERS[0], "BambuStudio")).toEqual(["0.2", "0.4"]);
    expect(getPrinterNozzleSizeOptions(PRINTERS[0], "OrcaSlicer")).toEqual(["0.2"]);
  });

  it("keeps native 0.25 mm Anycubic profiles selectable without exposing 0.6 or 0.8", () => {
    expect(getPrinterNozzleSizeOptions(PRINTERS[3], "AnycubicSlicerNext")).toEqual([
      "0.25",
      "0.4",
    ]);
    expect(
      resolveDeviceProfileOptionId(
        "",
        PRINTERS[3],
        "AnycubicSlicerNext",
        "0.25",
      ),
    ).toBe("AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.25");
  });

  it("keeps slicer-scoped machine ids separate", () => {
    expect("BambuStudio:bbl:bambu-lab-h2d:0.4").not.toBe(
      "OrcaSlicer:bbl:bambu-lab-h2d:0.4",
    );
    expect(
      resolveDeviceProfileOptionId(
        "OrcaSlicer:bbl:bambu-lab-h2d:0.2",
        PRINTERS[0],
        "BambuStudio",
        "0.4",
      ),
    ).toBe("BambuStudio:bbl:bambu-lab-h2d:0.4");
  });

  it("clears stale device profile ids when the selected machine has no registry profile", () => {
    expect(
      resolveDeviceProfileOptionId(
        "BambuStudio:bbl:bambu-lab-h2d:0.4",
        PRINTERS[1],
        "ElegooSlicer",
        "0.4",
      ),
    ).toBe("");
  });

  it("keeps same-model Orca and Elegoo device profiles scoped by selected slicer", () => {
    expect(getPrinterNozzleSizeOptions(MULTI_SOURCE_ELEGOO_CC2, "ElegooSlicer")).toEqual([
      "0.2",
      "0.4",
    ]);
    expect(
      resolveDeviceProfileOptionId(
        "OrcaSlicer:elegoo:elegoo-centauri-carbon-2:0.4",
        MULTI_SOURCE_ELEGOO_CC2,
        "ElegooSlicer",
        "0.4",
      ),
    ).toBe("ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.4");
    expect(
      resolveDeviceProfileOptionId(
        "ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.4",
        MULTI_SOURCE_ELEGOO_CC2,
        "OrcaSlicer",
        "0.4",
      ),
    ).toBe("OrcaSlicer:elegoo:elegoo-centauri-carbon-2:0.4");
  });

  describe("isBambuFamilySlicer", () => {
    it("returns true for canonical Bambu-family slicers", () => {
      expect(isBambuFamilySlicer("BambuStudio")).toBe(true);
      expect(isBambuFamilySlicer("OrcaSlicer")).toBe(true);
      expect(isBambuFamilySlicer("AnycubicSlicerNext")).toBe(true);
    });

    it("returns true for legacy aliases", () => {
      expect(isBambuFamilySlicer("bambu")).toBe(true);
      expect(isBambuFamilySlicer("orca_slicer")).toBe(true);
      expect(isBambuFamilySlicer("snapmaker orca")).toBe(true);
    });

    it("returns false for non-Bambu-family and empty values", () => {
      expect(isBambuFamilySlicer("PrusaSlicer")).toBe(false);
      expect(isBambuFamilySlicer("Cura")).toBe(false);
      expect(isBambuFamilySlicer("")).toBe(false);
      expect(isBambuFamilySlicer("UnknownSlicer")).toBe(false);
    });
  });
});
