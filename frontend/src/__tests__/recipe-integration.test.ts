/**
 * Integration tests for the Lumina recipe share card system.
 * 配方分享卡系统集成测试。
 *
 * These tests exercise the full export→import round-trip at higher levels
 * than the unit tests, including PNG embedding and multi-feature recipes.
 */

import { describe, it, expect } from "vitest";
import { exportConverterRecipe, buildFullRecipe, buildRecipeAssets } from "../recipe/exportRecipe";
import {
  parseRecipeFile,
  RECIPE_IMPORT_WARNING_LUT_DEGRADED,
  RECIPE_IMPORT_WARNING_LUT_MISSING,
  RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED,
  restoreConverterRecipe,
} from "../recipe/importRecipe";
import { annotateSpatialEditCompatibility } from "../recipe/importFlow";
import { embedRecipeInPng, extractRecipeFromPng, hasLuminaRecipe } from "../recipe/pngMetadata";
import { migrateRecipe } from "../recipe/migration";
import { DEFAULT_STATE } from "../stores/converter";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { ConverterState } from "../stores/converter/store";
import type { LutInfo, ColorReplacementItem } from "../api/types";
import { ColorMode } from "../api/types";
import type { LuminaRecipe, RecipeCover } from "../recipe/types";
import { translations } from "../i18n/translations";

// ========== Helpers ==========

/** Minimal valid 1x1 PNG for cover images. */
function createMinimalPng(): Blob {
  const data = new Uint8Array([
    137, 80, 78, 71, 13, 10, 26, 10,
    0, 0, 0, 13, 73, 72, 68, 82,
    0, 0, 0, 1, 0, 0, 0, 1, 8, 2, 0, 0, 0, 144, 119, 83, 222,
    0, 0, 0, 12, 73, 68, 65, 84,
    8, 215, 99, 248, 207, 192, 0, 0, 0, 4, 0, 1, 2, 127, 225, 72,
    0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
  ]);
  return new Blob([data], { type: "image/png" });
}

