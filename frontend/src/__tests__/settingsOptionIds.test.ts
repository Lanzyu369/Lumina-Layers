import { describe, expect, it } from "vitest";

import {
  filterCompatiblePrinters,
  getDetectedSlicerIdForSoftware,
  getSlicerSoftwareDisplayName,
  normalizePrinterOptionId,
  normalizeSlicerOptionId,
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
    supported_nozzle_sizes: ["0.2", "0.4"],
    supported_slicers: ["BambuStudio", "OrcaSlicer"],
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
];

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
    expect(filterCompatiblePrinters(PRINTERS, "AnycubicSlicerNext")).toHaveLength(1);
    expect(filterCompatiblePrinters(PRINTERS, "AnycubicSlicerNext")[0]?.id).toBe("anycubic-kobra-s1");
  });

  it("resolves unsupported nozzle size to the first supported option", () => {
    expect(resolveNozzleSizeOption("0.2", PRINTERS[1])).toBe("0.4");
    expect(resolveNozzleSizeOption("0.2", PRINTERS[0])).toBe("0.2");
    expect(resolveNozzleSizeOption("", undefined)).toBe("0.4");
  });
});
