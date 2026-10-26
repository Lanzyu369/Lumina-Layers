import { StructureMode } from "../api/types";
import type { ConverterState, ConverterActions } from "./converter/types";

export type ConversionParameters = Pick<ConverterState,
  "source_version" | "structure_mode" | "base_spacer_thick" |
  "backing_infill_density_percent" | "selectedMaterialDirNames" |
  "materialBackingMaterialDirName" | "materialLayerCount" |
  "materialLayerHeightMm" | "materialDynamicLayerCountEnabled" |
  "largeFormatEnabled" | "tileWidthMm" | "tileHeightMm"

export interface ConversionPreset {
  id: string;
  name: string;
  parameters: ConversionParameters;
}
export interface ConversionPreferences {
  last: ConversionParameters | null;
  presets: ConversionPreset[];
  selectedPresetId?: string | null;
}

export type PresetNameError = "invalid-name" | "duplicate-name";
export type SavePresetResult = { id: string } | { error: PresetNameError };

export function validatePresetName(name: string, presets: ConversionPreset[], exceptId?: string): PresetNameError | null {
  const clean = name.trim();
  if (!clean || clean.length > 40) return "invalid-name";
  return presets.some(p => p.id !== exceptId && p.name === clean) ? "duplicate-name" : null;
}

export function captureConversionParameters(state: ConverterState): ConversionParameters {
  return {
    source_version: state.source_version,
    structure_mode: state.structure_mode,
    base_spacer_thick: state.base_spacer_thick,
    backing_infill_density_percent: state.backing_infill_density_percent,
    selectedMaterialDirNames: state.selectedMaterialDirNames,
    materialBackingMaterialDirName: state.materialBackingMaterialDirName,
    materialLayerCount: state.materialLayerCount,
    materialLayerHeightMm: state.materialLayerHeightMm,
    materialDynamicLayerCountEnabled: state.materialDynamicLayerCountEnabled,
    materialMinLayerCount: state.materialMinLayerCount,
    materialMaxLayerCount: state.materialMaxLayerCount,
    enable_coating: state.enable_coating,
    coating_height_mm: state.coating_height_mm,
    lut_names: state.lut_names,
    selectedNativeBrandKey: state.selectedNativeBrandKey,
    selectedNativeDbNames: state.selectedNativeDbNames,
    largeFormatEnabled: state.largeFormatEnabled,
    tileWidthMm: state.tileWidthMm,
    tileHeightMm: state.tileHeightMm,
  };
}

