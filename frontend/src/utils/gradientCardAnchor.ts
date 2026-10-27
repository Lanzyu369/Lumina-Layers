import type { ManualOrientationLabel } from "../api/types";

/**
 * Visual position of the pure-substrate (zero-layer) anchor block on a
 * gradient card photo. Users select where the bare-board patch sits on
 * their photo so the extractor can determine the canonical sampling order
 * without forcing them to memorise abstract D4 transform names.
 *
 * 用户在梯度卡照片上指认"露出底板"的纯色块所在角。提取器以此推导规范化的
 * 采样顺序，使用户无需理解抽象的 D4 变换名。
 */
export type GradientCardAnchorCorner = "tl" | "tr" | "br" | "bl";

/**
 * Map an anchor-corner choice (or ``null`` for auto) to the backend's
 * canonical orientation label. The mapping assumes the user picked the
 * four corner points in the conventional TL → TR → BR → BL clockwise
 * order on screen, so:
 *   - anchor ``tl`` lines up with ``identity``;
 *   - anchor ``tr`` rotates clockwise by 90°;
 *   - anchor ``br`` rotates 180°;
 *   - anchor ``bl`` rotates counter-clockwise by 90°.
 *
 * 将"色块位置"选项（或 ``null`` 表示自动）映射为后端方向标签。映射假设
 * 用户按屏幕上"左上→右上→右下→左下"顺时针顺序点选 4 个角点。
 *
 * @param anchor User-selected anchor corner. (用户选择的色块角)
 * @returns Backend orientation label, or ``null`` when caller wants
 *          fully automatic detection. (后端方向标签；为 null 时表示自动)
 */
export function anchorToOrientationLabel(
  anchor: GradientCardAnchorCorner | null,
): ManualOrientationLabel | null {
  switch (anchor) {
    case "tl":
      return "identity";
    case "tr":
      return "flip_horizontal";
    case "br":
      return "rotate_180";
    case "bl":
      return "flip_vertical";
    case null:
    case undefined:
      return null;
    default: {
      const exhaustive: never = anchor;
      void exhaustive;
      return null;
    }
  }
}

/**
 * Ordered list of all valid anchor corners. The order matches the
 * conventional TL → TR → BR → BL clockwise sequence used throughout the
 * gradient-card UI.
 *
 * 全部有效的色块位置，按"左上→右上→右下→左下"顺时针顺序排列；与梯度卡
 * UI 中其他位置约定保持一致。
 */
export const GRADIENT_CARD_ANCHOR_CORNERS: readonly GradientCardAnchorCorner[] =
  ["tl", "tr", "br", "bl"];
