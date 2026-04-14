import { create } from 'zustand';
import type {
  ColorMode,
  ModelingMode,
  StructureMode,
  ColorReplacementItem,
  RecipeOverrideItem,
  BedSizeItem,
  PaletteEntry,
  AutoHeightMode,
  BatchResponse,
  LutInfoResponse,
  FridgeMagnetItem,
  PuzzleConnectorStyle,
  PuzzleSizingMode,
  PuzzleStyle,
  NativeBrandGroup,
  LutSupportedMode,
} from "../../api/types";
import {
  ColorMode as ColorModeEnum,
  ModelingMode as ModelingModeEnum,
  StructureMode as StructureModeEnum,
} from "../../api/types";
import {
  fetchLutList as apiFetchLutList,
  convertPreview as apiConvertPreview,
  convertGenerate as apiConvertGenerate,
  convertGenerateLargeFormat as apiConvertGenerateLargeFormat,
  convertGeneratePuzzle as apiConvertGeneratePuzzle,
  convertPuzzleLayoutPreview as apiConvertPuzzleLayoutPreview,
  fetchLayerImages as apiFetchLayerImages,
  fetchBedSizes as apiFetchBedSizes,
  uploadHeightmap as apiUploadHeightmap,
  fetchLutColors as apiFetchLutColors,
  cropImage as apiCropImage,
  convertBatch as apiConvertBatch,
  replaceColor as apiReplaceColor,
  colorHighlight as apiColorHighlight,
  detectRegion as apiDetectRegion,
  regionReplace as apiRegionReplace,
  applyRecipeOverride as apiApplyRecipeOverride,
  resetReplacements as apiResetReplacements,
  autoDetectColors as apiAutoDetectColors,
  cleanupSessionFiles as apiCleanupSessionFiles,
  beaconCleanupSessionFiles,
  uploadLut as apiUploadLut,
} from "../../api/converter";
import type { LutColorEntry, LutInfo } from "../../api/types";
import { fetchLutInfo as apiFetchLutInfo, fetchLutCatalog as apiFetchLutCatalog } from "../../api/lut";
import {
  computeAutoHeightMap,
  colorRemapToReplacementRegions,
} from "../../utils/colorUtils";
import { normalizeResourceUrl } from "../../utils/resourceUrl";
import {
  createFridgeMagnetFromPreset,
  getDefaultFridgeMagnetPresetKey,
  normalizeFridgeMagnetItem,
  resolveFridgeMagnetSpacerThick,
} from "../../constants/fridgeMagnets";
import { useSettingsStore } from "../settingsStore";
import { uploadImagePreview } from "../../api/system";

type LuminaWindow = Window & { __luminaGenerateStart?: number };

export const RAW_EXTENSIONS_CONVERTER = new Set([
  ".dng",
  ".cr2",
  ".cr3",
  ".nef",
  ".arw",
  ".orf",
  ".rw2",
  ".raf",
  ".pef",
  ".srw",
  ".raw",
]);

function isRawFileConverter(file: File): boolean {
  const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
  return RAW_EXTENSIONS_CONVERTER.has(ext);
}

// ========== Selection Mode Types ==========

export type SelectionMode =
  | "select-all"
  | "current"
  | "multi-select"
  | "region";

export type SourceVersion = "legacy" | "native";

export interface RegionData {
  regionId: string;
  colorHex: string;
  pixelCount: number;
  previewUrl: string;
  contours?: number[][][] | null;
  clickX?: number;
  clickY?: number;
}

// ========== Pending Replacement Types ==========

export interface PendingReplacement {
  sourceHex: string; // 原色 hex锛堜笉甯?#锛?
  targetHex: string; // 目标色 hex（不带 #）
  mode: SelectionMode; // 触发时的选择模式
  sourceColors?: string[]; // select-all 批量模式下的多个源色
  sourceRegions?: RegionData[]; // multi-select 模式下的多个连通区域
}

// ========== Helpers ==========

export function clampValue(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function buildLayerImagesSourceKey(
  state: Pick<
    ConverterState,
    "sessionId" | "previewGlbUrl" | "previewBaseImageUrl" | "previewImageUrl"
  >,
): string | null {
  if (!state.sessionId) {
    return null;
  }

  return [
    state.sessionId,
    state.previewGlbUrl ?? "",
    state.previewBaseImageUrl ?? state.previewImageUrl ?? "",
  ].join("|");
}

function getFallbackModelBounds(
  state: Pick<ConverterState, "modelBounds" | "target_width_mm" | "target_height_mm">,
): NonNullable<ConverterState["modelBounds"]> {
  if (state.modelBounds) {
    return state.modelBounds;
  }

  return {
    minX: -state.target_width_mm / 2,
    maxX: state.target_width_mm / 2,
    minY: -state.target_height_mm / 2,
    maxY: state.target_height_mm / 2,
    maxZ: 0,
  };
}

function getModelCenter(
  state: Pick<ConverterState, "modelBounds" | "target_width_mm" | "target_height_mm">,
): { x: number; y: number } {
  const bounds = getFallbackModelBounds(state);
  return {
    x: (bounds.minX + bounds.maxX) / 2,
    y: (bounds.minY + bounds.maxY) / 2,
  };
}

function getDefaultFridgeMagnetCount(
  state: Pick<ConverterState, "modelBounds" | "target_width_mm" | "target_height_mm">,
): number {
  const bounds = getFallbackModelBounds(state);
  const width = Math.max(bounds.maxX - bounds.minX, 0);
  const height = Math.max(bounds.maxY - bounds.minY, 0);
  const area = width * height;

  if (area <= 5000) {
    return 1;
  }
  if (area <= 15000) {
    return 2;
  }
  return 4;
}

const FRIDGE_MAGNET_LAYOUT_GAP_MM = 1;

function buildFridgeMagnetLayoutRatios(count: number): Array<[number, number]> {
  if (count <= 1) {
    return [[0.5, 0.5]];
  }
  if (count === 2) {
    return [[0.3, 0.5], [0.7, 0.5]];
  }
  if (count === 3) {
    return [[0.3, 0.35], [0.7, 0.35], [0.5, 0.72]];
  }
  if (count === 4) {
    return [[0.3, 0.3], [0.7, 0.3], [0.3, 0.7], [0.7, 0.7]];
  }

  const cols = Math.ceil(Math.sqrt(count));
  const rows = Math.ceil(count / cols);
  const marginX = 0.18;
  const marginY = 0.18;
  const usableWidth = 1 - marginX * 2;
  const usableHeight = 1 - marginY * 2;
  const ratios: Array<[number, number]> = [];

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      if (ratios.length >= count) {
        break;
      }
      const xRatio = cols === 1 ? 0.5 : marginX + (usableWidth * col) / (cols - 1);
      const yRatio = rows === 1 ? 0.5 : marginY + (usableHeight * row) / (rows - 1);
      ratios.push([xRatio, yRatio]);
    }
  }

  return ratios;
}

function buildSuggestedFridgeMagnetCenters(
  state: Pick<ConverterState, "modelBounds" | "target_width_mm" | "target_height_mm">,
  count: number,
): Array<{ x: number; y: number }> {
  const bounds = getFallbackModelBounds(state);
  const interpolate = (min: number, max: number, ratio: number) =>
    min + (max - min) * ratio;

  return buildFridgeMagnetLayoutRatios(Math.max(1, count)).map(([xRatio, yRatio]) => ({
    x: interpolate(bounds.minX, bounds.maxX, xRatio),
    y: interpolate(bounds.minY, bounds.maxY, yRatio),
  }));
}

function getFridgeMagnetLayoutSize(
  magnet: FridgeMagnetItem,
): { width: number; height: number } {
  if (magnet.shape === "round") {
    const diameter = magnet.diameter_mm ?? 0;
    return { width: diameter, height: diameter };
  }

  return {
    width: magnet.width_mm ?? 0,
    height: magnet.height_mm ?? 0,
  };
}

function clampFridgeMagnetLayoutCenter(
  center: { x: number; y: number },
  magnet: FridgeMagnetItem,
  bounds: NonNullable<ConverterState["modelBounds"]>,
): { x: number; y: number } {
  const { width, height } = getFridgeMagnetLayoutSize(magnet);
  const halfWidth = width / 2;
  const halfHeight = height / 2;
  const clampAxis = (value: number, min: number, max: number) =>
    min > max ? (min + max) / 2 : clampValue(value, min, max);

  return {
    x: clampAxis(center.x, bounds.minX + halfWidth, bounds.maxX - halfWidth),
    y: clampAxis(center.y, bounds.minY + halfHeight, bounds.maxY - halfHeight),
  };
}

function sanitizeFiniteNumber(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function sanitizeOptionalFiniteNumber(
  value: number | null | undefined,
  fallback: number | null,
): number | null {
  if (value === undefined) {
    return fallback;
  }
  if (value === null) {
    return null;
  }

  return Number.isFinite(value) ? value : fallback;
}

function layoutFridgeMagnetsByCenters(
  state: Pick<ConverterState, "modelBounds" | "target_width_mm" | "target_height_mm">,
  magnets: FridgeMagnetItem[],
  initialCenters?: Array<{ x: number; y: number }>,
): FridgeMagnetItem[] {
  if (magnets.length === 0) {
    return [];
  }

  const bounds = getFallbackModelBounds(state);
  const fallbackCenter = getModelCenter(state);
  const positioned = magnets.map((magnet, index) => ({
    ...magnet,
    ...clampFridgeMagnetLayoutCenter(
      initialCenters?.[index] ?? fallbackCenter,
      magnet,
      bounds,
    ),
  }));

  for (let iteration = 0; iteration < 48; iteration += 1) {
    let moved = false;

    for (let leftIndex = 0; leftIndex < positioned.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < positioned.length; rightIndex += 1) {
        const left = positioned[leftIndex];
        const right = positioned[rightIndex];
        const leftSize = getFridgeMagnetLayoutSize(left);
        const rightSize = getFridgeMagnetLayoutSize(right);
        const minSeparationX =
          leftSize.width / 2 + rightSize.width / 2 + FRIDGE_MAGNET_LAYOUT_GAP_MM;
        const minSeparationY =
          leftSize.height / 2 + rightSize.height / 2 + FRIDGE_MAGNET_LAYOUT_GAP_MM;
        const deltaX = right.center_x_mm - left.center_x_mm;
        const deltaY = right.center_y_mm - left.center_y_mm;
        const overlapX = minSeparationX - Math.abs(deltaX);
        const overlapY = minSeparationY - Math.abs(deltaY);

        if (overlapX <= 0 || overlapY <= 0) {
          continue;
        }

        const leftRoomX = left.center_x_mm - (bounds.minX + leftSize.width / 2);
        const rightRoomX = (bounds.maxX - rightSize.width / 2) - right.center_x_mm;
        const leftRoomY = left.center_y_mm - (bounds.minY + leftSize.height / 2);
        const rightRoomY = (bounds.maxY - rightSize.height / 2) - right.center_y_mm;
        const roomX = Math.max(0, leftRoomX) + Math.max(0, rightRoomX);
        const roomY = Math.max(0, leftRoomY) + Math.max(0, rightRoomY);
        const separateOnX = roomX >= overlapX && (roomX >= roomY || roomY < overlapY);
        const directionX = deltaX === 0 ? (leftIndex % 2 === 0 ? -1 : 1) : Math.sign(deltaX);
        const directionY = deltaY === 0 ? (leftIndex % 2 === 0 ? -1 : 1) : Math.sign(deltaY);

        if (separateOnX) {
          const shift = overlapX / 2 + 0.01;
          left.center_x_mm -= directionX * shift;
          right.center_x_mm += directionX * shift;
        } else {
          const shift = overlapY / 2 + 0.01;
          left.center_y_mm -= directionY * shift;
          right.center_y_mm += directionY * shift;
        }

        const clampedLeft = clampFridgeMagnetLayoutCenter(
          { x: left.center_x_mm, y: left.center_y_mm },
          left,
          bounds,
        );
        const clampedRight = clampFridgeMagnetLayoutCenter(
          { x: right.center_x_mm, y: right.center_y_mm },
          right,
          bounds,
        );
        left.center_x_mm = clampedLeft.x;
        left.center_y_mm = clampedLeft.y;
        right.center_x_mm = clampedRight.x;
        right.center_y_mm = clampedRight.y;
        moved = true;
      }
    }

    if (!moved) {
      break;
    }
  }

  return positioned;
}

function canonicalizeFridgeMagnets(
  state: Pick<
    ConverterState,
    | "modelBounds"
    | "target_width_mm"
    | "target_height_mm"
    | "base_spacer_thick"
    | "enable_fridge_magnet"
    | "fridge_magnets"
  >,
  magnets: FridgeMagnetItem[],
  options?: { resolveCollisions?: boolean },
): FridgeMagnetItem[] {
  if (magnets.length === 0) {
    return [];
  }

  const normalizedMagnets = magnets.map(normalizeFridgeMagnetItem);
  const fallbackCenter = getModelCenter(state);
  const bounds = getFallbackModelBounds(state);
  const sanitizedCenters = normalizedMagnets.map((magnet) => ({
    x: sanitizeFiniteNumber(magnet.center_x_mm, fallbackCenter.x),
    y: sanitizeFiniteNumber(magnet.center_y_mm, fallbackCenter.y),
  }));

  if (options?.resolveCollisions) {
    return layoutFridgeMagnetsByCenters(state, normalizedMagnets, sanitizedCenters);
  }

  return normalizedMagnets.map((magnet, index) => {
    const center = clampFridgeMagnetLayoutCenter(
      sanitizedCenters[index],
      magnet,
      bounds,
    );

    return {
      ...magnet,
      center_x_mm: center.x,
      center_y_mm: center.y,
    };
  });
}

function createNextFridgeMagnetId(fridgeMagnets: FridgeMagnetItem[]): string {
  const maxId = fridgeMagnets.reduce((max, item) => {
    const match = item.id.match(/^fridge-magnet-(\d+)$/);
    if (!match) {
      return max;
    }
    return Math.max(max, Number(match[1]));
  }, 0);

  return `fridge-magnet-${maxId + 1}`;
}

function buildDefaultFridgeMagnetLayout(
  state: Pick<ConverterState, "modelBounds" | "target_width_mm" | "target_height_mm">,
): FridgeMagnetItem[] {
  const magnets = buildSuggestedFridgeMagnetCenters(
    state,
    getDefaultFridgeMagnetCount(state),
  ).map(({ x, y }, index) =>
    createFridgeMagnetFromPreset(
      `fridge-magnet-${index + 1}`,
      getDefaultFridgeMagnetPresetKey("round"),
      x,
      y,
    ),
  );

  return layoutFridgeMagnetsByCenters(state, magnets, magnets.map((magnet) => ({
    x: magnet.center_x_mm,
    y: magnet.center_y_mm,
  })));
}

function autoLayoutFridgeMagnets(
  state: Pick<ConverterState, "modelBounds" | "target_width_mm" | "target_height_mm" | "fridge_magnets">,
): FridgeMagnetItem[] {
  const currentMagnets = state.fridge_magnets.map(normalizeFridgeMagnetItem);
  if (currentMagnets.length === 0) {
    return [];
  }

  const centers = buildSuggestedFridgeMagnetCenters(state, currentMagnets.length);
  return layoutFridgeMagnetsByCenters(state, currentMagnets, centers);
}

function buildFridgeMagnetState(
  state: Pick<
    ConverterState,
    | "modelBounds"
    | "target_width_mm"
    | "target_height_mm"
    | "base_spacer_thick"
    | "enable_fridge_magnet"
    | "fridge_magnets"
  >,
  overrides?: Partial<
    Pick<ConverterState, "enable_fridge_magnet" | "fridge_magnets" | "base_spacer_thick">
  >,
): Pick<
  ConverterState,
  "enable_fridge_magnet" | "fridge_magnets" | "base_spacer_thick" | "spacer_thick"
