/**
 * Shared helpers for rendering quick-recolor recipe suggestions.
 * 快速换色中配方推荐的共享展示辅助函数。
 */

/** One printable channel shown inside recipe layer chips. */
export interface RecipeChannel {
  name: string;
  hex: string | null;
}

/** ΔE00 thresholds that map to user-facing match-quality labels. */
const DELTA_E_CLOSE = 2;
const DELTA_E_NEAR = 5;

/** Return the i18n key describing how close a ΔE00 match is. */
export function deltaEQualityKey(deltaE: number): string {
  if (deltaE <= DELTA_E_CLOSE) return "quick_replace_delta_e_close";
  if (deltaE <= DELTA_E_NEAR) return "quick_replace_delta_e_near";
  return "quick_replace_delta_e_far";
}

/** Human-readable layer list, viewing face first (e.g. ``Red / White``). */
export function describeRecipeLayers(
  recipe: number[],
  channels: RecipeChannel[],
): string {
  return recipe
    .map((index) => channels[index]?.name ?? `#${index}`)
    .join(" / ");
}