const LOCAL_LUTS: LutInfo[] = [
  { name: "TestLUT", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/luts/test.json", fingerprint: "fp_test" },
  { name: "SixColorLUT", color_mode: ColorMode.SIX_COLOR, path: "/luts/six.json", fingerprint: "fp_six" },
  { name: "BWLUT", color_mode: ColorMode.BW, path: "/luts/bw.json", fingerprint: "fp_bw" },
];

const LOCAL_FP: Record<string, string> = {
  TestLUT: "fp_test",
  SixColorLUT: "fp_six",
  BWLUT: "fp_bw",
};

async function buildTestRecipe(stateOverrides: Partial<ConverterState> = {}, fingerprint?: string): Promise<{
  recipe: LuminaRecipe;
  state: ConverterState;
}> {
  const state = { ...DEFAULT_STATE, ...stateOverrides } as ConverterState;
  const fp = fingerprint ?? (LOCAL_FP[state.lut_name] || "unknown_fp");
  const converterRecipe = exportConverterRecipe(state, DEFAULT_SETTINGS, fp);
  const imageFile = new File([new Uint8Array([1, 2, 3, 4])], "photo.png", { type: "image/png" });
  const assets = await buildRecipeAssets(imageFile, state.heightmapFile);
  const cover: RecipeCover = { width: 100, height: 75, mime_type: "image/png" };
  const recipe = await buildFullRecipe(converterRecipe, cover, assets);
  return { recipe, state };
}

// ========== Integration Tests ==========

describe("recipe integration", () => {
  describe("full export → import round-trip", () => {
    it("basic state: export → clear → import → state equivalent", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        target_width_mm: 120,
        target_height_mm: 90,
        spacer_thick: 0.8,
      });

      const { state: restored, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FP);

      expect(restored.lut_name).toBe("TestLUT");
      expect(restored.target_width_mm).toBe(120);
      expect(restored.target_height_mm).toBe(90);
      expect(restored.spacer_thick).toBe(0.8);
      expect(warnings).toHaveLength(0); // fingerprint match, no warnings
    });

    it("complex recipe with loop + coating + outline + cloisonne + relief", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        add_loop: true,
        loop_width: 7,
        loop_length: 12,
        loop_hole: 4,
        loop_angle: -45,
        loop_offset_x: 3,
        loop_offset_y: -2,
        loop_position_preset: "bottom-left",
        enable_coating: true,
        coating_height_mm: 0.2,
        enable_outline: true,
        outline_width: 0.6,
        enable_cloisonne: true,
        wire_width_mm: 0.5,
        wire_height_mm: 0.4,
        enable_relief: true,
        autoHeightMode: "lighter-higher",
        color_height_map: { ff0000: 0.3, "00ff00": 0.5, "0000ff": 0.8 },
        heightmap_max_height: 1.2,
      });

      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FP);

      // Loop
      expect(restored.add_loop).toBe(true);
      expect(restored.loop_width).toBe(7);
      expect(restored.loop_angle).toBe(-45);
      expect(restored.loop_position_preset).toBe("bottom-left");

      // Coating
      expect(restored.enable_coating).toBe(true);
      expect(restored.coating_height_mm).toBe(0.2);

      // Outline
      expect(restored.enable_outline).toBe(true);
      expect(restored.outline_width).toBe(0.6);

      // Cloisonne
      expect(restored.enable_cloisonne).toBe(true);
      expect(restored.wire_width_mm).toBe(0.5);
      expect(restored.wire_height_mm).toBe(0.4);

      // Relief — hex keys are normalized (stripped '#')
      expect(restored.enable_relief).toBe(true);
      expect(restored.color_height_map).toEqual({ ff0000: 0.3, "00ff00": 0.5, "0000ff": 0.8 });
      expect(restored.heightmap_max_height).toBe(1.2);
    });

    it("replacement_regions + free_color_set round-trip correctly", async () => {
      const replacements: ColorReplacementItem[] = [
        { quantized_hex: "aa0000", matched_hex: "bb0000", replacement_hex: "cc0000" },
        { quantized_hex: "11ff00", matched_hex: "22ff00", replacement_hex: "33ff00" },
      ];
      const freeColors = new Set(["ff0000", "00ff00", "0000ff"]);

      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        replacement_regions: replacements,
        free_color_set: freeColors,
      });

      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FP);

      expect(restored.replacement_regions).toHaveLength(2);
      expect(restored.replacement_regions![0].quantized_hex).toBe("aa0000");
      expect(restored.replacement_regions![1].replacement_hex).toBe("33ff00");
      expect(restored.free_color_set).toEqual(new Set(["ff0000", "00ff00", "0000ff"]));
    });

    it("recipe_overrides and customRecipeHistory round-trip correctly", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        recipe_overrides: [
          {
            region_id: "r1",
            recipe: [0, 1, 2, 4],
            layer_order: "Top2Bottom",
            virtual_materials: [{ name: "Matte Black", hex: "#101010" }],
          },
          { region_id: "r2", recipe: [1, 1, 0, 2], layer_order: "Top2Bottom" },
        ],
        customRecipeHistory: [
          {
            id: "0-1-2-4@Top2Bottom",
            recipe: [0, 1, 2, 4],
            layerOrder: "Top2Bottom",
            predictedRgb: [10, 20, 30],
            predictedLab: [40, 5, -3],
            hex: "#0A141E",
            fromModel: true,
            virtualMaterials: [{ name: "Matte Black", hex: "#101010" }],
            createdAtMs: 1_700_000_000_000,
          },
        ],
      });

      expect(
        recipe.recipe.converter?.color_ops.recipe_overrides?.[0],
      ).toEqual({
        region_id: "r1",
        recipe: [0, 1, 2, 4],
        layer_order: "Top2Bottom",
        virtual_materials: [{ name: "Matte Black", hex: "#101010" }],
      });
      expect(
        recipe.recipe.converter?.color_ops.custom_recipe_history?.[0],
      ).toEqual(
        expect.objectContaining({
          id: "0-1-2-4@Top2Bottom",
          recipe: [0, 1, 2, 4],
          virtual_materials: [{ name: "Matte Black", hex: "#101010" }],
        }),
      );

      const { state: restored, warnings } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
        LOCAL_FP,
      );

      expect(restored.recipe_overrides).toHaveLength(2);
      expect(restored.recipe_overrides![0]).toEqual({
        region_id: "r1",
        recipe: [0, 1, 2, 4],
        layer_order: "Top2Bottom",
        virtual_materials: [{ name: "Matte Black", hex: "#101010" }],
      });
      expect(restored.recipe_overrides![1].recipe).toEqual([1, 1, 0, 2]);

      expect(restored.customRecipeHistory).toHaveLength(1);
      const history = restored.customRecipeHistory![0];
      expect(history.id).toBe("0-1-2-4@Top2Bottom");
      expect(history.recipe).toEqual([0, 1, 2, 4]);
      expect(history.layerOrder).toBe("Top2Bottom");
      expect(history.predictedRgb).toEqual([10, 20, 30]);
      expect(history.predictedLab).toEqual([40, 5, -3]);
      expect(history.hex).toBe("#0A141E");
      expect(history.fromModel).toBe(false);
      expect(history.virtualMaterials).toEqual([
        { name: "Matte Black", hex: "#101010" },
      ]);
      expect(history.createdAtMs).toBe(1_700_000_000_000);
      expect(warnings).toHaveLength(0);

      const embedded = await embedRecipeInPng(
        createMinimalPng(),
        recipe,
        recipe.integrity.recipe_sha256,
      );
      const extracted = await extractRecipeFromPng(embedded);
      expect(
        extracted?.recipe.converter?.color_ops.recipe_overrides?.[0],
      ).toEqual({
        region_id: "r1",
        recipe: [0, 1, 2, 4],
        layer_order: "Top2Bottom",
        virtual_materials: [{ name: "Matte Black", hex: "#101010" }],
      });
    });

    it("exports schema_version 2 and imports legacy v1 without warnings", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      expect(recipe.schema_version).toBe(2);

      const legacy = JSON.parse(JSON.stringify(recipe)) as LuminaRecipe;
      legacy.schema_version = 1;
      delete legacy.recipe.converter?.color_ops.recipe_overrides;
      delete legacy.recipe.converter?.color_ops.custom_recipe_history;

      const migrated = migrateRecipe(legacy);
      expect(
        migrated.warnings.filter((warning) => warning.includes("schema version")),
      ).toHaveLength(0);

      const { state: restored } = restoreConverterRecipe(
        migrated,
        LOCAL_LUTS,
        LOCAL_FP,
      );
      expect(restored.recipe_overrides).toEqual([]);
      expect(restored.customRecipeHistory).toEqual([]);
    });

    it("large format parameters round-trip", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        largeFormatEnabled: true,
        tileWidthMm: 180,
        tileHeightMm: 140,
        target_width_mm: 500,
        target_height_mm: 400,
      });

      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FP);

      expect(restored.largeFormatEnabled).toBe(true);
      expect(restored.tileWidthMm).toBe(180);
      expect(restored.tileHeightMm).toBe(140);
      expect(restored.target_width_mm).toBe(500);
    });
  });

  describe("PNG embed → extract round-trip", () => {
    it("recipe survives PNG embedding and extraction", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        target_width_mm: 80,
        enable_relief: true,
      });

      const png = createMinimalPng();
      const embedded = await embedRecipeInPng(png, recipe, recipe.integrity.recipe_sha256);

      expect(await hasLuminaRecipe(embedded)).toBe(true);

      const extracted = await extractRecipeFromPng(embedded);
      expect(extracted).not.toBeNull();
      expect(extracted!.recipe.converter!.base.target_width_mm).toBe(80);
      expect(extracted!.recipe.converter!.relief.enable_relief).toBe(true);
      expect(extracted!.recipe.converter!.base.lut.name).toBe("TestLUT");
    });

    it("full flow: export → embed → file parse → import", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "SixColorLUT",
        target_width_mm: 200,
        enable_coating: true,
        coating_height_mm: 0.15,
      });

      const png = createMinimalPng();
      const embedded = await embedRecipeInPng(png, recipe, recipe.integrity.recipe_sha256);

      // Create a File from the embedded blob
      const shareCardFile = new File([embedded], "share.png", { type: "image/png" });
      const parsed = await parseRecipeFile(shareCardFile);

      expect(parsed.source).toBe("png");
      const { state: restored, warnings } = restoreConverterRecipe(
        parsed.recipe,
        LOCAL_LUTS,
        LOCAL_FP,
      );

      expect(restored.lut_name).toBe("SixColorLUT");
      expect(restored.target_width_mm).toBe(200);
      expect(restored.enable_coating).toBe(true);
      expect(restored.coating_height_mm).toBe(0.15);
      expect(warnings).toHaveLength(0);
    });
  });

  describe("JSON sidecar round-trip", () => {
    it("export → JSON file → parse → import", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        target_width_mm: 60,
        add_loop: true,
      });

      const jsonStr = JSON.stringify(recipe, null, 2);
      const jsonFile = new File([jsonStr], "card.lumina.json", { type: "application/json" });

      const parsed = await parseRecipeFile(jsonFile);
      expect(parsed.source).toBe("json");

      const { state: restored } = restoreConverterRecipe(parsed.recipe, LOCAL_LUTS, LOCAL_FP);
      expect(restored.lut_name).toBe("TestLUT");
      expect(restored.target_width_mm).toBe(60);
      expect(restored.add_loop).toBe(true);
    });
  });

  describe("session-scoped spatial edit compatibility", () => {
    it("marks PNG and sidecar recipes as degraded and warns on import", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        regionReplacementCount: 2,
        replacement_regions: [],
        colorRemapMap: {},
      });

      expect(RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED).toBe(
        "recipe_import_warning_spatial_edits_not_serialized",
      );
      annotateSpatialEditCompatibility(recipe, 2);
      annotateSpatialEditCompatibility(recipe, 2);

      expect(recipe.recipe.converter?.color_ops.replacement_regions).toEqual([]);
      expect(recipe.compat.degraded_fields).toEqual([
        "converter.color_ops.spatial_region_edits",
      ]);
      expect(recipe.warnings).toEqual([
        RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED,
      ]);

      const png = await embedRecipeInPng(
        createMinimalPng(),
        recipe,
        recipe.integrity.recipe_sha256,
      );
      const files = [
        new File([png], "spatial-share.png", { type: "image/png" }),
        new File([JSON.stringify(recipe)], "spatial-share.lumina.json", {
          type: "application/json",
        }),
      ];

      for (const file of files) {
        const parsed = await parseRecipeFile(file);
        const restored = restoreConverterRecipe(parsed.recipe, LOCAL_LUTS, LOCAL_FP);
        expect(restored.warnings).toContain(
          RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED,
        );
      }

      expect(
        translations[RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED].zh,
      ).toContain("当前会话");
      expect(
        translations[RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED].en,
      ).toContain("current session");
    });

    it("does not mark a recipe when no spatial edits exist", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        regionReplacementCount: 0,
      });

      annotateSpatialEditCompatibility(recipe, 0);

      expect(recipe.compat.degraded_fields).toBeUndefined();
      expect(recipe.warnings).not.toContain(
        RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED,
      );
    });
  });

  describe("LUT missing scenarios", () => {
    it("missing LUT produces warning and empty lut_name", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "NonExistentLUT" }, "no_match_fp");

      const { state: restored, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FP);

      expect(restored.lut_name).toBe(""); // Cannot match
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_LUT_MISSING);
    });

    it("LUT fingerprint mismatch triggers name fallback with warning", async () => {
      const state = { ...DEFAULT_STATE, lut_name: "TestLUT" } as ConverterState;
      const converterRecipe = exportConverterRecipe(state, DEFAULT_SETTINGS, "wrong_fingerprint");

      const recipe = await buildFullRecipe(
        converterRecipe,
        { width: 1, height: 1, mime_type: "image/png" },
        {
          primary: {
            filename: "t.png",
            mime_type: "image/png",
            byte_size: 4,
            sha256: "a",
            encoding: "base64",
            payload_b64: "dGVzdA==",
          },
        },
      );

      const { state: restored, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FP);

      expect(restored.lut_name).toBe("TestLUT"); // Name fallback still works
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_LUT_DEGRADED);
    });
  });

  describe("import does not pollute unrelated state", () => {
    it("session/preview state is cleared on import", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FP);

      expect(restored.sessionId).toBeNull();
      expect(restored.previewImageUrl).toBeNull();
      expect(restored.previewGlbUrl).toBeNull();
      expect(restored.modelUrl).toBeNull();
      expect(restored.hasManualPreview).toBe(false);
      expect(restored.layerImages).toEqual([]);
      expect(restored.error).toBeNull();
    });

    it("colorRemapMap is cleared (merged into replacement_regions)", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FP);

      expect(restored.colorRemapMap).toEqual({});
      expect(restored.remapHistory).toEqual([]);
    });
  });

  describe("integrity", () => {
    it("recipe has valid integrity hashes", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });

      expect(recipe.integrity.recipe_sha256).toHaveLength(64);
      expect(recipe.integrity.asset_checksums.primary).toHaveLength(64);
    });

    it("rejects JSON sidecars whose recipe hash no longer matches the recipe section", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      recipe.recipe.converter!.base.target_width_mm += 1;
      const file = new File([JSON.stringify(recipe)], "tampered.lumina.json", {
        type: "application/json",
      });

      await expect(parseRecipeFile(file)).rejects.toThrow("Integrity check failed");
    });

    it("rejects JSON sidecars whose primary asset payload no longer matches its checksum", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      recipe.asset.primary.payload_b64 = "dGFtcGVyZWQ=";
      const file = new File([JSON.stringify(recipe)], "tampered.lumina.json", {
        type: "application/json",
      });

      await expect(parseRecipeFile(file)).rejects.toThrow("Asset data is corrupted");
    });

    it("rejects JSON sidecars whose heightmap asset payload no longer matches its checksum", async () => {
      const heightmapFile = new File([new Uint8Array([10, 20, 30])], "height.png", {
        type: "image/png",
      });
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        heightmapFile,
      });
      recipe.asset.heightmap!.payload_b64 = "dGFtcGVyZWQ=";
      const file = new File([JSON.stringify(recipe)], "tampered.lumina.json", {
        type: "application/json",
      });

      await expect(parseRecipeFile(file)).rejects.toThrow("Asset data is corrupted");
    });

    it("rejects PNG share cards whose embedded recipe integrity is stale", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      recipe.recipe.converter!.base.target_width_mm += 1;
      const embedded = await embedRecipeInPng(
        createMinimalPng(),
        recipe,
        recipe.integrity.recipe_sha256,
      );
      const file = new File([embedded], "tampered-share.png", { type: "image/png" });

      await expect(parseRecipeFile(file)).rejects.toThrow("Integrity check failed");
    });

    it("recipe with heightmap includes heightmap checksum", async () => {
      const hmFile = new File([new Uint8Array([10, 20, 30])], "height.png", { type: "image/png" });
      const state = { ...DEFAULT_STATE, lut_name: "TestLUT", heightmapFile: hmFile } as ConverterState;
      const converterRecipe = exportConverterRecipe(state, DEFAULT_SETTINGS, "fp_test");
      const assets = await buildRecipeAssets(
        new File([new Uint8Array([1, 2])], "img.png", { type: "image/png" }),
        hmFile,
      );
      const recipe = await buildFullRecipe(
        converterRecipe,
        { width: 1, height: 1, mime_type: "image/png" },
        assets,
      );

      expect(recipe.integrity.asset_checksums["heightmap"]).toHaveLength(64);
      expect(recipe.asset.heightmap).toBeDefined();
    });
  });

  describe("schema migration", () => {
    it("future schema version passes with warning", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      const futureRecipe = { ...recipe, schema_version: 99 };

      const migrated = migrateRecipe(futureRecipe);
      expect(migrated.warnings.some((w) => w.includes("schema version 99"))).toBe(true);
    });
  });
});
