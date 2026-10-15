import { describe, expect, it } from "vitest";
import { DEFAULT_STATE } from "../stores/converter";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import { buildFullRecipe, buildRecipeAssets, exportConverterRecipe } from "../recipe/exportRecipe";
import { parseRecipeFile, restoreConverterRecipe } from "../recipe/importRecipe";
import { embedRecipeInPng } from "../recipe/pngMetadata";

describe("portable editor project assets", () => {
  it.each(["json", "png"])("retains original SVG and editor bytes through %s", async (format) => {
    const source = new File(['<svg xmlns="http://www.w3.org/2000/svg"><rect width="6" height="4"/></svg>'], "source.svg", { type: "image/svg+xml" });
    const editor = new File([new Uint8Array([31, 139, 8, 0, 1, 2, 3])], "editor.json.gz", { type: "application/gzip" });
    const assets = await buildRecipeAssets(source, null, editor);
    const converter = exportConverterRecipe(DEFAULT_STATE, DEFAULT_SETTINGS);
    converter.coating = { enable_coating: true, coating_height_mm: 0.08, coating_material: { source: "palette", key: "White PETG" } };
    converter.color_ops.recipe_overrides = [{ region_id: "region-8", recipe: [1, 0, 1], layer_order: "Top2Bottom" }];
    const recipe = await buildFullRecipe(converter, { width: 1, height: 1, mime_type: "image/png" }, assets);
    const png = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jO6sAAAAASUVORK5CYII="), (c) => c.charCodeAt(0));
    const file = format === "json"
      ? new File([JSON.stringify(recipe)], "project.lumina.json", { type: "application/json" })
      : new File([await embedRecipeInPng(new Blob([png], { type: "image/png" }), recipe)], "project.png", { type: "image/png" });
    const parsed = await parseRecipeFile(file);
    const restored = restoreConverterRecipe(parsed.recipe, []);
    expect(parsed.recipe.schema_version).toBe(5);
    expect(restored.assetFile.name).toBe(source.name);
    expect(await restored.assetFile.text()).toBe(await source.text());
    expect(restored.state.pendingEditorProject).toBeInstanceOf(File);
    expect(new Uint8Array(await restored.state.pendingEditorProject!.arrayBuffer())).toEqual(new Uint8Array(await editor.arrayBuffer()));
    expect(restored.state.recipe_overrides).toEqual([]);
    expect(restored.state.coatingMaterial).toEqual(converter.coating.coating_material);
    expect(restored.warnings).not.toContain("recipe_import_warning_region_recipes_not_restored");
  });
});
