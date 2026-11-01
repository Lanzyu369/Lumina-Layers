/** Vector-mode SVG gradient steps. 矢量模式 SVG 渐变切分颜色数。 */
export const SVG_GRADIENT_COLOR_BANDS_DEFAULT = 32;
export const SVG_GRADIENT_COLOR_BANDS_MIN = 8;
export const SVG_GRADIENT_COLOR_BANDS_MAX = 64;

/** Older recipes derived gradient steps from quantize colors within this range. */
const LEGACY_BANDS_MIN = 16;
const LEGACY_BANDS_MAX = 32;

/** Round and clamp to the supported range. 取整并夹紧到支持范围。 */
export function normalizeSvgGradientColorBands(value: number): number {
  if (!Number.isFinite(value)) return SVG_GRADIENT_COLOR_BANDS_DEFAULT;
  return Math.min(
    SVG_GRADIENT_COLOR_BANDS_MAX,
    Math.max(SVG_GRADIENT_COLOR_BANDS_MIN, Math.round(value)),
  );
}

/** Keep older recipes' gradient result when the field is absent. 旧配方缺字段时保持原渐变结果。 */
export function restoreSvgGradientColorBands(
  value: number | undefined,
  quantizeColors: number,
): number {
  if (value !== undefined) return normalizeSvgGradientColorBands(value);
  return Math.min(LEGACY_BANDS_MAX, Math.max(LEGACY_BANDS_MIN, quantizeColors));
}
