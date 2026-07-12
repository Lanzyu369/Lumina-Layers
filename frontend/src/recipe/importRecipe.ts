/**
 * Recipe import adapter: parses recipe files and maps back to converter store state.
 * 配方导入适配器：解析配方文件并映射回 converter store 状态。
 */

import type {
  AssetEntry,
  ConverterRecipeSource,
  LuminaRecipe,
} from "./types";
import {
  MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
} from "../stores/converter/store";
import type { ConverterState } from "../stores/converter/store";
import type {
  ColorReplacementItem,
  FridgeMagnetItem,
  LutInfo,
  RecipeHistoryItem,
} from "../api/types";
import { extractRecipeFromPng } from "./pngMetadata";
import { migrateRecipe } from "./migration";
import { base64ToFile, sha256Hex, sha256String } from "./utils";
import {
  normalizeFridgeMagnetItems,
  resolveFridgeMagnetSpacerThick,
} from "../constants/fridgeMagnets";

// ========== Hex normalization ==========

/** Strip '#' prefix from a hex color string. */
function stripHash(hex: string): string {
  return hex.startsWith("#") ? hex.slice(1) : hex;
}

function cloneVirtualMaterials(
  materials: Array<{ name: string; hex: string }> | undefined,
): Array<{ name: string; hex: string }> | undefined {
  if (!materials || materials.length === 0) {
    return undefined;
  }
  return materials.map((material) => ({
    name: material.name,
    hex: material.hex,
  }));
}

function normalizeImportedDynamicLayerCount(
  value: unknown,
  fallback: number,
): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(
    MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
    Math.max(MATERIAL_DYNAMIC_LAYER_COUNT_MIN, Math.round(value)),
  );
}

function resolveImportedDynamicLayerBounds(
  source: ConverterRecipeSource | undefined,
): { minimum: number; maximum: number } {
  const minimum = normalizeImportedDynamicLayerCount(
    source?.material_min_layer_count,
    MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
  );
  const maximum = normalizeImportedDynamicLayerCount(
    source?.material_max_layer_count,
    MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  );
  return {
    minimum: Math.min(minimum, maximum),
    maximum: Math.max(minimum, maximum),
  };
}

// ========== Source detection ==========

export type RecipeFileSource = "png" | "json";

export const RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_PUZZLE =
  "recipe_import_warning_fridge_conflict_puzzle";
export const RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LARGE_FORMAT =
  "recipe_import_warning_fridge_conflict_large_format";
export const RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LOOP =
  "recipe_import_warning_fridge_conflict_loop";
export const RECIPE_IMPORT_WARNING_LUT_DEGRADED =
  "recipe_import_lut_degraded";
export const RECIPE_IMPORT_WARNING_LUT_MISSING =
  "recipe_import_lut_missing";
export const RECIPE_IMPORT_WARNING_SECONDARY_LUT_MISSING =
  "recipe_import_warning_secondary_lut_missing";
export const RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LARGE_FORMAT =
  "recipe_import_warning_puzzle_conflict_large_format";
export const RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LOOP =
  "recipe_import_warning_puzzle_conflict_loop";
export const RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE =
  "recipe_import_warning_back_labels_unavailable";

export const RECIPE_IMPORT_NOT_SHARE_CARD_ERROR =
  "PNG file does not contain Lumina recipe metadata";
export const RECIPE_INTEGRITY_ERROR =
  "Integrity check failed — recipe data may be corrupted";
export const RECIPE_ASSET_CORRUPT_ERROR =
  "Asset data is corrupted — unable to restore original file";

/**
 * Detect whether a file is a Lumina share card PNG or a .lumina.json sidecar.
 * 检测文件是 Lumina 分享卡 PNG 还是 .lumina.json sidecar。
 */
export function detectRecipeFileType(file: File): RecipeFileSource | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".lumina.json")) return "json";
  if (name.endsWith(".png") && file.type === "image/png") return "png";
  // Also accept PNG files without explicit type (some OS don't set MIME)
  if (name.endsWith(".png")) return "png";
  return null;
}

// ========== Parse entry ==========

export interface ParsedRecipe {
  recipe: LuminaRecipe;
  source: RecipeFileSource;
}

/**
 * Parse a recipe from a file (PNG or JSON).
 * 从文件（PNG 或 JSON）中解析配方。
 *
 * @throws Error if the file cannot be parsed or contains invalid recipe data.
 */
