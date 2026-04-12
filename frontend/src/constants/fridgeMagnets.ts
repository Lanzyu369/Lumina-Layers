import type { FridgeMagnetItem, FridgeMagnetShape } from "../api/types";

export interface FridgeMagnetPresetDefinition {
  key: string;
  shape: FridgeMagnetShape;
  labelKey: string;
  diameter_mm: number | null;
  width_mm: number | null;
  height_mm: number | null;
  thickness_mm: number;
}

export const DEFAULT_ROUND_FRIDGE_MAGNET_PRESET_KEY = "round-d12x3";
export const DEFAULT_RECT_FRIDGE_MAGNET_PRESET_KEY = "rect-15x5x2";
export const FRIDGE_MAGNET_CUSTOM_PRESET_KEY = "custom";
export const FRIDGE_MAGNET_SPACER_CLEARANCE_MM = 0.4;
export const FRIDGE_MAGNET_LAYER_HEIGHT_MM = 0.08;

function clampFridgeMagnetValue(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export const FRIDGE_MAGNET_PRESETS: readonly FridgeMagnetPresetDefinition[] = [
  {
    key: "round-d6x2",
    shape: "round",
    labelKey: "fridge_magnet_preset_round_d6x2",
    diameter_mm: 6,
    width_mm: null,
    height_mm: null,
    thickness_mm: 2,
  },
  {
    key: "round-d12x3",
    shape: "round",
    labelKey: "fridge_magnet_preset_round_d12x3",
    diameter_mm: 12,
    width_mm: null,
    height_mm: null,
    thickness_mm: 3,
  },
  {
    key: "round-d8x3",
    shape: "round",
    labelKey: "fridge_magnet_preset_round_d8x3",
    diameter_mm: 8,
    width_mm: null,
    height_mm: null,
    thickness_mm: 3,
  },
  {
    key: "round-d10x3",
    shape: "round",
    labelKey: "fridge_magnet_preset_round_d10x3",
    diameter_mm: 10,
    width_mm: null,
    height_mm: null,
    thickness_mm: 3,
  },
  {
    key: "rect-10x5x1",
    shape: "rect",
    labelKey: "fridge_magnet_preset_rect_10x5x1",
    diameter_mm: null,
    width_mm: 10,
    height_mm: 5,
    thickness_mm: 1,
  },
  {
    key: "rect-15x5x2",
    shape: "rect",
    labelKey: "fridge_magnet_preset_rect_15x5x2",
    diameter_mm: null,
    width_mm: 15,
    height_mm: 5,
    thickness_mm: 2,
  },
  {
    key: "rect-20x10x2",
    shape: "rect",
    labelKey: "fridge_magnet_preset_rect_20x10x2",
    diameter_mm: null,
    width_mm: 20,
    height_mm: 10,
    thickness_mm: 2,
  },
];

export function getDefaultFridgeMagnetPresetKey(
  shape: FridgeMagnetShape,
): string {
  return shape === "rect"
    ? DEFAULT_RECT_FRIDGE_MAGNET_PRESET_KEY
    : DEFAULT_ROUND_FRIDGE_MAGNET_PRESET_KEY;
}

export function getFridgeMagnetPreset(
  presetKey: string,
): FridgeMagnetPresetDefinition | undefined {
  return FRIDGE_MAGNET_PRESETS.find((preset) => preset.key === presetKey);
}

export function getFridgeMagnetPresetsByShape(
  shape: FridgeMagnetShape,
): FridgeMagnetPresetDefinition[] {
  return FRIDGE_MAGNET_PRESETS.filter((preset) => preset.shape === shape);
}

export function createFridgeMagnetFromPreset(
  id: string,
  presetKey: string,
  center_x_mm: number,
  center_y_mm: number,
): FridgeMagnetItem {
  const preset =
    getFridgeMagnetPreset(presetKey) ??
    getFridgeMagnetPreset(getDefaultFridgeMagnetPresetKey("round"))!;

  return {
    id,
    shape: preset.shape,
    preset_key: preset.key,
    diameter_mm: preset.diameter_mm,
    width_mm: preset.width_mm,
    height_mm: preset.height_mm,
    thickness_mm: preset.thickness_mm,
    center_x_mm,
    center_y_mm,
  };
}

export function normalizeFridgeMagnetItem(
  item: FridgeMagnetItem,
): FridgeMagnetItem {
  const preset = getFridgeMagnetPreset(item.preset_key);
  const defaultPreset = getFridgeMagnetPreset(
    getDefaultFridgeMagnetPresetKey(item.shape),
  )!;
  const basePreset = preset?.shape === item.shape ? preset : undefined;
  const thicknessMm = clampFridgeMagnetValue(item.thickness_mm, 0.1, 3.1);

  if (item.shape === "round") {
    return {
      ...item,
      preset_key: basePreset?.shape === "round"
        ? basePreset.key
        : FRIDGE_MAGNET_CUSTOM_PRESET_KEY,
      diameter_mm: clampFridgeMagnetValue(
        item.diameter_mm ?? basePreset?.diameter_mm ?? defaultPreset.diameter_mm ?? 12,
        1,
        50,
      ),
      width_mm: null,
      height_mm: null,
      thickness_mm: thicknessMm,
    };
  }

  return {
    ...item,
    preset_key: basePreset?.shape === "rect"
      ? basePreset.key
      : FRIDGE_MAGNET_CUSTOM_PRESET_KEY,
    diameter_mm: null,
    width_mm: clampFridgeMagnetValue(
      item.width_mm ?? basePreset?.width_mm ?? defaultPreset.width_mm ?? 15,
      1,
      80,
    ),
    height_mm: clampFridgeMagnetValue(
      item.height_mm ?? basePreset?.height_mm ?? defaultPreset.height_mm ?? 5,
      1,
      80,
    ),
    thickness_mm: thicknessMm,
  };
}

export function normalizeFridgeMagnetItems(
  items: FridgeMagnetItem[],
): FridgeMagnetItem[] {
  return items.map(normalizeFridgeMagnetItem);
}

export function resolveFridgeMagnetSpacerThick(
  baseSpacerThick: number,
  enableFridgeMagnet: boolean,
  fridgeMagnets: FridgeMagnetItem[],
): number {
  const shellLayers = Math.max(
    1,
    Math.round(FRIDGE_MAGNET_SPACER_CLEARANCE_MM / FRIDGE_MAGNET_LAYER_HEIGHT_MM),
  );
  const requiredSpacerThick = enableFridgeMagnet
    ? fridgeMagnets.reduce(
        (maxThickness, item) =>
          Math.max(
            maxThickness,
            (shellLayers + Math.max(1, Math.round(item.thickness_mm / FRIDGE_MAGNET_LAYER_HEIGHT_MM)))
              * FRIDGE_MAGNET_LAYER_HEIGHT_MM,
          ),
        0,
      )
    : 0;

  return clampFridgeMagnetValue(
    Math.max(baseSpacerThick, requiredSpacerThick),
    0.2,
    3.5,
  );
}
