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
  matchLut,
  RECIPE_IMPORT_WARNING_LUT_DEGRADED,
  RECIPE_IMPORT_WARNING_LUT_MISSING,
  RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED,
  RECIPE_IMPORT_WARNING_REGION_RECIPES_NOT_RESTORED,
  restoreConverterRecipe,
} from "../recipe/importRecipe";
import { annotateSpatialEditCompatibility, isShareCardFile } from "../recipe/importFlow";
import { embedRecipeInPng, extractRecipeFromPng, hasLuminaRecipe } from "../recipe/pngMetadata";
import { migrateRecipe } from "../recipe/migration";
import { DEFAULT_STATE } from "../stores/converter";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { SettingsState } from "../stores/settingsStore";
import type { ConverterState } from "../stores/converter/store";
import type {
  LutInfo,
  ColorReplacementItem,
  DynamicMaterialRecipe,
  MaterialLayerBenefitPoint,
} from "../api/types";
import { ColorMode } from "../api/types";
import type { LuminaRecipe, RecipeCover } from "../recipe/types";
import { translations } from "../i18n/translations";
import { createBeadRecipeSourceFixture } from "./fixtures/beadRecipeSource";
import { createLegacyRecipeV1 } from "./fixtures/legacyRecipeV1";

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
  { name: "TestLUT", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/luts/test.json" },
  { name: "SixColorLUT", color_mode: ColorMode.SIX_COLOR, path: "/luts/six.json" },
  { name: "BWLUT", color_mode: ColorMode.BW, path: "/luts/bw.json" },
];

async function buildTestRecipe(
  stateOverrides: Partial<ConverterState> = {},
  lutPath?: string,
  settingsOverrides: Partial<SettingsState> = {},
): Promise<{
  recipe: LuminaRecipe;
  state: ConverterState;
}> {
  const state = { ...DEFAULT_STATE, source_version: "legacy", ...stateOverrides } as ConverterState;
  const path = lutPath ?? LOCAL_LUTS.find((lut) => lut.name === state.lut_name)?.path;
  const converterRecipe = exportConverterRecipe(
    state,
    { ...DEFAULT_SETTINGS, ...settingsOverrides },
    path,
  );
  const imageFile = new File([new Uint8Array([1, 2, 3, 4])], "photo.png", { type: "image/png" });
  const assets = await buildRecipeAssets(imageFile, state.heightmapFile);
  const cover: RecipeCover = { width: 100, height: 75, mime_type: "image/png" };
  const recipe = await buildFullRecipe(
    converterRecipe,
    cover,
    assets,
    state.workshopSource,
  );
  return { recipe, state };
}

// ========== Integration Tests ==========

