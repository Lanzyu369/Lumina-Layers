/**
 * Recipe export adapter: extracts stable parameters from converter store state.
 * 配方导出适配器：从 converter store 状态中提取稳定参数。
 */

import type {
  ConverterRecipe,
  LuminaRecipe,
  LutReference,
  RecipeAssets,
  RecipeCover,
} from "./types";
import { RECIPE_FORMAT, RECIPE_SCHEMA_VERSION } from "./types";
import { buildAssetEntry, sha256String } from "./utils";
import { colorRemapToReplacementRegions } from "../utils/colorUtils";
import type { ConverterState } from "../stores/converter/store";
import type { SettingsState } from "../stores/settingsStore";
import type { ColorReplacementItem } from "../api/types";

// ========== Hex normalization ==========

/** Ensure hex color has '#' prefix. */
function ensureHash(hex: string): string {
  return hex.startsWith("#") ? hex : `#${hex}`;
}

// ========== App version ==========

declare const __LUMINA_VERSION__: string | undefined;

function getAppVersion(): string {
  try {
    return typeof __LUMINA_VERSION__ === "string" ? __LUMINA_VERSION__ : "0.0.0";
  } catch {
    return "0.0.0";
  }
}

// ========== Export adapter ==========

/**
 * Build a ConverterRecipe from the current converter store state and settings.
 * 从当前 converter store 状态和设置中构建 ConverterRecipe。
 *
 * @param state - Current ConverterState snapshot.
 * @param settings - Current SettingsState snapshot.
 * @param lutFingerprint - SHA-256 fingerprint of the current LUT (first 32 hex chars).
 */
export function exportConverterRecipe(
  state: ConverterState,
  settings: SettingsState,
  lutFingerprint: string,
): ConverterRecipe {
  // Merge colorRemapMap into replacement_regions
  let mergedReplacements: ColorReplacementItem[] = [
    ...state.replacement_regions,
  ];
  if (Object.keys(state.colorRemapMap).length > 0) {
    const remapRegions = colorRemapToReplacementRegions(
      state.colorRemapMap,
      state.palette,
    );
    mergedReplacements = [...mergedReplacements, ...remapRegions];
  }

  // Normalize replacement hex values to '#' prefix
  const normalizedReplacements = mergedReplacements.map((r) => ({
    quantized_hex: ensureHash(r.quantized_hex),
    matched_hex: ensureHash(r.matched_hex),
    replacement_hex: ensureHash(r.replacement_hex),
  }));

  // Normalize free_color_set to '#' prefix
  const normalizedFreeColors = Array.from(state.free_color_set).map(ensureHash);

  // Normalize color_height_map keys to '#' prefix
  const normalizedHeightMap: Record<string, number> = {};
  for (const [hex, height] of Object.entries(state.color_height_map)) {
    normalizedHeightMap[ensureHash(hex)] = height;
  }

  const lutRef: LutReference = {
    name: state.lut_name,
    color_mode: state.color_mode,
    fingerprint: lutFingerprint,
  };

  return {
    base: {
      lut: lutRef,
      color_mode: state.color_mode,
      modeling_mode: state.modeling_mode,
      target_width_mm: state.target_width_mm,
      target_height_mm: state.target_height_mm,
      quantize_colors: state.quantize_colors,
      enable_cleanup: state.enable_cleanup,
      svg_pixels_per_mm: settings.svgPixelsPerMm,
      hue_enable: state.hue_enable,
      chroma_gate: state.chroma_gate,
    },
    source: {
      source_version: state.source_version,
      selected_native_brand_key: state.selectedNativeBrandKey,
      selected_native_db_names: [...state.selectedNativeDbNames],
      color_layers: state.color_layers,
      layer_height_mm: state.layer_height_mm,
      model_enable: state.model_enable,
      model_only: state.model_only,
      model_threshold: state.model_threshold,
      model_margin: state.model_margin,
      selected_material_dir_names: [...state.selectedMaterialDirNames],
      material_layer_count: state.materialLayerCount,
      material_layer_height_mm: state.materialLayerHeightMm,
      material_backing_material_dir_name: state.materialBackingMaterialDirName,
    },
    geometry: {
      spacer_thick: state.enable_fridge_magnet
        ? state.base_spacer_thick
        : state.spacer_thick,
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
    },
    relief: {
      enable_relief: state.enable_relief,
      auto_height_mode: state.autoHeightMode,
      color_height_map: normalizedHeightMap,
      heightmap_max_height: state.heightmap_max_height,
    },
    outline: {
      enable_outline: state.enable_outline,
      outline_width: state.outline_width,
    },
    cloisonne: {
      enable_cloisonne: state.enable_cloisonne,
      wire_width_mm: state.wire_width_mm,
      wire_height_mm: state.wire_height_mm,
    },
    coating: {
      enable_coating: state.enable_coating,
      coating_height_mm: state.coating_height_mm,
    },
    color_ops: {
      replacement_regions: normalizedReplacements,
      free_color_set: normalizedFreeColors,
      recipe_overrides: state.recipe_overrides.map((item) => ({
        region_id: item.region_id,
        recipe: [...item.recipe],
        layer_order: item.layer_order,
      })),
      custom_recipe_history: state.customRecipeHistory.map((item) => ({
        id: item.id,
        recipe: [...item.recipe],
        layer_order: item.layerOrder,
        predicted_rgb: [...item.predictedRgb],
        predicted_lab: [...item.predictedLab],
        hex: item.hex,
        from_model: item.fromModel,
        created_at_ms: item.createdAtMs,
        ...(item.displayHexes
          ? { display_hexes: [...item.displayHexes] }
          : {}),
        ...(item.displayLabels
          ? { display_labels: [...item.displayLabels] }
          : {}),
      })),
    },
    large_format: {
      large_format_enabled: state.largeFormatEnabled,
      tile_width_mm: state.tileWidthMm,
      tile_height_mm: state.tileHeightMm,
    },
    puzzle: {
      puzzle_enabled: state.puzzleEnabled,
      puzzle_style: state.puzzleStyle,
      puzzle_sizing_mode: state.puzzleSizingMode,
      piece_width_mm: state.pieceWidthMm,
      piece_height_mm: state.pieceHeightMm,
      puzzle_rows: state.puzzleRows,
      puzzle_cols: state.puzzleCols,
      target_piece_count: state.targetPieceCount,
      puzzle_seed: 0,
      connector_style: state.connectorStyle,
      labels_enabled: state.labelsEnabled,
      engrave_back_labels: false,
      irregularity_strength: state.irregularityStrength,
      min_neck_width_mm: state.minNeckWidthMm,
    },
    fridge_magnet: {
      enable_fridge_magnet: state.enable_fridge_magnet,
      fridge_magnets: state.fridge_magnets.map((item) => ({
        ...item,
      })),
    },
    device: {
      printer_id: settings.printerModel,
      slicer: settings.slicerSoftware,
      nozzle_size: settings.nozzleSize,
    },
  };
}