export async function parseRecipeFile(file: File): Promise<ParsedRecipe> {
  const fileType = detectRecipeFileType(file);

  if (fileType === "json") {
    const text = await file.text();
    let raw: unknown;
    try {
      raw = JSON.parse(text);
    } catch {
      throw new Error("Invalid .lumina.json: failed to parse JSON");
    }
    const recipe = migrateRecipe(raw);
    await validateRecipeIntegrity(recipe);
    return { recipe, source: "json" };
  }

  if (fileType === "png") {
    const recipe = await extractRecipeFromPng(file);
    if (!recipe) {
      throw new Error(RECIPE_IMPORT_NOT_SHARE_CARD_ERROR);
    }
    const migrated = migrateRecipe(recipe);
    await validateRecipeIntegrity(migrated);
    return { recipe: migrated, source: "png" };
  }

  throw new Error(`Unsupported file type: ${file.name}`);
}

async function validateRecipeIntegrity(recipe: LuminaRecipe): Promise<void> {
  const integrity = recipe.integrity;
  if (
    !integrity ||
    typeof integrity.recipe_sha256 !== "string" ||
    !integrity.asset_checksums ||
    typeof integrity.asset_checksums !== "object"
  ) {
    throw new Error(RECIPE_INTEGRITY_ERROR);
  }

  const expectedRecipeHash = await sha256String(JSON.stringify(recipe.recipe));
  if (expectedRecipeHash !== integrity.recipe_sha256) {
    throw new Error(RECIPE_INTEGRITY_ERROR);
  }

  const assetEntries = recipe.asset;
  await validateAssetIntegrity("primary", assetEntries?.primary, integrity.asset_checksums);
  if (assetEntries?.heightmap) {
    await validateAssetIntegrity("heightmap", assetEntries.heightmap, integrity.asset_checksums);
  }
}

async function validateAssetIntegrity(
  key: "primary" | "heightmap",
  asset: AssetEntry | undefined,
  checksums: Record<string, string>,
): Promise<void> {
  if (
    !asset ||
    asset.encoding !== "base64" ||
    typeof asset.payload_b64 !== "string" ||
    typeof asset.sha256 !== "string" ||
    typeof asset.byte_size !== "number" ||
    typeof checksums[key] !== "string"
  ) {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }

  let bytes: ArrayBuffer;
  try {
    bytes = await base64ToFile(
      asset.payload_b64,
      asset.filename,
      asset.mime_type,
    ).arrayBuffer();
  } catch {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }

  if (bytes.byteLength !== asset.byte_size) {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }

  const actualHash = await sha256Hex(bytes);
  if (actualHash !== asset.sha256 || actualHash !== checksums[key]) {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }
}

// ========== LUT matching ==========

export type LutMatchResult =
  | { matched: true; lutName: string; matchType: "fingerprint" | "name" }
  | { matched: false; originalName: string; originalFingerprint: string };

/**
 * Match a LUT reference against the locally available LUT list.
 * 将 LUT 引用与本地可用的 LUT 列表匹配。
 *
 * Priority: fingerprint → name → not found.
 */
export function matchLut(
  lutRef: { name: string; fingerprint: string },
  localLuts: LutInfo[],
  localFingerprints: Record<string, string>,
): LutMatchResult {
  // 1. Fingerprint match
  for (const lut of localLuts) {
    const fp = localFingerprints[lut.name];
    if (fp && fp === lutRef.fingerprint) {
      return { matched: true, lutName: lut.name, matchType: "fingerprint" };
    }
  }

  // 2. Name match
  const byName = localLuts.find((l) => l.name === lutRef.name);
  if (byName) {
    return { matched: true, lutName: byName.name, matchType: "name" };
  }

  // 3. Not found
  return {
    matched: false,
    originalName: lutRef.name,
    originalFingerprint: lutRef.fingerprint,
  };
}

function normalizeStringList(values: string[] | undefined): string[] {
  const seen = new Set<string>();
  return (values ?? []).filter((value) => {
    const trimmed = value.trim();
    if (!trimmed || seen.has(trimmed)) {
      return false;
    }
    seen.add(trimmed);
    return true;
  });
}

function restoreLegacyLutNames(
  primaryName: string,
  selectedNames: string[] | undefined,
  localLuts: LutInfo[],
): { names: string[]; missingSecondary: boolean } {
  if (!primaryName) {
    return { names: [], missingSecondary: false };
  }

  const availableNames = new Set(localLuts.map((lut) => lut.name));
  const normalized = normalizeStringList(selectedNames);
  const secondaryNames = normalized.slice(1);
  const names = [primaryName];
  let missingSecondary = false;
  for (const name of secondaryNames) {
    if (name === primaryName || names.includes(name)) {
      continue;
    }
    if (availableNames.has(name)) {
      names.push(name);
    } else {
      missingSecondary = true;
    }
  }
  return { names, missingSecondary };
}

