/**
 * Recipe version migration chain.
 * 配方版本迁移链。
 *
 * Each version bump adds a migration function that transforms
 * the recipe from the previous version to the current one.
 * 每个版本升级都添加一个迁移函数，将配方从上一版本转换为当前版本。
 */

import type { LuminaRecipe } from "./types";
import { DEFAULT_CONVERTER_RECIPE_PUZZLE, RECIPE_FORMAT, RECIPE_SCHEMA_VERSION } from "./types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validateConverterShape(recipe: Record<string, unknown>, version: number): void {
  const converter = recipe.converter;
  if (converter === undefined) return;
  const sections = [
    "base", "geometry", "relief", "outline", "cloisonne", "coating",
    "color_ops", "large_format", "device",
  ];
  // Early V1 cards predate puzzle support; restore already owns its defaults.
  if (version >= 4) sections.push("puzzle");
  if (!isRecord(converter) || sections.some((key) => !isRecord(converter[key]))) {
    throw new Error("Invalid recipe: missing converter sections");
  }
  if (converter.puzzle !== undefined && !isRecord(converter.puzzle)) {
    throw new Error("Invalid recipe: malformed puzzle section");
  }
  const base = converter.base as Record<string, unknown>;
  if (
    !isRecord(base.lut) ||
    typeof base.lut.name !== "string" ||
    typeof base.lut.color_mode !== "string" ||
    [base.target_width_mm, base.target_height_mm].some(
      (value) => typeof value !== "number" || !Number.isFinite(value) || value <= 0,
    )
  ) {
    throw new Error("Invalid recipe: converter LUT or dimensions");
  }
  const colorOps = converter.color_ops as Record<string, unknown>;
  const relief = converter.relief as Record<string, unknown>;
  if (
    !Array.isArray(colorOps.replacement_regions) ||
    !Array.isArray(colorOps.free_color_set) ||
    !isRecord(relief.color_height_map)
  ) {
    throw new Error("Invalid recipe: converter color operations");
  }
}

function retireContentDigests(obj: Record<string, unknown>): LuminaRecipe {
  const migrated = { ...obj };
  delete migrated.integrity;
  if (isRecord(obj.asset)) {
    const assets = { ...obj.asset };
    for (const key of ["primary", "heightmap"]) {
      if (isRecord(assets[key])) {
        const asset = { ...assets[key] };
        delete asset.sha256;
        assets[key] = asset;
      }
    }
    migrated.asset = assets;
  }
  const sections = obj.recipe as Record<string, unknown>;
  if (isRecord(sections.converter)) {
    const converter = { ...sections.converter };
    const base = { ...(converter.base as Record<string, unknown>) };
    const lut = { ...(base.lut as Record<string, unknown>) };
    delete lut.fingerprint;
    base.lut = lut;
    converter.base = base;
    migrated.recipe = { ...sections, converter };
  }
  return migrated as unknown as LuminaRecipe;
}

/**
 * Validate and migrate a raw parsed recipe object to the current schema version.
 * 验证并迁移原始解析的配方对象到当前 schema 版本。
 *
 * @param raw - Parsed JSON object from a recipe file/PNG.
 * @returns Migrated LuminaRecipe.
 * @throws Error if format is invalid or schema version is unsupported.
 */
export function migrateRecipe(raw: unknown): LuminaRecipe {
  if (!isRecord(raw)) {
    throw new Error("Invalid recipe: not an object");
  }
  const obj = raw;
  if (obj.format !== RECIPE_FORMAT) {
    throw new Error(
      `Invalid recipe format: expected "${RECIPE_FORMAT}", got "${String(obj.format)}"`,
    );
  }
  const version = typeof obj.schema_version === "number" ? obj.schema_version : 0;
  if (!Number.isInteger(version) || version < 1) {
    throw new Error(`Unsupported recipe schema version: ${version}`);
  }
  if (
    !isRecord(obj.recipe) ||
    !Array.isArray(obj.warnings) ||
    obj.warnings.some((warning) => typeof warning !== "string")
  ) {
    throw new Error("Invalid recipe: recipe data or warnings");
  }
  validateConverterShape(obj.recipe, version);
  const recipe = retireContentDigests(obj);
  if (version > RECIPE_SCHEMA_VERSION) {
    // Future version — forward-compat pass-through with warning.
    recipe.warnings = [
      ...recipe.warnings,
      `Recipe was created with schema version ${version}, ` +
        `but this app only supports up to version ${RECIPE_SCHEMA_VERSION}. ` +
        `Some features may not be restored.`,
    ];
    return recipe;
  }
  // V1–V3 optional fields keep their existing defaults. V4 retires digests.
  // V1–V3 可选字段继续采用现有默认值；V4 移除已退役的摘要元数据。
  const converter = recipe.recipe.converter;
  if (converter && converter.puzzle === undefined) {
    converter.puzzle = { ...DEFAULT_CONVERTER_RECIPE_PUZZLE };
  }
  recipe.schema_version = RECIPE_SCHEMA_VERSION;
  recipe.compat = { ...recipe.compat, min_schema_version: RECIPE_SCHEMA_VERSION };
  return recipe;
}
