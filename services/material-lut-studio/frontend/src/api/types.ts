// MLS API response/request types.
// 这些类型镜像后端 api/schemas/lut.py 与 responses.py 的契约；保持字段同步。

export interface LutInfo {
  name: string;
  color_mode: string;
  path: string;
  fingerprint: string;
}

export interface LutListResponse {
  luts: LutInfo[];
}

export interface PaletteEntry {
  color: string;
  material: string;
  hex_color: string | null;
  color_name: string | null;
}

export interface LutInfoResponse {
  name: string;
  color_mode: string;
  color_count: number;
  palette: PaletteEntry[];
  max_color_layers: number;
  layer_height_mm: number;
  base_channel_idx: number;
  source_kind: string;
  capabilities: string[];
  supports_custom_recipe: boolean;
}

export interface MergeRequest {
  primary_name: string;
  secondary_names: string[];
  dedup_threshold: number;
}

export interface MergeStats {
  total_before: number;
  total_after: number;
  exact_dupes: number;
  similar_removed: number;
}

export interface MergeResponse {
  status: string;
  message: string;
  filename: string;
  stats: MergeStats;
  palette: PaletteEntry[];
  warnings: string[];
}

export interface CompareRequest {
  lut_a_name: string;
  lut_b_name: string;
  top_n: number;
}

export interface CompareStats {
  matched_recipe_count: number;
  recipe_coverage_a: number;
  recipe_coverage_b: number;
  mean_delta_e00: number;
  median_delta_e00: number;
  p95_delta_e00: number;
  max_delta_e00: number;
  identical_rgb_count: number;
  recipes_only_in_a: number;
  recipes_only_in_b: number;
}

export interface CompareDiffItem {
  recipe: string[];
  rgb_a: number[];
  rgb_b: number[];
  hex_a: string;
  hex_b: string;
  delta_e00: number;
}

export interface CompareResponse {
  status: string;
  message: string;
  lut_a_name: string;
  lut_b_name: string;
  lut_a_mode: string;
  lut_b_mode: string;
  stats: CompareStats;
  warnings: string[];
  worst_diffs: CompareDiffItem[];
}

export interface MaterialSummary {
  directory_name?: string;
  material_name?: string;
  name?: string;
  brand?: string;
  estimated_rgb?: number[];
  material_file_url?: string;
  stage_a_params_url?: string;
  [key: string]: unknown;
}

export interface MaterialLibraryResponse {
  status: string;
  message: string;
  materials: MaterialSummary[];
}

export interface MaterialDeleteResponse {
  status: string;
  message: string;
  directory_name: string;
  material_name: string;
}

export interface MaterialBulkExportResponse {
  status: string;
  message: string;
  download_url: string;
  filename: string;
  exported_count: number;
  exported_directory_names: string[];
}

export interface MaterialBulkImportResponse {
  status: string;
  message: string;
  imported_count: number;
  imported_materials: MaterialSummary[];
}

export interface SolverCacheEntry {
  palette_hash: string;
  material_directory_names: string[];
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  grid_resolution: number;
  total_combinations: number;
  valid_cell_count: number;
  total_cell_count: number;
  mean_delta_e: number;
  max_delta_e: number;
  build_time_seconds: number;
  built_at: string | null;
  cache_file_size_bytes: number;
  cache_file_path: string | null;
  [key: string]: unknown;
}

export interface SolverCacheListResponse {
  status: string;
  message: string;
  entries: SolverCacheEntry[];
}