> {
  const baseSpacerThick = overrides?.base_spacer_thick ?? state.base_spacer_thick;
  const enableFridgeMagnet =
    overrides?.enable_fridge_magnet ?? state.enable_fridge_magnet;
  const fridgeMagnets = canonicalizeFridgeMagnets(
    state,
    overrides?.fridge_magnets ?? state.fridge_magnets,
  );

  return {
    enable_fridge_magnet: enableFridgeMagnet,
    fridge_magnets: fridgeMagnets,
    base_spacer_thick: baseSpacerThick,
    spacer_thick: resolveFridgeMagnetSpacerThick(
      baseSpacerThick,
      enableFridgeMagnet,
      fridgeMagnets,
    ),
  };
}

function getLastSelectedRegion(regions: RegionData[]): RegionData | null {
  return regions.length > 0 ? regions[regions.length - 1] : null;
}

function getSelectedRegionPreviewUrl(
  regions: RegionData[],
  fallbackPreviewUrl: string | null,
): string | null {
  const lastRegion = getLastSelectedRegion(regions);
  return lastRegion ? lastRegion.previewUrl : fallbackPreviewUrl;
}

function getPreviewBaseUrl(
  state: Pick<ConverterState, "previewBaseImageUrl" | "originalPreviewUrl" | "previewImageUrl">,
): string | null {
  return state.previewBaseImageUrl ?? state.originalPreviewUrl ?? state.previewImageUrl;
}

function normalizeStringArray(values: string[]): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const value of values) {
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    normalized.push(value);
  }
  return normalized;
}

function getNativeBrandGroupByKey(
  groups: NativeBrandGroup[],
  brandKey: string,
): NativeBrandGroup | null {
  return groups.find((group) => group.brand_key === brandKey) ?? null;
}

function filterNativeBrandGroups(groups: NativeBrandGroup[]): NativeBrandGroup[] {
  return groups.filter((group) => group.brand_key === "bambulab_pla");
}

function getNativeDbOptionNames(group: NativeBrandGroup | null): string[] {
  return group ? normalizeStringArray(group.db_options.map((option) => option.name)) : [];
}

function hasNativePredictiveModel(group: NativeBrandGroup | null): boolean {
  return Boolean(group?.package_name?.trim() || group?.model_name?.trim());
}

function buildNativeModelDefaults(group: NativeBrandGroup | null): Pick<
  ConverterState,
  "model_enable" | "model_only" | "model_threshold" | "model_margin"
> {
  return hasNativePredictiveModel(group)
    ? {
        model_enable: true,
        model_only: false,
        model_threshold: null,
        model_margin: null,
      }
    : {
        model_enable: false,
        model_only: false,
        model_threshold: null,
        model_margin: null,
      };
}

function buildNativeModelState(
  group: NativeBrandGroup | null,
  currentState?: Pick<
    ConverterState,
    "selectedNativeBrandKey" | "model_enable" | "model_only" | "model_threshold" | "model_margin"
  >,
): Pick<ConverterState, "model_enable" | "model_only" | "model_threshold" | "model_margin"> {
  if (!group) {
    return buildNativeModelDefaults(null);
  }
  if (
    currentState &&
    currentState.selectedNativeBrandKey === group.brand_key &&
    hasNativePredictiveModel(group)
  ) {
    return {
      model_enable: currentState.model_enable,
      model_only: currentState.model_only,
      model_threshold: currentState.model_threshold,
      model_margin: currentState.model_margin,
    };
  }
  return buildNativeModelDefaults(group);
}

function getSelectedNativeBrandGroup(
  state: Pick<ConverterState, "nativeBrandGroups" | "selectedNativeBrandKey">,
): NativeBrandGroup | null {
  if (state.selectedNativeBrandKey) {
    const byKey = getNativeBrandGroupByKey(state.nativeBrandGroups, state.selectedNativeBrandKey);
    if (byKey) {
      return byKey;
    }
  }
  return state.nativeBrandGroups[0] ?? null;
}

function getNativeDbNamesForGroup(group: NativeBrandGroup | null): string[] {
  if (!group) {
    return [];
  }

  const allowed = new Set(getNativeDbOptionNames(group));
  return normalizeStringArray(group.default_db_names.filter((name) => allowed.has(name)));
}

function getSupportedModeByPair(
  modes: LutSupportedMode[],
  colorLayers: number | null,
  layerHeightMm: number | null,
): LutSupportedMode | null {
  if (colorLayers == null || layerHeightMm == null) {
    return null;
  }
  return (
    modes.find(
      (mode) =>
        mode.color_layers === colorLayers &&
        mode.layer_height_mm === layerHeightMm,
    ) ?? null
  );
}

function resolvePreferredSupportedMode(
  modes: LutSupportedMode[],
): LutSupportedMode | null {
  if (modes.length === 0) return null;
  const exactFive = modes.find((mode) => mode.color_layers === 5);
  if (exactFive) return exactFive;
  let preferred = modes[0];
  for (const mode of modes) {
    if (mode.color_layers > preferred.color_layers) {
      preferred = mode;
    }
  }
  return preferred;
}

function resolveNativeSupportedModeForBrand(
  brand: NativeBrandGroup,
  colorLayers: number | null,
  layerHeightMm: number | null,
): LutSupportedMode | null {
  const supported_modes = brand.supported_modes ?? [];
  const exactMode = getSupportedModeByPair(supported_modes, colorLayers, layerHeightMm);
  if (exactMode) {
    return exactMode;
  }
  const preferredFive = supported_modes.find((mode) => mode.color_layers === 5);
  if (preferredFive) {
    return preferredFive;
  }
  if (layerHeightMm != null) {
    const matchingHeight = supported_modes.filter((mode) => mode.layer_height_mm === layerHeightMm);
    if (matchingHeight.length > 0) {
      if (colorLayers != null) {
        let preferred = matchingHeight[0];
        let smallestDistance = Math.abs(preferred.color_layers - colorLayers);
        for (const mode of matchingHeight.slice(1)) {
          const distance = Math.abs(mode.color_layers - colorLayers);
          if (distance < smallestDistance) {
            preferred = mode;
            smallestDistance = distance;
          }
        }
        return preferred;
      }
      return matchingHeight[0];
    }
  }
  return resolvePreferredSupportedMode(supported_modes);
}

function resolveNativeBrandSelection(
  state: Pick<
    ConverterState,
    | "nativeBrandGroups"
    | "selectedNativeBrandKey"
    | "selectedNativeDbNames"
    | "color_layers"
    | "layer_height_mm"
  >,
): {
  brand: NativeBrandGroup | null;
  db_names: string[];
  supported_mode: LutSupportedMode | null;
  supported_modes: LutSupportedMode[];
  predictive_model_available: boolean;
  isReady: boolean;
} {
  const brand = getSelectedNativeBrandGroup(state);
  if (!brand) {
    return {
      brand: null,
      db_names: [],
      supported_mode: null,
      supported_modes: [],
      predictive_model_available: false,
      isReady: false,
    };
  }

  const allowedNames = new Set(getNativeDbOptionNames(brand));
  const selectedDbNames = normalizeStringArray(
    state.selectedNativeDbNames.filter((name) => allowedNames.has(name)),
  );
  const db_names = state.selectedNativeDbNames.length === 0
    ? []
    : selectedDbNames.length > 0
      ? selectedDbNames
      : normalizeStringArray(brand.default_db_names.filter((name) => allowedNames.has(name)));
  const supported_modes = brand.supported_modes ?? [];
  const supported_mode = resolveNativeSupportedModeForBrand(
    brand,
    state.color_layers,
    state.layer_height_mm,
  );

  return {
    brand,
    db_names,
    supported_mode,
    supported_modes,
    predictive_model_available: hasNativePredictiveModel(brand),
    isReady: db_names.length > 0 && supported_mode != null,
  };
}

export function resolveConverterSourceSelection(
  state: Pick<
    ConverterState,
    | "source_version"
    | "lut_name"
    | "nativeBrandGroups"
    | "selectedNativeBrandKey"
    | "selectedNativeDbNames"
    | "color_layers"
    | "layer_height_mm"
  >,
): {
  source_kind: "legacy_single" | "native_bundle";
  isReady: boolean;
  lut_name: string;
  native: ReturnType<typeof resolveNativeBrandSelection>;
  color_layers: number | null;
  layer_height_mm: number | null;
} {
  if (state.source_version === "legacy") {
    return {
      source_kind: "legacy_single",
      isReady: state.lut_name.length > 0,
      lut_name: state.lut_name,
      native: {
        brand: null,
        db_names: [],
        supported_mode: null,
        supported_modes: [],
        predictive_model_available: false,
        isReady: false,
      },
      color_layers: null,
      layer_height_mm: null,
    };
  }

  const native = resolveNativeBrandSelection(state);
  return {
    source_kind: "native_bundle",
    isReady: native.isReady,
    lut_name: "",
    native,
    color_layers: native.supported_mode?.color_layers ?? null,
    layer_height_mm: native.supported_mode?.layer_height_mm ?? null,
  };
}

function buildLegacySourceParams(lutName: string) {
  return {
    source_kind: "legacy_single" as const,
    lut_name: lutName,
  };
}

function buildNativeSourceParams(
  selection: ReturnType<typeof resolveConverterSourceSelection>,
  modelState?: Pick<
    ConverterState,
    "model_enable" | "model_only" | "model_threshold" | "model_margin"
  >,
) {
  if (
    selection.source_kind !== "native_bundle" ||
    !selection.native.brand
  ) {
    return null;
  }
  const supportedMode = selection.native.supported_mode;

  return {
    source_kind: "native_bundle" as const,
    material_type: selection.native.brand.material_type,
    vendor: selection.native.brand.vendor,
    db_names: selection.native.db_names,
    color_layers: supportedMode?.color_layers ?? undefined,
    layer_height_mm: supportedMode?.layer_height_mm ?? undefined,
    ...(selection.native.predictive_model_available
      ? {
          model_enable: modelState?.model_enable ?? false,
          model_only: modelState?.model_only ?? false,
          model_threshold: modelState?.model_threshold ?? undefined,
          model_margin: modelState?.model_margin ?? undefined,
        }
      : {}),
  };
}

function extractFileIdFromApiUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  const match = url.match(/\/api\/files\/([^/?#]+)/);
  return match ? match[1] : null;
}

function collectKeepFileIds(
  urls: Array<string | null | undefined>,
): string[] {
  const keepIds = new Set<string>();
  for (const url of urls) {
    const fileId = extractFileIdFromApiUrl(url);
    if (fileId) {
      keepIds.add(fileId);
    }
  }
  return Array.from(keepIds);
}

const VALID_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/svg+xml",
  "image/webp",
  "image/heic",
  "image/heif",
  "image/x-adobe-dng",
  "image/x-canon-cr2",
  "image/x-canon-cr3",
  "image/x-nikon-nef",
  "image/x-sony-arw",
  "image/x-olympus-orf",
  "image/x-panasonic-rw2",
  "image/x-fuji-raf",
  "image/x-pentax-pef",
  "image/x-samsung-srw",
  "image/x-raw",
]);

export const ACCEPT_IMAGE_FORMATS =
  Array.from(VALID_IMAGE_TYPES).join(",") +
  "," +
  Array.from(RAW_EXTENSIONS_CONVERTER).join(",") +
  ",.lumina.json";

export function isValidImageType(mimeType: string, fileName?: string): boolean {
  if (VALID_IMAGE_TYPES.has(mimeType)) return true;
  if (fileName) {
    const ext = fileName.toLowerCase().slice(fileName.lastIndexOf("."));
    if (RAW_EXTENSIONS_CONVERTER.has(ext)) return true;
  }
  return false;
}

// ========== State Interface ==========

export interface ConverterState {
  // 图片
  imageFile: File | null;
  imagePreviewUrl: string | null;
  aspectRatio: number | null;

  // 会话（预览后由后端返回）
  sessionId: string | null;

  // 基础参数
  source_version: SourceVersion;
  lut_name: string;
  nativeBrandGroups: NativeBrandGroup[];
  nativeBrandGroupsLoading: boolean;
  selectedNativeBrandKey: string;
  selectedNativeDbNames: string[];
  target_width_mm: number;
  target_height_mm: number;
  spacer_thick: number;
  structure_mode: StructureMode;
  color_mode: ColorMode;
  modeling_mode: ModelingMode;
  color_layers: number | null;
  layer_height_mm: number | null;
  model_enable: boolean;
  model_only: boolean;
  model_threshold: number | null;
  model_margin: number | null;
  selectedLutInfo: LutInfoResponse | null;

  // 高级设置
  auto_bg: boolean;
  bg_tol: number;
  quantize_colors: number;
  enable_cleanup: boolean;
  hue_enable: boolean;
  chroma_gate: number;
  separate_backing: boolean;

  // 挂件环
  add_loop: boolean;
  loop_width: number;
  loop_length: number;
  loop_hole: number;
  loop_angle: number; // -180 到 180 度，默认 0
  loop_offset_x: number; // -20 到 20 mm，默认 0
  loop_offset_y: number; // -20 到 20 mm，默认 0
  loop_position_preset: string; // 默认 "top-center"
  enable_fridge_magnet: boolean;
  fridge_magnets: FridgeMagnetItem[];
  selectedFridgeMagnetId: string | null;
  base_spacer_thick: number;

  // 浮雕
  enable_relief: boolean;
  color_height_map: Record<string, number>;
  heightmap_max_height: number;

  // 描边
  enable_outline: boolean;
  outline_width: number;

  // 掐丝珐琅
  enable_cloisonne: boolean;
  wire_width_mm: number;
  wire_height_mm: number;

  // 涂层
  enable_coating: boolean;
  coating_height_mm: number;

  // 大画幅
  largeFormatEnabled: boolean;
  tileWidthMm: number;
  tileHeightMm: number;
  puzzleEnabled: boolean;
  puzzleStyle: PuzzleStyle;
  puzzleSizingMode: PuzzleSizingMode;
  pieceWidthMm: number;
  pieceHeightMm: number;
  puzzleRows: number;
  puzzleCols: number;
  targetPieceCount: number;
  connectorStyle: PuzzleConnectorStyle;
  labelsEnabled: boolean;
  engraveBackLabels: boolean;
  irregularityStrength: number;
  minNeckWidthMm: number;
  puzzleOverlayUrl: string | null;
  puzzleWarnings: string[];
  puzzleResolvedRows: number | null;
  puzzleResolvedCols: number | null;
  puzzleResolvedPieceCount: number | null;
  puzzleDerivedPieceWidthMm: number | null;
  puzzleDerivedPieceHeightMm: number | null;

  // 颜色替换
  replacement_regions: ColorReplacementItem[];
  recipe_overrides: RecipeOverrideItem[];
  free_color_set: Set<string>;

  // 调色板与选择
  selectedColor: string | null;
  palette: PaletteEntry[];

  // 颜色替换映射（纯前端）
  colorRemapMap: Record<string, string>;
  remapHistory: Record<string, string>[];

  // 颜色轮廓数据（后端 OpenCV 提取，用于 3D 高亮）
  colorContours: Record<string, number[][][]>;
  // 浮雕联动
  autoHeightMode: AutoHeightMode;
  heightmapFile: File | null;
  heightmapThumbnailUrl: string | null;

  // 3D 预览
  previewGlbUrl: string | null;
  lutMatchMode: string | null;
  lutMatchInfo: Record<string, unknown> | null;

  // 预览时的原始尺寸（用于实时缩放比例计算）
  preview_width_mm: number | null; // 预览时的原始宽度
  preview_height_mm: number | null; // 预览时的原始高度
  preview_spacer_thick: number | null; // 预览时的原始厚度
  previewPixelWidth: number | null; // 预览图像像素宽度（用于 3D→像素坐标转换）
  previewPixelHeight: number | null; // 预览图像像素高度（用于 3D→像素坐标转换）
  previewWarnings: string[];
  largeFormatWarnings: string[];