function normalizeParameters(value: unknown): ConversionParameters | null {
  if (!value || typeof value !== "object") return null;
  const p = value as Record<string, unknown>;
  const number = (key: string, min: number, max = Infinity) =>
    typeof p[key] === "number" && Number.isFinite(p[key]) && p[key] >= min && p[key] <= max;
  const strings = (key: string) => Array.isArray(p[key]) && p[key].every(v => typeof v === "string");
  if (!(p.source_version === "material" || p.source_version === "legacy" || p.source_version === "native") ||
      !(p.structure_mode === StructureMode.SINGLE_SIDED || p.structure_mode === StructureMode.DOUBLE_SIDED) ||
      !number("base_spacer_thick", 0.2, 10) || !number("backing_infill_density_percent", 5, 100) ||
      !number("materialLayerCount", 1, 20) || !number("materialLayerHeightMm", 0.04, 0.2) ||
      !number("materialMinLayerCount", 1, 20) || !number("materialMaxLayerCount", 1, 20) ||
      ![p.materialLayerCount, p.materialMinLayerCount, p.materialMaxLayerCount].every(Number.isInteger) ||
      Number(p.materialMinLayerCount) > Number(p.materialMaxLayerCount) ||
      typeof p.largeFormatEnabled !== "boolean" || !number("tileWidthMm", 50) || !number("tileHeightMm", 50) ||
      !strings("selectedMaterialDirNames") || !strings("lut_names") || !strings("selectedNativeDbNames") ||
      typeof p.selectedNativeBrandKey !== "string" ||
      !(p.materialBackingMaterialDirName === null || typeof p.materialBackingMaterialDirName === "string")) return null;
  // Build a whitelist; never restore sessions, resource URLs, images, or edits.
  const keys: Array<keyof ConversionParameters> = ["source_version", "structure_mode", "size_axis", "size_mm",
    "base_spacer_thick", "backing_infill_density_percent", "selectedMaterialDirNames",
    "materialBackingMaterialDirName", "materialLayerCount", "materialLayerHeightMm",
    "materialDynamicLayerCountEnabled", "materialMinLayerCount", "materialMaxLayerCount",
    "enable_coating", "coating_height_mm", "lut_names", "selectedNativeBrandKey", "selectedNativeDbNames",
}

export function normalizeConversionPreferences(value: unknown): ConversionPreferences {
  if (!value || typeof value !== "object") return { last: null, presets: [], selectedPresetId: null };
  const raw = value as Record<string, unknown>;
  const presets: ConversionPreset[] = [];
  if (Array.isArray(raw.presets)) for (const entry of raw.presets) {
    if (!entry || typeof entry !== "object") continue;
    const parameters = normalizeParameters(entry.parameters);
    if (typeof entry.id !== "string" || !entry.id || typeof entry.name !== "string" ||
        !entry.name.trim() || entry.name.trim().length > 40 || !parameters ||
        presets.some(p => p.id === entry.id || p.name === entry.name.trim())) continue;
    presets.push({ id: entry.id, name: entry.name.trim(), parameters });
  }
  return { last: normalizeParameters(raw.last), presets,
    selectedPresetId: presets.some(p => p.id === raw.selectedPresetId) ? raw.selectedPresetId as string : null };
}

export function applyConversionParameters(getState: () => ConverterState & ConverterActions, p: ConversionParameters): void {
  const state = getState();
  const different = (a: unknown, b: unknown) => JSON.stringify(a) !== JSON.stringify(b);
  if (getState().source_version !== p.source_version) state.setSourceVersion(p.source_version);
  if (p.source_version === "legacy" && different(getState().lut_names, p.lut_names)) state.setLegacyLutNames(p.lut_names);
  if (p.source_version === "native") {
    if (getState().selectedNativeBrandKey !== p.selectedNativeBrandKey) state.setNativeBrandKey(p.selectedNativeBrandKey);
    if (different(getState().selectedNativeDbNames, p.selectedNativeDbNames)) state.setNativeDbNames(p.selectedNativeDbNames);
  }
  if (different(getState().selectedMaterialDirNames, p.selectedMaterialDirNames)) state.setSelectedMaterialDirNames(p.selectedMaterialDirNames);
  if (getState().materialBackingMaterialDirName !== p.materialBackingMaterialDirName) state.setMaterialBackingMaterialDirName(p.materialBackingMaterialDirName);
  if (getState().materialLayerCount !== p.materialLayerCount) state.setMaterialLayerCount(p.materialLayerCount);
  if (getState().materialLayerHeightMm !== p.materialLayerHeightMm) state.setMaterialLayerHeightMm(p.materialLayerHeightMm);
  if (getState().materialMinLayerCount !== p.materialMinLayerCount) state.setMaterialMinLayerCount(p.materialMinLayerCount);
  if (getState().materialMaxLayerCount !== p.materialMaxLayerCount) state.setMaterialMaxLayerCount(p.materialMaxLayerCount);
  if (getState().materialDynamicLayerCountEnabled !== p.materialDynamicLayerCountEnabled) state.setMaterialDynamicLayerCountEnabled(p.materialDynamicLayerCountEnabled);
  if (getState().base_spacer_thick !== p.base_spacer_thick) state.setSpacerThick(p.base_spacer_thick);
  if (getState().backing_infill_density_percent !== p.backing_infill_density_percent) state.setBackingInfillDensityPercent(p.backing_infill_density_percent);
  if (getState().structure_mode !== p.structure_mode) state.setStructureMode(p.structure_mode);
  if (getState().largeFormatEnabled !== p.largeFormatEnabled) state.setLargeFormatEnabled(p.largeFormatEnabled);
  if (getState().tileWidthMm !== p.tileWidthMm) state.setTileWidthMm(p.tileWidthMm);
  if (getState().tileHeightMm !== p.tileHeightMm) state.setTileHeightMm(p.tileHeightMm);
  else state.setTargetWidthMm(p.size_mm);
}
