import type { ConverterState } from "../stores/converter/store";
import type {
  AdvancedParams,
  AdvancedParamsColorReplacement,
  AdvancedParamsDimensions,
  AdvancedParamsFridgeMagnet,
  AdvancedParamsFull,
  AdvancedParamsGeneration,
  AdvancedParamsLargeFormat,
  AdvancedParamsLoop,
  AdvancedParamsCloisonne,
  AdvancedParamsCoating,
  AdvancedParamsOutline,
  AdvancedParamsPuzzle,
  AdvancedParamsRelief,
  AdvancedParamsSizeTrimmed,
  ColorReplacementScalarItem,
  FileMetadata,
  FridgeMagnetScalarItem,
} from "../types/actionHistory";
import type {
  ColorReplacementItem,
  FridgeMagnetItem,
  RecipeOverrideItem,
} from "../api/types";
import { SVG_PIXELS_PER_MM_DEFAULT } from "../stores/settingsStore";
import { colorRemapToReplacementRegions } from "./colorUtils";

/**
 * Hard limits enforced on the advanced_params payload before size
 * measurement. Keep these in sync with the backend sanitizer
 * (_sanitize_advanced_params) and the requirements document.
 * 在测量字节前对 advanced_params 应用的硬上限；需与后端 sanitizer 及需求文档保持一致。
 */
const MAX_COLOR_HEIGHT_MAP_ENTRIES = 64;
const MAX_FRIDGE_MAGNETS = 20;
const MAX_REPLACEMENT_REGIONS = 32;
const MAX_FREE_COLOR_SET_ENTRIES = 64;
const MAX_RECIPE_OVERRIDES = 32;

/**
 * Options controlling the serialized byte budget for the built object.
 * maxBytes is 8192 for the bug-report context payload and 4096 for each
 * action-history snapshot.
 * 构建选项：maxBytes 用于限制序列化后的字节预算；反馈上下文 8192、快照 4096。
 */
export interface BuildAdvancedParamsOptions {
  maxBytes: number;
  svgPixelsPerMm?: number;
}

/**
 * Build a grouped `AdvancedParams` snapshot from the converter store
 * state. Returns `null` when the converter tab is not active. The builder
 * is deterministic: identical `(state, activeTab, options.maxBytes)` tuples
 * produce byte-identical JSON output.
 *
 * The function applies, in order:
 *   1. Disabled-toggle → null rules for each of the 8 feature groups that
 *      have a master switch (relief, outline, cloisonne, coating, loop,
 *      fridge_magnet, puzzle, large_format).
 *   2. File → FileMetadata conversion (`name`, `size`, `type` only; never
 *      Blob or data URL).
 *   3. Truncation caps: color_height_map ≤ 64, fridge_magnets ≤ 20,
 *      replacement_regions ≤ 32 — each sets its corresponding
 *      `_truncated: true` flag when trimmed.
 *   4. Four-tier byte-limit trimming when the serialized object exceeds
 *      `options.maxBytes`; falls back to `AdvancedParamsSizeTrimmed`
 *      carrying the pre-trim UTF-8 byte count when every tier still
 *      overflows.
 *
 * 根据 converter store 状态构建分组化的 AdvancedParams 快照；非 converter Tab
 * 时返回 null。对于相同的 (state, activeTab, maxBytes) 组合，输出是字节级确定的。
 * 依次执行：各功能组"关闭即置 null"规则 → File 转 FileMetadata → 长度上限
 * 截断（并置 _truncated: true）→ 四层字节裁剪；全部裁剪后仍超限时回落到
 * AdvancedParamsSizeTrimmed（记录裁剪前的 UTF-8 字节数）。
 */
export function buildAdvancedParams(
  state: ConverterState,
  activeTab: string,
  options: BuildAdvancedParamsOptions,
): AdvancedParams | null {
  if (activeTab !== "converter") {
    return null;
  }

  const full = buildFullParams(state, options);
  return applyByteLimitTrimming(full, options.maxBytes);
}

// ---------------------------------------------------------------------------
// Full params assembly (no byte trimming)
// 完整参数组装（未进行字节裁剪）
// ---------------------------------------------------------------------------