describe("recipe integration", () => {
  it('recognizes an exported project renamed to ordinary JSON and restores it', async () => {
    const { recipe } = await buildTestRecipe({ lut_name: 'TestLUT', target_width_mm: 123 });
    const file = new File([JSON.stringify(recipe)], 'renamed.json', { type: 'application/json' });
    expect(await isShareCardFile(file)).toBe(true);
    const parsed = await parseRecipeFile(file);
    expect(parsed.recipe).toEqual(recipe);
    expect(restoreConverterRecipe(parsed.recipe, LOCAL_LUTS).state.target_width_mm).toBe(123);
    recipe.recipe.converter!.base.target_width_mm = 124;
    expect(await isShareCardFile(new File([JSON.stringify(recipe)], 'edited.json'))).toBe(true);
  });
  it('does not misidentify ordinary, LUT, broken or oversized JSON as a project', async () => {
    for (const text of ['{}', '{"colors":[[255,0,0]],"metadata":{"color_mode":"BW"}}', '{bad json']) {
      expect(await isShareCardFile(new File([text], 'ordinary.json'))).toBe(false);
    }
    const { recipe } = await buildTestRecipe();
    const file = new File([JSON.stringify(recipe)], 'large.json');
    Object.defineProperty(file, 'size', { value: 128 * 1024 * 1024 + 1 });
    file.text = () => { throw new Error('must reject before reading'); };
    expect(await isShareCardFile(file)).toBe(false);
    const namedSidecar = new File(['broken'], 'broken.lumina.json');
    expect(await isShareCardFile(namedSidecar)).toBe(true);
    await expect(parseRecipeFile(namedSidecar)).rejects.toThrow('failed to parse JSON');
  });
  describe("full export → import round-trip", () => {
    it("basic state: export → clear → import → state equivalent", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        target_width_mm: 120,
        target_height_mm: 90,
        spacer_thick: 0.8,
      });

      const { state: restored, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      expect(restored.lut_name).toBe("TestLUT");
      expect(restored.target_width_mm).toBe(120);
      expect(restored.target_height_mm).toBe(90);
      expect(restored.spacer_thick).toBe(0.8);
      expect(warnings).toHaveLength(0); // record match, no warnings
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

      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS);

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

      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS);

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
      );

      expect(restored.recipe_overrides).toEqual([]);

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
      expect(warnings).toContain(
        RECIPE_IMPORT_WARNING_REGION_RECIPES_NOT_RESTORED,
      );

      const embedded = await embedRecipeInPng(
        createMinimalPng(),
        recipe,
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

    it("exports schema_version 4 and imports legacy defaults without warnings", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      expect(recipe.schema_version).toBe(5);

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
      );
      expect(restored.recipe_overrides).toEqual([]);
      expect(restored.customRecipeHistory).toEqual([]);
      expect(restored.backing_infill_density_percent).toBe(100);

      const legacyV2 = JSON.parse(JSON.stringify(recipe)) as LuminaRecipe;
      legacyV2.schema_version = 2;
      if (legacyV2.recipe.converter) {
        delete legacyV2.recipe.converter.geometry
          .backing_infill_density_percent;
      }
      const { state: restoredV2 } = restoreConverterRecipe(
        migrateRecipe(legacyV2),
        LOCAL_LUTS,
      );
      expect(restoredV2.backing_infill_density_percent).toBe(100);
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

      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      expect(restored.largeFormatEnabled).toBe(true);
      expect(restored.tileWidthMm).toBe(180);
      expect(restored.tileHeightMm).toBe(140);
      expect(restored.target_width_mm).toBe(500);
    });
  });

  describe("PNG embed → extract round-trip", () => {
    it("recipe survives PNG embedding and extraction", async () => {
      const workshopSource = createBeadRecipeSourceFixture();
      const { recipe } = await buildTestRecipe(
        {
          lut_name: "TestLUT",
          target_width_mm: 80,
          enable_relief: true,
          workshopSource,
        },
        undefined,
        {
          deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
          buildPlateId: "textured-pei-plate",
        },
      );

      const png = createMinimalPng();
      const embedded = await embedRecipeInPng(png, recipe);

      expect(await hasLuminaRecipe(embedded)).toBe(true);

      const extracted = await extractRecipeFromPng(embedded);
      expect(extracted).not.toBeNull();
      expect(extracted!.recipe.converter!.base.target_width_mm).toBe(80);
      expect(extracted!.recipe.converter!.relief.enable_relief).toBe(true);
      expect(extracted!.recipe.converter!.base.lut.name).toBe("TestLUT");
      expect(extracted!.recipe.converter!.device.build_plate_id).toBe(
        "textured-pei-plate",
      );
      expect(extracted!.recipe.workshop).toEqual(workshopSource);
    });

    it("full flow: export → embed → file parse → import", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "SixColorLUT",
        color_mode: ColorMode.SIX_COLOR,
        target_width_mm: 200,
        enable_coating: true,
        coating_height_mm: 0.15,
      });

      const png = createMinimalPng();
      const embedded = await embedRecipeInPng(png, recipe);

      // Create a File from the embedded blob
      const shareCardFile = new File([embedded], "share.png", { type: "image/png" });
      const parsed = await parseRecipeFile(shareCardFile);

      expect(parsed.source).toBe("png");
      const { state: restored, warnings } = restoreConverterRecipe(
        parsed.recipe,
        LOCAL_LUTS,
      );

      expect(restored.lut_name).toBe("SixColorLUT");
      expect(restored.target_width_mm).toBe(200);
      expect(restored.enable_coating).toBe(true);
      expect(restored.coating_height_mm).toBe(0.15);
      expect(warnings).toHaveLength(0);
    });

    it("preserves a dynamic Lumina Box archive through PNG sharing without legacy LUT state", async () => {
      const dynamicRecipe: DynamicMaterialRecipe = {
        target_srgb: [240, 220, 200],
        matched_srgb: [238, 218, 198],
        actual_layer_count: 5,
        padding_layer_count: 3,
        actual_recipe_top_to_bottom: [0, 1, 0, 1, 0],
        print_recipe_top_to_bottom: [0, 1, 0, 1, 0, 1, 1, 1],
        selected_delta_e00: 0.7,
        best_range_delta_e00: 0.4,
        fixed_max_delta_e00: 0.5,
        delta_e00_sacrifice: 0.3,
        layer_cap_options: ([5, 6, 7, 8] as const).map((cap) => ({
          max_effective_layer_count: cap,
          actual_layer_count: 5,
          matched_srgb: [238, 218, 198],
          actual_recipe_top_to_bottom: [0, 1, 0, 1, 0],
          print_recipe_top_to_bottom: [0, 1, 0, 1, 0, 1, 1, 1],
          delta_e00: 0.7,
        })),
      };
      const benefitCurve: MaterialLayerBenefitPoint[] = (
        [5, 6, 7, 8] as const
      ).map(
        (cap) => ({
          max_effective_layer_count: cap,
          weighted_mean_delta_e00: 0.7,
          marginal_delta_e00_reduction: 0.2,
        }),
      );
      const { recipe } = await buildTestRecipe(
        {
          source_version: "lumina_box",
          lut_name: "SixColorLUT",
          color_mode: ColorMode.SIX_COLOR,
          selectedNativeBrandKey: "stale-native-brand",
          selectedNativeDbNames: ["Stale Native PLA"],
          color_layers: 8,
          layer_height_mm: 0.2,
          selectedMaterialDirNames: ["lb/blue", "lb/white"],
          materialLayerCount: 8,
          materialLayerHeightMm: 0.04,
          materialBackingMaterialDirName: "lb/white",
          materialDynamicLayerCountEnabled: true,
          materialMinLayerCount: 5,
          materialMaxLayerCount: 8,
          materialDynamicRecipes: [dynamicRecipe],
          materialLayerBenefitCurve: benefitCurve,
          materialLayerBenefitScope: "automatic_pixels",
          materialLayerBenefitPixelCount: 37,
        },
        undefined,
        { materialDeltaE00Tolerance: 0.65 },
      );

      expect(recipe.recipe.converter?.base).toMatchObject({
        lut: { name: "", color_mode: "" },
        color_mode: "",
      });
      expect(recipe.recipe.converter?.source).toMatchObject({
        source_version: "lumina_box",
        selected_native_brand_key: "",
        selected_native_db_names: [],
        color_layers: null,
        layer_height_mm: null,
        selected_material_dir_names: ["lb/blue", "lb/white"],
        material_layer_count: 8,
        material_layer_height_mm: 0.04,
        material_backing_material_dir_name: "lb/white",
        material_dynamic_layer_count_enabled: true,
        material_min_layer_count: 5,
        material_max_layer_count: 8,
        material_delta_e00_tolerance: 0.65,
      });

      const embedded = await embedRecipeInPng(
        createMinimalPng(),
        recipe,
      );
      const parsed = await parseRecipeFile(
        new File([embedded], "lumina-box-share.png", { type: "image/png" }),
      );
      const { state: restored, warnings } = restoreConverterRecipe(
        parsed.recipe,
        LOCAL_LUTS,
      );

      expect(restored).toMatchObject({
        source_version: "lumina_box",
        lut_name: "",
        lut_names: [],
        selectedMaterialDirNames: ["lb/blue", "lb/white"],
        materialLayerCount: 8,
        materialLayerHeightMm: 0.04,
        materialBackingMaterialDirName: "lb/white",
        materialDynamicLayerCountEnabled: true,
        materialMinLayerCount: 5,
        materialMaxLayerCount: 8,
        materialDynamicRecipes: [dynamicRecipe],
        materialLayerBenefitCurve: benefitCurve,
        materialLayerBenefitScope: "automatic_pixels",
        materialLayerBenefitPixelCount: 37,
      });
      expect(warnings).not.toContain(RECIPE_IMPORT_WARNING_LUT_MISSING);
    });
  });

  describe("JSON sidecar round-trip", () => {
    it("export → JSON file → parse → import", async () => {
      const workshopSource = createBeadRecipeSourceFixture();
      const { recipe } = await buildTestRecipe(
        {
          lut_name: "TestLUT",
          target_width_mm: 60,
          add_loop: true,
          quantize_colors_unlocked: true,
          use_lut_constrained: true,
          auto_dynamic_range: true,
          workshopSource,
        },
        undefined,
        {
          deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
          buildPlateId: "textured-pei-plate",
        },
      );

      const jsonStr = JSON.stringify(recipe, null, 2);
      const jsonFile = new File([jsonStr], "card.lumina.json", { type: "application/json" });

      const parsed = await parseRecipeFile(jsonFile);
      expect(parsed.source).toBe("json");
      expect(parsed.recipe.recipe.converter!.device.build_plate_id).toBe(
        "textured-pei-plate",
      );

      const { state: restored } = restoreConverterRecipe(parsed.recipe, LOCAL_LUTS);
      expect(restored.lut_name).toBe("TestLUT");
      expect(restored.target_width_mm).toBe(60);
      expect(restored.add_loop).toBe(true);
      expect(restored.quantize_colors_unlocked).toBe(true);
      expect(restored.use_lut_constrained).toBe(true);
      expect(restored.auto_dynamic_range).toBe(true);
      expect(restored.workshopSource).toEqual(workshopSource);
    });
  });

  describe("PNG project round-trip", () => {
    it("preserves output-affecting matching flags", async () => {
      const { recipe } = await buildTestRecipe({
        lut_name: "TestLUT",
        quantize_colors_unlocked: true,
        use_lut_constrained: true,
        auto_dynamic_range: true,
      });
      const embedded = await embedRecipeInPng(
        createMinimalPng(),
        recipe,
      );
      const parsed = await parseRecipeFile(
        new File([embedded], "project.png", { type: "image/png" }),
      );

      const { state: restored } = restoreConverterRecipe(
        parsed.recipe,
        LOCAL_LUTS,
      );

      expect(restored.quantize_colors_unlocked).toBe(true);
      expect(restored.use_lut_constrained).toBe(true);
      expect(restored.auto_dynamic_range).toBe(true);
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
      );
      const files = [
        new File([png], "spatial-share.png", { type: "image/png" }),
        new File([JSON.stringify(recipe)], "spatial-share.lumina.json", {
          type: "application/json",
        }),
      ];

      for (const file of files) {
        const parsed = await parseRecipeFile(file);
        const restored = restoreConverterRecipe(parsed.recipe, LOCAL_LUTS);
        expect(restored.warnings).toContain(
          RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED,
        );
      }

      expect(
        translations[RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED].zh,
      ).toContain("旧项目");
      expect(
        translations[RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED].en,
      ).toContain("older project");
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
      const { recipe } = await buildTestRecipe({ lut_name: "NonExistentLUT" }, "missing-record");

      const { state: restored, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      expect(restored.lut_name).toBe(""); // Cannot match
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_LUT_MISSING);
    });

    it("changed LUT record path triggers name fallback with warning", async () => {
      const state = { ...DEFAULT_STATE, source_version: "legacy", lut_name: "TestLUT" } as ConverterState;
      const converterRecipe = exportConverterRecipe(state, DEFAULT_SETTINGS, "missing-record");

      const recipe = await buildFullRecipe(
        converterRecipe,
        { width: 1, height: 1, mime_type: "image/png" },
        {
          primary: {
            filename: "t.png",
            mime_type: "image/png",
            byte_size: 4,
            encoding: "base64",
            payload_b64: "dGVzdA==",
          },
        },
      );

      const { state: restored, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      expect(restored.lut_name).toBe("TestLUT"); // Name fallback still works
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_LUT_DEGRADED);
    });
  });

  describe("import does not pollute unrelated state", () => {
    it("session/preview state is cleared on import", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS);

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
      const { state: restored } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      expect(restored.colorRemapMap).toEqual({});
      expect(restored.remapHistory).toEqual([]);
    });
  });

  describe("editable recipes and asset validation", () => {
    it("exports schema v4 without retired recipe or asset digests", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      expect(recipe.schema_version).toBe(5);
      expect(recipe.compat.min_schema_version).toBe(5);
      expect(recipe).not.toHaveProperty("integrity");
      expect(recipe.asset.primary).not.toHaveProperty("sha256");
      expect(recipe.recipe.converter!.base.lut).not.toHaveProperty("fingerprint");
    });

    it.each([1, 2, 3])("imports a legally edited v%s JSON with stale or absent digests", async (version) => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      const legacy = JSON.parse(JSON.stringify(recipe));
      legacy.schema_version = version;
      legacy.integrity = { recipe_sha256: "stale", asset_checksums: { primary: "stale" } };
      legacy.asset.primary.sha256 = "stale";
      legacy.recipe.converter.base.lut.fingerprint = "retired";
      legacy.recipe.converter.base.target_width_mm = 124;
      for (const hasDigest of [true, false]) {
        if (!hasDigest) {
          delete legacy.integrity;
          delete legacy.asset.primary.sha256;
        }
        const parsed = await parseRecipeFile(new File([JSON.stringify(legacy)], "edited.lumina.json"));
        expect(parsed.recipe.schema_version).toBe(5);
        expect(parsed.recipe).not.toHaveProperty("integrity");
        expect(parsed.recipe.asset.primary).not.toHaveProperty("sha256");
        expect(parsed.recipe.recipe.converter!.base.lut).not.toHaveProperty("fingerprint");
        expect(restoreConverterRecipe(parsed.recipe, LOCAL_LUTS).state.target_width_mm).toBe(124);
      }
    });

    it("rejects an invalid base64 primary attachment", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      recipe.asset.primary.payload_b64 = "@broken";
      const file = new File([JSON.stringify(recipe)], "tampered.lumina.json", {
        type: "application/json",
      });

      await expect(parseRecipeFile(file)).rejects.toThrow("Asset data is corrupted");
    });

    it("rejects a heightmap attachment whose declared byte size is wrong", async () => {
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

    it("rejects an active heightmap reference whose attachment is missing", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT", enable_relief: true, autoHeightMode: "use-heightmap" });
      await expect(parseRecipeFile(new File([JSON.stringify(recipe)], "missing-heightmap.lumina.json"))).rejects.toThrow("Asset data is corrupted");
    });

    it("imports an edited legacy PNG and preserves primary and heightmap bytes", async () => {
      const heightmapFile = new File([new Uint8Array([10, 20, 30])], "height.png", { type: "image/png" });
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT", heightmapFile });
      recipe.recipe.converter!.base.target_width_mm += 1;
      const legacy = JSON.parse(JSON.stringify(recipe));
      legacy.schema_version = 3;
      legacy.integrity = { recipe_sha256: "stale", asset_checksums: {} };
      const embedded = await embedRecipeInPng(
        createMinimalPng(),
        legacy,
      );
      const file = new File([embedded], "tampered-share.png", { type: "image/png" });

      const parsed = await parseRecipeFile(file);
      const restored = restoreConverterRecipe(parsed.recipe, LOCAL_LUTS);
      expect(restored.state.target_width_mm).toBe(recipe.recipe.converter!.base.target_width_mm);
      expect(new Uint8Array(await restored.assetFile.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3, 4]));
      expect(new Uint8Array(await restored.heightmapFile!.arrayBuffer())).toEqual(new Uint8Array([10, 20, 30]));
    });

    it("recipe with heightmap preserves its attachment without digest metadata", async () => {
      const hmFile = new File([new Uint8Array([10, 20, 30])], "height.png", { type: "image/png" });
      const state = { ...DEFAULT_STATE, source_version: "legacy", lut_name: "TestLUT", heightmapFile: hmFile } as ConverterState;
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

      expect(recipe.asset.heightmap).toBeDefined();
      expect(recipe.asset.heightmap).not.toHaveProperty("sha256");
    });

    it("does not silently choose between same-name LUT records", () => {
      const luts = [
        { ...LOCAL_LUTS[0], path: "first" },
        { ...LOCAL_LUTS[0], path: "second" },
      ];
      expect(matchLut({ name: "TestLUT", color_mode: ColorMode.FOUR_COLOR_RYBW }, luts)).toMatchObject({ matched: false });
    });

    it.each(["missing base", "non-positive width"])("rejects invalid converter structure: %s", async (invalid) => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      const raw = JSON.parse(JSON.stringify(recipe));
      if (invalid === "missing base") delete raw.recipe.converter.base;
      else raw.recipe.converter.base.target_width_mm = 0;
      await expect(parseRecipeFile(new File([JSON.stringify(raw)], "invalid.lumina.json"))).rejects.toThrow("Invalid recipe");
    });
  });

  describe("schema migration", () => {
    it("keeps the migrated early V1 recipe valid across repeated migrations", () => {
      const migrated = migrateRecipe(createLegacyRecipeV1());
      expect(migrateRecipe(migrated)).toEqual(migrated);
      expect(migrated.recipe.converter!.puzzle).toMatchObject({ puzzle_enabled: false, puzzle_rows: 3 });
    });

    it("imports an already migrated early V1 card after PNG serialization", async () => {
      const migrated = migrateRecipe(createLegacyRecipeV1());
      const png = await embedRecipeInPng(createMinimalPng(), migrated);
      const parsed = await parseRecipeFile(new File([png], "migrated-early-v1.png", { type: "image/png" }));
      const restored = restoreConverterRecipe(parsed.recipe, LOCAL_LUTS);
      expect(parsed.recipe).toEqual(migrated);
      expect(restored.state).toMatchObject({ puzzleEnabled: false, puzzleRows: 3, target_width_mm: 80, target_height_mm: 60 });
      expect(restored.assetFile.size).toBe(migrated.asset.primary.byte_size);
    });

    it.each(["json", "png"])("imports the published first V1 field shape from %s", async (container) => {
      const legacy = createLegacyRecipeV1();
      expect(legacy.recipe.converter).not.toHaveProperty("puzzle");
      expect(legacy.recipe.converter).not.toHaveProperty("source");
      expect(legacy.recipe.converter).not.toHaveProperty("fridge_magnet");
      expect(legacy.recipe.converter.device).not.toHaveProperty("nozzle_size");
      const body = container === "png"
        ? await embedRecipeInPng(createMinimalPng(), legacy as unknown as LuminaRecipe)
        : JSON.stringify(legacy);
      const parsed = await parseRecipeFile(new File([body], `first-v1.${container}`));
      const restored = restoreConverterRecipe(parsed.recipe, LOCAL_LUTS);
      expect(parsed.recipe.schema_version).toBe(5);
      expect(restored.state).toMatchObject({
        lut_name: "TestLUT", target_width_mm: 80, target_height_mm: 60,
        source_version: "legacy", puzzleEnabled: false, puzzleRows: 3,
        enable_fridge_magnet: false, backing_infill_density_percent: 100,
      });
      expect(restored.assetFile.name).toBe("original.png");
      expect(restored.assetFile.size).toBe(legacy.asset.primary.byte_size);
    });

    it("requires the puzzle section on newly exported schema V4 recipes", () => {
      expect(() => migrateRecipe({ ...createLegacyRecipeV1(), schema_version: 4 })).toThrow("Invalid recipe");
    });

    it.each([1, 4])("rejects a malformed puzzle section on schema V%s", (version) => {
      const legacy = createLegacyRecipeV1();
      const malformed = { ...legacy, schema_version: version, recipe: { converter: { ...legacy.recipe.converter, puzzle: [] } } };
      expect(() => migrateRecipe(malformed)).toThrow("Invalid recipe");
    });

    it("future schema version passes with warning", async () => {
      const { recipe } = await buildTestRecipe({ lut_name: "TestLUT" });
      const futureRecipe = { ...recipe, schema_version: 99 };

      const migrated = migrateRecipe(futureRecipe);
      expect(migrated.warnings.some((w) => w.includes("schema version 99"))).toBe(true);
    });
  });
});
