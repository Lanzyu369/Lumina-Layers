/**
 * Curated filament material presets used by the single-stage / gradient-card
 * calibration workflow.
 *
 * These values are written into the kit manifest (`material_default`) and
 * surface in the UI as the default material label for every generated job.
 * Exposing a free-text input lets users type non-standard names (typos,
 * internal codes, etc.), which then flow through 3MF metadata and the
 * ChromaPrint3D pipeline. Constraining the input to this curated list keeps
 * the downstream data clean and matches the filament naming conventions used
 * by the supported slicer profiles (BambuStudio / OrcaSlicer / SnapmakerOrca /
 * ElegooSlicer / AnycubicSlicerNext).
 *
 * 单阶段/梯度卡标定流程使用的耗材预设列表。该值会写入套件 manifest 的
 * `material_default` 字段，并作为每个生成任务的默认耗材标签显示在 UI 中。
 * 此前是自由文本输入，用户可能输入拼写错误或内部编号等非标准值，这些数据
 * 会向下游流入 3MF 元数据和 ChromaPrint3D 管线。用预设列表限定输入可以保持
 * 下游数据整洁，并与受支持的切片软件配置（BambuStudio / OrcaSlicer /
 * SnapmakerOrca / ElegooSlicer / AnycubicSlicerNext）的耗材命名保持一致。
 *
 * When adding a new preset, keep the display label consistent with the
 * canonical slicer label (e.g. "PLA Basic", not "Basic PLA").
 * 新增预设时请保持显示名与切片软件的规范命名一致（如 "PLA Basic"，
 * 而非 "Basic PLA"）。
 */

export interface MaterialPreset {
  /** Canonical filament label written to the kit manifest. */
  value: string;
}

export const MATERIAL_PRESETS: ReadonlyArray<MaterialPreset> = [
  // PLA family / PLA 系列
  { value: "PLA Basic" },
  { value: "PLA Matte" },
  { value: "PLA Silk" },
  { value: "PLA-CF" },
  { value: "PLA Metal" },
  { value: "PLA Marble" },
  { value: "PLA Wood" },
  { value: "PLA Glow" },
  { value: "PLA Galaxy" },
  { value: "PLA Aero" },
  // PETG family / PETG 系列
  { value: "PETG HF" },
  { value: "PETG Translucent" },
  { value: "PETG-CF" },
  // TPU / 柔性
  { value: "TPU 95A" },
  { value: "TPU for AMS" },
];

/**
 * Default value for `materialDefault` in the calibration store and backend
 * schemas. Must exist in `MATERIAL_PRESETS`.
 * 标定 store 与后端 schema 的默认值，必须存在于 `MATERIAL_PRESETS` 中。
 */
export const DEFAULT_MATERIAL_PRESET: string = "PLA Basic";

/**
 * Dropdown-ready options derived from the curated preset list.
 * 由预设列表派生的 Dropdown 可用选项。
 */
export const MATERIAL_PRESET_OPTIONS: ReadonlyArray<{ label: string; value: string }> =
  MATERIAL_PRESETS.map((preset) => ({ label: preset.value, value: preset.value }));

/**
 * True when `value` is part of the curated preset list.
 * 判断 `value` 是否为预设之一。
 */
export function isKnownMaterialPreset(value: string): boolean {
  return MATERIAL_PRESETS.some((preset) => preset.value === value);
}