function buildFullParams(
  state: ConverterState,
  options: BuildAdvancedParamsOptions,
): AdvancedParamsFull {
  return {
    dimensions: buildDimensions(state),
    generation: buildGeneration(state, options),
    relief: buildRelief(state),
    outline: buildOutline(state),
    cloisonne: buildCloisonne(state),
    coating: buildCoating(state),
    loop: buildLoop(state),
    fridge_magnet: buildFridgeMagnet(state),
    puzzle: buildPuzzle(state),
    large_format: buildLargeFormat(state),
    color_replacement: buildColorReplacement(state),
  };
}

function buildDimensions(state: ConverterState): AdvancedParamsDimensions {
  return {
    target_width_mm: state.target_width_mm,
    target_height_mm: state.target_height_mm,
    spacer_thick: state.spacer_thick,
    base_spacer_thick: state.base_spacer_thick,
  };
}

function buildGeneration(
  state: ConverterState,
  options: BuildAdvancedParamsOptions,
): AdvancedParamsGeneration {
  return {
    structure_mode: state.structure_mode,
    modeling_mode: state.modeling_mode,
    color_layers: state.color_layers,
    layer_height_mm: state.layer_height_mm,
    model_enable: state.model_enable,
    model_only: state.model_only,
    model_threshold: state.model_threshold,
    model_margin: state.model_margin,
    quantize_colors: state.quantize_colors,
    quantize_colors_unlocked: state.quantize_colors_unlocked,
    high_precision_3d_preview: state.high_precision_3d_preview,
    enable_cleanup: state.enable_cleanup,
    svg_pixels_per_mm:
      typeof options.svgPixelsPerMm === "number"
        ? options.svgPixelsPerMm
        : SVG_PIXELS_PER_MM_DEFAULT,
    hue_enable: state.hue_enable,
    chroma_gate: state.chroma_gate,
    use_lut_constrained: state.use_lut_constrained,
    auto_dynamic_range: state.auto_dynamic_range,
    separate_backing: state.separate_backing,
  };
}

function buildRelief(state: ConverterState): AdvancedParamsRelief {
  const hasHeightmapThumbnail = state.heightmapThumbnailUrl !== null;

  if (!state.enable_relief) {
    return {
      enable_relief: false,
      color_height_map: null,
      heightmap_max_height: null,
      autoHeightMode: null,
      heightmapFile: null,
      hasHeightmapThumbnail,
    };
  }

  const { map, truncated } = trimColorHeightMap(state.color_height_map);
  const result: AdvancedParamsRelief = {
    enable_relief: true,
    color_height_map: map,
    heightmap_max_height: state.heightmap_max_height,
    autoHeightMode: state.autoHeightMode ?? null,
    heightmapFile: serializeFileMetadata(state.heightmapFile),
    hasHeightmapThumbnail,
  };
  if (truncated) {
    result.color_height_map_truncated = true;
  }
  return result;
}

function buildOutline(state: ConverterState): AdvancedParamsOutline {
  if (!state.enable_outline) {
    return { enable_outline: false, outline_width: null };
  }
  return {
    enable_outline: true,
    outline_width: state.outline_width,
  };
}

function buildCloisonne(state: ConverterState): AdvancedParamsCloisonne {
  if (!state.enable_cloisonne) {
    return {
      enable_cloisonne: false,
      wire_width_mm: null,
      wire_height_mm: null,
    };
  }
  return {
    enable_cloisonne: true,
    wire_width_mm: state.wire_width_mm,
    wire_height_mm: state.wire_height_mm,
  };
}

function buildCoating(state: ConverterState): AdvancedParamsCoating {
  if (!state.enable_coating) {
    return { enable_coating: false, coating_height_mm: null };
  }
  return {
    enable_coating: true,
    coating_height_mm: state.coating_height_mm,
  };
}