  // 模型边界（供 KeychainRing3D 定位）
  modelBounds: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
    maxZ: number;
  } | null;

  // 裁剪
  enableCrop: boolean;
  cropModalOpen: boolean;
  isCropping: boolean;

  // 自动检测颜色
  autoDetectColorsLoading: boolean;

  // UI 状态
  isLoading: boolean;
  isGenerating: boolean;
  error: string | null;
  previewImageUrl: string | null;
  modelUrl: string | null;

  // LUT 列表
  lutList: string[];
  lutListLoading: boolean;
  lutListFull: LutInfo[];

  // LUT 全部颜色
  lutColors: LutColorEntry[];
  lutColorsLoading: boolean;
  lutColorsLutName: string;

  // 热床尺寸
  bed_label: string;
  bedSizes: BedSizeItem[];
  bedSizesLoading: boolean;

  // 批量模式
  batchMode: boolean;
  batchFiles: File[];
  batchLoading: boolean;
  batchResult: BatchResponse | null;

  // 颜色替换预览
  replacePreviewLoading: boolean;
  originalPreviewUrl: string | null;
  previewBaseImageUrl: string | null;

  // 切片集成：3MF 路径
  threemfDiskPath: string | null;
  downloadUrl: string | null;

  // 分层预览
  layerImages: { layer_index: number; name: string; url: string }[];
  layerImagesLoading: boolean;
  layerImagesOpen: boolean;
  layerImagesSourceKey: string | null;

  // 颜色选择模式
  selectionMode: SelectionMode;
  selectedColors: Set<string>;
  regionData: RegionData | null;
  selectedRegions: RegionData[];

  // 待确认颜色替换
  pendingReplacement: PendingReplacement | null;

  // 区域替换计数（current 模式不走 colorRemapMap，需要独立计数以启用清除按钮）
  regionReplacementCount: number;

  // 当前图片是否已手动点击过预览按钮（自动预览的前置条件）
  hasManualPreview: boolean;
}

// ========== Actions Interface ==========

export interface ConverterActions {
  // 图片
  setImageFile: (file: File | null) => void;

  // 参数 setter
  setLutName: (name: string) => void;
  setTargetWidthMm: (width: number) => void;
  setTargetHeightMm: (height: number) => void;
  setSpacerThick: (thick: number) => void;
  setStructureMode: (mode: StructureMode) => void;
  setColorMode: (mode: ColorMode) => void;
  setModelingMode: (mode: ModelingMode) => void;
  setColorLayers: (layers: number | null) => void;
  setLayerHeightMm: (height: number | null) => void;
  setModelEnable: (enabled: boolean) => void;
  setModelOnly: (enabled: boolean) => void;
  setModelThreshold: (value: number | null) => void;
  setModelMargin: (value: number | null) => void;
  setAutoBg: (enabled: boolean) => void;
  setBgTol: (tol: number) => void;
  setQuantizeColors: (colors: number) => void;
  setEnableCleanup: (enabled: boolean) => void;
  setHueEnable: (enabled: boolean) => void;
  setChromaGate: (gate: number) => void;
  setSeparateBacking: (enabled: boolean) => void;
  setAddLoop: (enabled: boolean) => void;
  setLoopWidth: (width: number) => void;
  setLoopLength: (length: number) => void;
  setLoopHole: (hole: number) => void;
  setLoopAngle: (angle: number) => void;
  setLoopOffsetX: (x: number) => void;
  setLoopOffsetY: (y: number) => void;
  setLoopPositionPreset: (preset: string) => void;
  setEnableFridgeMagnet: (enabled: boolean) => void;
  resetFridgeMagnetLayout: () => void;
  addFridgeMagnet: () => void;
  removeFridgeMagnet: (id: string) => void;
  updateFridgeMagnet: (
    id: string,
    updates: Partial<Omit<FridgeMagnetItem, "id">>,
  ) => void;
  updateFridgeMagnetCenter: (
    id: string,
    centerX: number,
    centerY: number,
  ) => void;
  selectFridgeMagnet: (id: string | null) => void;
  clearSelectedFridgeMagnet: () => void;
  setEnableRelief: (enabled: boolean) => void;
  setColorHeightMap: (map: Record<string, number>) => void;
  setHeightmapMaxHeight: (height: number) => void;
  setEnableOutline: (enabled: boolean) => void;
  setOutlineWidth: (width: number) => void;
  setEnableCloisonne: (enabled: boolean) => void;
  setWireWidthMm: (width: number) => void;
  setWireHeightMm: (height: number) => void;
  setEnableCoating: (enabled: boolean) => void;
  setCoatingHeightMm: (height: number) => void;

  // 大画幅
  setLargeFormatEnabled: (enabled: boolean) => void;
  setTileWidthMm: (width: number) => void;
  setTileHeightMm: (height: number) => void;
  setPuzzleEnabled: (enabled: boolean) => void;
  setPuzzleStyle: (style: PuzzleStyle) => void;
  setPuzzleSizingMode: (mode: PuzzleSizingMode) => void;
  setPieceWidthMm: (width: number) => void;
  setPieceHeightMm: (height: number) => void;
  setPuzzleRows: (rows: number) => void;
  setPuzzleCols: (cols: number) => void;
  setTargetPieceCount: (count: number) => void;
  setConnectorStyle: (style: PuzzleConnectorStyle) => void;
  setLabelsEnabled: (enabled: boolean) => void;
  setEngraveBackLabels: (enabled: boolean) => void;
  setIrregularityStrength: (strength: number) => void;
  setMinNeckWidthMm: (width: number) => void;
  submitPuzzleLayoutPreview: () => Promise<boolean>;
  clearPuzzleLayoutPreview: () => void;

  // 热床尺寸
  setBedLabel: (label: string) => void;
  fetchBedSizes: () => Promise<void>;

  // 调色板与选择
  setSelectedColor: (hex: string | null) => void;
  setPalette: (entries: PaletteEntry[]) => void;

  // 颜色选择模式
  setSelectionMode: (mode: SelectionMode) => void;
  toggleColorInSelection: (hex: string) => void;
  applyBatchColorRemap: (newHex: string) => Promise<void>;
  detectRegion: (x: number, y: number) => Promise<void>;
  detectAndAccumulateRegion: (x: number, y: number) => Promise<void>;
  removeRegionFromSelection: (regionId: string) => void;
  applyRegionReplace: (newHex: string) => Promise<void>;
  applyCustomRecipeOverride: (regionIds: string[], recipe: number[], layerOrder?: string) => Promise<void>;
  upsertRecipeOverrides: (
    regionIds: string[],
    recipe: number[],
    layerOrder: string,
  ) => void;
  clearRecipeOverrides: (regionIds?: string[]) => void;

  // 待确认颜色替换
  setPendingReplacement: (pending: PendingReplacement | null) => void;
  confirmReplacement: () => Promise<void>;

  // 颜色替换（纯前端）
  applyColorRemap: (origHex: string, newHex: string) => void;
  undoColorRemap: () => void;
  clearAllRemaps: () => void;

  // 浮雕高度
  updateColorHeight: (hex: string, heightMm: number) => void;
  applyAutoHeight: (mode: "darker-higher" | "lighter-higher") => void;
  setAutoHeightMode: (mode: AutoHeightMode) => void;

  // 高度图
  setHeightmapFile: (file: File | null) => void;
  uploadHeightmap: () => Promise<void>;

  // GLB 预览
  setPreviewGlbUrl: (url: string | null) => void;

  // 模型边界
  setModelBounds: (bounds: ConverterState["modelBounds"]) => void;

  // API 操作
  uploadLut: (file: File) => Promise<void>;
  fetchLutList: () => Promise<void>;
  fetchLutCatalog: () => Promise<void>;
  fetchLutColors: (lutName: string) => Promise<void>;
  setSourceVersion: (version: SourceVersion) => void;
  setNativeBrandKey: (brandKey: string) => void;
  setNativeSupportedMode: (mode: { color_layers: number; layer_height_mm: number }) => void;
  setNativeDbNames: (dbNames: string[]) => void;
  submitPreview: () => Promise<void>;
  submitGenerate: () => Promise<string | null>;

  // 裁剪
  setEnableCrop: (enabled: boolean) => void;
  setCropModalOpen: (open: boolean) => void;
  submitCrop: (
    x: number,
    y: number,
    width: number,
    height: number,
  ) => Promise<void>;

  // 自动检测颜色
  autoDetectColors: () => Promise<void>;

  // 批量模式
  addBatchFiles: (files: File[]) => void;
  removeBatchFile: (index: number) => void;
  clearBatchFiles: () => void;
  submitBatch: () => Promise<void>;

  // 统一文件选择（auto-batch-multiselect）
  handleFilesSelect: (files: File[]) => void;

  // 颜色替换预览
  submitReplacePreview: () => Promise<void>;
  submitSingleReplace: (origHex: string, newHex: string) => Promise<void>;
  cleanupAfterDownload: () => void;

  // 完整流水线（preview → generate）
  submitFullPipeline: () => Promise<string | null>;

  // 自由色
  toggleFreeColor: (hex: string) => void;
  clearFreeColors: () => void;

  // UI 状态
  setError: (error: string | null) => void;
  clearError: () => void;

  // 分层预览
  fetchLayerImages: (previewSourceKey?: string | null) => Promise<void>;
  resetLayerImages: () => void;
  setLayerImagesOpen: (open: boolean) => void;

  // 配方导入
  importRecipeState: (partial: Partial<ConverterState>, imageFile: File, heightmapFile?: File | null) => void;
}

// ========== localStorage Helpers ==========

const EMPTY_LUT_MATCH_STATE = {
  lutMatchMode: null,
  lutMatchInfo: null,
} as const;

const DEFAULT_LAYER_IMAGES_STATE = {
  layerImages: [] as { layer_index: number; name: string; url: string }[],
  layerImagesLoading: false,
  layerImagesOpen: false,
  layerImagesSourceKey: null as string | null,
};

const DEFAULT_PUZZLE_PREVIEW_STATE = {
  puzzleOverlayUrl: null,
  puzzleWarnings: [] as string[],
  puzzleResolvedRows: null,
  puzzleResolvedCols: null,
  puzzleResolvedPieceCount: null,
  puzzleDerivedPieceWidthMm: null,
  puzzleDerivedPieceHeightMm: null,
};

const DEFAULT_PUZZLE_LAYOUT_SEED = 0;

function buildPreviewSessionResetState(): Partial<ConverterState> {
  return {
    sessionId: null,
    previewImageUrl: null,
    originalPreviewUrl: null,
    previewBaseImageUrl: null,
    previewGlbUrl: null,
    modelUrl: null,
    threemfDiskPath: null,
    downloadUrl: null,
    palette: [],
    colorContours: {},
    colorRemapMap: {},
    remapHistory: [],
    replacement_regions: [],
    recipe_overrides: [],
    free_color_set: new Set<string>(),
    regionReplacementCount: 0,
    selectedColor: null,
    selectedColors: new Set<string>(),
    regionData: null,
    selectedRegions: [],
    pendingReplacement: null,
    preview_width_mm: null,
    preview_height_mm: null,
    preview_spacer_thick: null,
    previewPixelWidth: null,
    previewPixelHeight: null,
    modelBounds: null,
    hasManualPreview: false,
    ...EMPTY_LUT_MATCH_STATE,
    ...DEFAULT_LAYER_IMAGES_STATE,
    ...DEFAULT_PUZZLE_PREVIEW_STATE,
  };
}

function loadEnableCrop(): boolean {
  try {
    const stored = localStorage.getItem("lumina_enableCrop");
    if (stored === null) return true;
    return stored === "true";
  } catch {
    return true;
  }
}

function loadLutName(): string {
  try {
    return localStorage.getItem("lumina_lastLut") ?? "";
  } catch {
    return "";
  }
}

// ========== Default State ==========

export const DEFAULT_STATE: ConverterState = {
  imageFile: null,
  imagePreviewUrl: null,
  aspectRatio: null,
  sessionId: null,
  source_version: "legacy",
  lut_name: loadLutName(),
  nativeBrandGroups: [],
  nativeBrandGroupsLoading: false,
  selectedNativeBrandKey: "",
  selectedNativeDbNames: [],
  target_width_mm: 60,
  target_height_mm: 60,
  spacer_thick: 1.2,
  structure_mode: StructureModeEnum.DOUBLE_SIDED,
  color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
  modeling_mode: ModelingModeEnum.HIGH_FIDELITY,
  color_layers: null,
  layer_height_mm: null,
  model_enable: false,
  model_only: false,
  model_threshold: null,
  model_margin: null,
  selectedLutInfo: null,
  auto_bg: false,
  bg_tol: 40,
  quantize_colors: 48,
  enable_cleanup: true,
  hue_enable: false,
  chroma_gate: 15,
  separate_backing: false,
  add_loop: false,
  loop_width: 4.0,
  loop_length: 8.0,
  loop_hole: 2.5,
  loop_angle: 0,
  loop_offset_x: 0,
  loop_offset_y: 0,
  loop_position_preset: "top-center",
  enable_fridge_magnet: false,
  fridge_magnets: [],
  selectedFridgeMagnetId: null,
  base_spacer_thick: 1.2,
  enable_relief: false,
  color_height_map: {},
  heightmap_max_height: 3.0,
  enable_outline: false,
  outline_width: 2.0,
  enable_cloisonne: false,
  wire_width_mm: 0.4,
  wire_height_mm: 0.4,
  enable_coating: false,
  coating_height_mm: 0.08,
  largeFormatEnabled: false,
  tileWidthMm: 250,
  tileHeightMm: 250,
  puzzleEnabled: false,
  puzzleStyle: "regular" as PuzzleStyle,
  puzzleSizingMode: "piece_size" as PuzzleSizingMode,
  pieceWidthMm: 20,
  pieceHeightMm: 20,
  puzzleRows: 3,
  puzzleCols: 3,
  targetPieceCount: 12,
  connectorStyle: "classic" as PuzzleConnectorStyle,
  labelsEnabled: false,
  engraveBackLabels: false,
  irregularityStrength: 0.35,
  minNeckWidthMm: 1.2,
  ...DEFAULT_PUZZLE_PREVIEW_STATE,
  replacement_regions: [],
  recipe_overrides: [],
  free_color_set: new Set(),
  selectedColor: null,
  palette: [],
  colorRemapMap: {},
  remapHistory: [],
  colorContours: {},
  autoHeightMode: "darker-higher" as AutoHeightMode,
  heightmapFile: null,
  heightmapThumbnailUrl: null,
  previewGlbUrl: null,
  lutMatchMode: null,
  lutMatchInfo: null,
  preview_width_mm: null,
  preview_height_mm: null,
  preview_spacer_thick: null,
  previewPixelWidth: null,
  previewPixelHeight: null,
  previewWarnings: [],
  largeFormatWarnings: [],
  modelBounds: null,
  enableCrop: loadEnableCrop(),
  cropModalOpen: false,
  isCropping: false,
  autoDetectColorsLoading: false,
  isLoading: false,
  isGenerating: false,
  error: null,
  previewImageUrl: null,
  modelUrl: null,
  lutList: [],
  lutListLoading: false,
  lutListFull: [],
  lutColors: [],
  lutColorsLoading: false,
  lutColorsLutName: "",
  bed_label: "256脳256 mm",
  bedSizes: [],
  bedSizesLoading: false,
  batchMode: false,
  batchFiles: [],
  batchLoading: false,
  batchResult: null,
  replacePreviewLoading: false,
  originalPreviewUrl: null,
  previewBaseImageUrl: null,
  threemfDiskPath: null,
  downloadUrl: null,
  ...DEFAULT_LAYER_IMAGES_STATE,
  selectionMode: "current" as SelectionMode,
  selectedColors: new Set<string>(),
  regionData: null,
  selectedRegions: [],
  pendingReplacement: null,
  regionReplacementCount: 0,
  hasManualPreview: false,
};

// ========== Preview AbortController ==========

let _previewAbortController: AbortController | null = null;

