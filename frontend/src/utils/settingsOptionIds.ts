import type { PrinterInfo, SlicerOption } from "../api/types";

const LEGACY_SLICER_ID_MAP: Record<string, string> = {
  bambu: "BambuStudio",
  bambu_studio: "BambuStudio",
  "bambu studio": "BambuStudio",
  bambustudio: "BambuStudio",
  orca: "OrcaSlicer",
  orca_slicer: "OrcaSlicer",
  orcaslicer: "OrcaSlicer",
  snapmaker: "SnapmakerOrca",
  snapmaker_orca: "SnapmakerOrca",
  "snapmaker orca": "SnapmakerOrca",
  snapmakerorca: "SnapmakerOrca",
  elegoo: "ElegooSlicer",
  elegoo_slicer: "ElegooSlicer",
  "elegoo slicer": "ElegooSlicer",
  elegooslicer: "ElegooSlicer",
  anycubic: "AnycubicSlicerNext",
  anycubic_slicer: "AnycubicSlicerNext",
  anycubic_slicer_next: "AnycubicSlicerNext",
  "anycubic slicer": "AnycubicSlicerNext",
  "anycubic slicer next": "AnycubicSlicerNext",
  anycubicslicer: "AnycubicSlicerNext",
  anycubicslicernext: "AnycubicSlicerNext",
  prusa: "PrusaSlicer",
  prusa_slicer: "PrusaSlicer",
  prusaslicer: "PrusaSlicer",
  cura: "Cura",
  "ultimaker cura": "Cura",
  "ultimaker-cura": "Cura",
};

const DETECTED_SLICER_ID_MAP: Record<string, string> = {
  BambuStudio: "bambu_studio",
  OrcaSlicer: "orca_slicer",
  SnapmakerOrca: "snapmaker_orca",
  ElegooSlicer: "elegoo_slicer",
  AnycubicSlicerNext: "anycubic_slicer_next",
  PrusaSlicer: "prusa_slicer",
  Cura: "cura",
};

const SOFTWARE_ID_BY_DETECTED_SLICER_ID: Record<string, string> = Object.fromEntries(
  Object.entries(DETECTED_SLICER_ID_MAP).map(([softwareId, detectedId]) => [
    detectedId,
    softwareId,
  ]),
);

const SLICER_SOFTWARE_DISPLAY_NAME_MAP: Record<string, string> = {
  BambuStudio: "Bambu Studio",
  OrcaSlicer: "OrcaSlicer",
  SnapmakerOrca: "Snapmaker Orca",
  ElegooSlicer: "ElegooSlicer",
  AnycubicSlicerNext: "Anycubic Slicer Next",
  PrusaSlicer: "PrusaSlicer",
  Cura: "Ultimaker Cura",
};

const BAMBU_FAMILY_SLICER_IDS: ReadonlySet<string> = new Set([
  "BambuStudio",
  "OrcaSlicer",
  "SnapmakerOrca",
  "ElegooSlicer",
  "AnycubicSlicerNext",
]);

export function normalizeSlicerOptionId(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return LEGACY_SLICER_ID_MAP[trimmed.toLowerCase()] ?? trimmed;
}

export function getDetectedSlicerIdForSoftware(value: string): string | null {
  const canonicalId = normalizeSlicerOptionId(value);
  return DETECTED_SLICER_ID_MAP[canonicalId] ?? null;
}

export function getSoftwareIdForDetectedSlicerId(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  return SOFTWARE_ID_BY_DETECTED_SLICER_ID[trimmed] ?? null;
}

export function getSlicerSoftwareDisplayName(value: string): string {
  const canonicalId = normalizeSlicerOptionId(value);
  return SLICER_SOFTWARE_DISPLAY_NAME_MAP[canonicalId] ?? canonicalId;
}

export function isBambuFamilySlicer(value: string): boolean {
  const canonicalId = normalizeSlicerOptionId(value);
  return BAMBU_FAMILY_SLICER_IDS.has(canonicalId);
}

export function normalizePrinterOptionId(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return trimmed.toLowerCase().replace(/_/g, "-");
}

export function supportsSlicer(printer: PrinterInfo, slicerId: string): boolean {
  return (
    !printer.supported_slicers ||
    printer.supported_slicers.length === 0 ||
    printer.supported_slicers.includes(slicerId)
  );
}

export function filterCompatiblePrinters(
  printers: PrinterInfo[],
  slicerId: string,
): PrinterInfo[] {
  return printers.filter((printer) => supportsSlicer(printer, slicerId));
}

export function resolveSlicerOptionId(
  currentValue: string,
  slicers: SlicerOption[],
): string {
  const normalized = normalizeSlicerOptionId(currentValue);
  if (slicers.some((slicer) => slicer.id === normalized)) {
    return normalized;
  }
  return slicers[0]?.id ?? normalized;
}

export function resolvePrinterOptionId(
  currentValue: string,
  printers: PrinterInfo[],
  slicerId: string,
): string {
  const normalized = normalizePrinterOptionId(currentValue);
  const compatiblePrinters = filterCompatiblePrinters(printers, slicerId);

  if (compatiblePrinters.some((printer) => printer.id === normalized)) {
    return normalized;
  }
  return compatiblePrinters[0]?.id ?? printers[0]?.id ?? normalized;
}

export function resolveNozzleSizeOption(
  currentValue: string,
  printer: PrinterInfo | undefined,
): string {
  const normalized = currentValue.trim() || "0.4";
  const supported = printer?.supported_nozzle_sizes ?? ["0.2", "0.4"];

  if (supported.includes(normalized)) {
    return normalized;
  }
  return supported[0] ?? normalized;
}
