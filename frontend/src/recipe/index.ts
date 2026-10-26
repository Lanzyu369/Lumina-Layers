/**
 * Lumina Recipe module — unified exports.
 * Lumina 配方模块 — 统一导出。
 */

// Types
export type {
  LuminaRecipe,
  AssetEntry,
  LutReference,
  ConverterRecipe,
  ConverterRecipeBase,
  ConverterRecipeGeometry,
  ConverterRecipeRelief,
  ConverterRecipeOutline,
  ConverterRecipeCloisonne,
  ConverterRecipeCoating,
  ConverterRecipeColorOps,
  ConverterRecipeLargeFormat,
  ConverterRecipeDevice,
  RecipeSource,
  RecipeCover,
  RecipeAssets,
  RecipeCompat,
} from "./types";

export { RECIPE_FORMAT, RECIPE_SCHEMA_VERSION } from "./types";

// Utils
export { fileToBase64, base64ToFile, buildAssetEntry } from "./utils";

// PNG metadata
export { embedRecipeInPng, extractRecipeFromPng, hasLuminaRecipe, extractCoverFromPng } from "./pngMetadata";

// Export adapter
export { exportConverterRecipe, buildFullRecipe, buildRecipeAssets, buildCoverImage } from "./exportRecipe";

// Import adapter
export { parseRecipeFile, restoreConverterRecipe, matchLut, detectRecipeFileType } from "./importRecipe";
export type { ParsedRecipe, RestoreResult, LutMatchResult, RecipeFileSource } from "./importRecipe";

// Migration
export { migrateRecipe } from "./migration";

// Import flow (orchestration)
export { isShareCardFile, prepareImport, applyImport, revokeImportCoverUrl, exportShareCard, exportSidecar } from "./importFlow";
export type { ImportPreview } from "./importFlow";
