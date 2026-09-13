/** Physical SVG source compensation settings. SVG 原图二维补洞参数。 */
export interface SvgHoleCompensationOptions {
  svg_hole_compensation_enabled: boolean;
  svg_hole_max_area_mm2: number;
  svg_hole_max_width_mm: number;
}

export const SVG_HOLE_COMPENSATION_DEFAULTS: SvgHoleCompensationOptions = {
  svg_hole_compensation_enabled: false,
  svg_hole_max_area_mm2: 0.5,
  svg_hole_max_width_mm: 0.1,
};

/** Keep only the three public source-SVG options. 只提取公开的 SVG 补洞参数。 */
export function svgHoleCompensationOptions(
  value: Partial<SvgHoleCompensationOptions>,
): SvgHoleCompensationOptions {
  return {
    svg_hole_compensation_enabled: value.svg_hole_compensation_enabled ?? false,
    svg_hole_max_area_mm2:
      value.svg_hole_max_area_mm2 ?? SVG_HOLE_COMPENSATION_DEFAULTS.svg_hole_max_area_mm2,
    svg_hole_max_width_mm:
      value.svg_hole_max_width_mm ?? SVG_HOLE_COMPENSATION_DEFAULTS.svg_hole_max_width_mm,
  };
}

/** Validate the physical contract without changing values. 校验物理参数，不修改数值。 */
export function validSvgHoleCompensationOptions(
  value: SvgHoleCompensationOptions,
): boolean {
  return typeof value.svg_hole_compensation_enabled === "boolean" &&
    Number.isFinite(value.svg_hole_max_area_mm2) && value.svg_hole_max_area_mm2 >= 0 &&
    Number.isFinite(value.svg_hole_max_width_mm) && value.svg_hole_max_width_mm >= 0;
}
