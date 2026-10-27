import { describe, expect, it } from "vitest";
import {
  applyRecipePattern,
  buildPaletteHint,
  buildPaletteLetterMap,
  validateRecipePattern,
} from "../utils/recipePattern";

const materialPalette = [
  { color: "PETG-HF品红" },
  { color: "彩格PETG蓝色 by MingDee" },
  { color: "黄色petg basic" },
  { color: "青色petg basic" },
  { color: "彩格红petg" },
];

describe("recipe shortcuts share the displayed material mapping", () => {
  it("accepts and applies every shortcut advertised for real material names", () => {
    const map = buildPaletteLetterMap(materialPalette);
    const hint = buildPaletteHint(materialPalette);
    for (const [key, channels] of map) {
      expect(hint).toContain(`${key}=${materialPalette[channels[0]].color}`);
      expect(validateRecipePattern(key, materialPalette)).toBeNull();
      expect(applyRecipePattern(key, materialPalette, 1, [4])).toEqual([channels[0]]);
    }
  });

  it("uses Chinese keys and case-insensitive English keys in one recipe", () => {
    expect(validateRecipePattern("黄青彩p", materialPalette)).toBeNull();
    expect(applyRecipePattern("黄青彩p", materialPalette, 4, [4, 4, 4, 4])).toEqual([2, 3, 1, 0]);
  });

  it("retains the first channel when several material names share a shortcut", () => {
    expect(buildPaletteLetterMap(materialPalette).get("彩")).toEqual([1, 4]);
    expect(applyRecipePattern("彩彩", materialPalette, 2, [0, 0])).toEqual([1, 1]);
  });

  it("preserves canonical English colors and lowercase input", () => {
    const palette = ["White", "Black", "Cyan", "Magenta", "Yellow", "Red", "Green", "Blue"].map((color) => ({ color }));
    expect(validateRecipePattern("wkcmyrgb", palette)).toBeNull();
    expect(applyRecipePattern("wkcmyrgb", palette, 8, Array(8).fill(0))).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
  });

  it("preserves separators, keep-layer and stop semantics with Chinese keys", () => {
    const current = [4, 0, 1, 3, 0];
    expect(validateRecipePattern("黄-?-青*P", materialPalette)).toBeNull();
    expect(applyRecipePattern("黄-?-青*P", materialPalette, 5, current)).toEqual([2, 0, 3, 3, 0]);
    expect(current).toEqual([4, 0, 1, 3, 0]);
    expect(applyRecipePattern("---", materialPalette, 3, current)).toEqual([4, 0, 1]);
  });

  it.each(["Z", "无", "/", "☃"])("rejects a token absent from the current palette: %s", (token) => {
    expect(validateRecipePattern(`黄${token}`, materialPalette)).toBe(token);
  });
});
