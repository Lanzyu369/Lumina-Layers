import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import type {
  ColorMode,
  ModelingMode,
  StructureMode,
  ColorReplacementItem,
  RecipeOverrideItem,
  RecipeHistoryItem,
  VirtualMaterial,
  BedSizeItem,
  PaletteEntry,
  AutoHeightMode,
  BatchResponse,
  BatchPreviewItem,
  LutInfoResponse,
  FridgeMagnetItem,
  PuzzleConnectorStyle,
  PuzzleSizingMode,
  PuzzleStyle,
  NativeBrandGroup,
  LutSupportedMode,
  LutDetailsCatalogGroup,
  LutColorsCard,
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
  replaceColorsBatch as apiReplaceColorsBatch,
  colorHighlight as apiColorHighlight,
  detectRegion as apiDetectRegion,
  regionReplace as apiRegionReplace,
  regionReplaceBatch as apiRegionReplaceBatch,
  regionRequantize as apiRegionRequantize,
  applyRecipeOverride as apiApplyRecipeOverride,
  resetReplacements as apiResetReplacements,
  autoDetectColors as apiAutoDetectColors,
  cleanupSessionFiles as apiCleanupSessionFiles,
  uploadLut as apiUploadLut,
  getGlbStatus as apiGetGlbStatus,
} from "../../api/converter";
import { closeSession as apiCloseSession } from "../../api/session";
import type { LutColorEntry, LutInfo } from "../../api/types";
import {
  fetchLutInfo as apiFetchLutInfo,
  fetchLutCatalog as apiFetchLutCatalog,
  fetchLutDetailsCatalog as apiFetchLutDetailsCatalog,
  fetchSessionLutInfo as apiFetchSessionLutInfo,
} from "../../api/lut";
import {
  computeAutoHeightMap,
  colorRemapToReplacementRegions,
  toAbsoluteReliefHeightMap,
} from "../../utils/colorUtils";
import { normalizeResourceUrl } from "../../utils/resourceUrl";
import {
  createFridgeMagnetFromPreset,
  getDefaultFridgeMagnetPresetKey,
  normalizeFridgeMagnetItem,
  resolveFridgeMagnetSpacerThick,
} from "../../constants/fridgeMagnets";
import { useSettingsStore } from "../settingsStore";
import {
  postClientLog,
  summarizeErrorForLog,
  summarizeFileForLog,
} from "../../utils/clientLog";
import { trackLuminaEvent } from "../../analytics/umami";
import { registerGeneratedArtifactInvalidator } from "../generatedArtifactInvalidation";
import { uploadImagePreview } from "../../api/system";
import { fetchMaterialColorSuggestions } from "../../api/materialCache";
import { fetchGradientGroups as apiFetchGradientGroups } from "../../api/converter";
import type {
  GradientGroupItem,
  GradientSelectionSource,
  MaterialColorSuggestionsResponse,
} from "../../api/types";
import {
  buildLutCatalogIndex,
  findLutLocationByPath,
} from "./legacyLutSelection";

type LuminaWindow = Window & {
  __luminaGenerateStart?: number;
  __luminaPreviewStart?: number;
};

const BATCH_PREVIEW_BROWSER_SAFE_LIMIT = 96;

// ===========================================================================
// Material-archive achievable-color suggestion helpers (module-local state)
// 材料档案可达色建议的模块级辅助状态（LRU + AbortController）
// ===========================================================================

/**
 * Upper bound on the number of cached suggestion responses kept in memory.
 * Suggestions are small (~4 KB each), and users rarely explore more than a
 * handful of targets per session, so a modest cap avoids unbounded growth
 * while still delivering instant re-picks when the same target is clicked.
 * 缓存上限：每条约 4 KB，此上限既能覆盖典型交互又避免无界增长。
 */
const MATERIAL_SUGGEST_LRU_LIMIT = 64;

/**
 * Insertion-order :class:`Map` used as an LRU cache. Re-inserting on hit
 * refreshes recency; eviction removes the oldest key when capacity is hit.
 * 以插入顺序维护的 LRU：命中时重新插入以刷新，超额时淘汰最早项。
 */
const _materialSuggestCache = new Map<
  string,
  MaterialColorSuggestionsResponse
>();

/**
 * Holds the currently in-flight suggestion request so a newer call can
 * cancel the older one and avoid races on ``materialSuggestions`` state.
 * 持有当前未完成请求，便于后续请求取消前者、避免状态竞态。
 */
let _materialSuggestAbortController: AbortController | null = null;

/**
 * In-flight gradient-groups request controller.
 * 当前未完成的渐变分组请求控制器。
 */
let _gradientGroupsAbortController: AbortController | null = null;

/**
 * Build a deterministic cache key from a suggestion request's parameters.
 * ``directoryNames`` is joined (order-sensitive: we want the user palette
 * ordering preserved, matching the backend recipe rebinding). Substrate is
 * included for forward compatibility once the UI exposes black substrates.
 * 从请求参数生成确定性缓存键；保留耗材顺序以匹配后端配方重绑定语义。
 */
function _materialSuggestCacheKey(params: {
  directoryNames: string[];
  layerCount: number;
  layerHeightMm: number;
  substrate: string;
  targetHex: string;
}): string {
  const dirs = params.directoryNames.join(",");
  const hex = params.targetHex.replace(/^#/, "").toLowerCase();
  return `${dirs}|${params.layerCount}|${params.layerHeightMm}|${params.substrate}|${hex}`;
}

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

function isSvgFile(file: File): boolean {
  return (
    file.type === "image/svg+xml" ||
    file.name.toLowerCase().endsWith(".svg")
  );
}

// ========== Selection Mode Types ==========

export type SelectionMode =
  | "select-all"
  | "current"
  | "multi-select"
  | "region";

export type SourceVersion = "legacy" | "native" | "material";

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

function matchesColorHighlightSnapshot(
  state: Pick<ConverterState, "sessionId" | "selectionMode" | "selectedColors">,
  snapshot: {
    sessionId: string;
    selectionMode: SelectionMode;
    selectedColors: string[];
  },
): boolean {
  if (state.sessionId !== snapshot.sessionId) return false;
  if (state.selectionMode !== snapshot.selectionMode) return false;
  if (state.selectedColors.size !== snapshot.selectedColors.length)
    return false;
  return snapshot.selectedColors.every((hex) => state.selectedColors.has(hex));
}

function getFallbackModelBounds(
  state: Pick<
    ConverterState,
    "modelBounds" | "target_width_mm" | "target_height_mm"
  >,
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
  state: Pick<
    ConverterState,
    "modelBounds" | "target_width_mm" | "target_height_mm"
  >,
): { x: number; y: number } {
  const bounds = getFallbackModelBounds(state);
  return {
    x: (bounds.minX + bounds.maxX) / 2,
    y: (bounds.minY + bounds.maxY) / 2,
  };
}

function getDefaultFridgeMagnetCount(
  state: Pick<
    ConverterState,
    "modelBounds" | "target_width_mm" | "target_height_mm"
  >,
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
    return [
      [0.3, 0.5],
      [0.7, 0.5],
    ];
  }
  if (count === 3) {
    return [
      [0.3, 0.35],
      [0.7, 0.35],
      [0.5, 0.72],
    ];
  }
  if (count === 4) {
    return [
      [0.3, 0.3],
      [0.7, 0.3],
      [0.3, 0.7],
      [0.7, 0.7],
    ];
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
      const xRatio =
        cols === 1 ? 0.5 : marginX + (usableWidth * col) / (cols - 1);
      const yRatio =
        rows === 1 ? 0.5 : marginY + (usableHeight * row) / (rows - 1);
      ratios.push([xRatio, yRatio]);
    }
  }

  return ratios;
}

function buildSuggestedFridgeMagnetCenters(
  state: Pick<
    ConverterState,
    "modelBounds" | "target_width_mm" | "target_height_mm"
  >,
  count: number,
): Array<{ x: number; y: number }> {
  const bounds = getFallbackModelBounds(state);
  const interpolate = (min: number, max: number, ratio: number) =>
    min + (max - min) * ratio;

  return buildFridgeMagnetLayoutRatios(Math.max(1, count)).map(
    ([xRatio, yRatio]) => ({
      x: interpolate(bounds.minX, bounds.maxX, xRatio),
      y: interpolate(bounds.minY, bounds.maxY, yRatio),
    }),
  );
}