// ========== Client-side timing log (writes to server log) ==========
let _generateStartTime: number | null = null;
const _GENERATE_TIMER_LABEL = "[LUMINA] generate";
let _generateTimerActive = false;

function _startGenerateTimer(): void {
  if (_generateTimerActive) {
    try {
      console.timeEnd(_GENERATE_TIMER_LABEL);
    } catch {
      // Ignore missing timer in non-browser/test environments.
    }
  }
  console.time(_GENERATE_TIMER_LABEL);
  _generateTimerActive = true;
}

function _logGenerateTimer(message: string): void {
  if (!_generateTimerActive) return;
  try {
    console.timeLog(_GENERATE_TIMER_LABEL, message);
  } catch {
    // Ignore when console.timeLog is unavailable.
  }
}

function _endGenerateTimer(): void {
  if (!_generateTimerActive) return;
  try {
    console.timeEnd(_GENERATE_TIMER_LABEL);
  } catch {
    // Ignore missing timer in non-browser/test environments.
  }
  _generateTimerActive = false;
}

function _clientLog(label: string) {
  const elapsed = _generateStartTime != null ? performance.now() - _generateStartTime : null;
  const msg = elapsed != null ? `${label} (+${elapsed.toFixed(0)}ms)` : label;
  console.log(`[LUMINA] ${msg}`);
  fetch('/api/client-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label, elapsed_ms: elapsed }),
  }).catch(() => {});
}

function buildPuzzlePreviewParams(
  state: Pick<
    ConverterState,
    | "target_height_mm"
    | "puzzleStyle"
    | "puzzleSizingMode"
    | "pieceWidthMm"
    | "pieceHeightMm"
    | "puzzleRows"
    | "puzzleCols"
    | "targetPieceCount"
    | "connectorStyle"
    | "labelsEnabled"
    | "engraveBackLabels"
    | "irregularityStrength"
    | "minNeckWidthMm"
  >,
) {
  return {
    target_height_mm: state.target_height_mm,
    puzzle_style: state.puzzleStyle,
    sizing_mode: state.puzzleSizingMode,
    piece_width_mm: state.pieceWidthMm,
    piece_height_mm: state.pieceHeightMm,
    rows: state.puzzleRows,
    cols: state.puzzleCols,
    target_piece_count: state.targetPieceCount,
    seed: DEFAULT_PUZZLE_LAYOUT_SEED,
    connector_style: state.connectorStyle,
    labels_enabled: state.labelsEnabled,
    engrave_back_labels: false,
    irregularity_strength: state.irregularityStrength,
    min_neck_width_mm: state.minNeckWidthMm,
  } as const;
}

// ========== Store ==========

