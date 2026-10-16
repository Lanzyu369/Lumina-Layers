export interface RecipePaletteEntry {
  color: string;
}

const RECIPE_LETTER_BY_COLOR: Record<string, string> = {
  white: "W",
  black: "K",
  cyan: "C",
  magenta: "M",
  yellow: "Y",
  red: "R",
  green: "G",
  blue: "B",
};

function getRecipeLetter(color: string): string {
  return RECIPE_LETTER_BY_COLOR[color.trim().toLowerCase()] ?? color.charAt(0).toUpperCase();
}

export function buildPaletteLetterMap(
  palette: RecipePaletteEntry[],
): Map<string, number[]> {
  const map = new Map<string, number[]>();
  for (let i = 0; i < palette.length; i += 1) {
    const name = palette[i]?.color;
    if (!name) continue;
    const letter = getRecipeLetter(name);
    const existing = map.get(letter);
    if (existing) {
      existing.push(i);
    } else {
      map.set(letter, [i]);
    }
  }
  return map;
}

export function buildPaletteHint(palette: RecipePaletteEntry[]): string {
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const entry of palette) {
    if (!entry?.color) continue;
    const letter = getRecipeLetter(entry.color);
    if (seen.has(letter)) continue;
    seen.add(letter);
    parts.push(`${letter}=${entry.color}`);
  }
  return parts.join("  ");
}

export function validateRecipePattern(
  pattern: string,
  palette: RecipePaletteEntry[],
): string | null {
  if (!pattern) return null;
  const letterMap = buildPaletteLetterMap(palette);
  for (const char of pattern) {
    if (char === "-" || char === "?" || char === "*") continue;
    if (!letterMap.has(char.toUpperCase())) {
      return char;
    }
  }
  return null;
}

export function applyRecipePattern(
  pattern: string,
  palette: RecipePaletteEntry[],
  layerCount: number,
  currentRecipe: number[],
): number[] {
  const compact = pattern.replace(/-/g, "").trim();
  if (!compact) {
    return currentRecipe.slice(0, layerCount);
  }
  const letterMap = buildPaletteLetterMap(palette);
  const next = currentRecipe.slice(0, layerCount);
  for (let i = 0; i < Math.min(compact.length, layerCount); i += 1) {
    const char = compact[i];
    if (char === "?") continue;
    if (char === "*") break;
    const candidates = letterMap.get(char.toUpperCase());
    if (candidates && candidates.length > 0) {
      next[i] = candidates[0];
    }
  }
  return next;
}
