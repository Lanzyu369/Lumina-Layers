import { describe, expect, it } from "vitest";
import type { FridgeMagnetItem } from "../api/types";
import {
  autoLayoutFridgeMagnets,
  canonicalizeFridgeMagnets,
} from "../utils/fridgeMagnetLayout";

describe("fridge magnet layout inputs", () => {
  const bounds = Object.freeze({ minX: -40, maxX: 40, minY: -30, maxY: 30, maxZ: 3 });
  const magnets: readonly FridgeMagnetItem[] = Object.freeze([
    Object.freeze({
      id: "round-custom", shape: "round", preset_key: "custom",
      diameter_mm: 12, width_mm: null, height_mm: null, thickness_mm: 2,
      center_x_mm: -20, center_y_mm: 0,
    }),
    Object.freeze({
      id: "rect-custom", shape: "rect", preset_key: "custom",
      diameter_mm: null, width_mm: 15, height_mm: 5, thickness_mm: 1.5,
      center_x_mm: 20, center_y_mm: 0,
    }),
  ]);

  it.each([autoLayoutFridgeMagnets, canonicalizeFridgeMagnets])(
    "%s preserves mixed magnet identities without mutating caller objects",
    (layout) => {
      const result = layout(bounds, magnets);

      expect(result).not.toBe(magnets);
      result.forEach((magnet, index) => {
        expect(magnet).not.toBe(magnets[index]);
        const { center_x_mm: _x, center_y_mm: _y, ...identity } = magnets[index];
        expect(magnet).toMatchObject(identity);
      });
      expect(magnets.map((magnet) => magnet.center_x_mm)).toEqual([-20, 20]);
    },
  );
});
