/**
 * Recipe version migration chain.
 * 配方版本迁移链。
 *
 * Each version bump adds a migration function that transforms
 * the recipe from the previous version to the current one.
 * 每个版本升级都添加一个迁移函数，将配方从上一版本转换为当前版本。
 */

import type { LuminaRecipe } from "./types";
import { RECIPE_FORMAT, RECIPE_SCHEMA_VERSION } from "./types";

/**
 * Validate and migrate a raw parsed recipe object to the current schema version.
 * 验证并迁移原始解析的配方对象到当前 schema 版本。
 *
 * @param raw - Parsed JSON object from a recipe file/PNG.
 * @returns Migrated LuminaRecipe.
 * @throws Error if format is invalid or schema version is unsupported.
 */
export function migrateRecipe(raw: unknown): LuminaRecipe {
  if (!raw || typeof raw !== "object") {
    throw new Error("Invalid recipe: not an object");
  }
  const obj = raw as Record<string, unknown>;
  if (obj.format !== RECIPE_FORMAT) {
    throw new Error(
      `Invalid recipe format: expected "${RECIPE_FORMAT}", got "${String(obj.format)}"`,
    );
  }
  const version = typeof obj.schema_version === "number" ? obj.schema_version : 0;
  if (version < 1) {
    throw new Error(`Unsupported recipe schema version: ${version}`);
  }
  if (version > RECIPE_SCHEMA_VERSION) {
    // Future version — forward-compat pass-through with warning.
    const recipe = obj as unknown as LuminaRecipe;
    if (!recipe.warnings) recipe.warnings = [];
    recipe.warnings.push(
      `Recipe was created with schema version ${version}, ` +
        `but this app only supports up to version ${RECIPE_SCHEMA_VERSION}. ` +
        `Some features may not be restored.`,
    );
    return recipe;
  }
  // v1 → v2: optional fields (recipe_overrides, custom_recipe_history)
  // default to undefined which importRecipe reads as empty arrays.
  // 旧 v1 文件缺少可选字段时，importRecipe 会按空数组处理。
  return obj as unknown as LuminaRecipe;
}
