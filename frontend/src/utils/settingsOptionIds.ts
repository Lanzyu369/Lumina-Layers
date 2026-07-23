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
  flashforge: "FlashStudio",
  flash_studio: "FlashStudio",
  "flash studio": "FlashStudio",
  "flash studio desktop": "FlashStudio",
  flashstudio: "FlashStudio",
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
  FlashStudio: "flash_studio",
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
  FlashStudio: "Flash Studio Desktop",
  PrusaSlicer: "PrusaSlicer",
  Cura: "Ultimaker Cura",
};

const LAYER_CONFIG_RANGE_SLICER_IDS: ReadonlySet<string> = new Set([
  "BambuStudio",
  "OrcaSlicer",
  "SnapmakerOrca",
  "ElegooSlicer",
  "AnycubicSlicerNext",
  "FlashStudio",
]);

const DEFAULT_NOZZLE_SIZE = "0.4";
const DEFAULT_SUPPORTED_NOZZLE_SIZES = ["0.2", "0.25", DEFAULT_NOZZLE_SIZE] as const;

function supportedNozzleSizesForSlicer(_slicerId: string): readonly string[] {
  return DEFAULT_SUPPORTED_NOZZLE_SIZES;
}

function normalizeSupportedNozzleOptions(
  nozzleSizes: string[],
  slicerId: string,
): string[] {
  const supported = supportedNozzleSizesForSlicer(slicerId);
  const supportedSet = new Set(supported);
  const available = new Set(
    nozzleSizes
      .map((size) => size.trim())
      .filter((size) => supportedSet.has(size)),
  );
  return supported.filter((size) => available.has(size));
}

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

export function supportsLayerConfigRanges(value: string): boolean {
  const canonicalId = normalizeSlicerOptionId(value);
  return LAYER_CONFIG_RANGE_SLICER_IDS.has(canonicalId);
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

export function getPrinterNozzleSizeOptions(
  printer: PrinterInfo | undefined,
  slicerId: string,
): string[] {
  const registryNozzles =
    printer?.device_profiles
      ?.filter((profile) => profile.supported !== false && profile.slicer_id === slicerId)
      .map((profile) => profile.nozzle_size) ?? [];
  const uniqueRegistryNozzles = normalizeSupportedNozzleOptions(registryNozzles, slicerId);
  if (uniqueRegistryNozzles.length > 0) {
    return uniqueRegistryNozzles;
  }
  const declaredNozzles = normalizeSupportedNozzleOptions(
    printer?.supported_nozzle_sizes ?? [...supportedNozzleSizesForSlicer(slicerId)],
    slicerId,
  );
  return declaredNozzles.length > 0 ? declaredNozzles : [DEFAULT_NOZZLE_SIZE];
}

export function resolveDeviceProfileOptionId(
  currentValue: string,
  printer: PrinterInfo | undefined,
  slicerId: string,
  nozzleSize: string,
): string {
  const supportedNozzleSizes = new Set(supportedNozzleSizesForSlicer(slicerId));
  const profiles =
    printer?.device_profiles?.filter(
      (profile) =>
        profile.supported !== false &&
        profile.slicer_id === slicerId &&
        supportedNozzleSizes.has(profile.nozzle_size.trim()),
    ) ?? [];
  if (profiles.length === 0) {
    return "";
  }
  const exactCurrent = profiles.find(
    (profile) =>
      profile.device_profile_id === currentValue && profile.nozzle_size === nozzleSize,
  );
  if (exactCurrent) {
    return exactCurrent.device_profile_id;
  }
  const matchingNozzle = profiles.find((profile) => profile.nozzle_size === nozzleSize);
  return matchingNozzle?.device_profile_id ?? profiles[0].device_profile_id;
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
  slicerId = "",
): string {
  const normalized = currentValue.trim() || "0.4";
  const supported = slicerId
    ? getPrinterNozzleSizeOptions(printer, slicerId)
    : printer?.supported_nozzle_sizes ?? ["0.2", "0.4"];

  if (supported.includes(normalized)) {
    return normalized;
  }
  return supported.includes(DEFAULT_NOZZLE_SIZE)
    ? DEFAULT_NOZZLE_SIZE
    : supported[0] ?? DEFAULT_NOZZLE_SIZE;
}