function buildLoop(state: ConverterState): AdvancedParamsLoop {
  if (!state.add_loop) {
    return {
      add_loop: false,
      loop_width: null,
      loop_length: null,
      loop_hole: null,
      loop_angle: null,
      loop_offset_x: null,
      loop_offset_y: null,
      loop_position_preset: null,
    };
  }
  return {
    add_loop: true,
    loop_width: state.loop_width,
    loop_length: state.loop_length,
    loop_hole: state.loop_hole,
    loop_angle: state.loop_angle,
    loop_offset_x: state.loop_offset_x,
    loop_offset_y: state.loop_offset_y,
    loop_position_preset: state.loop_position_preset,
  };
}

function buildFridgeMagnet(state: ConverterState): AdvancedParamsFridgeMagnet {
  if (!state.enable_fridge_magnet) {
    return {
      enable_fridge_magnet: false,
      selectedFridgeMagnetId: null,
      fridge_magnets: null,
    };
  }
  const { magnets, truncated } = serializeFridgeMagnets(state.fridge_magnets);
  const result: AdvancedParamsFridgeMagnet = {
    enable_fridge_magnet: true,
    selectedFridgeMagnetId: state.selectedFridgeMagnetId ?? null,
    fridge_magnets: magnets,
  };
  if (truncated) {
    result.fridge_magnets_truncated = true;
  }
  return result;
}

function buildPuzzle(state: ConverterState): AdvancedParamsPuzzle {
  if (!state.puzzleEnabled) {
    return {
      puzzleEnabled: false,
      puzzleStyle: null,
      puzzleSizingMode: null,
      pieceWidthMm: null,
      pieceHeightMm: null,
      puzzleRows: null,
      puzzleCols: null,
      targetPieceCount: null,
      connectorStyle: null,
      labelsEnabled: null,
      engraveBackLabels: null,
      irregularityStrength: null,
      minNeckWidthMm: null,
    };
  }
  return {
    puzzleEnabled: true,
    puzzleStyle: state.puzzleStyle,
    puzzleSizingMode: state.puzzleSizingMode,
    pieceWidthMm: state.pieceWidthMm,
    pieceHeightMm: state.pieceHeightMm,
    puzzleRows: state.puzzleRows,
    puzzleCols: state.puzzleCols,
    targetPieceCount: state.targetPieceCount,
    connectorStyle: state.connectorStyle,
    labelsEnabled: state.labelsEnabled,
    engraveBackLabels: state.engraveBackLabels,
    irregularityStrength: state.irregularityStrength,
    minNeckWidthMm: state.minNeckWidthMm,
  };
}

function buildLargeFormat(state: ConverterState): AdvancedParamsLargeFormat {
  if (!state.largeFormatEnabled) {
    return {
      largeFormatEnabled: false,
      tileWidthMm: null,
      tileHeightMm: null,
    };
  }
  return {
    largeFormatEnabled: true,
    tileWidthMm: state.tileWidthMm,
    tileHeightMm: state.tileHeightMm,
  };
}

function buildColorReplacement(
  state: ConverterState,
): AdvancedParamsColorReplacement {
  const liveReplacementRegions = colorRemapToReplacementRegions(
    state.colorRemapMap,
    state.palette,
  );
  const globalReplacementRegions = mergeGlobalReplacementRegions(
    state.replacement_regions,
    liveReplacementRegions,
  );
  const { regions, truncated } = serializeReplacementRegions(
    globalReplacementRegions,
  );
  const { colors, truncated: freeColorsTruncated } = serializeFreeColorSet(
    state.free_color_set,
  );
  const { overrides, truncated: overridesTruncated } =
    serializeRecipeOverrides(state.recipe_overrides);
  const result: AdvancedParamsColorReplacement = {
    replacement_regions: regions,
    spatial_edit_count: Number.isFinite(state.regionReplacementCount)
      ? Math.max(0, Math.trunc(state.regionReplacementCount))
      : 0,
    free_color_set: colors,
    recipe_overrides: overrides,
  };
  if (truncated) {
    result.replacement_regions_truncated = true;
  }
  if (freeColorsTruncated) {
    result.free_color_set_truncated = true;
  }
  if (overridesTruncated) {
    result.recipe_overrides_truncated = true;
  }
  return result;
}

// ---------------------------------------------------------------------------
// Serialization helpers
// 序列化辅助
// ---------------------------------------------------------------------------