/**
 * Build a full LuminaRecipe from components.
 * 从各组件构建完整 LuminaRecipe。
 *
 * @param converterRecipe - The converter recipe section.
 * @param cover - Cover image metadata.
 * @param assets - Primary and optional heightmap asset entries.
 * @returns The complete LuminaRecipe with integrity hashes.
 */
export async function buildFullRecipe(
  converterRecipe: ConverterRecipe,
  cover: RecipeCover,
  assets: RecipeAssets,
): Promise<LuminaRecipe> {
  // Compute asset checksums
  const assetChecksums: Record<string, string> = {
    primary: assets.primary.sha256,
  };
  if (assets.heightmap) {
    assetChecksums["heightmap"] = assets.heightmap.sha256;
  }

  // Build recipe without integrity first (for hashing)
  const recipeWithoutIntegrity: Omit<LuminaRecipe, "integrity"> & {
    integrity?: unknown;
  } = {
    format: RECIPE_FORMAT,
    schema_version: RECIPE_SCHEMA_VERSION,
    app_version: getAppVersion(),
    created_at: new Date().toISOString(),
    source: "converter",
    cover,
    asset: assets,
    recipe: {
      converter: converterRecipe,
    },
    compat: {
      min_schema_version: 1,
    },
    warnings: [],
  };

  // Compute recipe SHA-256 (over the recipe section only, for stability)
  const recipeJsonForHash = JSON.stringify(recipeWithoutIntegrity.recipe);
  const recipeSha256 = await sha256String(recipeJsonForHash);

  const fullRecipe: LuminaRecipe = {
    ...(recipeWithoutIntegrity as Omit<LuminaRecipe, "integrity">),
    integrity: {
      recipe_sha256: recipeSha256,
      asset_checksums: assetChecksums,
    },
  };

  return fullRecipe;
}

/**
 * Build assets from File objects.
 * 从 File 对象构建 assets。
 */
export async function buildRecipeAssets(
  primaryFile: File,
  heightmapFile?: File | null,
): Promise<RecipeAssets> {
  const primary = await buildAssetEntry(primaryFile);
  const assets: RecipeAssets = { primary };
  if (heightmapFile) {
    assets.heightmap = await buildAssetEntry(heightmapFile);
  }
  return assets;
}

/**
 * Create a cover image by rendering the preview URL to a resized canvas PNG.
 * 通过将预览 URL 渲染到缩放画布上来创建封面图。
 *
 * @param previewUrl - URL of the current 2D preview image.
 * @param maxWidth - Maximum width for the cover thumbnail (default: 800).
 * @returns Cover PNG blob and metadata.
 */
export async function buildCoverImage(
  previewUrl: string,
  maxWidth: number = 800,
): Promise<{ blob: Blob; cover: RecipeCover }> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const scale = Math.min(1, maxWidth / img.naturalWidth);
      const w = Math.round(img.naturalWidth * scale);
      const h = Math.round(img.naturalHeight * scale);

      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("Failed to create canvas context"));
        return;
      }
      ctx.drawImage(img, 0, 0, w, h);

      canvas.toBlob(
        (blob) => {
          if (!blob) {
            reject(new Error("Failed to create cover PNG blob"));
            return;
          }
          resolve({
            blob,
            cover: { width: w, height: h, mime_type: "image/png" },
          });
        },
        "image/png",
      );
    };
    img.onerror = () => reject(new Error("Failed to load preview image for cover"));
    img.src = previewUrl;
  });
}
