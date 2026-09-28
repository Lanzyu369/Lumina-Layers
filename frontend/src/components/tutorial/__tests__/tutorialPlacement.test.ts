import { describe, expect, it } from "vitest";
import {
  computeTutorialCardPosition,
  TUTORIAL_CARD_GAP_PX,
  TUTORIAL_VIEWPORT_MARGIN_PX,
} from "../tutorialPlacement";

const viewport = { width: 1440, height: 900 };
const card = { width: 380, height: 280 };

describe("computeTutorialCardPosition", () => {
  it("centers the card when there is no target", () => {
    const position = computeTutorialCardPosition(null, card, viewport);
    expect(position).toEqual({ side: "center", top: 310, left: 530 });
  });

  it("prefers the right side of a left-docked panel", () => {
    const target = { top: 200, left: 20, width: 340, height: 120 };
    const position = computeTutorialCardPosition(target, card, viewport);
    expect(position.side).toBe("right");
    expect(position.left).toBe(20 + 340 + TUTORIAL_CARD_GAP_PX);
    expect(position.top).toBe(200 + 60 - 140);
  });

  it("uses the left side for a right-docked panel", () => {
    const target = { top: 300, left: 1080, width: 340, height: 60 };
    const position = computeTutorialCardPosition(target, card, viewport);
    expect(position.side).toBe("left");
    expect(position.left).toBe(1080 - TUTORIAL_CARD_GAP_PX - 380);
  });

  it("places the card below a full-width header strip", () => {
    const target = { top: 10, left: 0, width: 1440, height: 50 };
    const position = computeTutorialCardPosition(target, card, viewport);
    expect(position.side).toBe("bottom");
    expect(position.top).toBe(10 + 50 + TUTORIAL_CARD_GAP_PX);
  });

  it("clamps the card inside the viewport near an edge", () => {
    const target = { top: 4, left: 1380, width: 40, height: 36 };
    const position = computeTutorialCardPosition(target, card, viewport);
    expect(position.left + card.width).toBeLessThanOrEqual(
      viewport.width - TUTORIAL_VIEWPORT_MARGIN_PX,
    );
    expect(position.top).toBeGreaterThanOrEqual(TUTORIAL_VIEWPORT_MARGIN_PX);
  });

  it("falls back to the roomiest side when nothing fits", () => {
    const small = { width: 400, height: 400 };
    const target = { top: 50, left: 50, width: 300, height: 300 };
    const position = computeTutorialCardPosition(target, card, small);
    expect(["right", "bottom", "left", "top"]).toContain(position.side);
    expect(position.left).toBeGreaterThanOrEqual(TUTORIAL_VIEWPORT_MARGIN_PX);
    expect(position.top).toBeGreaterThanOrEqual(TUTORIAL_VIEWPORT_MARGIN_PX);
  });
});