function serializeFileMetadata(file: File | null): FileMetadata | null {
  if (!file) return null;
  return {
    name: file.name,
    size: file.size,
    type: file.type,
  };
}

function ensureHash(hex: string): string {
  return hex.startsWith("#") ? hex : `#${hex}`;
}

function normalizeReplacementSource(hex: string): string {
  return hex.trim().replace(/^#/, "").toLowerCase();
}

/**
 * Merge persisted and live global remaps by the source color used downstream.
 * Live store mappings are authoritative because they reflect the latest user
 * choice; deduplicating before serialization prevents stale duplicates from
 * consuming the 32-item telemetry allowance.
 *
 * 按下游实际使用的源色合并持久化与实时全局映射。实时映射代表用户最新选择，
 * 因此覆盖旧记录；在序列化前去重，避免陈旧重复项占用 32 条遥测上限。
 */
function mergeGlobalReplacementRegions(
  persisted: ColorReplacementItem[],
  live: ColorReplacementItem[],
): ColorReplacementItem[] {
  const bySource = new Map<string, ColorReplacementItem>();
  for (const item of [...persisted, ...live]) {
    const source =
      normalizeReplacementSource(item.matched_hex) ||
      normalizeReplacementSource(item.quantized_hex);
    bySource.set(source, item);
  }
  return Array.from(bySource.values());
}

function trimColorHeightMap(map: Record<string, number>): {
  map: Record<string, number> | null;
  truncated: boolean;
} {
  const entries = Object.entries(map);
  if (entries.length === 0) {
    return { map: null, truncated: false };
  }
  if (entries.length <= MAX_COLOR_HEIGHT_MAP_ENTRIES) {
    // Preserve insertion order.
    const out: Record<string, number> = {};
    for (const [key, value] of entries) {
      out[key] = value;
    }
    return { map: out, truncated: false };
  }
  const out: Record<string, number> = {};
  for (const [key, value] of entries.slice(0, MAX_COLOR_HEIGHT_MAP_ENTRIES)) {
    out[key] = value;
  }
  return { map: out, truncated: true };
}

function serializeFridgeMagnets(magnets: FridgeMagnetItem[]): {
  magnets: FridgeMagnetScalarItem[] | null;
  truncated: boolean;
} {
  if (magnets.length === 0) {
    return { magnets: null, truncated: false };
  }
  const truncated = magnets.length > MAX_FRIDGE_MAGNETS;
  const source = truncated ? magnets.slice(0, MAX_FRIDGE_MAGNETS) : magnets;
  const out: FridgeMagnetScalarItem[] = source.map((item) => ({
    id: item.id,
    shape: item.shape,
    preset_key: item.preset_key,
    diameter_mm: item.diameter_mm,
    width_mm: item.width_mm,
    height_mm: item.height_mm,
    thickness_mm: item.thickness_mm,
    center_x_mm: item.center_x_mm,
    center_y_mm: item.center_y_mm,
  }));
  return { magnets: out, truncated };
}

function serializeReplacementRegions(regions: ColorReplacementItem[]): {
  regions: ColorReplacementScalarItem[] | null;
  truncated: boolean;
} {
  if (regions.length === 0) {
    return { regions: null, truncated: false };
  }
  const truncated = regions.length > MAX_REPLACEMENT_REGIONS;
  const source = truncated
    ? regions.slice(0, MAX_REPLACEMENT_REGIONS)
    : regions;
  const out: ColorReplacementScalarItem[] = source.map((item) => ({
    quantized_hex: item.quantized_hex,
    matched_hex: item.matched_hex,
    replacement_hex: item.replacement_hex,
  }));
  return { regions: out, truncated };
}

function serializeFreeColorSet(colors: Set<string>): {
  colors: string[] | null;
  truncated: boolean;
} {
  if (colors.size === 0) {
    return { colors: null, truncated: false };
  }
  const source = Array.from(colors);
  const truncated = source.length > MAX_FREE_COLOR_SET_ENTRIES;
  const out = source
    .slice(0, MAX_FREE_COLOR_SET_ENTRIES)
    .map(ensureHash);
  return { colors: out, truncated };
}

function serializeRecipeOverrides(overrides: RecipeOverrideItem[]): {
  overrides: AdvancedParamsColorReplacement["recipe_overrides"];
  truncated: boolean;
} {
  if (overrides.length === 0) {
    return { overrides: null, truncated: false };
  }
  const truncated = overrides.length > MAX_RECIPE_OVERRIDES;
  const source = truncated
    ? overrides.slice(0, MAX_RECIPE_OVERRIDES)
    : overrides;
  const out = source.map((item) => ({
    region_id: item.region_id,
    recipe: [...item.recipe],
    layer_order: item.layer_order,
    ...(item.virtual_materials && item.virtual_materials.length > 0
      ? {
          virtual_materials: item.virtual_materials.map((material) => ({
            name: material.name,
            hex: material.hex,
          })),
        }
      : {}),
  }));
  return { overrides: out, truncated };
}

// ---------------------------------------------------------------------------
// Byte measurement and tiered trimming
// 字节测量与分层裁剪
// ---------------------------------------------------------------------------

const _textEncoder = new TextEncoder();

function serializedByteLength(obj: unknown): number {
  return _textEncoder.encode(JSON.stringify(obj)).length;
}

/**
 * Mutate `full` in place to null out the Tier-N payload.
 * 按层级就地清空对应字段。
 */
function applyTier(full: AdvancedParamsFull, tier: number): void {
  switch (tier) {
    case 1:
      full.fridge_magnet = {
        ...full.fridge_magnet,
        fridge_magnets: null,
      };
      return;
    case 2:
      full.relief = {
        ...full.relief,
        color_height_map: null,
      };
      return;
    case 3:
      full.color_replacement = {
        ...full.color_replacement,
        replacement_regions: null,
        free_color_set: null,
        recipe_overrides: null,
      };
      return;
    case 4:
      full.puzzle = {
        ...full.puzzle,
        puzzleStyle: null,
        puzzleSizingMode: null,
        pieceWidthMm: null,
        pieceHeightMm: null,
        puzzleRows: null,
        puzzleCols: null,
        targetPieceCount: null,
        connectorStyle: null,
        labelsEnabled: null,
        engraveBackLabels: null,
        irregularityStrength: null,
        minNeckWidthMm: null,
      };
      full.large_format = {
        ...full.large_format,
        tileWidthMm: null,
        tileHeightMm: null,
      };
      return;
    default:
      return;
  }
}

/**
 * Build a trimmed view with bookkeeping flags, so we can measure the
 * final size including `_size_trimmed` and `_dropped_tiers`.
 * 组装带裁剪标记的对象，便于把裁剪记录也纳入字节测量。
 */
function withTrimFlags(
  full: AdvancedParamsFull,
  droppedTiers: number[],
): AdvancedParamsFull {
  return {
    ...full,
    _size_trimmed: true,
    _dropped_tiers: [...droppedTiers],
  };
}

function applyByteLimitTrimming(
  full: AdvancedParamsFull,
  maxBytes: number,
): AdvancedParams {
  // Capture the pre-trim byte length exactly once. This is the only value
  // permitted to populate `_original_byte_length` in the fallback.
  // 仅在此处采样一次裁剪前的字节长度；fallback 只能使用该值。
  const originalByteLength = serializedByteLength(full);

  if (originalByteLength <= maxBytes) {
    return full;
  }

  const working: AdvancedParamsFull = { ...full };
  const droppedTiers: number[] = [];

  for (let tier = 1; tier <= 4; tier += 1) {
    applyTier(working, tier);
    droppedTiers.push(tier);

    // Measure with bookkeeping flags included so the post-flag size still
    // respects `maxBytes`. If it does not, drop another tier and repeat.
    // 测量时把裁剪标记也一起算入；标记推过上限时继续下一层。
    const candidate = withTrimFlags(working, droppedTiers);
    if (serializedByteLength(candidate) <= maxBytes) {
      return candidate;
    }
  }

  // Every tier + the trim flags still overflow; emit the minimal fallback.
  // 所有层级加上标记仍超限，返回最小回落对象。
  const fallback: AdvancedParamsSizeTrimmed = {
    _size_trimmed: true,
    _original_byte_length: originalByteLength,
  };
  return fallback;
}