// ========== Restore result ==========

export interface RestoreResult {
  /** Partial state to merge into converter store. */
  state: Partial<ConverterState>;
  /** Restored primary asset as a File object. */
  assetFile: File;
  /** Restored heightmap as a File object (if present). */
  heightmapFile: File | null;
  /** Warnings to display to the user. */
  warnings: string[];
  /** The full parsed recipe (for display in confirm dialog). */
  recipe: LuminaRecipe;
}

/**
 * Restore converter state from a parsed LuminaRecipe.
 * 从解析的 LuminaRecipe 恢复 converter 状态。
 *
 * @param recipe - The parsed and migrated LuminaRecipe.
 * @param localLuts - Available LUT list from the store.
 * @param localFingerprints - LUT name → fingerprint map.
 * @returns RestoreResult with partial state, files, and warnings.
 */
export function restoreConverterRecipe(
  recipe: LuminaRecipe,
  localLuts: LutInfo[],
  localFingerprints: Record<string, string>,
): RestoreResult {
  if (!recipe.recipe.converter) {
    throw new Error("Recipe does not contain converter data");
  }

  const conv = recipe.recipe.converter;
  const warnings: string[] = [...recipe.warnings];

  // --- Restore primary asset ---
  const primaryAsset = recipe.asset.primary;
  const assetFile = base64ToFile(
    primaryAsset.payload_b64,
    primaryAsset.filename,
    primaryAsset.mime_type,
  );

  // --- Restore heightmap asset ---
  let heightmapFile: File | null = null;
  if (recipe.asset.heightmap) {
    const hm = recipe.asset.heightmap;
    heightmapFile = base64ToFile(hm.payload_b64, hm.filename, hm.mime_type);
  }

  // --- LUT matching ---
  const lutMatch = matchLut(conv.base.lut, localLuts, localFingerprints);
  let lutName = "";
  if (lutMatch.matched) {
    lutName = lutMatch.lutName;
    if (lutMatch.matchType === "name") {
      warnings.push(RECIPE_IMPORT_WARNING_LUT_DEGRADED);
    }
  } else {
    warnings.push(RECIPE_IMPORT_WARNING_LUT_MISSING);
  }
  const source = conv.source;
  const dynamicBounds = resolveImportedDynamicLayerBounds(source);
  const dynamicMaterialEnabled =
    source?.source_version === "material" &&
    source.material_dynamic_layer_count_enabled === true;
  const restoredLegacyLutNames = restoreLegacyLutNames(
    lutName,
    source?.selected_legacy_lut_names,
    localLuts,
  );
  if (restoredLegacyLutNames.missingSecondary) {
    warnings.push(RECIPE_IMPORT_WARNING_SECONDARY_LUT_MISSING);
  }

  // --- Normalize hex values (strip '#' for store) ---
  const replacementRegions: ColorReplacementItem[] =
    conv.color_ops.replacement_regions.map((r) => ({
      quantized_hex: stripHash(r.quantized_hex),
      matched_hex: stripHash(r.matched_hex),
      replacement_hex: stripHash(r.replacement_hex),
    }));

  const freeColorSet = new Set(
    conv.color_ops.free_color_set.map(stripHash),
  );

  // V2+ optional: recipe_overrides (back-compat: missing → empty array)
  const recipeOverrides = (conv.color_ops.recipe_overrides ?? []).map(
    (item) => {
      const virtualMaterials = cloneVirtualMaterials(item.virtual_materials);
      return {
        region_id: item.region_id,
        recipe: [...item.recipe],
        layer_order: item.layer_order,
        ...(virtualMaterials
          ? { virtual_materials: virtualMaterials }
          : {}),
      };
    },
  );

  // V2+ optional: custom_recipe_history — fromModel is forced to false on import
  // because we left the original session's forward-model context.
  // 历史条目导入后 fromModel 强制为 false：离开原会话模型上下文后不再保留"来自模型"标记。
  const customRecipeHistory: RecipeHistoryItem[] = (
    conv.color_ops.custom_recipe_history ?? []
  ).map((item) => {
    const virtualMaterials = cloneVirtualMaterials(item.virtual_materials);
    return {
      id: item.id,
      recipe: [...item.recipe],
      layerOrder: item.layer_order,
      predictedRgb: [
        item.predicted_rgb[0],
        item.predicted_rgb[1],
        item.predicted_rgb[2],
      ],
      predictedLab: [
        item.predicted_lab[0],
        item.predicted_lab[1],
        item.predicted_lab[2],
      ],
      hex: item.hex,
      fromModel: false,
      createdAtMs: item.created_at_ms,
      ...(item.display_hexes
        ? { displayHexes: [...item.display_hexes] }
        : {}),
      ...(item.display_labels
        ? { displayLabels: [...item.display_labels] }
        : {}),
      ...(virtualMaterials ? { virtualMaterials } : {}),
    };
  });

  const colorHeightMap: Record<string, number> = {};
  for (const [hex, height] of Object.entries(conv.relief.color_height_map)) {
    colorHeightMap[stripHash(hex)] = height;
  }

  const puzzle = conv.puzzle ?? {
    puzzle_enabled: false,
    puzzle_style: "regular",
    puzzle_sizing_mode: "piece_size",
    piece_width_mm: 20,
    piece_height_mm: 20,
    puzzle_rows: 3,
    puzzle_cols: 3,
    target_piece_count: 12,
    puzzle_seed: 0,
    connector_style: "classic",
    labels_enabled: false,
    engrave_back_labels: false,
    irregularity_strength: 0.35,
    min_neck_width_mm: 1.2,
  };

  const fridgeMagnet = conv.fridge_magnet ?? {
    enable_fridge_magnet: false,
    fridge_magnets: [],
  };
  const normalizedFridgeMagnets = normalizeFridgeMagnetItems(
    fridgeMagnet.fridge_magnets as FridgeMagnetItem[],
  );

  const fridgeMagnetEnabled = Boolean(fridgeMagnet.enable_fridge_magnet);
  const puzzleEnabled = fridgeMagnetEnabled
    ? false
    : Boolean(puzzle.puzzle_enabled);
  const largeFormatEnabled = fridgeMagnetEnabled
    ? false
    : puzzleEnabled
      ? false
      : conv.large_format.large_format_enabled;
  const addLoop = fridgeMagnetEnabled
    ? false
    : puzzleEnabled
      ? false
      : conv.geometry.add_loop;
  const engraveBackLabels = false;

  if (fridgeMagnetEnabled && puzzle.puzzle_enabled) {
    warnings.push(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_PUZZLE);
  }
  if (fridgeMagnetEnabled && conv.large_format.large_format_enabled) {
    warnings.push(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LARGE_FORMAT);
  }
  if (fridgeMagnetEnabled && conv.geometry.add_loop) {
    warnings.push(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LOOP);
  }
  if (puzzleEnabled && conv.large_format.large_format_enabled) {
    warnings.push(
      RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LARGE_FORMAT,
    );
  }
  if (puzzleEnabled && conv.geometry.add_loop) {
    warnings.push(
      RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LOOP,
    );
  }
  if (puzzle.engrave_back_labels) {
    warnings.push(
      RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE,
    );
  }

  // --- Build partial state ---
  const state: Partial<ConverterState> = {
    // Base
    source_version: (source?.source_version ?? "legacy") as ConverterState["source_version"],
    lut_name: lutName,
    lut_names: restoredLegacyLutNames.names,
    color_mode: conv.base.color_mode as ConverterState["color_mode"],
    modeling_mode: conv.base.modeling_mode as ConverterState["modeling_mode"],
    target_width_mm: conv.base.target_width_mm,
    target_height_mm: conv.base.target_height_mm,
    quantize_colors: conv.base.quantize_colors,
    high_precision_3d_preview: Boolean(conv.base.high_precision_3d_preview),
    enable_cleanup: conv.base.enable_cleanup,
    hue_enable: dynamicMaterialEnabled ? false : conv.base.hue_enable,
    chroma_gate: conv.base.chroma_gate,
    selectedNativeBrandKey: source?.selected_native_brand_key ?? "",
    selectedNativeDbNames: [...(source?.selected_native_db_names ?? [])],
    color_layers: source?.color_layers ?? null,
    layer_height_mm: source?.layer_height_mm ?? null,
    model_enable: source?.model_enable ?? false,
    model_only: source?.model_only ?? false,
    model_threshold: source?.model_threshold ?? null,
    model_margin: source?.model_margin ?? null,
    selectedMaterialDirNames: [...(source?.selected_material_dir_names ?? [])],
    materialLayerCount: source?.material_layer_count ?? 5,
    materialLayerHeightMm: source?.material_layer_height_mm ?? 0.08,
    materialBackingMaterialDirName: source?.material_backing_material_dir_name ?? null,
    materialDynamicLayerCountEnabled: dynamicMaterialEnabled,
    materialMinLayerCount: dynamicBounds.minimum,
    materialMaxLayerCount: dynamicBounds.maximum,
    // Exported result metadata is historical evidence only. A new preview
    // must recompute it for the imported image/material runtime.
    materialDynamicRecipes: [],
    materialLayerBenefitCurve: [],

    // Geometry
    spacer_thick: resolveFridgeMagnetSpacerThick(
      conv.geometry.spacer_thick,
      fridgeMagnetEnabled,
      normalizedFridgeMagnets,
    ),
    base_spacer_thick: conv.geometry.spacer_thick,
    structure_mode: (
      fridgeMagnetEnabled
        ? "Single-sided"
        : conv.geometry.structure_mode
    ) as ConverterState["structure_mode"],
    separate_backing: conv.geometry.separate_backing,
    add_loop: addLoop,
    loop_width: conv.geometry.loop_width,
    loop_length: conv.geometry.loop_length,
    loop_hole: conv.geometry.loop_hole,
    loop_angle: conv.geometry.loop_angle,
    loop_offset_x: conv.geometry.loop_offset_x,
    loop_offset_y: conv.geometry.loop_offset_y,
    loop_position_preset: conv.geometry.loop_position_preset,

    // Relief
    enable_relief: conv.relief.enable_relief,
    autoHeightMode: conv.relief.auto_height_mode as ConverterState["autoHeightMode"],
    color_height_map: colorHeightMap,
    heightmap_max_height: conv.relief.heightmap_max_height,

    // Outline
    enable_outline: conv.outline.enable_outline,
    outline_width: conv.outline.outline_width,

    // Cloisonne
    enable_cloisonne: conv.cloisonne.enable_cloisonne,
    wire_width_mm: conv.cloisonne.wire_width_mm,
    wire_height_mm: conv.cloisonne.wire_height_mm,

    // Coating
    enable_coating: conv.coating.enable_coating,
    coating_height_mm: conv.coating.coating_height_mm,

    // Color ops
    replacement_regions: replacementRegions,
    free_color_set: freeColorSet,
    recipe_overrides: recipeOverrides,
    customRecipeHistory: customRecipeHistory,
    // Clear remap state — replacement_regions already contains merged data
    colorRemapMap: {},
    remapHistory: [],

    // Large format
    largeFormatEnabled: largeFormatEnabled,
    tileWidthMm: conv.large_format.tile_width_mm,
    tileHeightMm: conv.large_format.tile_height_mm,
    puzzleEnabled,
    puzzleStyle: puzzle.puzzle_style as ConverterState["puzzleStyle"],
    puzzleSizingMode: puzzle.puzzle_sizing_mode as ConverterState["puzzleSizingMode"],
    pieceWidthMm: puzzle.piece_width_mm,
    pieceHeightMm: puzzle.piece_height_mm,
    puzzleRows: puzzle.puzzle_rows,
    puzzleCols: puzzle.puzzle_cols,
    targetPieceCount: puzzle.target_piece_count,
    connectorStyle: puzzle.connector_style as ConverterState["connectorStyle"],
    labelsEnabled: puzzle.labels_enabled,
    engraveBackLabels,
    irregularityStrength: puzzle.irregularity_strength,
    minNeckWidthMm: puzzle.min_neck_width_mm,
    enable_fridge_magnet: fridgeMagnetEnabled,
    fridge_magnets: normalizedFridgeMagnets,
    selectedFridgeMagnetId: null,

    // Clear session/preview state (will be rebuilt on next preview)
    sessionId: null,
    previewImageUrl: null,
    previewGlbUrl: null,
    modelUrl: null,
    threemfDiskPath: null,
    downloadUrl: null,
    hasManualPreview: false,
    layerImages: [],
    layerImagesOpen: false,
    layerImagesSourceKey: null,
    regionData: null,
    selectedRegions: [],
    pendingReplacement: null,
    regionReplacementCount: 0,
    error: null,
    puzzleOverlayUrl: null,
    puzzleWarnings: [],
    puzzleResolvedRows: null,
    puzzleResolvedCols: null,
    puzzleResolvedPieceCount: null,
    puzzleDerivedPieceWidthMm: null,
    puzzleDerivedPieceHeightMm: null,
  };

  return {
    state,
    assetFile,
    heightmapFile,
    warnings,
    recipe,
  };
}