export const useConverterStore = create<ConverterState & ConverterActions>(
  (set, _get) => ({
    ...DEFAULT_STATE,

    // --- 图片 ---
    setImageFile: (file: File | null) => {
      // Revoke previous blob URL to avoid memory leaks
      const prev = _get().imagePreviewUrl;
      if (prev && prev.startsWith("blob:")) {
        URL.revokeObjectURL(prev);
      }

      if (!file) {
        set({
          imageFile: null,
          imagePreviewUrl: null,
          aspectRatio: null,
          ...buildPreviewSessionResetState(),
        });
        return;
      }

      if (isRawFileConverter(file)) {
        const shouldOpenCrop = _get().enableCrop;
        set({
          imageFile: file,
          imagePreviewUrl: null,
          aspectRatio: null,
          ...buildPreviewSessionResetState(),
          cropModalOpen: shouldOpenCrop,
        });
        uploadImagePreview(file)
          .then(({ preview_url, width, height }) => {
            set({
              imagePreviewUrl: preview_url,
              aspectRatio: width / height,
            });
          })
          .catch(() => {
            /* non-fatal */
          });
        return;
      }

      const previewUrl = URL.createObjectURL(file);

      // Calculate aspect ratio from image dimensions
      const img = new Image();
      img.onload = () => {
        const ratio = img.naturalWidth / img.naturalHeight;
        set({ aspectRatio: ratio });
      };
      img.src = previewUrl;

      const shouldOpenCrop = _get().enableCrop;
      set({
        imageFile: file,
        imagePreviewUrl: previewUrl,
        ...buildPreviewSessionResetState(),
        cropModalOpen: shouldOpenCrop,
      });
      console.log("[DEBUG] setImageFile: cleared layerImages");
    },

    // --- 基础参数 ---
    setLutName: (name: string) => {
      const state = _get();
      const lutInfo = state.lutListFull.find((l) => l.name === name);
      const updates: Partial<ConverterState> = {
        source_version: "legacy",
        lut_name: name,
        selectedLutInfo: null,
        selectedNativeBrandKey: "",
        selectedNativeDbNames: [],
        color_layers: null,
        layer_height_mm: null,
        model_enable: false,
        model_only: false,
        model_threshold: null,
        model_margin: null,
        ...buildPreviewSessionResetState(),
      };
      if (lutInfo && lutInfo.color_mode) {
        updates.color_mode = lutInfo.color_mode as ColorMode;
      }
      set(updates);
      try {
        localStorage.setItem("lumina_lastLut", name);
      } catch {
        /* noop */
      }
      // 仅当 LUT 名称实际变化时获取颜色
      if (name && name !== state.lutColorsLutName) {
        _get().fetchLutColors(name);
      }
      if (name) {
        void apiFetchLutInfo(name)
          .then((info) => {
            const nextUpdates: Partial<ConverterState> = {
              selectedLutInfo: info,
            };
            if (info.color_mode) {
              nextUpdates.color_mode = info.color_mode as ColorMode;
            }
            if (info.supports_predictive_match || info.supports_dynamic_layer_count) {
              if (Array.isArray(info.supported_modes) && info.supported_modes.length > 0) {
                const preferredMode =
                  info.supported_modes.find((mode) => mode.color_layers === 5) ??
                  info.supported_modes.find((mode) => mode.color_layers === info.max_color_layers) ??
                  info.supported_modes[0];
                nextUpdates.color_layers = preferredMode.color_layers ?? info.max_color_layers ?? null;
                nextUpdates.layer_height_mm = preferredMode.layer_height_mm ?? info.layer_height_mm ?? null;
              } else {
                nextUpdates.color_layers = info.max_color_layers ?? null;
                nextUpdates.layer_height_mm = info.layer_height_mm ?? null;
              }
            } else {
              nextUpdates.color_layers = null;
              nextUpdates.layer_height_mm = null;
            }
            set(nextUpdates);
          })
          .catch(() => {
            /* best effort */
          });
      }
    },

    setSourceVersion: (version: SourceVersion) =>
      set((state) => {
        if (version === state.source_version) {
          return {};
        }

        if (version === "legacy") {
          return {
            source_version: "legacy",
            color_layers: null,
            layer_height_mm: null,
            selectedNativeBrandKey: "",
            selectedNativeDbNames: [],
            model_enable: false,
            model_only: false,
            model_threshold: null,
            model_margin: null,
            ...buildPreviewSessionResetState(),
          };
        }

        const selection = resolveNativeBrandSelection(state);
        const selectedBrand = selection.brand ?? state.nativeBrandGroups[0] ?? null;
        const preferredMode = selectedBrand
          ? resolveNativeSupportedModeForBrand(
              selectedBrand,
              state.color_layers,
              state.layer_height_mm,
            )
          : null;
        return {
          source_version: "native",
          selectedNativeBrandKey: selectedBrand?.brand_key ?? "",
          selectedNativeDbNames: getNativeDbNamesForGroup(selectedBrand),
          color_layers: preferredMode?.color_layers ?? null,
          layer_height_mm: preferredMode?.layer_height_mm ?? null,
          ...buildNativeModelState(selectedBrand, state),
          ...buildPreviewSessionResetState(),
        };
      }),

    setNativeBrandKey: (brandKey: string) =>
      set((state) => {
        const selectedBrand = getNativeBrandGroupByKey(state.nativeBrandGroups, brandKey);
        if (!selectedBrand) {
          return {
            selectedNativeBrandKey: brandKey,
            selectedNativeDbNames: [],
            color_layers: null,
            layer_height_mm: null,
            ...buildNativeModelDefaults(null),
            ...buildPreviewSessionResetState(),
          };
        }

        const preferredMode = resolveNativeSupportedModeForBrand(
          selectedBrand,
          state.color_layers,
          state.layer_height_mm,
        );
        return {
          source_version: "native",
          selectedNativeBrandKey: selectedBrand.brand_key,
          selectedNativeDbNames: getNativeDbNamesForGroup(selectedBrand),
          color_layers: preferredMode?.color_layers ?? null,
          layer_height_mm: preferredMode?.layer_height_mm ?? null,
          ...buildNativeModelState(selectedBrand, state),
          ...buildPreviewSessionResetState(),
        };
      }),

    setNativeSupportedMode: (mode: { color_layers: number; layer_height_mm: number }) =>
      set((state) => {
        const brand = getSelectedNativeBrandGroup(state);
        if (!brand) {
          return {
            source_version: "native",
            color_layers: mode.color_layers,
            layer_height_mm: mode.layer_height_mm,
            ...buildPreviewSessionResetState(),
          };
        }
        const supported = getSupportedModeByPair(
          brand.supported_modes ?? [],
          mode.color_layers,
          mode.layer_height_mm,
        );
        if (!supported) {
          const preferred = resolveNativeSupportedModeForBrand(
            brand,
            mode.color_layers,
            mode.layer_height_mm,
          );
          return {
            source_version: "native",
            color_layers: preferred?.color_layers ?? null,
            layer_height_mm: preferred?.layer_height_mm ?? null,
            ...buildPreviewSessionResetState(),
          };
        }
        return {
          source_version: "native",
          color_layers: supported.color_layers,
          layer_height_mm: supported.layer_height_mm,
          ...buildPreviewSessionResetState(),
        };
      }),

    setNativeDbNames: (dbNames: string[]) =>
      set((state) => {
        const selectedBrand = getSelectedNativeBrandGroup(state);
        const allowed = selectedBrand ? new Set(getNativeDbOptionNames(selectedBrand)) : null;
        const normalized = normalizeStringArray(
          dbNames.filter((dbName) => (allowed ? allowed.has(dbName) : true)),
        );
        return {
          source_version: "native",
          selectedNativeDbNames: normalized,
          ...buildPreviewSessionResetState(),
        };
      }),

    setTargetWidthMm: (width: number) =>
      set((state) => {
        const max = state.largeFormatEnabled ? 9999 : 400;
        const clamped = clampValue(width, 10, max);
        if (state.aspectRatio) {
          return {
            target_width_mm: clamped,
            target_height_mm: clampValue(
              Math.round(clamped / state.aspectRatio),
              10,
              max,
            ),
            threemfDiskPath: null,
            downloadUrl: null,
          };
        }
        return {
          target_width_mm: clamped,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      }),

    setTargetHeightMm: (height: number) =>
      set((state) => {
        const max = state.largeFormatEnabled ? 9999 : 400;
        const clamped = clampValue(height, 10, max);
        if (state.aspectRatio) {
          return {
            target_height_mm: clamped,
            target_width_mm: clampValue(
              Math.round(clamped * state.aspectRatio),
              10,
              max,
            ),
          };
        }
        return { target_height_mm: clamped };
      }),

    setSpacerThick: (thick: number) =>
      set((state) => ({
        ...buildFridgeMagnetState(state, {
          base_spacer_thick: clampValue(thick, 0.2, 3.5),
        }),
        threemfDiskPath: null,
        downloadUrl: null,
      })),

    setStructureMode: (mode: StructureMode) =>
      set((state) => ({
        structure_mode:
          state.enable_fridge_magnet && mode !== StructureModeEnum.SINGLE_SIDED
            ? StructureModeEnum.SINGLE_SIDED
            : mode,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setColorMode: (mode: ColorMode) =>
      set({ color_mode: mode, threemfDiskPath: null, downloadUrl: null }),
    setModelingMode: (mode: ModelingMode) =>
      set({ modeling_mode: mode, threemfDiskPath: null, downloadUrl: null }),
    setColorLayers: (layers: number | null) =>
      set({
        color_layers:
          layers == null ? null : clampValue(Math.round(layers), 1, 20),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setLayerHeightMm: (height: number | null) =>
      set({
        layer_height_mm:
          height == null ? null : clampValue(height, 0.04, 0.20),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setModelEnable: (enabled: boolean) =>
      set({
        model_enable: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setModelOnly: (enabled: boolean) =>
      set({
        model_only: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setModelThreshold: (value: number | null) =>
      set({
        model_threshold: value == null ? null : Number(value),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setModelMargin: (value: number | null) =>
      set({
        model_margin: value == null ? null : Number(value),
        threemfDiskPath: null,
        downloadUrl: null,
      }),

    // --- 高级设置 ---
    setAutoBg: (enabled: boolean) =>
      set({ auto_bg: enabled, threemfDiskPath: null, downloadUrl: null }),
    setBgTol: (tol: number) =>
      set({
        bg_tol: clampValue(tol, 0, 150),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setQuantizeColors: (colors: number) =>
      set({
        quantize_colors: clampValue(colors, 8, 256),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setEnableCleanup: (enabled: boolean) =>
      set({
        enable_cleanup: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setHueEnable: (enabled: boolean) =>
      set({
        hue_enable: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setChromaGate: (gate: number) =>
      set({
        chroma_gate: clampValue(gate, 0, 50),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setSeparateBacking: (enabled: boolean) =>
      set({ separate_backing: enabled }),

    // --- 鎸備欢鐜?---
    setAddLoop: (enabled: boolean) =>
      set((state) => ({
        add_loop:
          enabled && (state.puzzleEnabled || state.enable_fridge_magnet)
            ? false
            : enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setLoopWidth: (width: number) =>
      set({ loop_width: clampValue(width, 2, 10) }),
    setLoopLength: (length: number) =>
      set({ loop_length: clampValue(length, 4, 15) }),
    setLoopHole: (hole: number) => set({ loop_hole: clampValue(hole, 1, 5) }),
    setLoopAngle: (angle: number) =>
      set({ loop_angle: clampValue(angle, -180, 180) }),
    setLoopOffsetX: (x: number) =>
      set({ loop_offset_x: clampValue(x, -200, 200) }),
    setLoopOffsetY: (y: number) =>
      set({ loop_offset_y: clampValue(y, -200, 200) }),
    setLoopPositionPreset: (preset: string) => {
      set({ loop_position_preset: preset });
    },

    setEnableFridgeMagnet: (enabled: boolean) =>
      set((state) => {
        const shouldSeedDefaults =
          enabled &&
          !state.enable_fridge_magnet &&
          state.fridge_magnets.length === 0;
        const fridgeMagnets = shouldSeedDefaults
          ? buildDefaultFridgeMagnetLayout(state)
          : state.fridge_magnets;

        return {
          ...buildFridgeMagnetState(state, {
            enable_fridge_magnet: enabled,
            fridge_magnets: fridgeMagnets,
          }),
          structure_mode: enabled
            ? StructureModeEnum.SINGLE_SIDED
            : state.structure_mode,
          largeFormatEnabled: enabled ? false : state.largeFormatEnabled,
          puzzleEnabled: enabled ? false : state.puzzleEnabled,
          add_loop: enabled ? false : state.add_loop,
          selectedFridgeMagnetId: enabled
            ? state.selectedFridgeMagnetId
            : null,
          ...DEFAULT_PUZZLE_PREVIEW_STATE,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      }),

    resetFridgeMagnetLayout: () =>
      set((state) => ({
        ...buildFridgeMagnetState(state, {
          fridge_magnets: autoLayoutFridgeMagnets(state),
        }),
        selectedFridgeMagnetId: null,
        threemfDiskPath: null,
        downloadUrl: null,
      })),

    addFridgeMagnet: () =>
      set((state) => {
        const nextFridgeMagnets = autoLayoutFridgeMagnets({
          ...state,
          fridge_magnets: [
            ...state.fridge_magnets,
            createFridgeMagnetFromPreset(
              createNextFridgeMagnetId(state.fridge_magnets),
              getDefaultFridgeMagnetPresetKey("round"),
              getModelCenter(state).x,
              getModelCenter(state).y,
            ),
          ],
        });

        return {
          ...buildFridgeMagnetState(state, {
            fridge_magnets: nextFridgeMagnets,
          }),
          selectedFridgeMagnetId: nextFridgeMagnets[nextFridgeMagnets.length - 1].id,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      }),

    removeFridgeMagnet: (id: string) =>
      set((state) => {
        const nextFridgeMagnets = state.fridge_magnets.filter(
          (item) => item.id !== id,
        );

        return {
          ...buildFridgeMagnetState(state, {
            fridge_magnets: nextFridgeMagnets,
          }),
          selectedFridgeMagnetId:
            state.selectedFridgeMagnetId === id
              ? null
              : state.selectedFridgeMagnetId,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      }),

    updateFridgeMagnet: (id: string, updates: Partial<Omit<FridgeMagnetItem, "id">>) =>
      set((state) => {
        const nextFridgeMagnets = state.fridge_magnets.map((item) =>
          item.id === id
            ? normalizeFridgeMagnetItem({
                ...item,
                ...updates,
                diameter_mm: sanitizeOptionalFiniteNumber(
                  updates.diameter_mm,
                  item.diameter_mm,
                ),
                width_mm: sanitizeOptionalFiniteNumber(
                  updates.width_mm,
                  item.width_mm,
                ),
                height_mm: sanitizeOptionalFiniteNumber(
                  updates.height_mm,
                  item.height_mm,
                ),
                thickness_mm: updates.thickness_mm == null
                  ? item.thickness_mm
                  : sanitizeFiniteNumber(
                      updates.thickness_mm,
                      item.thickness_mm,
                    ),
                center_x_mm: updates.center_x_mm == null
                  ? item.center_x_mm
                  : sanitizeFiniteNumber(
                      updates.center_x_mm,
                      item.center_x_mm,
                    ),
                center_y_mm: updates.center_y_mm == null
                  ? item.center_y_mm
                  : sanitizeFiniteNumber(
                      updates.center_y_mm,
                      item.center_y_mm,
                    ),
              })
            : item,
        );

        return {
          ...buildFridgeMagnetState(state, {
            fridge_magnets: nextFridgeMagnets,
          }),
          threemfDiskPath: null,
          downloadUrl: null,
        };
      }),

    updateFridgeMagnetCenter: (id: string, centerX: number, centerY: number) =>
      set((state) => {
        const nextFridgeMagnets = state.fridge_magnets.map((item) =>
          item.id === id
            ? {
                ...item,
                center_x_mm: sanitizeFiniteNumber(centerX, item.center_x_mm),
                center_y_mm: sanitizeFiniteNumber(centerY, item.center_y_mm),
              }
            : item,
        );

        return {
          ...buildFridgeMagnetState(state, {
            fridge_magnets: nextFridgeMagnets,
          }),
          threemfDiskPath: null,
          downloadUrl: null,
        };
      }),

    selectFridgeMagnet: (id: string | null) =>
      set({ selectedFridgeMagnetId: id }),

    clearSelectedFridgeMagnet: () =>
      set({ selectedFridgeMagnetId: null }),

    // --- 浮雕（互斥） ---
    setEnableRelief: (enabled: boolean) => {
      set((state) => {
        const updates: Partial<ConverterState> = {
          enable_relief: enabled,
          enable_cloisonne: enabled ? false : state.enable_cloisonne,
          // Relief only supports single-sided structure
          structure_mode: enabled
            ? StructureModeEnum.SINGLE_SIDED
            : state.structure_mode,
          threemfDiskPath: null,
          downloadUrl: null,
        };
        // Requirement 6.5: When switching enable_relief from false to true,
        // auto-initialize color_height_map ONLY if it is currently empty.
        // Use computeAutoHeightMap to assign different heights based on
        // luminance, so the relief effect is visible immediately.
        if (
          enabled &&
          !state.enable_relief &&
          state.palette.length > 0 &&
          Object.keys(state.color_height_map).length === 0
        ) {
          const mode =
            state.autoHeightMode === "use-heightmap"
              ? "darker-higher"
              : (state.autoHeightMode as "darker-higher" | "lighter-higher");
          updates.color_height_map = computeAutoHeightMap(
            state.palette,
            mode,
            state.heightmap_max_height,
          );
        }
        return updates;
      });
    },
    setColorHeightMap: (map: Record<string, number>) =>
      set({ color_height_map: map }),
    setHeightmapMaxHeight: (height: number) => {
      const state = _get();
      const newMax = clampValue(height, 0.08, 15.0);
      const oldMax = state.heightmap_max_height;
      // Proportionally rescale all existing color heights
      if (oldMax > 0 && Object.keys(state.color_height_map).length > 0) {
        const ratio = newMax / oldMax;
        const scaled: Record<string, number> = {};
        for (const [hex, h] of Object.entries(state.color_height_map)) {
          scaled[hex] = clampValue(h * ratio, 0.08, newMax);
        }
        set({ heightmap_max_height: newMax, color_height_map: scaled });
      } else {
        set({ heightmap_max_height: newMax });
      }
    },

    // --- 描边 ---
    setEnableOutline: (enabled: boolean) =>
      set({
        enable_outline: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setOutlineWidth: (width: number) =>
      set({ outline_width: clampValue(width, 0.5, 10.0) }),

    // --- 掐丝珐琅（互斥） ---
    setEnableCloisonne: (enabled: boolean) =>
      set((state) => ({
        enable_cloisonne: enabled,
        enable_relief: enabled ? false : state.enable_relief,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setWireWidthMm: (width: number) =>
      set({ wire_width_mm: clampValue(width, 0.2, 1.2) }),
    setWireHeightMm: (height: number) =>
      set({ wire_height_mm: clampValue(height, 0.04, 1.0) }),

    // --- 涂层 ---
    setEnableCoating: (enabled: boolean) =>
      set({
        enable_coating: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setCoatingHeightMm: (height: number) =>
      set({ coating_height_mm: clampValue(height, 0.04, 0.12) }),

    // --- 大画幅 ---
    setLargeFormatEnabled: (enabled: boolean) =>
      set((state) => ({
        largeFormatEnabled:
          enabled && (state.puzzleEnabled || state.enable_fridge_magnet)
            ? false
            : enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setTileWidthMm: (width: number) =>
      set({
        tileWidthMm: clampValue(width, 50, 500),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setTileHeightMm: (height: number) =>
      set({
        tileHeightMm: clampValue(height, 50, 500),
        threemfDiskPath: null,
        downloadUrl: null,
      }),

    setPuzzleEnabled: (enabled: boolean) =>
      set((state) => ({
        puzzleEnabled: enabled && !state.batchMode,
        largeFormatEnabled: enabled ? false : state.largeFormatEnabled,
        add_loop: enabled ? false : state.add_loop,
        ...buildFridgeMagnetState(state, {
          enable_fridge_magnet: enabled ? false : state.enable_fridge_magnet,
        }),
        selectedFridgeMagnetId: enabled ? null : state.selectedFridgeMagnetId,
        ...(!enabled ? DEFAULT_PUZZLE_PREVIEW_STATE : {}),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setPuzzleStyle: (style: PuzzleStyle) =>
      set({
        puzzleStyle: style,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setPuzzleSizingMode: (mode: PuzzleSizingMode) =>
      set({
        puzzleSizingMode: mode,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setPieceWidthMm: (width: number) =>
      set({
        pieceWidthMm: clampValue(width, 5, 200),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setPieceHeightMm: (height: number) =>
      set({
        pieceHeightMm: clampValue(height, 5, 200),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setPuzzleRows: (rows: number) =>
      set({
        puzzleRows: clampValue(Math.round(rows), 1, 200),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setPuzzleCols: (cols: number) =>
      set({
        puzzleCols: clampValue(Math.round(cols), 1, 200),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setTargetPieceCount: (count: number) =>
      set({
        targetPieceCount: clampValue(Math.round(count), 2, 2000),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setConnectorStyle: (style: PuzzleConnectorStyle) =>
      set({
        connectorStyle: style,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setLabelsEnabled: (enabled: boolean) =>
      set({
        labelsEnabled: enabled,
        engraveBackLabels: false,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setEngraveBackLabels: () => {
      set({
        engraveBackLabels: false,
        threemfDiskPath: null,
        downloadUrl: null,
      });
    },
    setIrregularityStrength: (strength: number) =>
      set({
        irregularityStrength: clampValue(strength, 0, 1),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setMinNeckWidthMm: (width: number) =>
      set({
        minNeckWidthMm: clampValue(width, 0.2, 20),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    submitPuzzleLayoutPreview: async () => {
      const state = _get();
      if (!state.puzzleEnabled || !state.sessionId) {
        set({ ...DEFAULT_PUZZLE_PREVIEW_STATE });
        return false;
      }

      const requestedSessionId = state.sessionId;
      const requestedParams = buildPuzzlePreviewParams(state);

      try {
        const response = await apiConvertPuzzleLayoutPreview(
          requestedSessionId,
          requestedParams,
        );
        const latestState = _get();
        const latestParams = buildPuzzlePreviewParams(latestState);
        if (
          latestState.sessionId !== requestedSessionId ||
          !latestState.puzzleEnabled ||
          JSON.stringify(latestParams) !== JSON.stringify(requestedParams)
        ) {
          return false;
        }
        set({
          puzzleOverlayUrl:
            normalizeResourceUrl(response.overlay_url) ?? response.overlay_url,
          puzzleWarnings: response.warnings ?? [],
          puzzleResolvedRows: response.grid_rows,
          puzzleResolvedCols: response.grid_cols,
          puzzleResolvedPieceCount: response.piece_count,
          puzzleDerivedPieceWidthMm: response.derived_piece_width_mm,
          puzzleDerivedPieceHeightMm: response.derived_piece_height_mm,
          error: null,
        });
        return true;
      } catch (err) {
        const latestState = _get();
        const latestParams = buildPuzzlePreviewParams(latestState);
        if (
          latestState.sessionId !== requestedSessionId ||
          !latestState.puzzleEnabled ||
          JSON.stringify(latestParams) !== JSON.stringify(requestedParams)
        ) {
          return false;
        }
        set({
          ...DEFAULT_PUZZLE_PREVIEW_STATE,
          error: err instanceof Error ? err.message : "Puzzle preview failed",
        });
        return false;
      }
    },
    clearPuzzleLayoutPreview: () =>
      set({
        ...DEFAULT_PUZZLE_PREVIEW_STATE,
      }),

    // --- 热床尺寸 ---
    setBedLabel: (label: string) => {
      set({ bed_label: label });
    },

    // --- 调色板与选择 ---
    setSelectedColor: (hex: string | null) => set({ selectedColor: hex }),
    setPalette: (entries: PaletteEntry[]) => set({ palette: entries }),

    // --- 颜色选择模式 ---
    // current: 单区域替换（3D 点击 → region-detect → 可替换该连通区域）
    // select-all: 全局单色替换（选一个颜色 → 全图该颜色都替换）
    // multi-select: 多区域替换（3D 点击累积多个连通区域 → 批量替换）
    // region: 保留的局部区域模式
    setSelectionMode: (mode: SelectionMode) => {
      switch (mode) {
        case "current": {
          const baseCur = getPreviewBaseUrl(_get());
          set({
            selectionMode: mode,
            selectedColors: new Set<string>(),
            selectedColor: null,
            regionData: null,
            selectedRegions: [],
            previewImageUrl: baseCur,
          });
          break;
        }
        case "select-all": {
          const baseSelectAll = getPreviewBaseUrl(_get());
          set({
            selectionMode: mode,
            selectedColors: new Set<string>(),
            selectedRegions: [],
            previewImageUrl: baseSelectAll,
          });
          break;
        }
        case "multi-select": {
          const baseMulti = getPreviewBaseUrl(_get());
          set({
            selectionMode: mode,
            selectedColors: new Set<string>(),
            selectedColor: null,
            regionData: null,
            selectedRegions: [],
            previewImageUrl: baseMulti,
          });
          break;
        }
        case "region": {
          const baseRegion = getPreviewBaseUrl(_get());
          set({
            selectionMode: mode,
            selectedColors: new Set<string>(),
            selectedColor: null,
            regionData: null,
            selectedRegions: [],
            previewImageUrl: baseRegion,
          });
          break;
        }
      }
    },

    // --- 多选模式颜色切换 ---
    toggleColorInSelection: (hex: string) => {
      const prev = _get().selectedColors;
      const next = new Set(prev);
      if (next.has(hex)) {
        next.delete(hex);
      } else {
        next.add(hex);
      }
      set({ selectedColors: next });

      // 2D 预览高亮：调用后端生成颜色高亮预览（与 detectRegion 同风格）
      const state = _get();
      const sid = state.sessionId;
      if (!sid) return;

      if (next.size === 0) {
        set({ previewImageUrl: getPreviewBaseUrl(state) });
      } else {
        const hexes = Array.from(next);
        void apiColorHighlight(sid, hexes)
          .then((res) => {
            if (_get().selectedColors.size > 0) {
              set({ previewImageUrl: normalizeResourceUrl(res.preview_url) });
            }
          })
          .catch(() => {
            // 静默忽略高亮失败（不影响核心流程）
          });
      }
    },

    // --- 批量颜色替换 ---
    applyBatchColorRemap: async (newHex: string) => {
      const state = _get();
      const colors = Array.from(state.selectedColors);
      if (colors.length === 0) return;

      // 1. 快照当前 colorRemapMap，作为单条记录推入 remapHistory
      const snapshot = { ...state.colorRemapMap };
      const newHistory = [...state.remapHistory, snapshot];

      // 2. 批量更新 colorRemapMap
      const newMap = { ...state.colorRemapMap };
      for (const hex of colors) {
        newMap[hex] = newHex;
      }
      set({
        colorRemapMap: newMap,
        remapHistory: newHistory,
        replacePreviewLoading: true,
        threemfDiskPath: null,
        downloadUrl: null,
      });

      // 3. 依次调用后端替换
      try {
        for (const hex of colors) {
          await _get().submitSingleReplace(hex, newHex);
        }
        set({ replacePreviewLoading: false });
      } catch {
        // 回滚整个批量操作
        set({
          colorRemapMap: snapshot,
          remapHistory: state.remapHistory,
          replacePreviewLoading: false,
          error: "批量颜色替换失败",
        });
      }
    },

    // --- 连通区域检测（current 模式：单区域） ---
    detectRegion: async (x: number, y: number) => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return;
      }
      try {
        const response = await apiDetectRegion(state.sessionId, x, y);
        const previewUrl = normalizeResourceUrl(response.preview_url) ?? response.preview_url;
        set({
          regionData: {
            regionId: response.region_id,
            colorHex: response.color_hex,
            pixelCount: response.pixel_count,
            previewUrl,
            contours: response.contours ?? null,
            clickX: x,
            clickY: y,
          },
          selectedColor: response.color_hex.replace(/^#/, ""),
        });
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "Region detect failed",
        });
      }
    },

    // --- 连通区域累积检测（multi-select 模式：多区域） ---
    detectAndAccumulateRegion: async (x: number, y: number) => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return;
      }
      try {
        const response = await apiDetectRegion(state.sessionId, x, y);
        const newRegion: RegionData = {
          regionId: response.region_id,
          colorHex: response.color_hex,
          pixelCount: response.pixel_count,
          previewUrl: normalizeResourceUrl(response.preview_url) ?? response.preview_url,
          contours: response.contours ?? null,
          clickX: x,
          clickY: y,
        };
        const currentState = _get();
        const existing = currentState.selectedRegions;
        const idx = existing.findIndex(
          (r) => r.regionId === newRegion.regionId,
        );
        if (idx >= 0) {
          const next = existing.filter((_, i) => i !== idx);
          const lastRegion = getLastSelectedRegion(next);
          set({
            selectedRegions: next,
            selectedColor: lastRegion
              ? lastRegion.colorHex.replace(/^#/, "")
              : null,
          });
        } else {
          set({
            selectedRegions: [...existing, newRegion],
            selectedColor: response.color_hex.replace(/^#/, ""),
            previewImageUrl: newRegion.previewUrl,
          });
        }
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "Region detect failed",
        });
      }
    },

    removeRegionFromSelection: (regionId: string) => {
      const state = _get();
      const next = state.selectedRegions.filter((region) => region.regionId !== regionId);
      if (next.length === state.selectedRegions.length) {
        return;
      }
      const lastRegion = getLastSelectedRegion(next);
      set({
        selectedRegions: next,
        selectedColor: lastRegion ? lastRegion.colorHex.replace(/^#/, "") : null,
        previewImageUrl: getSelectedRegionPreviewUrl(next, getPreviewBaseUrl(state)),
      });
    },

    upsertRecipeOverrides: (regionIds: string[], recipe: number[], layerOrder: string) => {
      const validRegionIds = regionIds.filter((value) => !!value);
      if (validRegionIds.length === 0) {
        return;
      }
      const normalizedRecipe = recipe.map((value) => Math.max(0, Math.round(value)));
      set((state) => {
        const existing = state.recipe_overrides.filter(
          (item) => !validRegionIds.includes(item.region_id),
        );
        const next = [
          ...existing,
          ...validRegionIds.map((regionId) => ({
            region_id: regionId,
            recipe: normalizedRecipe,
            layer_order: layerOrder,
          })),
        ];
        return {
          recipe_overrides: next,
          color_layers: Math.max(
            state.color_layers ?? 0,
            normalizedRecipe.length,
          ),
        };
      });
    },

    clearRecipeOverrides: (regionIds?: string[]) => {
      if (!regionIds || regionIds.length === 0) {
        set({ recipe_overrides: [] });
        return;
      }
      set((state) => ({
        recipe_overrides: state.recipe_overrides.filter(
          (item) => !regionIds.includes(item.region_id),
        ),
      }));
    },

    // --- 连通区域替换 ---
    applyRegionReplace: async (newHex: string) => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return;
      }
      if (!state.regionData) {
        set({ error: "Please select a connected region first" });
        return;
      }
      const sourceColorHex = state.regionData.colorHex;
      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiRegionReplace(state.sessionId, `#${newHex}`);
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          regionData: null,
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
        };

        // 更新 3D 预览 GLB URL（仅当后端返回非空 URL 时）
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(response.preview_glb_url);
        }
        // preview_glb_url 为 null 时不清除现有 previewGlbUrl

        // 更新颜色轮廓数据（仅当后端返回非空数据时）
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }

        // 记录替换到 replacement_regions，供分享卡导出使用
        const paletteEntry = state.palette.find(
          (p) => p.matched_hex === sourceColorHex,
        );
        updates.replacement_regions = [
          ..._get().replacement_regions,
          {
            quantized_hex: paletteEntry?.quantized_hex ?? sourceColorHex,
            matched_hex: sourceColorHex,
            replacement_hex: newHex,
          },
        ];

        // 不递增 regionReplacementCount（已在 confirmReplacement 中处理）
        set(updates);
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "区域颜色替换失败",
        });
      }
    },

    applyCustomRecipeOverride: async (
      regionIds: string[],
      recipe: number[],
      layerOrder: string = "Top2Bottom",
    ) => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return;
      }
      const targetRegionIds = regionIds.filter(Boolean);
      if (targetRegionIds.length === 0) {
        set({ error: "请先选择区域" });
        return;
      }
      const resolvedLayers = Math.max(
        recipe.length,
        state.color_layers ?? recipe.length,
      );
      const resolvedHeight =
        state.layer_height_mm ?? state.selectedLutInfo?.layer_height_mm ?? 0.08;

      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiApplyRecipeOverride({
          session_id: state.sessionId,
          region_ids: targetRegionIds,
          recipe,
          layer_order: layerOrder,
          color_layers: resolvedLayers,
          layer_height_mm: resolvedHeight,
        });
        set((current) => ({
          replacePreviewLoading: false,
          previewImageUrl: normalizeResourceUrl(response.preview_url) ?? response.preview_url,
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url) ?? response.preview_url,
          previewGlbUrl: response.preview_glb_url
            ? normalizeResourceUrl(response.preview_glb_url)
            : current.previewGlbUrl,
          color_layers: Math.max(current.color_layers ?? 0, resolvedLayers),
          layer_height_mm: resolvedHeight,
          recipe_overrides: [
            ...current.recipe_overrides.filter(
              (item) => !targetRegionIds.includes(item.region_id),
            ),
            ...targetRegionIds.map((regionId) => ({
              region_id: regionId,
              recipe: [...recipe],
              layer_order: layerOrder,
            })),
          ],
          lutMatchMode: "predictive",
          lutMatchInfo: {
            ...(current.lutMatchInfo ?? {}),
            match_mode: "predictive",
            runtime_mode_key: response.runtime_mode_key ?? null,
            source: response.source,
            override: true,
          },
        }));
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "自定义配方应用失败",
        });
      }
    },

    // --- 待确认颜色替换 ---
    setPendingReplacement: (pending: PendingReplacement | null) => {
      set({ pendingReplacement: pending });
    },

    confirmReplacement: async () => {
      const state = _get();
      const pending = state.pendingReplacement;
      if (!pending) return;

      // 清除 pending 状态
      set({ pendingReplacement: null });

      switch (pending.mode) {
        case "select-all":
          if (pending.sourceColors && pending.sourceColors.length > 1) {
            // 多选批量替换：所有选中的源色 → 同一目标色
            // 先临时写入 selectedColors 以供 applyBatchColorRemap 使用
            set({ selectedColors: new Set(pending.sourceColors) });
            await _get().applyBatchColorRemap(pending.targetHex);
            set({ selectedColors: new Set<string>(), selectedColor: null });
          } else {
            // 单色替换：乐观更新 colorRemapMap → 3D 预览即时响应
            _get().applyColorRemap(pending.sourceHex, pending.targetHex);
          }
          break;
        case "multi-select": {
          // 多区域模式：顺序 re-detect → replace 每个连通区域
          const regions = pending.sourceRegions ?? [];
          if (regions.length === 0) break;
          const curState = _get();
          const sid = curState.sessionId;
          if (!sid) break;
          set({
            replacePreviewLoading: true,
            regionReplacementCount:
              curState.regionReplacementCount + regions.length,
            threemfDiskPath: null,
            downloadUrl: null,
          });
          try {
            const newEntries: ColorReplacementItem[] = [];
            for (const region of regions) {
              if (region.clickX != null && region.clickY != null) {
                await apiDetectRegion(sid, region.clickX, region.clickY);
              }
              const response = await apiRegionReplace(
                sid,
                `#${pending.targetHex}`,
              );
              const updates: Partial<ConverterState> = {
                previewImageUrl: normalizeResourceUrl(response.preview_url),
                previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
              };
              if (response.preview_glb_url) {
                updates.previewGlbUrl = normalizeResourceUrl(response.preview_glb_url);
              }
              if (response.color_contours) {
                updates.colorContours = response.color_contours;
              }
              set(updates);
              // 记录替换条目，供分享卡导出使用
              const pe = curState.palette.find(
                (p) => p.matched_hex === region.colorHex,
              );
              newEntries.push({
                quantized_hex: pe?.quantized_hex ?? region.colorHex,
                matched_hex: region.colorHex,
                replacement_hex: pending.targetHex,
              });
            }
            set({
              replacePreviewLoading: false,
              selectedRegions: [],
              regionData: null,
              selectedColor: null,
              replacement_regions: [
                ..._get().replacement_regions,
                ...newEntries,
              ],
            });
          } catch (err) {
            set({
              replacePreviewLoading: false,
              error: err instanceof Error ? err.message : "Multi-region color replacement failed",
            });
          }
          break;
        }
        case "current":
        case "region": {
          // 不更新 colorRemapMap（避免 3D 预览全局变色）
          // 仅递增 regionReplacementCount 并调用后端区域替换
          const curState = _get();
          set({
            regionReplacementCount: curState.regionReplacementCount + 1,
          });
          // 调用后端 region-replace → 2D 预览精确区域替换
          if (curState.regionData) {
            await _get().applyRegionReplace(pending.targetHex);
          }
          break;
        }
      }
    },

    // --- 颜色替换（纯前端） ---
    applyColorRemap: (origHex: string, newHex: string) => {
      const state = _get();
      // 推入当前快照到 history
      const snapshot = { ...state.colorRemapMap };
      const newHistory = [...state.remapHistory, snapshot];
      // 更新 map
      const newMap = { ...state.colorRemapMap, [origHex]: newHex };
      set({
        colorRemapMap: newMap,
        remapHistory: newHistory,
        threemfDiskPath: null,
        downloadUrl: null,
      });
      // 立即触发后端替换预览
      _get().submitSingleReplace(origHex, newHex);
    },

    undoColorRemap: () => {
      const state = _get();
      if (state.remapHistory.length === 0) return;
      const newHistory = [...state.remapHistory];
      const previousMap = newHistory.pop()!;
      set({
        colorRemapMap: previousMap,
        remapHistory: newHistory,
        threemfDiskPath: null,
        downloadUrl: null,
      });
      if (Object.keys(previousMap).length === 0) {
        const originalUrl = _get().originalPreviewUrl;
        set({
          previewImageUrl: originalUrl,
          previewBaseImageUrl: originalUrl,
        });
      } else {
        _get().submitReplacePreview();
      }
    },

    clearAllRemaps: () => {
      const state = _get();
      set({
        colorRemapMap: {},
        remapHistory: [],
        replacement_regions: [],
        threemfDiskPath: null,
        downloadUrl: null,
        regionData: null,
        selectedRegions: [],
        regionReplacementCount: 0,
      });
      // 调用后端清空 replacement_regions 并从原始 matched_rgb 重新生成预览和 GLB
      // 不能依赖 originalPreviewUrl，因为 region-replace 会修改后端缓存的 matched_rgb
      if (state.sessionId) {
        apiResetReplacements(state.sessionId)
          .then((res) => {
            const url = `${res.preview_url}`;
            const updates: Partial<ConverterState> = {
              previewImageUrl: url,
              originalPreviewUrl: url,
              previewBaseImageUrl: url,
            };
            if (res.preview_glb_url) {
              updates.previewGlbUrl = `${res.preview_glb_url}`;
            }
            set(updates);
          })
          .catch(() => {
            const fallback = _get().originalPreviewUrl;
            set({
              previewImageUrl: fallback,
              previewBaseImageUrl: fallback,
            });
          });
      } else {
        const originalUrl = state.originalPreviewUrl;
        set({
          previewImageUrl: originalUrl,
          previewBaseImageUrl: originalUrl,
        });
      }
    },

    // --- 浮雕高度 ---
    updateColorHeight: (hex: string, heightMm: number) => {
      set((state) => ({
        color_height_map: { ...state.color_height_map, [hex]: heightMm },
      }));
    },

    applyAutoHeight: (mode: "darker-higher" | "lighter-higher") => {
      const state = _get();
      const heightMap = computeAutoHeightMap(
        state.palette,
        mode,
        state.heightmap_max_height,
      );
      set({ color_height_map: heightMap });
    },

    setAutoHeightMode: (mode: AutoHeightMode) => set({ autoHeightMode: mode }),

    // --- 高度图 ---
    setHeightmapFile: (file: File | null) => set({ heightmapFile: file }),

    uploadHeightmap: async () => {
      const state = _get();
      if (!state.heightmapFile || !state.sessionId) {
        set({ error: "请先上传高度图文件并完成预览" });
        return;
      }
      set({ isLoading: true, error: null });
      try {
        const response = await apiUploadHeightmap(
          state.heightmapFile,
          state.sessionId,
        );
        const thumbnailUrl = `${response.thumbnail_url}`;
        set({
          isLoading: false,
          heightmapThumbnailUrl: thumbnailUrl,
          color_height_map: response.color_height_map,
        });
      } catch (err) {
        set({
          isLoading: false,
          error: err instanceof Error ? err.message : "Heightmap upload failed",
        });
      }
    },

    // --- GLB 预览 ---
    setPreviewGlbUrl: (url: string | null) => set({ previewGlbUrl: url }),

    // --- 模型边界 ---
    setModelBounds: (bounds: ConverterState["modelBounds"]) =>
      set((state) => ({
        modelBounds: bounds,
        ...(state.fridge_magnets.length > 0
          ? buildFridgeMagnetState(
              {
                ...state,
                modelBounds: bounds,
              },
              {
                fridge_magnets: state.fridge_magnets,
              },
            )
          : {}),
      })),

    fetchBedSizes: async () => {
      set({ bedSizesLoading: true });
      try {
        const response = await apiFetchBedSizes();
        const beds = response.beds;

        const settingsPrinterModel = useSettingsStore.getState().printerModel;
        const printerBed = beds.find(
          (bed) => bed.printer_id === settingsPrinterModel,
        );

        set({
          bedSizes: beds,
          bedSizesLoading: false,
          ...(printerBed ? { bed_label: printerBed.label } : {}),
        });
      } catch (err) {
        set({
          bedSizesLoading: false,
          error: err instanceof Error ? err.message : "热床尺寸列表加载失败",
        });
      }
    },

    // --- API 操作 ---
    uploadLut: async (file: File) => {
      set({ lutListLoading: true, error: null });
      try {
        const res = await apiUploadLut(file);
        // 上传成功后通过 catalog 刷新 legacy/native 共享状态，再选中新 LUT
        await _get().fetchLutCatalog();
        _get().setLutName(res.name);
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "LUT 上传失败",
        });
      } finally {
        set({ lutListLoading: false });
      }
    },

    fetchLutList: async () => {
      set({ lutListLoading: true });
      try {
        const response = await apiFetchLutList();
        const luts = response.luts;
        const updates: Partial<ConverterState> = {
          lutList: luts.map((l) => l.name),
          lutListFull: luts,
          lutListLoading: false,
        };

        // If a remembered LUT exists, apply its color_mode
        const remembered = _get().lut_name;
        if (remembered) {
          const info = luts.find((l) => l.name === remembered);
          if (info && info.color_mode) {
            updates.color_mode = info.color_mode as ColorMode;
          } else if (!info) {
            // Remembered LUT no longer exists — clear it
            updates.lut_name = "";
            try {
              localStorage.removeItem("lumina_lastLut");
            } catch {
              /* noop */
            }
          }
        }

        set(updates);
      } catch (err) {
        set({
          lutListLoading: false,
          error: err instanceof Error ? err.message : "LUT 列表加载失败",
        });
      }
    },

    fetchLutCatalog: async () => {
      set({ nativeBrandGroupsLoading: true });
      try {
        const response = await apiFetchLutCatalog();
        const legacyGroups = response.legacy_groups ?? [];
        const groups = filterNativeBrandGroups(response.native_brand_groups ?? []);
        const legacyLuts = legacyGroups.flatMap((group) => group.items ?? []);
        const currentState = _get();
        const updates: Partial<ConverterState> = {
          lutList: legacyLuts.map((lut) => lut.name),
          lutListFull: legacyLuts,
          nativeBrandGroups: groups,
          nativeBrandGroupsLoading: false,
        };
        const remembered = currentState.lut_name;
        if (remembered) {
          const info = legacyLuts.find((lut) => lut.name === remembered);
          if (info && info.color_mode) {
            updates.color_mode = info.color_mode as ColorMode;
          } else if (!info) {
            updates.lut_name = "";
            try {
              localStorage.removeItem("lumina_lastLut");
            } catch {
              /* noop */
            }
          }
        }
        const selection =
          currentState.source_version === "native"
            ? resolveNativeBrandSelection({
                nativeBrandGroups: groups,
                selectedNativeBrandKey: currentState.selectedNativeBrandKey,
                selectedNativeDbNames: currentState.selectedNativeDbNames,
                color_layers: currentState.color_layers,
                layer_height_mm: currentState.layer_height_mm,
              })
            : null;
        const fallbackBrand = selection?.brand ?? groups[0] ?? null;
        const preferredMode = selection?.supported_mode ?? resolvePreferredSupportedMode(fallbackBrand?.supported_modes ?? []);
        set({
          ...updates,
          ...(currentState.source_version === "native" && fallbackBrand
            ? {
                selectedNativeBrandKey: fallbackBrand.brand_key,
                selectedNativeDbNames: selection?.db_names ?? getNativeDbNamesForGroup(fallbackBrand),
                color_layers: preferredMode?.color_layers ?? null,
                layer_height_mm: preferredMode?.layer_height_mm ?? null,
                ...buildNativeModelState(fallbackBrand, currentState),
              }
            : {}),
        });
      } catch (err) {
        set({
          nativeBrandGroupsLoading: false,
          error: err instanceof Error ? err.message : "品牌目录加载失败",
        });
      }
    },

    fetchLutColors: async (lutName: string) => {
      if (!lutName) {
        set({ lutColors: [], lutColorsLutName: "" });
        return;
      }
      // 缓存命中检查：LUT 名称未变且已有数据时跳过请求
      if (lutName === _get().lutColorsLutName && _get().lutColors.length > 0) {
        return;
      }
      set({ lutColorsLoading: true });
      try {
        const response = await apiFetchLutColors(lutName);
        set({
          lutColors: response.colors,
          lutColorsLoading: false,
          lutColorsLutName: lutName,
        });
      } catch (err) {
        set({
          lutColorsLoading: false,
          error: err instanceof Error ? err.message : "LUT 颜色加载失败",
        });
      }
    },

    submitPreview: async () => {
        const state = _get();
        if (!state.imageFile) {
          set({ error: "请先上传图片" });
          return;
        }
      const sourceSelection = resolveConverterSourceSelection(state);
      if (!sourceSelection.isReady) {
        set({
          error:
            state.source_version === "native"
              ? "请先选择品牌和数据库"
              : "请先选择 LUT",
        });
        return;
      }

      // Cancel any in-flight preview request
      if (_previewAbortController) {
        _previewAbortController.abort();
      }
      _previewAbortController = new AbortController();
      const { signal } = _previewAbortController;

      set({
        isLoading: true,
        error: null,
        hasManualPreview: false,
        previewWarnings: [],
        largeFormatWarnings: [],
        ...DEFAULT_LAYER_IMAGES_STATE,
        ...DEFAULT_PUZZLE_PREVIEW_STATE,
      });
      console.log("[DEBUG] submitPreview: cleared layerImages");
      try {
        const resolvedSourceSelection = resolveConverterSourceSelection(state);
        const sourceParams =
          state.source_version === "native"
            ? buildNativeSourceParams(resolvedSourceSelection, state)
            : buildLegacySourceParams(state.lut_name);
        if (!sourceParams) {
          set({
            isLoading: false,
            error: "请先选择品牌和数据库",
          });
          return;
        }
        const response = await apiConvertPreview(
          state.imageFile,
          {
            ...sourceParams,
            color_layers:
              sourceParams.source_kind === "native_bundle"
                ? sourceParams.color_layers ?? undefined
                : state.color_layers ?? undefined,
            layer_height_mm:
              sourceParams.source_kind === "native_bundle"
                ? sourceParams.layer_height_mm ?? undefined
                : state.layer_height_mm ?? undefined,
            target_width_mm: state.target_width_mm,
            auto_bg: state.auto_bg,
            bg_tol: state.bg_tol,
            color_mode: state.color_mode,
            modeling_mode: state.modeling_mode,
            quantize_colors: state.quantize_colors,
            enable_cleanup: state.enable_cleanup,
            ...(sourceParams.source_kind === "native_bundle" &&
            resolvedSourceSelection.native.predictive_model_available
              ? {
                  model_enable: state.model_enable,
                  model_only: state.model_only,
                  model_threshold: state.model_threshold ?? undefined,
                  model_margin: state.model_margin ?? undefined,
                }
              : {}),
            hue_weight: state.hue_enable ? 0.5 : 0.0,
            chroma_gate: state.hue_enable ? state.chroma_gate : 0,
            is_dark: useSettingsStore.getState().theme === "dark",
          },
          signal,
        );
        // 后端返回 JSON，preview_url 是相对路径如 /api/files/xxx
        const previewUrl = normalizeResourceUrl(response.preview_url) ?? response.preview_url;
        const glbUrl = response.preview_glb_url
          ? normalizeResourceUrl(response.preview_glb_url)
          : null;
        // Normalize palette hex values: strip leading '#' for frontend consistency
        const normalizedPalette = (response.palette ?? []).map((e) => ({
          ...e,
          quantized_hex: e.quantized_hex.replace(/^#/, ""),
          matched_hex: e.matched_hex.replace(/^#/, ""),
        }));
        const resolvedColorLayers =
          sourceSelection.source_kind === "native_bundle"
            ? sourceSelection.color_layers ?? null
            : state.color_layers;
        const resolvedLayerHeightMm =
          sourceSelection.source_kind === "native_bundle"
            ? sourceSelection.layer_height_mm ?? null
            : state.layer_height_mm;

        set({
          isLoading: false,
          sessionId: response.session_id,
          previewImageUrl: previewUrl,
          originalPreviewUrl: previewUrl,
          previewBaseImageUrl:
            normalizeResourceUrl(response.dimensions?.preview_raw_url) ?? previewUrl,
          lutMatchMode: response.lut_match_mode ?? "legacy",
          lutMatchInfo:
            response.lut_match_info ??
            { match_mode: response.lut_match_mode ?? "legacy" },
          palette: normalizedPalette,
          colorContours: response.contours ?? {},
          previewGlbUrl: glbUrl,
          colorRemapMap: {},
          remapHistory: [],
          replacement_regions: [],
          recipe_overrides: [],
          free_color_set: new Set<string>(),
          regionReplacementCount: 0,
          selectedColor: null,
          selectedColors: new Set<string>(),
          regionData: null,
          selectedRegions: [],
          pendingReplacement: null,
          preview_width_mm: state.target_width_mm,
          preview_height_mm: state.target_height_mm,
          preview_spacer_thick: state.spacer_thick,
          color_layers: resolvedColorLayers,
          layer_height_mm: resolvedLayerHeightMm,
          previewPixelWidth: response.dimensions?.width ?? null,
          previewPixelHeight: response.dimensions?.height ?? null,
          previewWarnings: response.warnings ?? [],
          largeFormatWarnings: [],
          hasManualPreview: true,
          layerImages: [],
          layerImagesOpen: false,
        });
        console.log(
          "[DEBUG] submitPreview success: cleared layerImages for new sessionId",
        );
      } catch (err) {
        // Ignore aborted requests (user started a new preview)
        if (err instanceof Error && err.name === "CanceledError") {
          return;
        }
        set({
          isLoading: false,
          error: err instanceof Error ? err.message : "预览失败",
        });
      }
    },

    submitGenerate: async () => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return null;
      }
      const sourceSelection = resolveConverterSourceSelection(state);
      if (!sourceSelection.isReady) {
        set({
          error:
            state.source_version === "native"
              ? "请先选择品牌和数据库"
              : "请先选择 LUT",
        });
        return null;
      }
      // Requirement 10.4: enable_relief 为 true 且 color_height_map 为空时阻止生成
      if (
        state.enable_relief &&
        Object.keys(state.color_height_map).length === 0
      ) {
        // Requirement 10.3: 高度图模式时给出更具体的提示
        if (state.autoHeightMode === "use-heightmap") {
          set({ error: "请先上传高度图并获取高度映射后再生成" });
        } else {
          set({ error: "请先设置颜色高度映射后再生成" });
        }
        return null;
      }

      set({ isGenerating: true, error: null });
      _generateStartTime = performance.now();
      (window as LuminaWindow).__luminaGenerateStart = _generateStartTime;
      _clientLog('generate: click');
      _startGenerateTimer();
      try {
        // 合并 colorRemapMap 转换的 replacement_regions 与已有的 replacement_regions
        let mergedReplacements: ColorReplacementItem[] | undefined =
          state.replacement_regions.length > 0
            ? [...state.replacement_regions]
            : undefined;

        if (Object.keys(state.colorRemapMap).length > 0) {
          const remapRegions = colorRemapToReplacementRegions(
            state.colorRemapMap,
            state.palette,
          );
          mergedReplacements = [...(mergedReplacements ?? []), ...remapRegions];
        }

        const resolvedSourceSelection = resolveConverterSourceSelection(state);
        const sourceParams =
          state.source_version === "native"
            ? buildNativeSourceParams(resolvedSourceSelection, state)
            : buildLegacySourceParams(state.lut_name);
        if (!sourceParams) {
          set({
            isGenerating: false,
            error: "请先选择品牌和数据库",
          });
          return null;
        }
        const baseParams = {
          ...sourceParams,
          color_layers:
            sourceParams.source_kind === "native_bundle"
              ? sourceParams.color_layers ?? undefined
              : state.color_layers ?? undefined,
          layer_height_mm:
            sourceParams.source_kind === "native_bundle"
              ? sourceParams.layer_height_mm ?? undefined
              : state.layer_height_mm ?? undefined,
          target_width_mm: state.target_width_mm,
          auto_bg: state.auto_bg,
          bg_tol: state.bg_tol,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          quantize_colors: state.quantize_colors,
          enable_cleanup: state.enable_cleanup,
          hue_weight: state.hue_enable ? 0.5 : 0.0,
          chroma_gate: state.hue_enable ? state.chroma_gate : 0,
          is_dark: useSettingsStore.getState().theme === "dark",
          spacer_thick: state.spacer_thick,
          structure_mode: state.structure_mode,
          separate_backing: state.separate_backing,
          add_loop: state.add_loop,
          loop_width: state.loop_width,
          loop_length: state.loop_length,
          loop_hole: state.loop_hole,
          loop_angle: state.loop_angle,
          loop_offset_x: state.loop_offset_x,
          loop_offset_y: state.loop_offset_y,
          loop_position_preset: state.loop_position_preset,
          enable_relief: state.enable_relief,
          height_mode: state.enable_relief
            ? state.autoHeightMode === "use-heightmap"
              ? "heightmap"
              : "color"
            : undefined,
          color_height_map: state.enable_relief
            ? state.color_height_map
            : undefined,
          heightmap_max_height: state.heightmap_max_height,
          enable_outline: state.enable_outline,
          outline_width: state.outline_width,
          enable_cloisonne: state.enable_cloisonne,
          wire_width_mm: state.wire_width_mm,
          wire_height_mm: state.wire_height_mm,
          enable_coating: state.enable_coating,
          coating_height_mm: state.coating_height_mm,
          ...(sourceParams.source_kind === "native_bundle" &&
          resolvedSourceSelection.native.predictive_model_available
            ? {
                model_enable: state.model_enable,
                model_only: state.model_only,
                model_threshold: state.model_threshold ?? undefined,
                model_margin: state.model_margin ?? undefined,
              }
            : {}),
          enable_fridge_magnet: state.enable_fridge_magnet,
          fridge_magnets:
            state.enable_fridge_magnet && state.fridge_magnets.length > 0
              ? state.fridge_magnets
              : undefined,
          replacement_regions:
            mergedReplacements && mergedReplacements.length > 0
              ? mergedReplacements
              : undefined,
          recipe_overrides: state.recipe_overrides,
          free_color_set:
            state.free_color_set.size > 0
              ? Array.from(state.free_color_set).map((h) => `#${h}`)
              : undefined,
          printer_id: useSettingsStore.getState().printerModel,
          slicer: useSettingsStore.getState().slicerSoftware,
          use_cached_matched_rgb: state.regionReplacementCount > 0,
        } as const;

        if (state.puzzleEnabled) {
          const puzzleResponse = await apiConvertGeneratePuzzle(
            state.sessionId,
            {
              ...buildPuzzlePreviewParams(state),
              params: baseParams,
            },
          );
          set({
            isGenerating: false,
            modelUrl: null,
            threemfDiskPath: puzzleResponse.threemf_disk_path ?? null,
            downloadUrl: puzzleResponse.download_url
              ? `${puzzleResponse.download_url}`
              : null,
            puzzleWarnings: puzzleResponse.warnings ?? [],
            puzzleResolvedRows: puzzleResponse.grid_rows ?? null,
            puzzleResolvedCols: puzzleResponse.grid_cols ?? null,
            puzzleResolvedPieceCount: puzzleResponse.piece_count ?? null,
          });
          _logGenerateTimer('puzzle 3mf received');
          _clientLog('generate: puzzle 3mf received');
          return null;
        }

        if (state.largeFormatEnabled) {
          const lfResponse = await apiConvertGenerateLargeFormat(
            state.sessionId!,
            {
              target_height_mm: state.target_height_mm,
              tile_width_mm: state.tileWidthMm,
              tile_height_mm: state.tileHeightMm,
              params: baseParams,
            },
          );
          set({
            isGenerating: false,
            modelUrl: null,
            threemfDiskPath: null,
            downloadUrl: lfResponse.download_url
              ? `${lfResponse.download_url}`
              : null,
            largeFormatWarnings: lfResponse.warnings ?? [],
          });
          return null;
        }

        _logGenerateTimer('request sent');
        _clientLog('generate: request sent');
        const response = await apiConvertGenerate(state.sessionId, baseParams);
        _logGenerateTimer('response received');
        _clientLog('generate: response received');
        const modelUrl = response.preview_3d_url
          ? `${response.preview_3d_url}`
          : null;
        set({
          isGenerating: false,
          modelUrl,
          threemfDiskPath: response.threemf_disk_path ?? null,
          downloadUrl: response.download_url
            ? `${response.download_url}`
            : null,
          largeFormatWarnings: [],
        });
        _logGenerateTimer('UI unlocked (isGenerating=false, modelUrl set)');
        _clientLog('generate: UI unlocked');
        return modelUrl;
      } catch (err) {
        set({
          isGenerating: false,
          error: err instanceof Error ? err.message : "生成失败",
        });
        return null;
      } finally {
        _endGenerateTimer();
      }
    },

    // --- 裁剪 ---
    setEnableCrop: (enabled: boolean) => {
      set({ enableCrop: enabled });
      try {
        localStorage.setItem("lumina_enableCrop", String(enabled));
      } catch {
        // localStorage unavailable, ignore
      }
    },

    setCropModalOpen: (open: boolean) => set({ cropModalOpen: open }),

    submitCrop: async (x: number, y: number, width: number, height: number) => {
      const state = _get();
      if (!state.imageFile) {
        set({ error: "No image file to crop" });
        return;
      }
      set({ isCropping: true, error: null });
      try {
        const response = await apiCropImage(
          state.imageFile,
          x,
          y,
          width,
          height,
        );
        const croppedFullUrl = `${response.cropped_url}`;

        // Fetch cropped image as Blob to create a new File
        const blob = await fetch(croppedFullUrl).then((r) => r.blob());
        const croppedFile = new File([blob], state.imageFile.name, {
          type: "image/png",
        });

        // Revoke previous preview URL
        const prev = _get().imagePreviewUrl;
        if (prev) URL.revokeObjectURL(prev);

        const newPreviewUrl = URL.createObjectURL(croppedFile);

        // Update aspect ratio from cropped dimensions
        const ratio = response.width / response.height;

        set({
          imageFile: croppedFile,
          imagePreviewUrl: newPreviewUrl,
          aspectRatio: ratio,
          cropModalOpen: false,
          isCropping: false,
        });
      } catch (err) {
        set({
          isCropping: false,
          error: err instanceof Error ? err.message : "Crop failed",
        });
      }
    },

    // --- 自动检测颜色 ---
    autoDetectColors: async () => {
      const state = _get();
      if (!state.imageFile) {
        set({ error: "请先上传图片" });
        return;
      }
      set({ autoDetectColorsLoading: true });
      try {
        const result = await apiAutoDetectColors(
          state.imageFile,
          state.target_width_mm,
        );
        set({
          quantize_colors: clampValue(result.recommended, 8, 256),
          autoDetectColorsLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
        });
      } catch (err) {
        set({
          autoDetectColorsLoading: false,
          error: err instanceof Error ? err.message : "Auto color detection failed",
        });
      }
    },

    // --- 批量模式 ---
    addBatchFiles: (files: File[]) => {
      const valid = files.filter((f) => isValidImageType(f.type, f.name));
      if (valid.length === 0) return;
      set((state) => ({ batchFiles: [...state.batchFiles, ...valid] }));
    },

    removeBatchFile: (index: number) => {
      const state = _get();
      const remaining = state.batchFiles.filter((_, i) => i !== index);

      if (remaining.length === 1) {
        // Auto-downgrade: move last file to imageFile, exit BatchMode
        const lastFile = remaining[0];
        if (isRawFileConverter(lastFile)) {
          set({
            batchFiles: [],
            imageFile: lastFile,
            imagePreviewUrl: null,
            aspectRatio: null,
            batchMode: false,
            hasManualPreview: false,
          });
          uploadImagePreview(lastFile)
            .then(({ preview_url, width, height }) => {
              set({
                imagePreviewUrl: preview_url,
                aspectRatio: width / height,
              });
            })
            .catch(() => {
              /* non-fatal */
            });
        } else {
          const previewUrl = URL.createObjectURL(lastFile);
          const img = new Image();
          img.onload = () => {
            set({ aspectRatio: img.naturalWidth / img.naturalHeight });
          };
          img.src = previewUrl;

          set({
            batchFiles: [],
            imageFile: lastFile,
            imagePreviewUrl: previewUrl,
            batchMode: false,
            hasManualPreview: false,
          });
        }
      } else if (remaining.length === 0) {
        // All files removed: clear all image state
        const prev = state.imagePreviewUrl;
        if (prev) URL.revokeObjectURL(prev);

        set({
          batchFiles: [],
          imageFile: null,
          imagePreviewUrl: null,
          aspectRatio: null,
          previewImageUrl: null,
          originalPreviewUrl: null,
          previewBaseImageUrl: null,
          sessionId: null,
          previewGlbUrl: null,
          ...EMPTY_LUT_MATCH_STATE,
          selectedColor: null,
          selectedColors: new Set<string>(),
          regionData: null,
          selectedRegions: [],
          batchMode: false,
          hasManualPreview: false,
        });
      } else {
        // Still in BatchMode with multiple files
        set({ batchFiles: remaining });
      }
    },

    clearBatchFiles: () =>
      set({
        batchFiles: [],
        ...EMPTY_LUT_MATCH_STATE,
        puzzleEnabled: false,
        threemfDiskPath: null,
        downloadUrl: null,
        previewWarnings: [],
        largeFormatWarnings: [],
        ...DEFAULT_PUZZLE_PREVIEW_STATE,
      }),

    handleFilesSelect: (files: File[]) => {
      // Filter out falsy values and invalid formats
      const validFiles = files.filter(
        (f) => f && isValidImageType(f.type, f.name),
      );
      if (validFiles.length === 0) return;

      const state = _get();
      const inBatchMode = state.batchFiles.length > 0;

      // Already in BatchMode → append new files
      if (inBatchMode) {
        set({
          batchFiles: [...state.batchFiles, ...validFiles],
          batchMode: true,
        });
        return;
      }

      if (validFiles.length === 1) {
        const singleFile = validFiles[0];
        const isSvg =
          singleFile.name.toLowerCase().endsWith(".svg") ||
          singleFile.type === "image/svg+xml";
        const autoModelingMode = isSvg ? ModelingModeEnum.VECTOR : undefined;

        if (isRawFileConverter(singleFile)) {
          const prev = state.imagePreviewUrl;
          if (prev && prev.startsWith("blob:")) URL.revokeObjectURL(prev);
          set({
            imageFile: singleFile,
            imagePreviewUrl: null,
            aspectRatio: null,
            previewImageUrl: null,
            previewBaseImageUrl: null,
            sessionId: null,
            previewGlbUrl: null,
            modelUrl: null,
            threemfDiskPath: null,
            downloadUrl: null,
            previewWarnings: [],
            largeFormatWarnings: [],
            ...EMPTY_LUT_MATCH_STATE,
            puzzleEnabled: false,
            ...DEFAULT_PUZZLE_PREVIEW_STATE,
            batchMode: false,
            hasManualPreview: false,
            cropModalOpen: state.enableCrop,
            layerImages: [],
            layerImagesOpen: false,
          });
          uploadImagePreview(singleFile)
            .then(({ preview_url, width, height }) => {
              set({
                imagePreviewUrl: preview_url,
                aspectRatio: width / height,
              });
            })
            .catch(() => {
              /* non-fatal */
            });
          return;
        }

        if (state.imageFile) {
          const prev = state.imagePreviewUrl;
          if (prev && prev.startsWith("blob:")) URL.revokeObjectURL(prev);

          const previewUrl = URL.createObjectURL(singleFile);
          const img = new Image();
          img.onload = () => {
            set({ aspectRatio: img.naturalWidth / img.naturalHeight });
          };
          img.src = previewUrl;

          set({
            imageFile: singleFile,
            imagePreviewUrl: previewUrl,
            previewImageUrl: null,
            previewBaseImageUrl: null,
            sessionId: null,
            previewGlbUrl: null,
            modelUrl: null,
            threemfDiskPath: null,
            downloadUrl: null,
            previewWarnings: [],
            largeFormatWarnings: [],
            ...EMPTY_LUT_MATCH_STATE,
            puzzleEnabled: false,
            ...DEFAULT_PUZZLE_PREVIEW_STATE,
            batchMode: false,
            hasManualPreview: false,
            cropModalOpen: isSvg ? false : state.enableCrop,
            layerImages: [],
            layerImagesOpen: false,
            ...(autoModelingMode ? { modeling_mode: autoModelingMode } : {}),
          });
        } else {
          const previewUrl = URL.createObjectURL(singleFile);
          const img = new Image();
          img.onload = () => {
            set({ aspectRatio: img.naturalWidth / img.naturalHeight });
          };
          img.src = previewUrl;

          set({
            imageFile: singleFile,
            imagePreviewUrl: previewUrl,
            previewImageUrl: null,
            previewBaseImageUrl: null,
            sessionId: null,
            previewGlbUrl: null,
            modelUrl: null,
            threemfDiskPath: null,
            downloadUrl: null,
            previewWarnings: [],
            largeFormatWarnings: [],
            ...EMPTY_LUT_MATCH_STATE,
            puzzleEnabled: false,
            ...DEFAULT_PUZZLE_PREVIEW_STATE,
            batchMode: false,
            hasManualPreview: false,
            cropModalOpen: isSvg ? false : state.enableCrop,
            layerImages: [],
            layerImagesOpen: false,
            ...(autoModelingMode ? { modeling_mode: autoModelingMode } : {}),
          });
        }
        return;
      }

      // validFiles.length >= 2: enter BatchMode
      // Merge existing imageFile (if any) into batchFiles
      const allFiles = state.imageFile
        ? [state.imageFile, ...validFiles]
        : [...validFiles];

      // Revoke previous preview URL
      const prev = state.imagePreviewUrl;
      if (prev) URL.revokeObjectURL(prev);

      set({
        batchFiles: allFiles,
        imageFile: null,
        imagePreviewUrl: null,
        aspectRatio: null,
        previewImageUrl: null,
        previewBaseImageUrl: null,
        sessionId: null,
        previewGlbUrl: null,
        modelUrl: null,
        threemfDiskPath: null,
        downloadUrl: null,
        previewWarnings: [],
        largeFormatWarnings: [],
        ...EMPTY_LUT_MATCH_STATE,
        puzzleEnabled: false,
        ...DEFAULT_PUZZLE_PREVIEW_STATE,
        batchMode: true,
        hasManualPreview: false,
        layerImages: [],
        layerImagesOpen: false,
      });
      console.log("[DEBUG] handleFilesSelect (batch): cleared layerImages");
    },

    submitBatch: async () => {
      const state = _get();
      set({ batchLoading: true, batchResult: null, error: null });
      try {
        const params = {
          lut_name: state.lut_name,
          target_width_mm: state.target_width_mm,
          spacer_thick: state.spacer_thick,
          structure_mode: state.structure_mode,
          auto_bg: state.auto_bg,
          bg_tol: state.bg_tol,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          quantize_colors: state.quantize_colors,
          enable_cleanup: state.enable_cleanup,
          hue_weight: state.hue_enable ? 0.5 : 0.0,
          chroma_gate: state.hue_enable ? state.chroma_gate : 0,
        };
        const result = await apiConvertBatch(state.batchFiles, params);
        set({ batchResult: result, batchLoading: false });
      } catch (err) {
        set({
          batchLoading: false,
          error: err instanceof Error ? err.message : "批量处理失败",
        });
      }
    },

    // --- 颜色替换：单次即时替换 ---
    submitSingleReplace: async (origHex: string, newHex: string) => {
      const state = _get();
      if (!state.sessionId) return;
      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiReplaceColor(
          state.sessionId,
          `#${origHex}`,
          `#${newHex}`,
        );
        const updates: Partial<ConverterState> = {
          replacePreviewLoading: false,
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
        };
        if (response.preview_3d_url) {
          updates.previewGlbUrl = normalizeResourceUrl(response.preview_3d_url);
        }
        set(updates);
      } catch (err) {
        // 回滚 colorRemapMap 到操作前状态
        const currentHistory = _get().remapHistory;
        if (currentHistory.length > 0) {
          const previousMap = currentHistory[currentHistory.length - 1];
          set({
            colorRemapMap: previousMap,
            remapHistory: currentHistory.slice(0, -1),
            replacePreviewLoading: false,
            error: err instanceof Error ? err.message : "颜色替换失败",
          });
        } else {
          set({
            replacePreviewLoading: false,
            error: err instanceof Error ? err.message : "颜色替换失败",
          });
        }
      }
    },

    // --- 颜色替换预览 ---
    submitReplacePreview: async () => {
      const state = _get();
      const entries = Object.entries(state.colorRemapMap);
      if (entries.length === 0 || !state.sessionId) return;

      set({ replacePreviewLoading: true, error: null });
      try {
        let lastPreviewUrl = state.previewImageUrl;
        let lastGlbUrl: string | null = null;
        for (const [origHex, newHex] of entries) {
          // 查找 palette 中对应的 matched_hex 作为 selected_color
          const paletteEntry = state.palette.find(
            (p) => p.matched_hex === origHex,
          );
          const selectedColor = `#${paletteEntry ? paletteEntry.matched_hex : origHex}`;
          const replacementColor = `#${newHex}`;

          const response = await apiReplaceColor(
            state.sessionId,
            selectedColor,
            replacementColor,
          );
          lastPreviewUrl = normalizeResourceUrl(response.preview_url);
          if (response.preview_3d_url) {
            lastGlbUrl = normalizeResourceUrl(response.preview_3d_url);
          }
        }
        const updates: Partial<ConverterState> = {
          replacePreviewLoading: false,
          previewImageUrl: lastPreviewUrl,
          previewBaseImageUrl: lastPreviewUrl,
        };
        if (lastGlbUrl) {
          updates.previewGlbUrl = lastGlbUrl;
        }
        set(updates);
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "颜色替换预览失败",
        });
      }
    },

    // --- 完整流水线（preview → generate）---
    submitFullPipeline: async () => {
      const state = _get();

      // 步骤 1：如果没有 sessionId，先执行预览
      if (!state.sessionId) {
        await _get().submitPreview();
        // 检查预览是否成功
        const afterPreview = _get();
        if (!afterPreview.sessionId) {
          return null; // 预览失败，错误已由 submitPreview 设置
        }
      }

      // 步骤 2：执行生成
      return await _get().submitGenerate();
    },

    // --- 自由色 ---
    toggleFreeColor: (hex: string) => {
      set((state) => {
        const next = new Set(state.free_color_set);
        if (next.has(hex)) {
          next.delete(hex);
        } else {
          next.add(hex);
        }
        return {
          free_color_set: next,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      });
    },

    clearFreeColors: () => {
      set({
        free_color_set: new Set(),
        threemfDiskPath: null,
        downloadUrl: null,
      });
    },

    // --- UI 状态 ---
    setError: (error: string | null) => set({ error }),
    clearError: () => set({ error: null }),

    // --- 分层预览 ---
    fetchLayerImages: async (previewSourceKey) => {
      const currentState = _get();
      const requestedSourceKey =
        previewSourceKey ?? buildLayerImagesSourceKey(currentState);
      if (!currentState.sessionId || !requestedSourceKey) return;
      const requestedSessionId = currentState.sessionId;
      const shouldClearStaleLayers =
        currentState.layerImages.length > 0 &&
        currentState.layerImagesSourceKey !== requestedSourceKey;

      set({
        ...(shouldClearStaleLayers ? DEFAULT_LAYER_IMAGES_STATE : {}),
        layerImagesLoading: true,
      });
      try {
        const res = await apiFetchLayerImages(requestedSessionId);
        const latestState = _get();
        if (
          latestState.sessionId !== requestedSessionId ||
          res.session_id !== requestedSessionId ||
          buildLayerImagesSourceKey(latestState) !== requestedSourceKey
        ) {
          set({ layerImagesLoading: false });
          return;
        }
        set({
          layerImages: res.layers,
          layerImagesLoading: false,
          layerImagesOpen: true,
          layerImagesSourceKey: requestedSourceKey,
        });
      } catch (e) {
        console.error("fetchLayerImages failed:", e);
        set({ layerImagesLoading: false });
      }
    },
    resetLayerImages: () =>
      set({
        ...DEFAULT_LAYER_IMAGES_STATE,
      }),
    setLayerImagesOpen: (open: boolean) => set({ layerImagesOpen: open }),

    importRecipeState: (partial: Partial<ConverterState>, imageFile: File, heightmapFile?: File | null) => {
      // 1. Apply restored parameters (without triggering crop modal)
      const prevEnableCrop = _get().enableCrop;
      const baseState = _get();
      const nextState = {
        ...baseState,
        ...partial,
        modelBounds: null,
      };
      const fridgeMagnetState = buildFridgeMagnetState(nextState, {
        enable_fridge_magnet: partial.enable_fridge_magnet,
        fridge_magnets: partial.fridge_magnets,
        base_spacer_thick: partial.base_spacer_thick,
      });
      set({
        ...partial,
        modelBounds: null,
        ...fridgeMagnetState,
        engraveBackLabels: false,
        enableCrop: false,
      });

      // 2. Set image file (creates blob URL, triggers preview flow)
      _get().setImageFile(imageFile);

      // 3. Restore crop setting
      set({ enableCrop: prevEnableCrop });

      // 4. Set heightmap if present
      if (heightmapFile) {
        _get().setHeightmapFile(heightmapFile);
      }
    },

    cleanupAfterDownload: () => {
      const state = _get();
      if (!state.sessionId) return;
      // Preserve download, preview, and GLB files so share card export
      // and 3D viewer still work after slicer launch / download.
      const urlsToKeep = [
        state.downloadUrl,
        state.previewImageUrl,
        state.previewBaseImageUrl,
        state.originalPreviewUrl,
        state.previewGlbUrl,
        state.puzzleOverlayUrl,
        state.regionData?.previewUrl ?? null,
        ...state.selectedRegions.map((region) => region.previewUrl),
        ...state.layerImages.map((layer) => layer.url),
      ];
      const keepIds = collectKeepFileIds(urlsToKeep);
      apiCleanupSessionFiles(state.sessionId, keepIds);
    },
  }),
);

if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", () => {
    const { sessionId } = useConverterStore.getState();
    if (sessionId) {
      beaconCleanupSessionFiles(sessionId);
    }
  });
}


