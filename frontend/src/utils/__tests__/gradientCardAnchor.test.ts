import { describe, expect, it } from "vitest";

import type { ManualOrientationLabel } from "../../api/types";
import {
  GRADIENT_CARD_ANCHOR_CORNERS,
  anchorToOrientationLabel,
  type GradientCardAnchorCorner,
} from "../gradientCardAnchor";

describe("anchorToOrientationLabel", () => {
  it("maps each anchor-corner choice to its canonical orientation label", () => {
    const mapping: Array<[
      GradientCardAnchorCorner,
      ManualOrientationLabel,
    ]> = [
      ["tl", "identity"],
      ["tr", "flip_horizontal"],
      ["br", "rotate_180"],
      ["bl", "flip_vertical"],
    ];
    for (const [anchor, label] of mapping) {
      expect(anchorToOrientationLabel(anchor)).toBe(label);
    }
  });

  it("returns null when the user wants automatic detection", () => {
    expect(anchorToOrientationLabel(null)).toBeNull();
  });

  it("covers every advertised anchor-corner without dropping any", () => {
    for (const corner of GRADIENT_CARD_ANCHOR_CORNERS) {
      expect(anchorToOrientationLabel(corner)).not.toBeNull();
    }
  });
});

describe("GRADIENT_CARD_ANCHOR_CORNERS", () => {
  it("lists exactly the four screen corners in clockwise order", () => {
    expect(GRADIENT_CARD_ANCHOR_CORNERS).toEqual(["tl", "tr", "br", "bl"]);
  });
});
