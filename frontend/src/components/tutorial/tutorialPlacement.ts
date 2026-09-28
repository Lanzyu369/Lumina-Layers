/**
 * Placement math for the tutorial step card.
 * 新手引导步骤卡片的定位计算。
 */

export interface TutorialRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface TutorialSize {
  width: number;
  height: number;
}

export type TutorialCardSide = "right" | "left" | "bottom" | "top" | "center";

export interface TutorialCardPosition {
  top: number;
  left: number;
  side: TutorialCardSide;
}

/** Gap between the spotlight and the card. 高亮框与卡片之间的间距。 */
export const TUTORIAL_CARD_GAP_PX = 16;
/** Minimum distance between the card and the viewport edge. 卡片与视口边缘的最小距离。 */
export const TUTORIAL_VIEWPORT_MARGIN_PX = 16;

const SIDE_ORDER: readonly Exclude<TutorialCardSide, "center">[] = [
  "right",
  "left",
  "bottom",
  "top",
];

function clamp(value: number, min: number, max: number): number {
  if (max < min) {
    return min;
  }
  return Math.min(Math.max(value, min), max);
}

function availableSpace(
  side: Exclude<TutorialCardSide, "center">,
  target: TutorialRect,
  viewport: TutorialSize,
): number {
  switch (side) {
    case "right":
      return viewport.width - (target.left + target.width);
    case "left":
      return target.left;
    case "bottom":
      return viewport.height - (target.top + target.height);
    case "top":
      return target.top;
  }
}

function requiredSpace(
  side: Exclude<TutorialCardSide, "center">,
  card: TutorialSize,
): number {
  const extent = side === "left" || side === "right" ? card.width : card.height;
  return extent + TUTORIAL_CARD_GAP_PX + TUTORIAL_VIEWPORT_MARGIN_PX;
}

function placeOnSide(
  side: Exclude<TutorialCardSide, "center">,
  target: TutorialRect,
  card: TutorialSize,
  viewport: TutorialSize,
): TutorialCardPosition {
  const margin = TUTORIAL_VIEWPORT_MARGIN_PX;
  const maxLeft = viewport.width - card.width - margin;
  const maxTop = viewport.height - card.height - margin;
  const centeredTop = target.top + target.height / 2 - card.height / 2;
  const centeredLeft = target.left + target.width / 2 - card.width / 2;

  let top: number;
  let left: number;
  switch (side) {
    case "right":
      left = target.left + target.width + TUTORIAL_CARD_GAP_PX;
      top = centeredTop;
      break;
    case "left":
      left = target.left - TUTORIAL_CARD_GAP_PX - card.width;
      top = centeredTop;
      break;
    case "bottom":
      top = target.top + target.height + TUTORIAL_CARD_GAP_PX;
      left = centeredLeft;
      break;
    case "top":
      top = target.top - TUTORIAL_CARD_GAP_PX - card.height;
      left = centeredLeft;
      break;
  }

  return {
    side,
    top: clamp(top, margin, maxTop),
    left: clamp(left, margin, maxLeft),
  };
}

/**
 * Compute where the step card should sit next to the spotlighted element.
 * 计算步骤卡片相对高亮元素的摆放位置。
 *
 * Tries right, left, bottom, then top and uses the first side with enough
 * room; otherwise uses the roomiest side and clamps into the viewport. A
 * missing target centers the card.
 * 依次尝试右、左、下、上，取第一个放得下的方向；都放不下时取空间最大的一侧
 * 并夹紧到视口内。没有目标时卡片居中。
 *
 * Args:
 *     target (TutorialRect | null): Spotlight rect in viewport pixels. 高亮区域。
 *     card (TutorialSize): Measured card size. 卡片尺寸。
 *     viewport (TutorialSize): Viewport size. 视口尺寸。
 *
 * Returns:
 *     TutorialCardPosition: Top-left corner and chosen side. 卡片左上角坐标与方向。
 */
export function computeTutorialCardPosition(
  target: TutorialRect | null,
  card: TutorialSize,
  viewport: TutorialSize,
): TutorialCardPosition {
  const margin = TUTORIAL_VIEWPORT_MARGIN_PX;
  if (!target) {
    return {
      side: "center",
      top: clamp((viewport.height - card.height) / 2, margin, viewport.height - card.height - margin),
      left: clamp((viewport.width - card.width) / 2, margin, viewport.width - card.width - margin),
    };
  }

  const fitting = SIDE_ORDER.find(
    (side) => availableSpace(side, target, viewport) >= requiredSpace(side, card),
  );
  if (fitting) {
    return placeOnSide(fitting, target, card, viewport);
  }

  const roomiest = [...SIDE_ORDER].sort(
    (a, b) => availableSpace(b, target, viewport) - availableSpace(a, target, viewport),
  )[0];
  return placeOnSide(roomiest, target, card, viewport);
}
