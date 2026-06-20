/**
 * Lumina Recipe schema type definitions.
 * Lumina 配方 schema 类型定义。
 *
 * V1: Full-site unified recipe schema, initially wired to converter only.
 * V1: 全站统一配方 schema，首批仅接入 converter。
 */

import type { FridgeMagnetItem } from "../api/types";

// ========== Asset ==========

/** Embedded asset entry (original file bytes preserved). */
export interface AssetEntry {
  filename: string;
  mime_type: string;
  byte_size: number;
  sha256: string;
  encoding: "base64";
  payload_b64: string;
}

// ========== LUT Reference ==========

/** LUT identity for fingerprint-based matching. */
export interface LutReference {
  name: string;
  color_mode: string;
  fingerprint: string;
  path_hint?: string;
}

// ========== Converter Recipe Sub-sections ==========

export interface ConverterRecipeBase {
  lut: LutReference;
  color_mode: string;
  modeling_mode: string;
  target_width_mm: number;
  target_height_mm: number;
  /** @deprecated removed; kept optional for legacy recipe parsing only */
  auto_bg?: boolean;
  /** @deprecated removed; kept optional for legacy recipe parsing only */
  bg_tol?: number;
  quantize_colors: number;
  high_precision_3d_preview?: boolean;
  enable_cleanup: boolean;
  svg_pixels_per_mm?: number;
  hue_enable: boolean;
  chroma_gate: number;
}

export interface ConverterRecipeGeometry {
  spacer_thick: number;
  structure_mode: string;
  separate_backing: boolean;
  add_loop: boolean;
  loop_width: number;
  loop_length: number;
  loop_hole: number;
  loop_angle: number;
  loop_offset_x: number;
  loop_offset_y: number;
  loop_position_preset: string;
}

export interface ConverterRecipeRelief {
  enable_relief: boolean;
  auto_height_mode: string;
  color_height_map: Record<string, number>;
  heightmap_max_height: number;
}

export interface ConverterRecipeOutline {
  enable_outline: boolean;
  outline_width: number;
}

export interface ConverterRecipeCloisonne {
  enable_cloisonne: boolean;
  wire_width_mm: number;
  wire_height_mm: number;
}

export interface ConverterRecipeCoating {
  enable_coating: boolean;
  coating_height_mm: number;
}

export interface ConverterRecipeColorOps {
  replacement_regions: Array<{
    quantized_hex: string;
    matched_hex: string;
    replacement_hex: string;
  }>;
  free_color_set: string[];
  /** V2+: per-region custom recipe overrides (region_id, recipe, layer_order). */
  recipe_overrides?: Array<{
    region_id: string;
    recipe: number[];
    layer_order: string;
    virtual_materials?: Array<{
      name: string;
      hex: string;
    }>;
  }>;
  /** V2+: session-scoped custom recipe history; imported with fromModel forced to false. */
  custom_recipe_history?: Array<{
    id: string;
    recipe: number[];
    layer_order: string;
    predicted_rgb: [number, number, number];
    predicted_lab: [number, number, number];
    hex: string;
    from_model: boolean;
    /** 每层用户意图原色 hex（可选，v2 之后新增）。 */
    display_hexes?: string[];
    /** 每层用户意图原色名（可选，v2 之后新增）。 */
    display_labels?: string[];
    virtual_materials?: Array<{
      name: string;
      hex: string;
    }>;
    created_at_ms: number;
  }>;
}

export interface ConverterRecipeLargeFormat {
  large_format_enabled: boolean;
  tile_width_mm: number;
  tile_height_mm: number;
}

export interface ConverterRecipePuzzle {
  puzzle_enabled: boolean;
  puzzle_style: string;
  puzzle_sizing_mode: string;
  piece_width_mm: number;
  piece_height_mm: number;
  puzzle_rows: number;
  puzzle_cols: number;
  target_piece_count: number;
  puzzle_seed: number;
  connector_style: string;
  labels_enabled: boolean;
  engrave_back_labels: boolean;
  irregularity_strength: number;
  min_neck_width_mm: number;
}

export interface ConverterRecipeDevice {
  printer_id: string;
  slicer: string;
  nozzle_size: string;
  /** V2 generated machine-registry device profile ID. */
  device_profile_id?: string;
}

export interface ConverterRecipeFridgeMagnet {
  enable_fridge_magnet: boolean;
  fridge_magnets: FridgeMagnetItem[];
}

export interface ConverterRecipeSource {
  source_version: "legacy" | "native" | "material" | string;
  selected_native_brand_key: string;
  selected_native_db_names: string[];
  color_layers: number | null;
  layer_height_mm: number | null;
  model_enable: boolean;
  model_only: boolean;
  model_threshold: number | null;
  model_margin: number | null;
  selected_material_dir_names: string[];
  material_layer_count: number;
  material_layer_height_mm: number;
  material_backing_material_dir_name: string | null;
}

// ========== Converter Recipe (combined) ==========

export interface ConverterRecipe {
  base: ConverterRecipeBase;
  source?: ConverterRecipeSource;
  geometry: ConverterRecipeGeometry;
  relief: ConverterRecipeRelief;
  outline: ConverterRecipeOutline;
  cloisonne: ConverterRecipeCloisonne;
  coating: ConverterRecipeCoating;
  color_ops: ConverterRecipeColorOps;
  large_format: ConverterRecipeLargeFormat;
  puzzle: ConverterRecipePuzzle;
  fridge_magnet?: ConverterRecipeFridgeMagnet;
  device: ConverterRecipeDevice;
}

// ========== Top-level Recipe ==========

export type RecipeSource =
  | "converter"
  | "extractor"
  | "calibration"
  | "lut-manager";

export interface RecipeCover {
  width: number;
  height: number;
  mime_type: "image/png";
}

export interface RecipeAssets {
  primary: AssetEntry;
  heightmap?: AssetEntry;
}

export interface RecipeIntegrity {
  recipe_sha256: string;
  asset_checksums: Record<string, string>;
}

export interface RecipeCompat {
  min_schema_version: number;
  degraded_fields?: string[];
}

export interface LuminaRecipe {
  format: "lumina-recipe";
  schema_version: number;
  app_version: string;
  created_at: string;
  source: RecipeSource;
  cover: RecipeCover;
  asset: RecipeAssets;
  recipe: {
    converter?: ConverterRecipe;
  };
  integrity: RecipeIntegrity;
  compat: RecipeCompat;
  warnings: string[];
}

// ========== Constants ==========

export const RECIPE_FORMAT = "lumina-recipe" as const;
export const RECIPE_SCHEMA_VERSION = 2;