function getFridgeMagnetLayoutSize(magnet: FridgeMagnetItem): {
  width: number;
  height: number;
} {
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
  state: Pick<
    ConverterState,
    "modelBounds" | "target_width_mm" | "target_height_mm"
  >,
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
      for (
        let rightIndex = leftIndex + 1;
        rightIndex < positioned.length;
        rightIndex += 1
      ) {
        const left = positioned[leftIndex];
        const right = positioned[rightIndex];
        const leftSize = getFridgeMagnetLayoutSize(left);
        const rightSize = getFridgeMagnetLayoutSize(right);
        const minSeparationX =
          leftSize.width / 2 +
          rightSize.width / 2 +
          FRIDGE_MAGNET_LAYOUT_GAP_MM;
        const minSeparationY =
          leftSize.height / 2 +
          rightSize.height / 2 +
          FRIDGE_MAGNET_LAYOUT_GAP_MM;
        const deltaX = right.center_x_mm - left.center_x_mm;
        const deltaY = right.center_y_mm - left.center_y_mm;
        const overlapX = minSeparationX - Math.abs(deltaX);
        const overlapY = minSeparationY - Math.abs(deltaY);

        if (overlapX <= 0 || overlapY <= 0) {
          continue;
        }

        const leftRoomX = left.center_x_mm - (bounds.minX + leftSize.width / 2);
        const rightRoomX =
          bounds.maxX - rightSize.width / 2 - right.center_x_mm;
        const leftRoomY =
          left.center_y_mm - (bounds.minY + leftSize.height / 2);
        const rightRoomY =
          bounds.maxY - rightSize.height / 2 - right.center_y_mm;
        const roomX = Math.max(0, leftRoomX) + Math.max(0, rightRoomX);
        const roomY = Math.max(0, leftRoomY) + Math.max(0, rightRoomY);
        const separateOnX =
          roomX >= overlapX && (roomX >= roomY || roomY < overlapY);
        const directionX =
          deltaX === 0 ? (leftIndex % 2 === 0 ? -1 : 1) : Math.sign(deltaX);
        const directionY =
          deltaY === 0 ? (leftIndex % 2 === 0 ? -1 : 1) : Math.sign(deltaY);

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
    return layoutFridgeMagnetsByCenters(
      state,
      normalizedMagnets,
      sanitizedCenters,
    );
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
  state: Pick<
    ConverterState,
    "modelBounds" | "target_width_mm" | "target_height_mm"
  >,
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

  return layoutFridgeMagnetsByCenters(
    state,
    magnets,
    magnets.map((magnet) => ({
      x: magnet.center_x_mm,
      y: magnet.center_y_mm,
    })),
  );
}

function autoLayoutFridgeMagnets(
  state: Pick<
    ConverterState,
    "modelBounds" | "target_width_mm" | "target_height_mm" | "fridge_magnets"
  >,
): FridgeMagnetItem[] {
  const currentMagnets = state.fridge_magnets.map(normalizeFridgeMagnetItem);
  if (currentMagnets.length === 0) {
    return [];
  }

  const centers = buildSuggestedFridgeMagnetCenters(
    state,
    currentMagnets.length,
  );
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
    Pick<
      ConverterState,
      "enable_fridge_magnet" | "fridge_magnets" | "base_spacer_thick"
    >
  >,
): Pick<
  ConverterState,
  | "enable_fridge_magnet"
  | "fridge_magnets"
  | "base_spacer_thick"
  | "spacer_thick"
> {
  const baseSpacerThick =
    overrides?.base_spacer_thick ?? state.base_spacer_thick;
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
  state: Pick<
    ConverterState,
    "previewBaseImageUrl" | "originalPreviewUrl" | "previewImageUrl"
  >,
): string | null {
  return (
    state.previewBaseImageUrl ??
    state.originalPreviewUrl ??
    state.previewImageUrl
  );
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

function normalizePublicColorMode(value: string): ColorMode {
  return value === "8-Color" ? ColorModeEnum.EIGHT_COLOR : (value as ColorMode);
}

function normalizeLutColorMode<T extends { color_mode?: string }>(info: T): T {
  if (!info.color_mode) {
    return info;
  }
  const colorMode = normalizePublicColorMode(info.color_mode);
  return colorMode === info.color_mode
    ? info
    : { ...info, color_mode: colorMode };
}

function normalizeLutGroups<
  TGroup extends { items?: TItem[] },
  TItem extends { color_mode?: string },
>(groups: TGroup[]): TGroup[] {
  return groups.map((group) => ({
    ...group,
    items: (group.items ?? []).map(normalizeLutColorMode),
  }));
}

function normalizeNativeBrandGroups(
  groups: NativeBrandGroup[],
): NativeBrandGroup[] {
  return groups.map((group) => ({
    ...group,
    db_options: group.db_options.map(normalizeLutColorMode),
  }));
}

function getNativeBrandGroupByKey(
  groups: NativeBrandGroup[],
  brandKey: string,
): NativeBrandGroup | null {
  return groups.find((group) => group.brand_key === brandKey) ?? null;
}

function filterNativeBrandGroups(
  groups: NativeBrandGroup[],
): NativeBrandGroup[] {
  return groups.filter((group) => group.brand_key === "bambulab_pla");
}

function getNativeDbOptionNames(group: NativeBrandGroup | null): string[] {
  return group
    ? normalizeStringArray(group.db_options.map((option) => option.name))
    : [];
}

function hasNativePredictiveModel(group: NativeBrandGroup | null): boolean {
  return Boolean(group?.package_name?.trim() || group?.model_name?.trim());
}

function buildNativeModelDefaults(
  group: NativeBrandGroup | null,
): Pick<
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
    | "selectedNativeBrandKey"
    | "model_enable"
    | "model_only"
    | "model_threshold"
    | "model_margin"
  >,
): Pick<
  ConverterState,
  "model_enable" | "model_only" | "model_threshold" | "model_margin"
> {
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
    const byKey = getNativeBrandGroupByKey(
      state.nativeBrandGroups,
      state.selectedNativeBrandKey,
    );
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
  return normalizeStringArray(
    group.default_db_names.filter((name) => allowed.has(name)),
  );
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
  const exactMode = getSupportedModeByPair(
    supported_modes,
    colorLayers,
    layerHeightMm,
  );
  if (exactMode) {
    return exactMode;
  }
  const preferredFive = supported_modes.find((mode) => mode.color_layers === 5);
  if (preferredFive) {
    return preferredFive;
  }
  if (layerHeightMm != null) {
    const matchingHeight = supported_modes.filter(
      (mode) => mode.layer_height_mm === layerHeightMm,
    );
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
  const db_names =
    state.selectedNativeDbNames.length === 0
      ? []
      : selectedDbNames.length > 0
        ? selectedDbNames
        : normalizeStringArray(
            brand.default_db_names.filter((name) => allowedNames.has(name)),
          );
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
    | "selectedMaterialDirNames"
    | "materialLayerCount"
    | "materialLayerHeightMm"
  >,
): {
  source_kind: "legacy_single" | "native_bundle";
  isReady: boolean;
  isMaterial: boolean;
  lut_name: string;
  db_names: string[];
  native: ReturnType<typeof resolveNativeBrandSelection>;
  color_layers: number | null;
  layer_height_mm: number | null;
} {
  const emptyNative = {
    brand: null,
    db_names: [] as string[],
    supported_mode: null,
    supported_modes: [] as { color_layers: number; layer_height_mm: number }[],
    predictive_model_available: false,
    isReady: false,
  };

  if (state.source_version === "material") {
    return {
      source_kind: "legacy_single",
      isReady: (state.selectedMaterialDirNames ?? []).length > 0,
      isMaterial: true,
      lut_name: "",
      db_names: [],
      native: emptyNative,
      color_layers: state.materialLayerCount ?? 5,
      layer_height_mm: state.materialLayerHeightMm ?? 0.08,
    };
  }

  if (state.source_version === "legacy") {
    return {
      source_kind: "legacy_single",
      isReady: state.lut_name.length > 0,
      isMaterial: false,
      lut_name: state.lut_name,
      db_names: [],
      native: emptyNative,
      color_layers: null,
      layer_height_mm: null,
    };
  }

  const native = resolveNativeBrandSelection(state);
  return {
    source_kind: "native_bundle",
    isReady: native.isReady,
    isMaterial: false,
    lut_name: "",
    db_names: native.db_names,
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

function buildMaterialSourceParams(
  state: Pick<
    ConverterState,
    | "selectedMaterialDirNames"
    | "materialLayerCount"
    | "materialLayerHeightMm"
    | "materialBackingMaterialDirName"
  >,
) {
  const settingsState = useSettingsStore.getState();
  const materialGridResolution = settingsState.enableSolverCacheGridSelection
    ? settingsState.solverCacheGridResolution
    : undefined;
  const backingMaterialIndex = state.materialBackingMaterialDirName
    ? state.selectedMaterialDirNames.indexOf(
        state.materialBackingMaterialDirName,
      )
    : 0;
  return {
    source_kind: "legacy_single" as const,
    lut_name: "__material_archive__",
    material_source: "material_archive" as const,
    selected_materials: state.selectedMaterialDirNames,
    material_layer_count: state.materialLayerCount,
    material_layer_height_mm: state.materialLayerHeightMm,
    material_grid_resolution: materialGridResolution,
    material_backing_material_index:
      backingMaterialIndex >= 0 ? backingMaterialIndex : 0,
  };
}

function buildNativeSourceParams(
  selection: ReturnType<typeof resolveConverterSourceSelection>,
  modelState?: Pick<
    ConverterState,
    "model_enable" | "model_only" | "model_threshold" | "model_margin"
  >,
) {
  if (selection.source_kind !== "native_bundle" || !selection.native.brand) {
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

function extractFileIdFromApiUrl(
  url: string | null | undefined,
): string | null {
  if (!url) return null;
  const match = url.match(/\/api\/files\/([^/?#]+)/);
  return match ? match[1] : null;
}

function collectKeepFileIds(urls: Array<string | null | undefined>): string[] {
  const keepIds = new Set<string>();
  for (const url of urls) {
    const fileId = extractFileIdFromApiUrl(url);
    if (fileId) {
      keepIds.add(fileId);
    }
  }
  return Array.from(keepIds);
}

export function collectConverterKeepFileIds(state: {
  downloadUrl: string | null;
  previewImageUrl: string | null;
  previewBaseImageUrl: string | null;
  originalPreviewUrl: string | null;
  previewGlbUrl: string | null;
  puzzleOverlayUrl: string | null;
  batchPreviewItems: Array<{ url: string | null }>;
  regionData: { previewUrl: string | null } | null;
  selectedRegions: Array<{ previewUrl: string | null }>;
  layerImages: Array<{ url: string | null }>;
}): string[] {
  return collectKeepFileIds([
    state.downloadUrl,
    state.previewImageUrl,
    state.previewBaseImageUrl,
    state.originalPreviewUrl,
    state.previewGlbUrl,
    state.puzzleOverlayUrl,
    ...state.batchPreviewItems.map((item) => item.url),
    state.regionData?.previewUrl ?? null,
    ...state.selectedRegions.map((region) => region.previewUrl),
    ...state.layerImages.map((layer) => layer.url),
  ]);
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

  // Material-archive mode
  selectedMaterialDirNames: string[];
  materialLayerCount: number;
  materialLayerHeightMm: number;
  materialBackingMaterialDirName: string | null;

  // 高级设置
  quantize_colors: number;
  quantize_colors_unlocked: boolean;
  enable_cleanup: boolean;
  hue_enable: boolean;
  use_lut_constrained: boolean;
  auto_dynamic_range: boolean;
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
  customRecipeHistory: RecipeHistoryItem[];
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
  legacyCatalogGroups: LutDetailsCatalogGroup[];
  legacyCatalogLoading: boolean;
  selectedLegacyManufacturer: string;

  // LUT 全部颜色
  lutColors: LutColorEntry[];
  lutColorCards: LutColorsCard[];
  lutColorsLoading: boolean;
  lutColorsLutName: string;

  // 材料档案模式下的可达色建议（替换 lutColors 的作用）
  // Material-archive mode's achievable-color suggestions (replaces lutColors).
  materialSuggestions: MaterialColorSuggestionsResponse | null;
  materialSuggestionsLoading: boolean;
  materialSuggestionsTargetHex: string | null;
  materialSuggestionsError: string | null;

  // 预览完成后后端同步计算的"渐变海带纹分组"。用于颜色工作站的按组多选替换
  // 以及可选的自动去海带纹批量换色。未计算 / 未命中时保持为 ``null``。
  // Gradient-banding groups computed synchronously by the preview pipeline.
  // Drives the Color Workstation group multi-select flow and the optional
  // "auto replace gradient banding" setting. Stays ``null`` until a fetch
  // completes; ``[]`` means the backend ran but reported no banding.
  gradientGroups: GradientGroupItem[] | null;
  gradientGroupsLoading: boolean;
  gradientGroupsError: string | null;
  /** Session ID of the currently-loaded groups (for staleness checks). */
  gradientGroupsSessionId: string | null;
  /**
   * Which gradient group/region the user most recently clicked in the
   * Gradient Groups panel. ``null`` when the current multi-selection was not
   * initiated from the panel. UI uses this to disambiguate group vs region
   * highlight when their hex sets are identical.
   *
   * 面板最近一次点击的分组/区域标识；当前多选不是由面板发起时为 null。
   */
  gradientSelection: GradientSelectionSource | null;

  /**
   * Ordered list of regions the user ticked in the Gradient Groups panel
   * for merged flatten/recolor. All entries share the same ``groupIndex``
   * (same-group invariant enforced by the toggle action). Empty array
   * means "no multi-region selection" — the existing single-region /
   * single-group flows stay untouched.
   * 用户在面板勾选的 region 列表（保持勾选顺序），用于"合并去海带纹 / 合并
   * 换色"；同 group 不变式由 toggle action 守护。
   */
  selectedGradientRegions: Array<{
    groupIndex: number;
    regionIndex: number;
  }>;

  // 热床尺寸
  bed_label: string;
  bedSizes: BedSizeItem[];
  bedSizesLoading: boolean;

  // 批量模式
  batchMode: boolean;
  batchFiles: File[];
  batchLoading: boolean;
  batchResult: BatchResponse | null;
  batchPreviewItems: BatchPreviewItem[];

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
  loadVectorizedSvgIntoConverter: (file: File) => void;

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
  setQuantizeColors: (colors: number) => void;
  setQuantizeColorsUnlocked: (unlocked: boolean) => void;
  setEnableCleanup: (enabled: boolean) => void;
  setHueEnable: (enabled: boolean) => void;
  setUseLutConstrained: (enabled: boolean) => void;
  setAutoDynamicRange: (enabled: boolean) => void;
  setChromaGate: (threshold: number) => void;
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
  applyCustomRecipeOverride: (
    regionIds: string[],
    recipe: number[],
    layerOrder?: string,
    /** Virtual materials declared at apply time; required when ``recipe`` carries indices ``>= LUT.N``. */
    virtualMaterials?: VirtualMaterial[],
  ) => Promise<void>;
  upsertRecipeOverrides: (
    regionIds: string[],
    recipe: number[],
    layerOrder: string,
    /** Optional virtuals to persist alongside the override so ``/generate`` can extend the palette. */
    virtualMaterials?: VirtualMaterial[],
  ) => void;
  clearRecipeOverrides: (regionIds?: string[]) => void;
  /** 追加一条历史；按 id LRU 置顶，容量 10。 */
  pushCustomRecipeHistory: (item: RecipeHistoryItem) => void;
  /** 清空历史（一般在 submitPreview 之外很少主动调）。 */
  clearCustomRecipeHistory: () => void;
  /** 应用一条历史到当前选区；内部复用 applyCustomRecipeOverride。 */
  applyCustomRecipeFromHistory: (
    historyId: string,
    regionIds: string[],
  ) => Promise<void>;

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

  /**
   * Poll ``/api/convert/glb-status`` after a replace-* endpoint returned
   * ``preview_glb_url: null``; on ``ready`` the new URL is written into
   * ``previewGlbUrl``. Re-entrant: later replace calls override the
   * poller via a monotonic token so stale results can never overwrite
   * the freshest GLB. 异步 GLB 轮询；各 replace 成功后一行调用即可。
   */
  _pollAsyncGlb: () => void;

  // 模型边界
  setModelBounds: (bounds: ConverterState["modelBounds"]) => void;

  // API 操作
  uploadLut: (file: File) => Promise<void>;
  fetchLutList: () => Promise<void>;
  fetchLutCatalog: () => Promise<void>;
  fetchLegacyCatalog: () => Promise<void>;
  setLegacyManufacturer: (name: string) => void;
  fetchLutColors: (lutName: string) => Promise<void>;

  // 材料档案模式下按目标色请求建议
  // Query achievable-color suggestions for a target hex (material-archive mode).
  fetchMaterialSuggestions: (targetHex: string) => Promise<void>;
  clearMaterialSuggestions: () => void;

  /**
   * Pull the preview's gradient-banding groups from the backend session.
   * Safe to call multiple times: if ``sessionId`` matches the currently
   * loaded groups the call is a cheap no-op. A new session triggers a
   * fresh fetch that aborts any in-flight request.
   *
   * 从后端 session 拉取渐变海带纹分组：同 sessionId 直接复用缓存，不同则
   * 触发新请求并取消旧请求。
   */
  fetchGradientGroups: (sessionId: string) => Promise<void>;
  /** Reset gradient-group state (e.g. on new image upload or mode switch). */
  clearGradientGroups: () => void;
  /**
   * Collapse every gradient group to its representative colour by populating
   * ``colorRemapMap`` with non-representative → representative pairs and
   * flushing the batch through the existing replace-preview path.
   *
   * 把每个渐变分组统一替换为代表色：在 ``colorRemapMap`` 里注册非代表色 →
   * 代表色的映射，然后走既有的 ``submitReplacePreview`` 批量通道。
   *
   * Called automatically when ``autoReplaceGradientBanding`` is on, but
   * also exposed so a button can trigger it on demand.
   */
  applyAutoGradientReplace: () => Promise<void>;
  /**
   * Replace ``selectedColors`` with the given hexes in one shot and switch
   * to ``select-all`` mode. Used by the Gradient Groups panel so a single
   * click multi-selects every colour inside a gradient group or region
   * without firing N sequential highlight requests. When ``source`` is
   * provided the store remembers *which* group/region triggered the batch
   * so the panel can highlight exactly one row even when a region and its
   * enclosing group share an identical hex set.
   *
   * 一次性把渐变分组内的所有耗材色写入多选集合：切到 select-all 模式 +
   * 合并成一次高亮预览请求。传 ``source`` 可记录触发本次多选的分组/区域，
   * 供面板按钮排它性高亮使用。
   */
  selectGradientGroupColors: (
    hexes: string[],
    source?: GradientSelectionSource,
  ) => void;
  /**
   * Flatten gradient banding for a single group — or a specific region
   * inside that group — without requiring the user to first multi-select
   * and pick a target colour. Mirrors :func:`applyAutoGradientReplace`
   * but scoped to one gradient, so the user can fix one band at a time.
   *
   * 针对单个渐变分组（或组内某个区域）一键去除海带纹：把非代表色映射
   * 到代表色并走 ``submitReplacePreview`` 刷预览，无需先选中再拾色器。
   */
  applyGradientReplaceForGroup: (
    groupIndex: number,
    regionIndex?: number,
  ) => Promise<void>;
  /**
   * Replace the pixels inside exactly one gradient sub-region with
   * ``targetHex``. Backed by ``POST /api/convert/region-replace`` with
   * ``gradient_group_index`` / ``gradient_region_index``; the server
   * rebuilds the mask from the cached per-pixel ``gradient_region_id_map``
   * so only that banded region changes, even when other regions on the
   * canvas share the same quantised hex.
   *
   * Unlike :func:`confirmReplacement` + ``colorRemapMap`` (which is a
   * whole-image ``hex → hex`` mapping and would recolour every matching
   * pixel), this action is strictly spatial. Callers are the Gradient
   * Groups panel + LUT picker when the current selection originated from
   * a region button.
   *
   * 仅替换某个 gradient 子区域内的像素为 ``targetHex``。用后端 region-replace
   * 的 gradient 路径，通过缓存的 region_id_map 精确定位，不会误伤共享
   * 同一量化 hex 的其它区域——修复"换一条 cyan 带 → 全身皮肤变色"的 bug。
   */
  applyGradientRegionPixelReplace: (
    groupIndex: number,
    regionIndex: number,
    targetHex: string,
  ) => Promise<void>;

  /**
   * Toggle a sub-region's checkbox in the Gradient Groups panel.
   *
   * Same-group invariant: if the new region's ``groupIndex`` differs from
   * the current selection's group, the existing list is dropped and only
   * the new region kept. This prevents users accidentally merging regions
   * from unrelated gradients (e.g. a sky band + a skin band) while still
   * letting them switch groups smoothly without an explicit clear.
   * 勾选同一 group 内的 region；点了别的 group 的 region 时清空旧选择，
   * 避免把不相关的渐变误合并。
   */
  toggleGradientRegionSelection: (
    groupIndex: number,
    regionIndex: number,
  ) => void;
  /** Clear all multi-region checkboxes. 清空多区域勾选。 */
  clearGradientRegionSelection: () => void;
  /**
   * Flatten the currently-checked regions by computing one pixel-count-
   * weighted representative colour across their union and repainting all
   * of them to that colour in a single ``/region-replace-batch`` call.
   * Noop when fewer than 2 regions are selected.
   * 对勾选的 region 求像素加权代表色，一次 batch 调用统一刷成该色。
   */
  flattenSelectedGradientRegions: () => Promise<void>;
  /**
   * Re-quantise gradient regions through the material-archive solver with
   * a fresh per-region palette of ``localQuantizeColors`` colours (range
   * 12-256). Unlike flatten which collapses everything to one
   * representative hex, this keeps each region's low-frequency gradient
   * by giving it a dedicated colour budget and re-matching those colours
   * to material recipes.
   *
   * Two call modes:
   *   - **Implicit** (``targets`` omitted): operates on
   *     ``selectedGradientRegions`` (the checkbox-driven list) and clears
   *     it on success so the panel resets to "nothing checked".
   *   - **Explicit** (``targets`` provided): operates on the caller-
   *     supplied list. Leaves ``selectedGradientRegions`` untouched so a
   *     per-region "re-quantize" button can run without nuking an
   *     unrelated batch selection the user was assembling.
   *
   * 支持两种调用形式：缺省 targets 走当前勾选列表并清空；显式 targets
   * 则仅量化调用方传入的 region 并保留 ``selectedGradientRegions``，便于
   * "某一个 region 单独二次量化"的按钮不破坏用户正在构造的批量选择。
   */
  requantizeSelectedGradientRegions: (
    localQuantizeColors: number,
    targets?: ReadonlyArray<{ groupIndex: number; regionIndex: number }>,
  ) => Promise<void>;
  /**
   * Repaint every currently-checked region with ``targetHex`` via a single
   * ``/region-replace-batch`` call. Used by the LUT picker flow when the
   * user has a multi-region selection and picks a target colour.
   * 用户从 LUT 选定 ``targetHex`` 后，把所有勾选的 region 一次 batch 刷成该色。
   */
  applyMultiRegionPixelReplace: (targetHex: string) => Promise<void>;
  setSourceVersion: (version: SourceVersion) => void;
  setSelectedMaterialDirNames: (names: string[]) => void;
  setMaterialLayerCount: (count: number) => void;
  setMaterialLayerHeightMm: (height: number) => void;
  setMaterialBackingMaterialDirName: (name: string | null) => void;
  setNativeBrandKey: (brandKey: string) => void;
  setNativeSupportedMode: (mode: {
    color_layers: number;
    layer_height_mm: number;
  }) => void;
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
  importRecipeState: (
    partial: Partial<ConverterState>,
    imageFile: File,
    heightmapFile?: File | null,
  ) => void;
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

/**
 * Partial invalidation for cached per-layer preview images after a color
 * replacement. Preserves `layerImagesOpen` (user panel visibility) and
 * `layerImagesLoading`, but drops stale image URLs and source key so the
 * next hover/fetch refreshes layer data against the new preview.
 * 颜色替换后用于失效分层预览图缓存的局部状态：保留用户面板可见性与
 * 加载状态，清除过期的图片 URL 与 source key，确保下次悬停/拉取
 * 能针对新预览刷新分层数据。
 */
const INVALIDATE_LAYER_IMAGES_AFTER_REPLACE = {
  layerImages: [] as { layer_index: number; name: string; url: string }[],
  layerImagesSourceKey: null as string | null,
} as const;

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
    batchPreviewItems: [],
    threemfDiskPath: null,
    downloadUrl: null,
    palette: [],
    colorContours: {},
    colorRemapMap: {},
    remapHistory: [],
    replacement_regions: [],
    recipe_overrides: [],
    customRecipeHistory: [],
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

function buildMissingAutoReliefHeightMap(
  state: Pick<
    ConverterState,
    | "enable_relief"
    | "autoHeightMode"
    | "color_height_map"
    | "heightmap_max_height"
    | "palette"
    | "lutColors"
  >,
  paletteOverride?: PaletteEntry[],
): Record<string, number> | null {
  if (!state.enable_relief) return null;
  if (state.autoHeightMode === "use-heightmap") return null;
  if (Object.keys(state.color_height_map).length > 0) return null;
  const palette =
    paletteOverride ??
    (state.palette.length > 0
      ? state.palette
      : state.lutColors.map((color: LutColorEntry) => {
          const hex = color.hex.replace(/^#/, "").toLowerCase();
          return {
            quantized_hex: hex,
            matched_hex: hex,
            pixel_count: 0,
            percentage: 0,
          };
        }));
  if (palette.length === 0) return null;
  return computeAutoHeightMap(
    palette,
    state.autoHeightMode,
    state.heightmap_max_height,
  );
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

const SELECTED_MATERIAL_DIR_NAMES_KEY = "lumina_selectedMaterialDirNames";
const MATERIAL_BACKING_MATERIAL_DIR_NAME_KEY =
  "lumina_materialBackingMaterialDirName";

function loadSelectedMaterialDirNames(): string[] {
  try {
    const raw = localStorage.getItem(SELECTED_MATERIAL_DIR_NAMES_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (value): value is string =>
        typeof value === "string" && value.trim().length > 0,
    );
  } catch {
    return [];
  }
}

function persistSelectedMaterialDirNames(names: string[]): void {
  try {
    localStorage.setItem(
      SELECTED_MATERIAL_DIR_NAMES_KEY,
      JSON.stringify(names),
    );
  } catch {
    /* localStorage unavailable, ignore */
  }
}

function loadMaterialBackingMaterialDirName(): string | null {
  try {
    const raw = localStorage.getItem(MATERIAL_BACKING_MATERIAL_DIR_NAME_KEY);
    return raw && raw.trim().length > 0 ? raw : null;
  } catch {
    return null;
  }
}

function persistMaterialBackingMaterialDirName(name: string | null): void {
  try {
    if (name && name.trim().length > 0) {
      localStorage.setItem(MATERIAL_BACKING_MATERIAL_DIR_NAME_KEY, name);
    } else {
      localStorage.removeItem(MATERIAL_BACKING_MATERIAL_DIR_NAME_KEY);
    }
  } catch {
    return;
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
  selectedMaterialDirNames: loadSelectedMaterialDirNames(),
  materialLayerCount: 5,
  materialLayerHeightMm: 0.08,
  materialBackingMaterialDirName: loadMaterialBackingMaterialDirName(),
  quantize_colors: 48,
  quantize_colors_unlocked: false,
  enable_cleanup: true,
  hue_enable: false,
  use_lut_constrained: false,
  auto_dynamic_range: false,
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
  customRecipeHistory: [],
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
  legacyCatalogGroups: [],
  legacyCatalogLoading: false,
  selectedLegacyManufacturer: "",
  lutColors: [],
  lutColorCards: [],
  lutColorsLoading: false,
  lutColorsLutName: "",
  materialSuggestions: null,
  materialSuggestionsLoading: false,
  materialSuggestionsTargetHex: null,
  materialSuggestionsError: null,
  gradientGroups: null,
  gradientGroupsLoading: false,
  gradientGroupsError: null,
  gradientGroupsSessionId: null,
  gradientSelection: null,
  selectedGradientRegions: [],
  bed_label: "256脳256 mm",
  bedSizes: [],
  bedSizesLoading: false,
  batchMode: false,
  batchFiles: [],
  batchLoading: false,
  batchResult: null,
  batchPreviewItems: [],
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
let _previewStartTime: number | null = null;
const _PREVIEW_TIMER_LABEL = "[LUMINA] preview";
let _previewTimerActive = false;
let _generateStartTime: number | null = null;
const _GENERATE_TIMER_LABEL = "[LUMINA] generate";
let _generateTimerActive = false;

function _startPreviewTimer(): void {
  if (_previewTimerActive) {
    try {
      console.timeEnd(_PREVIEW_TIMER_LABEL);
    } catch {
      void 0;
    }
  }
  console.time(_PREVIEW_TIMER_LABEL);
  _previewTimerActive = true;
}

function _logPreviewTimer(message: string): void {
  if (!_previewTimerActive) return;
  try {
    console.timeLog(_PREVIEW_TIMER_LABEL, message);
  } catch {
    void 0;
  }
}

function _endPreviewTimer(): void {
  if (!_previewTimerActive) return;
  try {
    console.timeEnd(_PREVIEW_TIMER_LABEL);
  } catch {
    void 0;
  }
  _previewTimerActive = false;
}

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

function _previewClientLog(
  label: string,
  details?: Record<string, unknown>,
  method: "log" | "warn" | "error" = "log",
) {
  postClientLog(label, {
    startTime: _previewStartTime,
    details,
    scope: "preview",
    phase: label,
    method,
  });
}

function _clientLog(
  label: string,
  details?: Record<string, unknown>,
  method: "log" | "warn" | "error" = "log",
) {
  postClientLog(label, {
    startTime: _generateStartTime,
    details,
    scope: "generate",
    phase: label,
    method,
  });
}

function getElapsedMsSince(startTime: number | null): number | null {
  if (startTime == null || typeof performance === "undefined") {
    return null;
  }
  return Math.round(performance.now() - startTime);
}

function getFileCountBucket(count: number): string {
  if (count <= 0) return "0";
  if (count === 1) return "1";
  if (count <= 5) return "2-5";
  if (count <= 10) return "6-10";
  if (count <= 25) return "11-25";
  return "26+";
}

function getErrorType(error: unknown): string {
  return error instanceof Error ? error.name : typeof error;
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

// ========== Async segmented-GLB polling ==========
//
// The backend replace endpoints (replace-color, region-replace and their
// batch variants, apply-recipe-override, reset-replacements) now return
// ``preview_glb_url: null`` immediately and rebuild the segmented GLB on
// a background thread — this dropped the typical ``/region-replace``
// latency from ~45 s to ~10 s for 6 Mpix images. The frontend therefore
// has to poll ``/api/convert/glb-status/{sid}`` after every replace to
// pick up the new GLB URL once the worker finishes.
// 由于 replace 端点改为异步生成 GLB，前端需要在每次 replace 后轮询
// /glb-status，拿到新 URL 后再刷新 3D 预览（previewGlbUrl）。
const GLB_POLL_INTERVAL_MS = 500;
// Segmented-GLB builds for large material-archive images can run 35–60 s;
// allow 5 minutes of wall time before giving up so we don't leave the
// user staring at a stale 3D preview during very heavy edits.
// 超大图的 GLB 构建可达分钟级；给 5 分钟上限避免永久轮询。
const GLB_POLL_MAX_MS = 5 * 60_000;
// Monotonic token used by every poll loop; starting a new poll or
// changing sessionId bumps this so any older loop exits on its next tick.
// 单调递增的 token：新轮询/切换 session 都会自增，旧循环下一轮检测到 token
// 变了就退出，避免多路 polling 互相覆盖 previewGlbUrl。
let _glbPollSequence = 0;

function _startGlbStatusPolling(
  sessionId: string,
  applyGlbResult: (
    url: string,
    colorContours?: Record<string, number[][][]> | null,
  ) => void,
  getCurrentSessionId: () => string | null,
): void {
  _glbPollSequence += 1;
  const mySeq = _glbPollSequence;
  const started = Date.now();

  const tick = async (): Promise<void> => {
    // Lost-focus guard: if a newer poll started, the user switched
    // sessions, or we've been polling longer than the max, exit silently.
    // 三重退出条件：被新轮询覆盖 / session 切换 / 达到超时上限。
    if (_glbPollSequence !== mySeq) return;
    if (getCurrentSessionId() !== sessionId) return;
    if (Date.now() - started > GLB_POLL_MAX_MS) return;

    try {
      const status = await apiGetGlbStatus(sessionId);
      // Re-check all guards after the awaited round-trip: another replace
      // may have scheduled a newer build while we waited, and its token
      // will surface via the next poll started by that replace — we must
      // not race it by writing stale state here.
      // 网络往返后再次校验，避免把中途被覆盖的旧 URL 写进 state。
      if (_glbPollSequence !== mySeq) return;
      if (getCurrentSessionId() !== sessionId) return;

      if (status.status === "ready" && status.glb_url) {
        const normalized = normalizeResourceUrl(status.glb_url);
        if (normalized) {
          applyGlbResult(normalized, status.color_contours ?? null);
        }
        return;
      }
      if (status.status === "error") {
        // GLB build failed but the 2D preview already updated; keep the
        // old 3D preview rather than surfacing a modal — the user can
        // retry via any replace action to re-trigger a build.
        // GLB 生成失败时不弹错；2D 已可用，旧 3D 继续显示，再次替换即重试。
        postClientLog("converter: glb async build failed", {
          scope: "converter",
          phase: "glb-error",
          details: { session_id: sessionId, error: status.error },
        });
        return;
      }
      // idle / pending — continue polling on next tick.
      // idle / pending 继续轮询下一轮。
      window.setTimeout(() => {
        void tick();
      }, GLB_POLL_INTERVAL_MS);
    } catch (err) {
      // Network blip: log and stop. Next replace will kick off a fresh
      // poll, so we'd only mask a transient error by retrying here.
      // 网络抖动时停止，下一次 replace 会重新起轮询，无需原地重试。
      postClientLog("converter: glb poll network error", {
        scope: "converter",
        phase: "glb-poll-error",
        details: { session_id: sessionId, error: summarizeErrorForLog(err) },
      });
    }
  };

  window.setTimeout(() => {
    void tick();
  }, GLB_POLL_INTERVAL_MS);
}

// ========== Store ==========

export const useConverterStore = create<ConverterState & ConverterActions>()(
  subscribeWithSelector((set, _get) => ({
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

    loadVectorizedSvgIntoConverter: (file: File) => {
      if (_previewAbortController) {
        _previewAbortController.abort();
        _previewAbortController = null;
      }
      _gradientGroupsAbortController?.abort();
      _gradientGroupsAbortController = null;

      const prev = _get().imagePreviewUrl;
      if (prev && prev.startsWith("blob:")) {
        URL.revokeObjectURL(prev);
      }

      const previewUrl = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        set({ aspectRatio: img.naturalWidth / img.naturalHeight });
      };
      img.src = previewUrl;

      set({
        imageFile: file,
        imagePreviewUrl: previewUrl,
        aspectRatio: null,
        ...buildPreviewSessionResetState(),
        modeling_mode: ModelingModeEnum.VECTOR,
        isLoading: false,
        error: null,
        cropModalOpen: false,
        batchMode: false,
        batchFiles: [],
        batchResult: null,
        batchLoading: false,
        previewWarnings: [],
        largeFormatWarnings: [],
        gradientGroups: null,
        gradientGroupsLoading: false,
        gradientGroupsError: null,
        gradientGroupsSessionId: null,
        gradientSelection: null,
        selectedGradientRegions: [],
        puzzleEnabled: false,
      });
    },

    // --- 基础参数 ---
    setLutName: (name: string) => {
      const state = _get();
      const lutInfo = state.lutListFull.find((l) => l.name === name);
      const lutLocation = lutInfo
        ? findLutLocationByPath(
            buildLutCatalogIndex(state.legacyCatalogGroups),
            lutInfo.path,
          )
        : null;
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
      if (lutLocation) {
        updates.selectedLegacyManufacturer = lutLocation.manufacturer;
      }
      if (lutInfo && lutInfo.color_mode) {
        updates.color_mode = normalizePublicColorMode(lutInfo.color_mode);
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
            const normalizedInfo = normalizeLutColorMode(info);
            const nextUpdates: Partial<ConverterState> = {
              selectedLutInfo: normalizedInfo,
            };
            if (normalizedInfo.color_mode) {
              nextUpdates.color_mode = normalizePublicColorMode(
                normalizedInfo.color_mode,
              );
            }
            if (
              normalizedInfo.supports_predictive_match ||
              normalizedInfo.supports_dynamic_layer_count
            ) {
              if (
                Array.isArray(normalizedInfo.supported_modes) &&
                normalizedInfo.supported_modes.length > 0
              ) {
                const preferredMode =
                  normalizedInfo.supported_modes.find(
                    (mode) => mode.color_layers === 5,
                  ) ??
                  normalizedInfo.supported_modes.find(
                    (mode) =>
                      mode.color_layers === normalizedInfo.max_color_layers,
                  ) ??
                  normalizedInfo.supported_modes[0];
                nextUpdates.color_layers =
                  preferredMode.color_layers ??
                  normalizedInfo.max_color_layers ??
                  null;
                nextUpdates.layer_height_mm =
                  preferredMode.layer_height_mm ??
                  normalizedInfo.layer_height_mm ??
                  null;
              } else {
                nextUpdates.color_layers =
                  normalizedInfo.max_color_layers ?? null;
                nextUpdates.layer_height_mm =
                  normalizedInfo.layer_height_mm ?? null;
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

    setLegacyManufacturer: (name: string) => {
      const state = _get();
      const index = buildLutCatalogIndex(state.legacyCatalogGroups);
      const currentLutInfo = state.lut_name
        ? state.lutListFull.find((l) => l.name === state.lut_name)
        : null;
      const currentLocation = currentLutInfo
        ? findLutLocationByPath(index, currentLutInfo.path)
        : null;
      const keepCurrentLut = currentLocation?.manufacturer === name;
      const updates: Partial<ConverterState> = {
        source_version: "legacy",
        selectedLegacyManufacturer: name,
        selectedNativeBrandKey: "",
        selectedNativeDbNames: [],
      };

      if (!keepCurrentLut) {
        updates.lut_name = "";
        updates.selectedLutInfo = null;
        updates.color_layers = null;
        updates.layer_height_mm = null;
        updates.model_enable = false;
        updates.model_only = false;
        updates.model_threshold = null;
        updates.model_margin = null;
        Object.assign(updates, buildPreviewSessionResetState());
        try {
          localStorage.removeItem("lumina_lastLut");
        } catch {
          /* noop */
        }
      }

      set(updates);
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

        if (version === "material") {
          return {
            source_version: "material",
            model_enable: false,
            model_only: false,
            model_threshold: null,
            model_margin: null,
            ...buildPreviewSessionResetState(),
          };
        }

        const selection = resolveNativeBrandSelection(state);
        const selectedBrand =
          selection.brand ?? state.nativeBrandGroups[0] ?? null;
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

    setSelectedMaterialDirNames: (names: string[]) => {
      persistSelectedMaterialDirNames(names);
      set((state) => {
        const currentBacking = state.materialBackingMaterialDirName;
        const nextBacking =
          currentBacking && names.includes(currentBacking)
            ? currentBacking
            : (names[0] ?? null);
        persistMaterialBackingMaterialDirName(nextBacking);
        return {
          selectedMaterialDirNames: names,
          materialBackingMaterialDirName: nextBacking,
          ...buildPreviewSessionResetState(),
        };
      });
    },
    setMaterialLayerCount: (count: number) =>
      set(() => ({
        materialLayerCount: count,
        ...buildPreviewSessionResetState(),
      })),
    setMaterialLayerHeightMm: (height: number) =>
      set(() => ({
        materialLayerHeightMm: height,
        ...buildPreviewSessionResetState(),
      })),
    setMaterialBackingMaterialDirName: (name: string | null) => {
      persistMaterialBackingMaterialDirName(name);
      set({
        materialBackingMaterialDirName: name,
        modelUrl: null,
        threemfDiskPath: null,
        downloadUrl: null,
      });
    },

    setNativeBrandKey: (brandKey: string) =>
      set((state) => {
        const selectedBrand = getNativeBrandGroupByKey(
          state.nativeBrandGroups,
          brandKey,
        );
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

    setNativeSupportedMode: (mode: {
      color_layers: number;
      layer_height_mm: number;
    }) =>
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
        const allowed = selectedBrand
          ? new Set(getNativeDbOptionNames(selectedBrand))
          : null;
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
        layer_height_mm: height == null ? null : clampValue(height, 0.04, 0.2),
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
    setQuantizeColors: (colors: number) => {
      const state = _get();
      const upperBound = state.quantize_colors_unlocked ? 8192 : 256;
      set({
        quantize_colors: clampValue(colors, 8, upperBound),
        threemfDiskPath: null,
        downloadUrl: null,
      });
    },
    setQuantizeColorsUnlocked: (unlocked: boolean) => {
      const state = _get();
      const upperBound = unlocked ? 8192 : 256;
      set({
        quantize_colors_unlocked: unlocked,
        quantize_colors: clampValue(state.quantize_colors, 8, upperBound),
        threemfDiskPath: null,
        downloadUrl: null,
      });
    },
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
    setUseLutConstrained: (enabled: boolean) =>
      set({ use_lut_constrained: enabled }),
    setAutoDynamicRange: (enabled: boolean) =>
      set({
        auto_dynamic_range: enabled,
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
          selectedFridgeMagnetId: enabled ? state.selectedFridgeMagnetId : null,
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
          selectedFridgeMagnetId:
            nextFridgeMagnets[nextFridgeMagnets.length - 1].id,
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

    updateFridgeMagnet: (
      id: string,
      updates: Partial<Omit<FridgeMagnetItem, "id">>,
    ) =>
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
                thickness_mm:
                  updates.thickness_mm == null
                    ? item.thickness_mm
                    : sanitizeFiniteNumber(
                        updates.thickness_mm,
                        item.thickness_mm,
                      ),
                center_x_mm:
                  updates.center_x_mm == null
                    ? item.center_x_mm
                    : sanitizeFiniteNumber(
                        updates.center_x_mm,
                        item.center_x_mm,
                      ),
                center_y_mm:
                  updates.center_y_mm == null
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

    clearSelectedFridgeMagnet: () => set({ selectedFridgeMagnetId: null }),

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
            gradientSelection: null,
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
            gradientSelection: null,
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
            gradientSelection: null,
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
            gradientSelection: null,
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
      // Any manual tweak to the multi-select set implies the user is no
      // longer inside a "gradient region"-scoped selection. Drop that stamp
      // so the palette tiles recover their normal selection rendering;
      // otherwise the palette would keep hiding selection borders even
      // after the user has diverged from the region's exact colour list.
      // 用户手动改动多选集合时，表示已从"区域选中"转为常规多选，清除
      // gradientSelection 让调色板恢复正常的选中态渲染。
      set({ selectedColors: next, gradientSelection: null });

      // 2D 预览高亮：调用后端生成颜色高亮预览（与 detectRegion 同风格）
      const state = _get();
      const sid = state.sessionId;
      if (!sid) return;

      if (next.size === 0) {
        set({ previewImageUrl: getPreviewBaseUrl(state) });
      } else {
        const hexes = Array.from(next);
        const snapshot = {
          sessionId: sid,
          selectionMode: state.selectionMode,
          selectedColors: hexes,
        };
        void apiColorHighlight(sid, hexes)
          .then((res) => {
            if (!matchesColorHighlightSnapshot(_get(), snapshot)) return;
            set({ previewImageUrl: normalizeResourceUrl(res.preview_url) });
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
      if (colors.length === 0 || !state.sessionId) return;

      // Snapshot + optimistic remap map update (kept exactly as before so
      // the undo/redo stack is unchanged).
      // 快照 colorRemapMap + 乐观更新（保留原 undo/redo 行为）。
      const snapshot = { ...state.colorRemapMap };
      const newHistory = [...state.remapHistory, snapshot];
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

      // Single round-trip: the backend runs styled PNG + segmented GLB +
      // material-matrix sync exactly once instead of N times. This is the
      // main "batch colour swap feels slow" fix.
      // 单次请求：后端 PNG + GLB + 物料 sync 只跑 1 次（不再 N 次），
      // 解决"多色一起替换很慢"的问题。
      try {
        const response = await apiReplaceColorsBatch(
          state.sessionId,
          colors.map((hex) => ({
            selectedColor: `#${hex}`,
            replacementColor: `#${newHex}`,
          })),
        );
        const updates: Partial<ConverterState> = {
          replacePreviewLoading: false,
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
        };
        if (response.preview_3d_url) {
          updates.previewGlbUrl = normalizeResourceUrl(response.preview_3d_url);
        }
        set(updates);
        _get()._pollAsyncGlb();
      } catch (err) {
        // Roll the whole batch back — same semantics as the old loop.
        // 整批回滚，和旧循环语义一致。
        set({
          colorRemapMap: snapshot,
          remapHistory: state.remapHistory,
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "批量颜色替换失败",
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
        const previewUrl =
          normalizeResourceUrl(response.preview_url) ?? response.preview_url;
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
          previewUrl:
            normalizeResourceUrl(response.preview_url) ?? response.preview_url,
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
      const next = state.selectedRegions.filter(
        (region) => region.regionId !== regionId,
      );
      if (next.length === state.selectedRegions.length) {
        return;
      }
      const lastRegion = getLastSelectedRegion(next);
      set({
        selectedRegions: next,
        selectedColor: lastRegion
          ? lastRegion.colorHex.replace(/^#/, "")
          : null,
        previewImageUrl: getSelectedRegionPreviewUrl(
          next,
          getPreviewBaseUrl(state),
        ),
      });
    },

    upsertRecipeOverrides: (
      regionIds: string[],
      recipe: number[],
      layerOrder: string,
      virtualMaterials?: VirtualMaterial[],
    ) => {
      const validRegionIds = regionIds.filter((value) => !!value);
      if (validRegionIds.length === 0) {
        return;
      }
      const normalizedRecipe = recipe.map((value) =>
        Math.max(0, Math.round(value)),
      );
      // Deep-copy the virtuals so later mutations on either the caller's
      // list or the stored items don't bleed across overrides. Virtuals are
      // the part of the override payload that ``/generate`` relies on to
      // extend the worker palette; losing them collapses virtual-index
      // pixels back onto the LUT's native channels.
      // 对 virtuals 做深拷贝，避免外部改动污染 store。generate 端依赖它扩
      // 展 worker 调色板，丢了会让虚拟索引像素坍缩回 LUT 原生通道。
      const clonedVirtuals = (virtualMaterials ?? []).map((material) => ({
        name: material.name,
        hex: material.hex,
      }));
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
            ...(clonedVirtuals.length > 0
              ? {
                  virtual_materials: clonedVirtuals.map((material) => ({
                    ...material,
                  })),
                }
              : {}),
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

    pushCustomRecipeHistory: (item: RecipeHistoryItem) => {
      set((state) => {
        const filtered = state.customRecipeHistory.filter(
          (history) => history.id !== item.id,
        );
        const next = [item, ...filtered].slice(0, 10);
        return { customRecipeHistory: next };
      });
    },

    clearCustomRecipeHistory: () => {
      set({ customRecipeHistory: [] });
    },

    applyCustomRecipeFromHistory: async (
      historyId: string,
      regionIds: string[],
    ) => {
      const state = _get();
      const entry = state.customRecipeHistory.find(
        (history) => history.id === historyId,
      );
      if (!entry) {
        set({ error: "Custom recipe history entry not found" });
        return;
      }
      // Forward the virtuals captured at the original apply so the replay
      // round-trips ``recipe[i] >= LUT.N`` through backend validation and
      // reaches the worker with an intact virtual-material registry.
      // 带上首次 apply 时记下的虚拟耗材，保证重放时 ``recipe[i] >= LUT.N``
      // 通过后端校验、worker 也能重建虚拟材料注册表。
      await _get().applyCustomRecipeOverride(
        regionIds,
        entry.recipe,
        entry.layerOrder,
        entry.virtualMaterials,
      );
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
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
        };

        // 更新 3D 预览 GLB URL（仅当后端返回非空 URL 时）
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
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
        _get()._pollAsyncGlb();
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "区域颜色替换失败",
        });
      }
    },

    applyGradientRegionPixelReplace: async (
      groupIndex: number,
      regionIndex: number,
      targetHex: string,
    ) => {
      const state = _get();
      const sid = state.sessionId;
      if (!sid) {
        set({ error: "请先预览图片" });
        return;
      }
      const hexNoHash = targetHex.replace(/^#/, "").toLowerCase();
      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiRegionReplace(sid, `#${hexNoHash}`, {
          gradientGroupIndex: groupIndex,
          gradientRegionIndex: regionIndex,
        });
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          // The edit is spatial and the chosen region's pixels are now
          // ``targetHex``; keep the panel state consistent by clearing
          // the region highlight and any leftover multi-selection so the
          // LUT picker/preview return to the default "nothing selected"
          // mode after the replace completes.
          // 空间替换完成后清除区域高亮与遗留的多选集合，恢复默认态。
          gradientSelection: null,
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          // generate() must reuse the cached matched_rgb (which the server
          // has just mutated) rather than re-running the fresh-pipeline,
          // exactly like applyRegionReplace does.
          // 与 applyRegionReplace 一致：让 generate 走 use_cached_matched_rgb。
          regionReplacementCount: state.regionReplacementCount + 1,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
        };
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        set(updates);
        _get()._pollAsyncGlb();
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "区域颜色替换失败",
        });
      }
    },

    toggleGradientRegionSelection: (
      groupIndex: number,
      regionIndex: number,
    ) => {
      const state = _get();
      const current = state.selectedGradientRegions;
      // Same-group invariant: a click on a region belonging to a different
      // group drops the prior list entirely and seeds the selection with
      // just the new region, so the user can "switch" between groups
      // without first pressing Clear. Matches the intuition that merging
      // regions from unrelated gradients isn't meaningful.
      // 同 group 不变式：点跨 group 的 region 时清空旧选择并只保留新的。
      const isCrossGroup =
        current.length > 0 && current[0].groupIndex !== groupIndex;
      let next: Array<{ groupIndex: number; regionIndex: number }>;
      if (isCrossGroup) {
        next = [{ groupIndex, regionIndex }];
      } else {
        const existingIdx = current.findIndex(
          (r) => r.groupIndex === groupIndex && r.regionIndex === regionIndex,
        );
        next =
          existingIdx >= 0
            ? [
                ...current.slice(0, existingIdx),
                ...current.slice(existingIdx + 1),
              ]
            : [...current, { groupIndex, regionIndex }];
      }
      // gradientSelection mirrors selectedGradientRegions so LUT dispatch
      // can route through applyMultiRegionPixelReplace via a single source
      // of truth. Empty list → null; single-entry list still uses
      // "multi-region" so the batch path stays active even with 1 box
      // ticked.
      // gradientSelection 与 selectedGradientRegions 同步，即便只勾 1 个
      // 也走 batch 路径，语义统一。
      const source: GradientSelectionSource | null =
        next.length === 0
          ? null
          : {
              kind: "multi-region",
              groupIndex: next[0].groupIndex,
              regionIndices: next.map((r) => r.regionIndex),
            };
      // Reset the 2D preview highlight state so ticking a checkbox is a
      // pure "mark region for batch merge" action — it must NOT trigger a
      // select-all-style cyan overlay on the canvas. Without this reset,
      // any leftover ``selectedColors`` / ``regionData`` / highlight PNG
      // from a prior "Select group" / "Select region" click or palette
      // tile interaction would still be visible, looking as if the
      // checkbox itself caused the highlight.
      // 勾选 checkbox 只是"标记 region 加入合并"，不应触发 2D 高亮。重置
      // selectedColors/regionData 并把 previewImageUrl 回退到 base，避免
      // 先前"选中整组/区域"或调色板点击留下的 cyan 覆盖被误认为是
      // checkbox 触发的。
      const baseUrl = getPreviewBaseUrl(state);
      set({
        selectedGradientRegions: next,
        gradientSelection: source,
        selectedColors: new Set<string>(),
        selectedColor: null,
        regionData: null,
        selectedRegions: [],
        previewImageUrl: baseUrl,
      });
    },

    clearGradientRegionSelection: () => {
      // Also null out gradientSelection when it was tracking the multi-
      // region list; leave the region/group kinds alone so clearing does
      // not disturb an unrelated single-row highlight.
      // 同步清空 multi-region 源标识；单 region/group 的高亮标识不受影响。
      const current = _get().gradientSelection;
      const nextSource = current?.kind === "multi-region" ? null : current;
      set({
        selectedGradientRegions: [],
        gradientSelection: nextSource,
      });
    },

    flattenSelectedGradientRegions: async () => {
      const state = _get();
      const sid = state.sessionId;
      if (!sid) return;
      const regions = state.selectedGradientRegions;
      if (regions.length < 2) return;
      const groups = state.gradientGroups;
      if (!groups || groups.length === 0) return;
      const groupIndex = regions[0].groupIndex;
      const group = groups.find((g) => g.group_index === groupIndex);
      if (!group) return;

      // Pixel-count-weighted representative across the union of the
      // selected regions' material_breakdowns: sum pixel_count per hex
      // across every picked region, then keep the hex with the largest
      // total. This matches the existing group-level representative_hex
      // semantics (majority colour wins) but restricted to the subset the
      // user actually checked, so merging "region 1 + region 3" collapses
      // to whatever colour dominates those two regions specifically — not
      // the whole-group majority.
      // 按勾选 region 的 material_breakdown 累加像素数，最多的 hex 做代表色。
      // 与整组 representative_hex 同思想，但只在选中的子集里评估，避免把未
      // 勾选的 region 纳入计算。
      const selectedRegionSet = new Set(regions.map((r) => r.regionIndex));
      const totals = new Map<string, number>();
      for (const region of group.regions) {
        if (!selectedRegionSet.has(region.region_index)) continue;
        for (const mb of region.material_breakdown) {
          const hex = mb.hex.replace(/^#/, "").toLowerCase();
          totals.set(hex, (totals.get(hex) ?? 0) + (mb.pixel_count ?? 0));
        }
      }
      if (totals.size === 0) return;
      let targetHex = "";
      let best = -1;
      for (const [hex, count] of totals.entries()) {
        if (count > best) {
          best = count;
          targetHex = hex;
        }
      }
      if (!targetHex) return;

      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiRegionReplaceBatch(
          sid,
          regions.map((r) => ({
            gradientGroupIndex: r.groupIndex,
            gradientRegionIndex: r.regionIndex,
            replacementColor: `#${targetHex}`,
          })),
        );
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          // Matched to applyGradientRegionPixelReplace / regionReplace
          // post-state: clear selection and bump regionReplacementCount so
          // downstream generate() takes the cached-matched_rgb shortcut.
          // 与单 region 替换后一致：清空选择 + regionReplacementCount 自增。
          gradientSelection: null,
          selectedGradientRegions: [],
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          regionReplacementCount: state.regionReplacementCount + regions.length,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
        };
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        set(updates);
        _get()._pollAsyncGlb();
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "合并去海带纹失败",
        });
      }
    },

    requantizeSelectedGradientRegions: async (
      localQuantizeColors: number,
      explicitTargets?: ReadonlyArray<{
        groupIndex: number;
        regionIndex: number;
      }>,
    ) => {
      const state = _get();
      const sid = state.sessionId;
      if (!sid) return;
      // Explicit targets from a per-region button: honour them and leave
      // the batch checkbox list intact so the user's in-progress merge
      // selection survives. Falls back to the checkbox list otherwise.
      // 显式 targets：per-region 按钮传入，保留用户已有的批量勾选。
      const usingExplicitTargets =
        explicitTargets !== undefined && explicitTargets.length > 0;
      const regions = usingExplicitTargets
        ? (explicitTargets as ReadonlyArray<{
            groupIndex: number;
            regionIndex: number;
          }>)
        : state.selectedGradientRegions;
      if (regions.length === 0) return;
      // Clamp to the backend's validated range [12, 256]. The dialog enforces
      // it too, but belt-and-braces protects against rogue callers.
      // 边界兜底：后端也校验 12-256，这里再夹一道避免发送非法值。
      const clamped = Math.max(
        12,
        Math.min(256, Math.round(localQuantizeColors)),
      );

      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiRegionRequantize(
          sid,
          regions.map((r) => ({
            gradientGroupIndex: r.groupIndex,
            gradientRegionIndex: r.regionIndex,
          })),
          clamped,
        );
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          // Match post-state of flatten / region-replace so generate() picks
          // up the cached-matched_rgb shortcut and layer images are invalidated.
          // 与 flatten 保持一致：LUT 选中/高亮一律清空；批量勾选仅在隐式调用
          // （走当前勾选列表）时清空，显式 per-region 操作保留用户选中。
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          regionReplacementCount: state.regionReplacementCount + regions.length,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
        };
        if (!usingExplicitTargets) {
          updates.gradientSelection = null;
          updates.selectedGradientRegions = [];
        }
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        // The backend re-runs gradient-group analysis because requantize
        // shifts matched_rgb enough to change the segmentation. When the
        // response carries the refreshed groups, write them straight into
        // the store (and pin gradientGroupsSessionId so the cached-short
        // circuit in fetchGradientGroups keeps working for later reads).
        // Without this, the panel would keep showing the pre-requantize
        // groups and the user would feel the panel is "frozen".
        // 后端在二次量化后会重跑分组分析；响应带了新分组时直接写进 store，
        // 并把 gradientGroupsSessionId 置回当前 session，保持
        // fetchGradientGroups 的缓存短路对后续读取仍然有效。
        if (response.gradient_groups !== undefined) {
          updates.gradientGroups = response.gradient_groups ?? [];
          updates.gradientGroupsError = null;
          updates.gradientGroupsLoading = false;
          updates.gradientGroupsSessionId = sid;
        }
        set(updates);
        _get()._pollAsyncGlb();
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "区域二次量化失败",
        });
      }
    },

    applyMultiRegionPixelReplace: async (targetHex: string) => {
      const state = _get();
      const sid = state.sessionId;
      if (!sid) return;
      const regions = state.selectedGradientRegions;
      if (regions.length === 0) return;
      const hexNoHash = targetHex.replace(/^#/, "").toLowerCase();
      if (!hexNoHash) return;

      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiRegionReplaceBatch(
          sid,
          regions.map((r) => ({
            gradientGroupIndex: r.groupIndex,
            gradientRegionIndex: r.regionIndex,
            replacementColor: `#${hexNoHash}`,
          })),
        );
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          gradientSelection: null,
          selectedGradientRegions: [],
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          regionReplacementCount: state.regionReplacementCount + regions.length,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
        };
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        set(updates);
        _get()._pollAsyncGlb();
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "合并换色失败",
        });
      }
    },

    applyCustomRecipeOverride: async (
      regionIds: string[],
      recipe: number[],
      layerOrder: string = "Top2Bottom",
      virtualMaterials?: VirtualMaterial[],
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
      // Deep-copy virtuals to isolate the payload / state from later
      // caller-side mutations; 422 on ``recipe[i] >= LUT.N`` requires this
      // list to be present, so forward it when non-empty.
      // 深拷贝 virtuals 避免调用方随后改动影响 store / 请求体；recipe 里有
      // 虚拟索引时后端 422 校验需要它，故非空时必须透传。
      const clonedVirtuals = (virtualMaterials ?? []).map((material) => ({
        name: material.name,
        hex: material.hex,
      }));

      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiApplyRecipeOverride({
          session_id: state.sessionId,
          region_ids: targetRegionIds,
          recipe,
          layer_order: layerOrder,
          color_layers: resolvedLayers,
          layer_height_mm: resolvedHeight,
          ...(clonedVirtuals.length > 0
            ? { virtual_materials: clonedVirtuals }
            : {}),
        });
        set((current) => ({
          replacePreviewLoading: false,
          previewImageUrl:
            normalizeResourceUrl(response.preview_url) ?? response.preview_url,
          previewBaseImageUrl:
            normalizeResourceUrl(response.preview_url) ?? response.preview_url,
          previewGlbUrl: response.preview_glb_url
            ? normalizeResourceUrl(response.preview_glb_url)
            : current.previewGlbUrl,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
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
              ...(clonedVirtuals.length > 0
                ? {
                    virtual_materials: clonedVirtuals.map((material) => ({
                      ...material,
                    })),
                  }
                : {}),
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
        _get()._pollAsyncGlb();
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

      // When the pending replacement was seeded by a Gradient Groups
      // *region* button, the user's intent is strictly spatial: repaint
      // only the pixels inside that banded sub-region. The classic
      // ``select-all`` branch below would apply a whole-image ``hex →
      // hex`` remap which recolours every matching pixel on the canvas —
      // that's exactly the "replace cyan band → whole body turns red"
      // regression we are fixing. Route to :func:`applyGradientRegionPixelReplace`
      // first so the backend rebuilds the mask from the cached
      // per-pixel ``gradient_region_id_map``.
      // 区域来源时改走空间替换：用 /region-replace 的 gradient 路径，
      // 服务端从 region_id_map 生成精确 mask，仅改该区域像素，避免全图
      // hex 替换误伤共享同色的其它区域。
      const gradSel = state.gradientSelection;
      if (gradSel?.kind === "multi-region") {
        // Multi-region checkbox flow: the user ticked ≥1 region box and
        // then picked a LUT colour. Fan out the pick to every selected
        // region via a single /region-replace-batch call (same spatial
        // path applyGradientRegionPixelReplace uses for one region).
        // 多勾 region → LUT 点色：一次 batch 把所有勾选 region 刷成该色，
        // 与单 region 的空间替换路径同源。
        await _get().applyMultiRegionPixelReplace(pending.targetHex);
        return;
      }
      if (gradSel?.kind === "region") {
        await _get().applyGradientRegionPixelReplace(
          gradSel.groupIndex,
          gradSel.regionIndex,
          pending.targetHex,
        );
        return;
      }

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
          // Multi-region mode: send every region's click coord + target in
          // one batch request. The server rebuilds each mask via the same
          // flood-fill kernel /region-detect uses, applies all mutations
          // to matched_rgb cumulatively, and renders PNG + GLB exactly
          // once for the whole batch. Previously this path looped N times
          // and triggered N GLB rebuilds — the main "multi-region replace
          // feels slow" regression we are fixing.
          // 多区域模式：每条 region 的 click 坐标 + 目标色一次性发批量请求，
          // 后端内部循环建 mask 并累积应用，PNG/GLB/物料 sync 各只跑 1 次。
          // 旧实现是 N 次 detect + N 次 replace → N 次 GLB 重建。
          const regions = pending.sourceRegions ?? [];
          if (regions.length === 0) break;
          const curState = _get();
          const sid = curState.sessionId;
          if (!sid) break;
          const batchItems = regions
            .filter((r) => r.clickX != null && r.clickY != null)
            .map((r) => ({
              clickX: r.clickX as number,
              clickY: r.clickY as number,
              replacementColor: `#${pending.targetHex}`,
            }));
          if (batchItems.length === 0) break;
          set({
            replacePreviewLoading: true,
            regionReplacementCount:
              curState.regionReplacementCount + batchItems.length,
            threemfDiskPath: null,
            downloadUrl: null,
          });
          try {
            const response = await apiRegionReplaceBatch(sid, batchItems);
            const updates: Partial<ConverterState> = {
              previewImageUrl: normalizeResourceUrl(response.preview_url),
              previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
              replacePreviewLoading: false,
              selectedRegions: [],
              regionData: null,
              selectedColor: null,
              ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
            };
            if (response.preview_glb_url) {
              updates.previewGlbUrl = normalizeResourceUrl(
                response.preview_glb_url,
              );
            }
            if (response.color_contours) {
              updates.colorContours = response.color_contours;
            }
            // Record per-region replacement entries for share-card export.
            // 记录每个区域的替换条目，供分享卡导出使用。
            const newEntries: ColorReplacementItem[] = regions.map((region) => {
              const pe = curState.palette.find(
                (p) => p.matched_hex === region.colorHex,
              );
              return {
                quantized_hex: pe?.quantized_hex ?? region.colorHex,
                matched_hex: region.colorHex,
                replacement_hex: pending.targetHex,
              };
            });
            updates.replacement_regions = [
              ..._get().replacement_regions,
              ...newEntries,
            ];
            set(updates);
            _get()._pollAsyncGlb();
          } catch (err) {
            set({
              replacePreviewLoading: false,
              error:
                err instanceof Error
                  ? err.message
                  : "Multi-region color replacement failed",
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
            _get()._pollAsyncGlb();
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
          state.heightmap_max_height,
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

    _pollAsyncGlb: () => {
      const sid = _get().sessionId;
      if (!sid) return;
      _startGlbStatusPolling(
        sid,
        (url, colorContours) =>
          set({
            previewGlbUrl: url,
            ...(colorContours ? { colorContours } : {}),
          }),
        () => _get().sessionId,
      );
    },

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
        await Promise.all([
          _get().fetchLutCatalog(),
          _get().fetchLegacyCatalog(),
        ]);
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
        const luts = response.luts.map(normalizeLutColorMode);
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
            updates.color_mode = normalizePublicColorMode(info.color_mode);
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
        const legacyGroups = normalizeLutGroups(response.legacy_groups ?? []);
        const groups = filterNativeBrandGroups(
          normalizeNativeBrandGroups(response.native_brand_groups ?? []),
        );
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
            updates.color_mode = normalizePublicColorMode(info.color_mode);
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
        const preferredMode =
          selection?.supported_mode ??
          resolvePreferredSupportedMode(fallbackBrand?.supported_modes ?? []);
        set({
          ...updates,
          ...(currentState.source_version === "native" && fallbackBrand
            ? {
                selectedNativeBrandKey: fallbackBrand.brand_key,
                selectedNativeDbNames:
                  selection?.db_names ??
                  getNativeDbNamesForGroup(fallbackBrand),
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

    fetchLegacyCatalog: async () => {
      set({ legacyCatalogLoading: true, error: null });
      try {
        const response = await apiFetchLutDetailsCatalog();
        const groups = normalizeLutGroups(response.groups ?? []);
        const currentState = _get();
        const index = buildLutCatalogIndex(groups);
        const currentLutInfo = currentState.lut_name
          ? currentState.lutListFull.find(
              (l) => l.name === currentState.lut_name,
            )
          : null;
        const location = currentLutInfo
          ? findLutLocationByPath(index, currentLutInfo.path)
          : null;
        const selectedManufacturer =
          location?.manufacturer ??
          (currentState.selectedLegacyManufacturer &&
          index.byManufacturer[currentState.selectedLegacyManufacturer]
            ? currentState.selectedLegacyManufacturer
            : "");

        set({
          legacyCatalogGroups: groups,
          legacyCatalogLoading: false,
          selectedLegacyManufacturer: selectedManufacturer,
        });
      } catch (err) {
        set({ legacyCatalogLoading: false });
        _get().setError(
          err instanceof Error ? err.message : "LUT 详情目录加载失败",
        );
      }
    },

    fetchLutColors: async (lutName: string) => {
      if (!lutName) {
        set({ lutColors: [], lutColorCards: [], lutColorsLutName: "" });
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
          lutColorCards: response.cards ?? [],
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

    fetchMaterialSuggestions: async (targetHex: string) => {
      // Require material-archive mode with a non-empty palette.
      // Caller (MaterialColorPicker) ensures this, but we double-check.
      // 调用方应保证处于材料档案模式且已选耗材，这里再校验一次。
      const state = _get();
      if (state.source_version !== "material") {
        set({
          materialSuggestionsError:
            "fetchMaterialSuggestions requires source_version='material'",
        });
        return;
      }
      const dirNames = state.selectedMaterialDirNames ?? [];
      if (dirNames.length === 0) {
        set({
          materialSuggestions: null,
          materialSuggestionsTargetHex: targetHex,
          materialSuggestionsError:
            "No materials selected; cannot suggest achievable colors",
        });
        return;
      }
      const cleaned = (targetHex || "").trim();
      if (!cleaned) {
        set({
          materialSuggestions: null,
          materialSuggestionsTargetHex: null,
          materialSuggestionsError: null,
        });
        return;
      }

      // Abort any in-flight suggestion request before launching a new one.
      // 发起新请求前先取消上一次未完成的请求。
      _materialSuggestAbortController?.abort();
      _materialSuggestAbortController = new AbortController();
      const { signal } = _materialSuggestAbortController;

      const cacheKey = _materialSuggestCacheKey({
        directoryNames: dirNames,
        layerCount: state.materialLayerCount,
        layerHeightMm: state.materialLayerHeightMm,
        substrate: "white",
        targetHex: cleaned,
      });
      const cached = _materialSuggestCache.get(cacheKey);
      if (cached) {
        // Re-insert to refresh LRU recency.
        _materialSuggestCache.delete(cacheKey);
        _materialSuggestCache.set(cacheKey, cached);
        set({
          materialSuggestions: cached,
          materialSuggestionsLoading: false,
          materialSuggestionsTargetHex: cleaned,
          materialSuggestionsError: null,
        });
        return;
      }

      set({
        materialSuggestionsLoading: true,
        materialSuggestionsTargetHex: cleaned,
        materialSuggestionsError: null,
      });
      // Forward the opt-in grid resolution so the suggest-colors lookup
      // hits the same on-disk cache the user built through the dialog;
      // otherwise we would silently fall back to a slower MITM run.
      const settingsState = useSettingsStore.getState();
      const gridResolutionOverride =
        settingsState.enableSolverCacheGridSelection
          ? settingsState.solverCacheGridResolution
          : undefined;
      try {
        const response = await fetchMaterialColorSuggestions(
          {
            materialDirectoryNames: dirNames,
            layerCount: state.materialLayerCount,
            layerHeightMm: state.materialLayerHeightMm,
            substrate: "white",
          },
          cleaned,
          { signal, gridResolution: gridResolutionOverride },
        );
        // Stash into LRU, evicting oldest when over limit.
        // 写入 LRU，超额时淘汰最早项。
        _materialSuggestCache.set(cacheKey, response);
        while (_materialSuggestCache.size > MATERIAL_SUGGEST_LRU_LIMIT) {
          const oldest = _materialSuggestCache.keys().next().value;
          if (oldest == null) break;
          _materialSuggestCache.delete(oldest);
        }
        set({
          materialSuggestions: response,
          materialSuggestionsLoading: false,
          materialSuggestionsTargetHex: cleaned,
          materialSuggestionsError: null,
        });
      } catch (err) {
        if (signal.aborted) {
          return; // Superseded by a newer request.
        }
        set({
          materialSuggestionsLoading: false,
          materialSuggestionsError:
            err instanceof Error
              ? err.message
              : "Material color suggestion request failed",
        });
      }
    },

    clearMaterialSuggestions: () => {
      _materialSuggestAbortController?.abort();
      _materialSuggestAbortController = null;
      set({
        materialSuggestions: null,
        materialSuggestionsLoading: false,
        materialSuggestionsTargetHex: null,
        materialSuggestionsError: null,
      });
    },

    fetchGradientGroups: async (sessionId: string) => {
      if (!sessionId) {
        return;
      }
      // Reuse cached groups when the session hasn't changed — the backend
      // recomputes synchronously on every new preview, so a matching session
      // id means the payload is still fresh.
      // 同一 session 的结果是稳定的，命中直接复用。
      const current = _get();
      if (
        current.gradientGroupsSessionId === sessionId &&
        current.gradientGroups !== null
      ) {
        return;
      }
      _gradientGroupsAbortController?.abort();
      _gradientGroupsAbortController = new AbortController();
      const { signal } = _gradientGroupsAbortController;

      set({
        gradientGroupsLoading: true,
        gradientGroupsError: null,
      });
      try {
        const response = await apiFetchGradientGroups(sessionId, signal);
        // Abandon the response if the user moved on to another session
        // between the request start and the response arrival.
        // 期间换了 session 则丢弃这次结果。
        if (_get().sessionId !== sessionId) {
          return;
        }
        set({
          gradientGroups: response.status === "ok" ? response.groups : [],
          gradientGroupsLoading: false,
          gradientGroupsError: null,
          gradientGroupsSessionId: sessionId,
        });
        // Advanced setting: after groups land, automatically collapse every
        // gradient to its representative colour so the user sees a clean
        // preview without touching the color workstation.
        // 高级设置：分组拉到手后，如果开启了"渐变自动换色"，自动批量折叠。
        if (
          useSettingsStore.getState().autoReplaceGradientBanding &&
          response.status === "ok" &&
          response.groups.length > 0
        ) {
          void _get().applyAutoGradientReplace();
        }
      } catch (err) {
        if (signal.aborted) {
          return; // Superseded by a newer fetch or an explicit clear.
        }
        set({
          gradientGroupsLoading: false,
          gradientGroupsError:
            err instanceof Error
              ? err.message
              : "Failed to load gradient groups",
        });
      }
    },

    clearGradientGroups: () => {
      _gradientGroupsAbortController?.abort();
      _gradientGroupsAbortController = null;
      set({
        gradientGroups: null,
        gradientGroupsLoading: false,
        gradientGroupsError: null,
        gradientGroupsSessionId: null,
        gradientSelection: null,
      });
    },

    selectGradientGroupColors: (
      hexes: string[],
      source?: GradientSelectionSource,
    ) => {
      const normalised = Array.from(
        new Set(hexes.map((h) => h.replace(/^#/, "").toLowerCase())),
      );
      if (normalised.length === 0) {
        return;
      }
      // Enter multi-colour mode and overwrite selectedColors atomically so
      // the existing MaterialColorPicker flow picks this up as a normal
      // "select-all" batch replacement source. The ``gradientSelection``
      // state records which panel row (group vs specific region) initiated
      // the batch, so the UI can highlight exactly one button even when a
      // region shares its material breakdown with the enclosing group.
      // 切到 select-all 模式并原子覆盖选中集合；``gradientSelection`` 记录
      // 此次批量的发起方（整组 / 哪个区域），供按钮排它性高亮使用。
      const baseUrl = getPreviewBaseUrl(_get());
      set({
        selectionMode: "select-all",
        selectedColors: new Set(normalised),
        selectedColor: null,
        regionData: null,
        selectedRegions: [],
        previewImageUrl: baseUrl,
        gradientSelection: source ?? null,
      });
      const sid = _get().sessionId;
      if (!sid) return;
      // If this batch originated from a specific region row, forward the
      // (group_index, region_index) identifiers so the backend clips the
      // highlight to that sub-region's *exact* pixel mask (via the cached
      // per-pixel region_id_map). A rectangular bbox is nowhere near
      // precise enough — a region's external rectangle almost always
      // contains many same-coloured pixels belonging to other regions of
      // the same group or unrelated background, which is exactly why
      // clicking a sub-region used to "light up the whole group".
      // 区域来源时传 (group_index, region_index) 让后端用精确像素 mask
      // 裁剪；矩形 bbox 无法避免把同色其他区域一起点亮。
      const scope =
        source?.kind === "region"
          ? {
              gradientGroupIndex: source.groupIndex,
              gradientRegionIndex: source.regionIndex,
            }
          : undefined;
      // Fire a single highlight request so the preview shows every chosen
      // colour at once, mirroring the visual feedback users already get
      // from :func:`toggleColorInSelection`.
      // 触发一次高亮请求，让预览整体高亮所有选中色块。
      void apiColorHighlight(sid, normalised, scope)
        .then((res) => {
          // Stale-response guard: if the user clicked a *different* group or
          // region while this request was in flight, the selection has
          // already changed and the returned preview URL would overwrite the
          // newer highlight with stale pixels. Only apply when the current
          // selection still equals the one this request asked for.
          // 过期响应丢弃：请求期间用户切换了别的分组/区域时，忽略本次返回。
          const current = _get().selectedColors;
          if (current.size !== normalised.length) return;
          if (!normalised.every((h) => current.has(h))) return;
          set({
            previewImageUrl: normalizeResourceUrl(res.preview_url),
          });
        })
        .catch(() => {
          // Silent: highlight is a best-effort UX nicety.
        });
    },

    applyGradientReplaceForGroup: async (
      groupIndex: number,
      regionIndex?: number,
    ) => {
      const state = _get();
      const sid = state.sessionId;
      if (!sid) return;
      const groups = state.gradientGroups;
      if (!groups || groups.length === 0) return;
      const group = groups.find((g) => g.group_index === groupIndex);
      if (!group) return;

      const rep = group.representative_hex.replace(/^#/, "").toLowerCase();
      if (!rep) return;

      // Use the spatially-scoped /region-replace endpoint so that only
      // pixels inside the gradient group (or single region) are repainted
      // with the representative colour. The old colorRemapMap approach
      // was a whole-image hex→hex remap that would pollute unrelated areas
      // sharing the same quantised hex — the "去海带纹 repaints the whole
      // body" bug.
      // 走空间受限的 /region-replace 端点，仅把组内（或单区域内）像素刷成
      // 代表色。旧方案 colorRemapMap 是全图 hex→hex，会误伤其它同色区域。
      const scope =
        regionIndex !== undefined
          ? { gradientGroupIndex: groupIndex, gradientRegionIndex: regionIndex }
          : { gradientGroupIndex: groupIndex };

      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiRegionReplace(sid, `#${rep}`, scope);
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          gradientSelection: null,
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          regionReplacementCount: state.regionReplacementCount + 1,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
        };
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        set(updates);
        _get()._pollAsyncGlb();
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "去海带纹替换失败",
        });
      }
    },

    applyAutoGradientReplace: async () => {
      const state = _get();
      if (!state.sessionId) return;
      const groups = state.gradientGroups;
      if (!groups || groups.length === 0) return;

      // Build "non-rep → rep" map from the groups. Hex values are stored
      // without the leading '#' and in lowercase, matching the frontend
      // ``colorRemapMap`` convention.
      // 构建 "非代表色 → 代表色" 映射（去掉 '#'、统一小写）。
      const remap: Record<string, string> = {};
      for (const g of groups) {
        const rep = g.representative_hex.replace(/^#/, "").toLowerCase();
        for (const mc of g.material_colours) {
          const src = mc.hex.replace(/^#/, "").toLowerCase();
          if (!src || src === rep) continue;
          remap[src] = rep;
        }
      }
      if (Object.keys(remap).length === 0) return;

      // Merge into existing remap map so earlier user edits survive.
      // 与已有手工 remap 合并，保留用户先前的手动替换。
      const snapshot = { ...state.colorRemapMap };
      const mergedMap = { ...state.colorRemapMap, ...remap };
      set({
        colorRemapMap: mergedMap,
        remapHistory: [...state.remapHistory, snapshot],
        threemfDiskPath: null,
        downloadUrl: null,
      });
      await _get().submitReplacePreview();
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
            state.source_version === "material"
              ? "请先选择耗材"
              : state.source_version === "native"
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

      _previewStartTime = performance.now();
      (window as LuminaWindow).__luminaPreviewStart = _previewStartTime;
      _startPreviewTimer();
      _previewClientLog("preview: click", {
        image: summarizeFileForLog(state.imageFile),
        source_version: state.source_version,
        target_width_mm: state.target_width_mm,
        color_mode: state.color_mode,
        modeling_mode: state.modeling_mode,
        quantize_colors: state.quantize_colors,
        enable_cleanup: state.enable_cleanup,
        hue_enable: state.hue_enable,
      });

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
        const colorMode = normalizePublicColorMode(state.color_mode);
        const sourceParams =
          state.source_version === "material"
            ? buildMaterialSourceParams(state)
            : state.source_version === "native"
              ? buildNativeSourceParams(resolvedSourceSelection, state)
              : buildLegacySourceParams(state.lut_name);
        if (!sourceParams) {
          _previewClientLog(
            "preview: invalid source",
            {
              source_version: state.source_version,
            },
            "warn",
          );
          set({
            isLoading: false,
            error: "请先选择品牌和数据库",
          });
          return;
        }
        const previewParams = {
          ...sourceParams,
          color_layers:
            state.source_version === "material"
              ? state.materialLayerCount
              : sourceParams.source_kind === "native_bundle"
                ? (sourceParams.color_layers ?? undefined)
                : (state.color_layers ?? undefined),
          layer_height_mm:
            state.source_version === "material"
              ? state.materialLayerHeightMm
              : sourceParams.source_kind === "native_bundle"
                ? (sourceParams.layer_height_mm ?? undefined)
                : (state.layer_height_mm ?? undefined),
          target_width_mm: state.target_width_mm,
          color_mode: colorMode,
          modeling_mode: state.modeling_mode,
          quantize_colors: state.quantize_colors,
          enable_cleanup: state.enable_cleanup,
          enable_outline: state.enable_outline,
          outline_width: state.outline_width,
          svg_pixels_per_mm: useSettingsStore.getState().svgPixelsPerMm,
          hue_weight: state.hue_enable ? 0.5 : 0.0,
          chroma_gate: state.hue_enable ? state.chroma_gate : 0,
          use_lut_constrained: state.use_lut_constrained,
          auto_dynamic_range: state.auto_dynamic_range,
          is_dark: useSettingsStore.getState().theme === "dark",
        };
        _logPreviewTimer("request sent");
        _previewClientLog("preview: request sent", {
          source_kind: sourceParams.source_kind,
          color_layers: previewParams.color_layers ?? null,
          layer_height_mm: previewParams.layer_height_mm ?? null,
          target_width_mm: previewParams.target_width_mm,
          color_mode: previewParams.color_mode,
          modeling_mode: previewParams.modeling_mode,
          quantize_colors: previewParams.quantize_colors,
          enable_outline: previewParams.enable_outline,
          outline_width: previewParams.outline_width,
        });
        const response = await apiConvertPreview(
          state.imageFile,
          previewParams,
          signal,
        );
        if (signal.aborted || _previewAbortController?.signal !== signal) {
          return;
        }
        _logPreviewTimer("response received");
        // 后端返回 JSON，preview_url 是相对路径如 /api/files/xxx
        const previewUrl =
          normalizeResourceUrl(response.preview_url) ?? response.preview_url;
        const glbUrl = response.preview_glb_url
          ? normalizeResourceUrl(response.preview_glb_url)
          : null;
        // Normalize palette hex values: strip leading '#' for frontend consistency
        const normalizedPalette = (response.palette ?? []).map((e) => ({
          ...e,
          quantized_hex: e.quantized_hex.replace(/^#/, ""),
          matched_hex: e.matched_hex.replace(/^#/, ""),
        }));
        const autoReliefHeightMap = buildMissingAutoReliefHeightMap(
          state,
          normalizedPalette,
        );
        const resolvedColorLayers = sourceSelection.isMaterial
          ? state.materialLayerCount
          : sourceSelection.source_kind === "native_bundle"
            ? (sourceSelection.color_layers ?? null)
            : state.color_layers;
        const resolvedLayerHeightMm = sourceSelection.isMaterial
          ? state.materialLayerHeightMm
          : sourceSelection.source_kind === "native_bundle"
            ? (sourceSelection.layer_height_mm ?? null)
            : state.layer_height_mm;

        _previewClientLog("preview: response received", {
          session_id: response.session_id,
          preview_url: previewUrl,
          preview_glb_url: glbUrl,
          palette_count: normalizedPalette.length,
          warning_count: (response.warnings ?? []).length,
          dimensions: response.dimensions ?? null,
          source_kind: sourceParams.source_kind,
        });

        set({
          isLoading: false,
          sessionId: response.session_id,
          previewImageUrl: previewUrl,
          originalPreviewUrl: previewUrl,
          previewBaseImageUrl:
            normalizeResourceUrl(response.dimensions?.preview_raw_url) ??
            previewUrl,
          lutMatchMode: response.lut_match_mode ?? "legacy",
          lutMatchInfo: response.lut_match_info ?? {
            match_mode: response.lut_match_mode ?? "legacy",
          },
          palette: normalizedPalette,
          ...(autoReliefHeightMap
            ? { color_height_map: autoReliefHeightMap }
            : {}),
          colorContours: response.contours ?? {},
          previewGlbUrl: glbUrl,
          colorRemapMap: {},
          remapHistory: [],
          replacement_regions: [],
          recipe_overrides: [],
          customRecipeHistory: [],
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
          // Reset gradient-group cache so the panel shows loading while the
          // new session's groups are fetched below. Without this the UI
          // would briefly show stale groups from the previous preview.
          // 新预览就位后先清空渐变组缓存，避免面板短暂显示旧 session 的分组。
          gradientGroups: null,
          gradientGroupsLoading: false,
          gradientGroupsError: null,
          gradientGroupsSessionId: null,
          gradientSelection: null,
        });
        if (!glbUrl) {
          _get()._pollAsyncGlb();
        }
        console.log(
          "[DEBUG] submitPreview success: cleared layerImages for new sessionId",
        );
        _logPreviewTimer("UI unlocked (isLoading=false, preview state set)");
        _previewClientLog("preview: UI unlocked", {
          session_id: response.session_id,
          preview_url: previewUrl,
          preview_glb_url: glbUrl,
          preview_pixel_width: response.dimensions?.width ?? null,
          preview_pixel_height: response.dimensions?.height ?? null,
          warning_count: (response.warnings ?? []).length,
        });
        trackLuminaEvent("lumina_converter_preview_done", {
          source_version: state.source_version,
          source_kind: sourceParams.source_kind,
          color_mode: colorMode,
          modeling_mode: state.modeling_mode,
          elapsed_ms: getElapsedMsSince(_previewStartTime),
          warning_count: (response.warnings ?? []).length,
          palette_count: normalizedPalette.length,
        });
        // 预览绑定会话后，拉取会话所绑定 LUT 的通道调色板，便于自定义配方编辑器
        // 在材料档案 / 原生打包流程里也能显示按通道顺序的耗材列表。
        // After the preview binds a session, refresh the channel palette for
        // the custom recipe editor so material-archive / native-bundle flows
        // also see the per-channel material list, not just legacy named LUTs.
        const previewSessionId = response.session_id;
        void apiFetchSessionLutInfo(previewSessionId)
          .then((info) => {
            // Only apply if the user hasn't moved on to another session.
            if (_get().sessionId === previewSessionId) {
              set({ selectedLutInfo: normalizeLutColorMode(info) });
            }
          })
          .catch(() => {
            // Best-effort: if the session hasn't been bound yet or the
            // endpoint errors, leave selectedLutInfo untouched.
          });
        // Non-blocking fetch of gradient-banding groups. Backend computed
        // these synchronously during preview, so this is a cheap read.
        // 非阻塞拉取渐变分组：后端已在预览流程中同步算完，这里只是读缓存。
        void _get().fetchGradientGroups(previewSessionId);
      } catch (err) {
        // Ignore aborted requests (user started a new preview)
        if (err instanceof Error && err.name === "CanceledError") {
          _previewClientLog(
            "preview: canceled",
            summarizeErrorForLog(err),
            "warn",
          );
          return;
        }
        set({
          isLoading: false,
          error: err instanceof Error ? err.message : "预览失败",
        });
        trackLuminaEvent("lumina_converter_preview_failed", {
          source_version: state.source_version,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          elapsed_ms: getElapsedMsSince(_previewStartTime),
          error_type: getErrorType(err),
        });
        _previewClientLog(
          "preview: failed",
          summarizeErrorForLog(err),
          "error",
        );
      } finally {
        _endPreviewTimer();
      }
    },

    submitGenerate: async () => {
      let state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return null;
      }
      const sessionId = state.sessionId;
      const sourceSelection = resolveConverterSourceSelection(state);
      if (!sourceSelection.isReady) {
        set({
          error:
            state.source_version === "material"
              ? "请先选择耗材"
              : state.source_version === "native"
                ? "请先选择品牌和数据库"
                : "请先选择 LUT",
        });
        return null;
      }
      const autoReliefHeightMap = buildMissingAutoReliefHeightMap(state);
      if (autoReliefHeightMap) {
        set({ color_height_map: autoReliefHeightMap });
        state = _get();
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
      _clientLog("generate: click", {
        image: summarizeFileForLog(state.imageFile),
        session_id: sessionId,
        source_version: state.source_version,
        target_width_mm: state.target_width_mm,
        color_mode: state.color_mode,
        modeling_mode: state.modeling_mode,
        quantize_colors: state.quantize_colors,
        enable_cleanup: state.enable_cleanup,
        enable_relief: state.enable_relief,
        enable_outline: state.enable_outline,
        enable_cloisonne: state.enable_cloisonne,
        puzzle_enabled: state.puzzleEnabled,
        large_format_enabled: state.largeFormatEnabled,
      });
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
        const colorMode = normalizePublicColorMode(state.color_mode);
        const sourceParams =
          state.source_version === "material"
            ? buildMaterialSourceParams(state)
            : state.source_version === "native"
              ? buildNativeSourceParams(resolvedSourceSelection, state)
              : buildLegacySourceParams(state.lut_name);
        if (!sourceParams) {
          set({
            isGenerating: false,
            error: "请先选择品牌和数据库",
          });
          return null;
        }
        const reliefHeightmapMaxHeight = state.enable_relief
          ? state.spacer_thick + state.heightmap_max_height
          : state.heightmap_max_height;
        const reliefColorHeightMap =
          state.enable_relief && state.autoHeightMode !== "use-heightmap"
            ? toAbsoluteReliefHeightMap(
                state.color_height_map,
                state.spacer_thick,
              )
            : state.enable_relief
              ? state.color_height_map
              : undefined;
        const baseParams = {
          ...sourceParams,
          color_layers:
            sourceParams.source_kind === "native_bundle"
              ? (sourceParams.color_layers ?? undefined)
              : (state.color_layers ?? undefined),
          layer_height_mm:
            sourceParams.source_kind === "native_bundle"
              ? (sourceParams.layer_height_mm ?? undefined)
              : (state.layer_height_mm ?? undefined),
          target_width_mm: state.target_width_mm,
          color_mode: colorMode,
          modeling_mode: state.modeling_mode,
          quantize_colors: state.quantize_colors,
          enable_cleanup: state.enable_cleanup,
          svg_pixels_per_mm: useSettingsStore.getState().svgPixelsPerMm,
          hue_weight: state.hue_enable ? 0.5 : 0.0,
          chroma_gate: state.hue_enable ? state.chroma_gate : 0,
          use_lut_constrained: state.use_lut_constrained,
          auto_dynamic_range: state.auto_dynamic_range,
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
          color_height_map: reliefColorHeightMap,
          heightmap_max_height: reliefHeightmapMaxHeight,
          enable_outline: state.enable_outline,
          outline_width: state.outline_width,
          enable_cloisonne: state.enable_cloisonne,
          wire_width_mm: state.wire_width_mm,
          wire_height_mm: state.wire_height_mm,
          enable_coating: state.enable_coating,
          coating_height_mm: state.coating_height_mm,
          enable_fridge_magnet: state.enable_fridge_magnet,
          fridge_magnets:
            state.enable_fridge_magnet && state.fridge_magnets.length > 0
              ? state.fridge_magnets
              : undefined,
          replacement_regions:
            mergedReplacements && mergedReplacements.length > 0
              ? mergedReplacements
              : undefined,
          recipe_overrides:
            state.recipe_overrides.length > 0
              ? state.recipe_overrides
              : undefined,
          free_color_set:
            state.free_color_set.size > 0
              ? Array.from(state.free_color_set).map((h) => `#${h}`)
              : undefined,
          printer_id: useSettingsStore.getState().printerModel,
          slicer: useSettingsStore.getState().slicerSoftware,
          nozzle_size: useSettingsStore.getState().nozzleSize,
          enable_base_layer_height_modifier:
            useSettingsStore.getState().enableBaseLayerHeightModifier,
          use_cached_matched_rgb: state.regionReplacementCount > 0,
        } as const;

        _clientLog("generate: request prepared", {
          source_kind: sourceParams.source_kind,
          replacement_count: mergedReplacements?.length ?? 0,
          recipe_override_count: state.recipe_overrides.length,
          free_color_count: state.free_color_set.size,
          fridge_magnet_count: state.fridge_magnets.length,
          color_layers: baseParams.color_layers ?? null,
          layer_height_mm: baseParams.layer_height_mm ?? null,
          structure_mode: baseParams.structure_mode,
          separate_backing: baseParams.separate_backing,
          enable_relief: baseParams.enable_relief,
          enable_outline: baseParams.enable_outline,
          enable_cloisonne: baseParams.enable_cloisonne,
        });

        if (state.puzzleEnabled) {
          const puzzleResponse = await apiConvertGeneratePuzzle(sessionId, {
            ...buildPuzzlePreviewParams(state),
            params: baseParams,
          });
          set({
            isGenerating: false,
            modelUrl: null,
            batchPreviewItems: [],
            threemfDiskPath: puzzleResponse.threemf_disk_path ?? null,
            downloadUrl: puzzleResponse.download_url
              ? `${puzzleResponse.download_url}`
              : null,
            puzzleWarnings: puzzleResponse.warnings ?? [],
            puzzleResolvedRows: puzzleResponse.grid_rows ?? null,
            puzzleResolvedCols: puzzleResponse.grid_cols ?? null,
            puzzleResolvedPieceCount: puzzleResponse.piece_count ?? null,
          });
          _logGenerateTimer("puzzle 3mf received");
          _clientLog("generate: puzzle 3mf received", {
            download_url: puzzleResponse.download_url ?? null,
            threemf_disk_path: puzzleResponse.threemf_disk_path ?? null,
            warning_count: (puzzleResponse.warnings ?? []).length,
            grid_rows: puzzleResponse.grid_rows ?? null,
            grid_cols: puzzleResponse.grid_cols ?? null,
            piece_count: puzzleResponse.piece_count ?? null,
          });
          trackLuminaEvent("lumina_converter_generate_done", {
            source_version: state.source_version,
            source_kind: sourceParams.source_kind,
            color_mode: colorMode,
            modeling_mode: state.modeling_mode,
            output_kind: "puzzle_3mf",
            puzzle: true,
            large_format: false,
            elapsed_ms: getElapsedMsSince(_generateStartTime),
            warning_count: (puzzleResponse.warnings ?? []).length,
          });
          return null;
        }

        if (state.largeFormatEnabled) {
          const lfResponse = await apiConvertGenerateLargeFormat(sessionId, {
            target_height_mm: state.target_height_mm,
            tile_width_mm: state.tileWidthMm,
            tile_height_mm: state.tileHeightMm,
            params: baseParams,
          });
          set({
            isGenerating: false,
            modelUrl: null,
            batchPreviewItems: [],
            threemfDiskPath: null,
            downloadUrl: lfResponse.download_url
              ? `${lfResponse.download_url}`
              : null,
            largeFormatWarnings: lfResponse.warnings ?? [],
          });
          _clientLog("generate: large-format zip received", {
            download_url: lfResponse.download_url ?? null,
            warning_count: (lfResponse.warnings ?? []).length,
            target_height_mm: state.target_height_mm,
            tile_width_mm: state.tileWidthMm,
            tile_height_mm: state.tileHeightMm,
          });
          trackLuminaEvent("lumina_converter_generate_done", {
            source_version: state.source_version,
            source_kind: sourceParams.source_kind,
            color_mode: colorMode,
            modeling_mode: state.modeling_mode,
            output_kind: "large_format_zip",
            puzzle: false,
            large_format: true,
            elapsed_ms: getElapsedMsSince(_generateStartTime),
            warning_count: (lfResponse.warnings ?? []).length,
          });
          return null;
        }

        _logGenerateTimer("request sent");
        _clientLog("generate: request sent", {
          session_id: sessionId,
          source_kind: sourceParams.source_kind,
          replacement_count: mergedReplacements?.length ?? 0,
          recipe_override_count: state.recipe_overrides.length,
          free_color_count: state.free_color_set.size,
        });
        const response = await apiConvertGenerate(sessionId, baseParams);
        _logGenerateTimer("response received");
        _clientLog("generate: response received", {
          preview_3d_url: response.preview_3d_url ?? null,
          download_url: response.download_url ?? null,
          threemf_disk_path: response.threemf_disk_path ?? null,
        });
        const modelUrl = response.preview_3d_url
          ? `${response.preview_3d_url}`
          : null;
        set({
          isGenerating: false,
          // Keep previewGlbUrl as the 3D viewer source: it renders the
          // pixel-level colour-mixed preview. The generate GLB contains the
          // exact per-material geometry used for 3MF export which looks like
          // solid single-colour blocks and confuses users. Only fall back to
          // modelUrl when no preview GLB exists (e.g. raster flow).
          // 保留 previewGlbUrl 作为 3D 预览源：它渲染像素级混色预览。
          // generate GLB 是 3MF 导出用的精确分材料几何，看起来是纯色块。
          // 只在没有 preview GLB 时（如光栅流程）才用 modelUrl。
          modelUrl: useConverterStore.getState().previewGlbUrl
            ? null
            : modelUrl,
          batchPreviewItems: [],
          threemfDiskPath: response.threemf_disk_path ?? null,
          downloadUrl: response.download_url
            ? `${response.download_url}`
            : null,
          largeFormatWarnings: [],
        });
        _logGenerateTimer("UI unlocked (isGenerating=false, modelUrl set)");
        _clientLog("generate: UI unlocked", {
          model_url: modelUrl,
          download_url: response.download_url ?? null,
          threemf_disk_path: response.threemf_disk_path ?? null,
        });
        trackLuminaEvent("lumina_converter_generate_done", {
          source_version: state.source_version,
          source_kind: sourceParams.source_kind,
          color_mode: colorMode,
          modeling_mode: state.modeling_mode,
          output_kind: "threemf",
          puzzle: false,
          large_format: false,
          elapsed_ms: getElapsedMsSince(_generateStartTime),
          warning_count: 0,
        });
        return modelUrl;
      } catch (err) {
        set({
          isGenerating: false,
          error: err instanceof Error ? err.message : "生成失败",
        });
        trackLuminaEvent("lumina_converter_generate_failed", {
          source_version: state.source_version,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          puzzle: state.puzzleEnabled,
          large_format: state.largeFormatEnabled,
          elapsed_ms: getElapsedMsSince(_generateStartTime),
          error_type: getErrorType(err),
        });
        _clientLog("generate: failed", summarizeErrorForLog(err), "error");
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
          quantize_colors: clampValue(
            result.recommended,
            8,
            _get().quantize_colors_unlocked ? 8192 : 256,
          ),
          autoDetectColorsLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
        });
      } catch (err) {
        set({
          autoDetectColorsLoading: false,
          error:
            err instanceof Error ? err.message : "Auto color detection failed",
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
          batchPreviewItems: [],
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
        batchPreviewItems: [],
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
        const isSvg = isSvgFile(singleFile);
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
            batchPreviewItems: [],
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
            batchPreviewItems: [],
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
            batchPreviewItems: [],
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
        batchPreviewItems: [],
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
      let state = _get();
      const batchStartTime =
        typeof performance !== "undefined" ? performance.now() : null;
      const batchFileCount = state.batchFiles.length;
      const sourceSelection = resolveConverterSourceSelection(state);
      if (!sourceSelection.isReady) {
        set({
          error:
            state.source_version === "material"
              ? "请先选择耗材"
              : state.source_version === "native"
                ? "请先选择品牌和数据库"
                : "请先选择 LUT",
        });
        return;
      }
      const autoReliefHeightMap = buildMissingAutoReliefHeightMap(state);
      if (autoReliefHeightMap) {
        set({ color_height_map: autoReliefHeightMap });
        state = _get();
      }
      if (state.enable_relief && state.autoHeightMode === "use-heightmap") {
        set({
          error: "批量生成暂不支持高度图浮雕，请改用按颜色浮雕或单图生成",
        });
        return;
      }
      if (
        state.enable_relief &&
        Object.keys(state.color_height_map).length === 0
      ) {
        set({ error: "请先设置颜色高度映射后再批量生成" });
        return;
      }
      set({
        batchLoading: true,
        batchResult: null,
        batchPreviewItems: [],
        modelUrl: null,
        previewGlbUrl: null,
        threemfDiskPath: null,
        downloadUrl: null,
        error: null,
      });
      try {
        const reliefHeightmapMaxHeight = state.enable_relief
          ? state.spacer_thick + state.heightmap_max_height
          : state.heightmap_max_height;
        const reliefColorHeightMap =
          state.enable_relief && state.autoHeightMode !== "use-heightmap"
            ? toAbsoluteReliefHeightMap(
                state.color_height_map,
                state.spacer_thick,
              )
            : undefined;
        const settings = useSettingsStore.getState();
        const resolvedSourceSelection = resolveConverterSourceSelection(state);
        const sourceParams =
          state.source_version === "material"
            ? buildMaterialSourceParams(state)
            : state.source_version === "native"
              ? buildNativeSourceParams(resolvedSourceSelection, state)
              : buildLegacySourceParams(state.lut_name);
        if (!sourceParams) {
          set({
            batchLoading: false,
            error: "请先选择品牌和数据库",
          });
          return;
        }
        const params = {
          ...sourceParams,
          target_width_mm: state.target_width_mm,
          spacer_thick: state.spacer_thick,
          structure_mode: state.structure_mode,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          color_layers:
            state.source_version === "material"
              ? state.materialLayerCount
              : sourceParams.source_kind === "native_bundle"
                ? (sourceParams.color_layers ?? undefined)
                : (state.color_layers ?? undefined),
          layer_height_mm:
            state.source_version === "material"
              ? state.materialLayerHeightMm
              : sourceParams.source_kind === "native_bundle"
                ? (sourceParams.layer_height_mm ?? undefined)
                : (state.layer_height_mm ?? undefined),
          quantize_colors: state.quantize_colors,
          enable_cleanup: state.enable_cleanup,
          svg_pixels_per_mm: settings.svgPixelsPerMm,
          hue_weight: state.hue_enable ? 0.5 : 0.0,
          chroma_gate: state.hue_enable ? state.chroma_gate : 0,
          use_lut_constrained: state.use_lut_constrained,
          auto_dynamic_range: state.auto_dynamic_range,
          enable_relief: state.enable_relief,
          printer_id: settings.printerModel,
          slicer: settings.slicerSoftware,
          nozzle_size: settings.nozzleSize,
          enable_base_layer_height_modifier:
            settings.enableBaseLayerHeightModifier,
          ...(state.enable_relief
            ? {
                height_mode: "color",
                color_height_map: reliefColorHeightMap,
                heightmap_max_height: reliefHeightmapMaxHeight,
              }
            : {}),
        };
        const result = await apiConvertBatch(state.batchFiles, params);
        const previewItems = (result.preview_items ?? [])
          .slice(0, BATCH_PREVIEW_BROWSER_SAFE_LIMIT)
          .map((item) => ({
            ...item,
            url: normalizeResourceUrl(item.url) ?? item.url,
          }));
        set({
          batchResult: result,
          batchLoading: false,
          batchPreviewItems: previewItems,
          // 批量预览只接受 preview_items。旧的 preview_3d_url 曾经指向
          // 合并 GLB，颜色与背面显示不可靠，因此不再作为 UI 兜底。
          modelUrl: null,
          previewGlbUrl: null,
          threemfDiskPath: result.threemf_disk_path ?? null,
          downloadUrl: result.download_url ? `${result.download_url}` : null,
        });
        trackLuminaEvent("lumina_batch_convert_done", {
          source_version: state.source_version,
          source_kind: sourceParams.source_kind,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          file_count_bucket: getFileCountBucket(batchFileCount),
          elapsed_ms: getElapsedMsSince(batchStartTime),
          preview_item_count: previewItems.length,
        });
      } catch (err) {
        set({
          batchLoading: false,
          error: err instanceof Error ? err.message : "批量处理失败",
        });
        trackLuminaEvent("lumina_batch_convert_failed", {
          source_version: state.source_version,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          file_count_bucket: getFileCountBucket(batchFileCount),
          elapsed_ms: getElapsedMsSince(batchStartTime),
          error_type: getErrorType(err),
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
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
        };
        if (response.preview_3d_url) {
          updates.previewGlbUrl = normalizeResourceUrl(response.preview_3d_url);
        }
        set(updates);
        _get()._pollAsyncGlb();
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
        // Resolve each remap entry to its palette-backed selected_color
        // (falling back to the key if the palette doesn't list it) and
        // send them in a single batch request — the backend runs PNG +
        // GLB + material sync exactly once for the whole map.
        // 将 colorRemapMap 一次性打包发给 /replace-colors-batch，后端
        // PNG/GLB/物料 sync 只跑 1 次，代替老的 N 次循环。
        const pairs = entries.map(([origHex, newHex]) => {
          const paletteEntry = state.palette.find(
            (p) => p.matched_hex === origHex,
          );
          const sel = paletteEntry ? paletteEntry.matched_hex : origHex;
          return {
            selectedColor: `#${sel}`,
            replacementColor: `#${newHex}`,
          };
        });
        const response = await apiReplaceColorsBatch(state.sessionId, pairs);
        const updates: Partial<ConverterState> = {
          replacePreviewLoading: false,
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
        };
        if (response.preview_3d_url) {
          updates.previewGlbUrl = normalizeResourceUrl(response.preview_3d_url);
        }
        set(updates);
        _get()._pollAsyncGlb();
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

    importRecipeState: (
      partial: Partial<ConverterState>,
      imageFile: File,
      heightmapFile?: File | null,
    ) => {
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
      const keepIds = collectConverterKeepFileIds(state);
      apiCleanupSessionFiles(state.sessionId, keepIds);
      void apiCloseSession(state.sessionId, keepIds);
      set({ sessionId: null });
    },
  })),
);

registerGeneratedArtifactInvalidator(() => {
  useConverterStore.setState({
    modelUrl: null,
    threemfDiskPath: null,
    downloadUrl: null,
  });
});
