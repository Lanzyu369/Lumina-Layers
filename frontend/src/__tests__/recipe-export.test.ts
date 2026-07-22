import { describe, it, expect } from "vitest";
import { exportConverterRecipe } from "../recipe/exportRecipe";
import type { ConverterState } from "../stores/converter/store";
import { DEFAULT_STATE } from "../stores/converter";
import type { SettingsState } from "../stores/settingsStore";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { DynamicMaterialRecipe } from "../api/types";

function makeState(overrides?: Partial<ConverterState>): ConverterState {
  return { ...DEFAULT_STATE, ...overrides } as ConverterState;
}

function makeSettings(overrides?: Partial<SettingsState>): SettingsState {
  return { ...DEFAULT_SETTINGS, ...overrides };
}

describe("recipe/exportRecipe", () => {
  describe("exportConverterRecipe", () => {
    it("exports base parameters correctly", () => {
      const state = makeState({
        lut_name: "TestLUT",
        color_mode: "4-Color (RYBW)" as ConverterState["color_mode"],
        modeling_mode: "high-fidelity" as ConverterState["modeling_mode"],
        target_width_mm: 100,
        target_height_mm: 75,
        quantize_colors: 64,
        high_precision_3d_preview: true,
        enable_cleanup: true,
        hue_enable: true,
        chroma_gate: 20,
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp123");

      expect(recipe.base.lut.name).toBe("TestLUT");
      expect(recipe.base.lut.fingerprint).toBe("fp123");
      expect(recipe.base.color_mode).toBe("4-Color (RYBW)");
      expect(recipe.base.target_width_mm).toBe(100);
      expect(recipe.base.target_height_mm).toBe(75);
      expect(recipe.base.high_precision_3d_preview).toBe(true);
      expect(recipe.base.hue_enable).toBe(true);
      expect(recipe.base.chroma_gate).toBe(20);
      expect(recipe.base.svg_pixels_per_mm).toBe(10);
    });

    it("exports geometry parameters including loop", () => {
      const state = makeState({
        add_loop: true,
        loop_width: 6,
        loop_length: 10,
        loop_hole: 4,
        loop_angle: 90,
        loop_offset_x: 2,
        loop_offset_y: -1,
        loop_position_preset: "bottom-center",
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      expect(recipe.geometry.add_loop).toBe(true);
      expect(recipe.geometry.loop_angle).toBe(90);
      expect(recipe.geometry.loop_position_preset).toBe("bottom-center");
    });

    it("merges colorRemapMap into replacement_regions", () => {
      const state = makeState({
        replacement_regions: [
          { quantized_hex: "aa0000", matched_hex: "bb0000", replacement_hex: "cc0000" },
        ],
        colorRemapMap: { dd0000: "ee0000" },
        palette: [
          { quantized_hex: "dd0000", matched_hex: "dd0000", pixel_count: 10, percentage: 0.5 },
        ],
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");

      // Should have 2 entries: original + remapped
      expect(recipe.color_ops.replacement_regions).toHaveLength(2);
      // All hex values should have '#' prefix
      expect(recipe.color_ops.replacement_regions[0].quantized_hex).toBe("#aa0000");
      expect(recipe.color_ops.replacement_regions[1].matched_hex).toBe("#dd0000");
    });

    it("does not serialize spatial edit count as a global color mapping", () => {
      const state = makeState({
        regionReplacementCount: 3,
        replacement_regions: [],
        colorRemapMap: {},
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");

      expect(recipe.color_ops.replacement_regions).toEqual([]);
      expect(JSON.stringify(recipe.color_ops)).not.toContain(
        "regionReplacementCount",
      );
    });

    it("serializes free_color_set with '#' prefix", () => {
      const state = makeState({
        free_color_set: new Set(["ff0000", "00ff00"]),
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      expect(recipe.color_ops.free_color_set).toEqual(["#ff0000", "#00ff00"]);
    });

    it("normalizes color_height_map keys with '#' prefix", () => {
      const state = makeState({
        enable_relief: true,
        color_height_map: { ff0000: 0.3, "00ff00": 0.5 },
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      expect(recipe.relief.color_height_map).toEqual({ "#ff0000": 0.3, "#00ff00": 0.5 });
    });

    it("exports device info from settings", () => {
      const settings = makeSettings({
        printerModel: "custom-printer",
        slicerSoftware: "OrcaSlicer",
        nozzleSize: "0.2",
        deviceProfileId: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
        svgPixelsPerMm: 18.5,
      });

      const recipe = exportConverterRecipe(makeState(), settings, "fp");
      expect(recipe.device.printer_id).toBe("custom-printer");
      expect(recipe.device.slicer).toBe("OrcaSlicer");
      expect(recipe.device.nozzle_size).toBe("0.2");
      expect(recipe.device.device_profile_id).toBe("OrcaSlicer:bbl:bambu-lab-p1s:0.2");
      expect(recipe.base.svg_pixels_per_mm).toBe(18.5);
    });

    it("exports converter source parameters for share-card restore", () => {
      const state = makeState({
        source_version: "native",
        selectedNativeBrandKey: "bambulab_pla",
        selectedNativeDbNames: ["PLA Basic", "PLA Matte"],
        color_layers: 6,
        layer_height_mm: 0.08,
        model_enable: true,
        model_only: false,
        model_threshold: 0.42,
        model_margin: 3,
        selectedMaterialDirNames: ["brand/red", "brand/white"],
        materialLayerCount: 10,
        materialLayerHeightMm: 0.06,
        materialBackingMaterialDirName: "brand/white",
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");

      expect(recipe.source).toEqual({
        source_version: "native",
        selected_native_brand_key: "bambulab_pla",
        selected_native_db_names: ["PLA Basic", "PLA Matte"],
        color_layers: 6,
        layer_height_mm: 0.08,
        model_enable: true,
        model_only: false,
        model_threshold: 0.42,
        model_margin: 3,
        selected_material_dir_names: ["brand/red", "brand/white"],
        material_layer_count: 10,
        material_layer_height_mm: 0.06,
        material_backing_material_dir_name: "brand/white",
      });
    });

    it("exports selected legacy LUT names for multi-select restore", () => {
      const state = makeState({
        source_version: "legacy",
        lut_name: "LUT-A",
        lut_names: ["LUT-A", "LUT-B", "LUT-A", ""],
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");

      expect(recipe.source!.selected_legacy_lut_names).toEqual([
        "LUT-A",
        "LUT-B",
      ]);
    });

    it("exports dynamic material settings and exact recipe metadata", () => {
      const dynamicRecipe: DynamicMaterialRecipe = {
        target_srgb: [240, 220, 200],
        matched_srgb: [238, 218, 198],
        actual_layer_count: 5,
        padding_layer_count: 2,
        actual_recipe_top_to_bottom: [0, 1, 0, 1, 0],
        print_recipe_top_to_bottom: [0, 1, 0, 1, 0, 1, 1],
        selected_delta_e00: 0.7,
        best_range_delta_e00: 0.4,
        fixed_max_delta_e00: 0.5,
        delta_e00_sacrifice: 0.3,
        layer_cap_options: [],
      };
      const recipe = exportConverterRecipe(
        makeState({
          source_version: "material",
          materialDynamicLayerCountEnabled: true,
          materialMinLayerCount: 5,
          materialMaxLayerCount: 7,
          materialDynamicRecipes: [dynamicRecipe],
        }),
        makeSettings({ materialDeltaE00Tolerance: 0.7 }),
        "fp",
      );

      expect(recipe.source).toMatchObject({
        material_dynamic_layer_count_enabled: true,
        material_min_layer_count: 5,
        material_max_layer_count: 7,
        material_delta_e00_tolerance: 0.7,
      });
      expect(recipe.material_dynamic?.recipes[0]).toEqual(dynamicRecipe);
      expect(recipe.material_dynamic?.recipes[0]).not.toBe(dynamicRecipe);
    });

    it("exports large format parameters", () => {
      const state = makeState({
        largeFormatEnabled: true,
        tileWidthMm: 180,
        tileHeightMm: 140,
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      expect(recipe.large_format.large_format_enabled).toBe(true);
      expect(recipe.large_format.tile_width_mm).toBe(180);
      expect(recipe.large_format.tile_height_mm).toBe(140);
    });

    it("exports puzzle parameters", () => {
      const state = makeState({
        puzzleEnabled: true,
        puzzleStyle: "irregular",
        puzzleSizingMode: "grid",
        puzzleRows: 4,
        puzzleCols: 6,
        targetPieceCount: 24,
        connectorStyle: "easy_cut",
        labelsEnabled: true,
        engraveBackLabels: true,
        irregularityStrength: 0.42,
        minNeckWidthMm: 1.5,
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      expect(recipe.puzzle.puzzle_enabled).toBe(true);
      expect(recipe.puzzle.puzzle_style).toBe("irregular");
      expect(recipe.puzzle.puzzle_sizing_mode).toBe("grid");
      expect(recipe.puzzle.puzzle_rows).toBe(4);
      expect(recipe.puzzle.puzzle_cols).toBe(6);
      expect(recipe.puzzle.puzzle_seed).toBe(0);
      expect(recipe.puzzle.connector_style).toBe("easy_cut");
      expect(recipe.puzzle.labels_enabled).toBe(true);
      expect(recipe.puzzle.engrave_back_labels).toBe(false);
    });

    it("exports fridge magnet parameters and omits the frontend-only base spacer thickness", () => {
      const state = makeState({
        spacer_thick: 3.4,
        enable_fridge_magnet: true,
        base_spacer_thick: 1.1,
        fridge_magnets: [
          {
            id: "magnet-round",
            shape: "round",
            preset_key: "round-d12x3",
            diameter_mm: 12,
            width_mm: null,
            height_mm: null,
            thickness_mm: 3,
            center_x_mm: 10,
            center_y_mm: 12,
          },
          {
            id: "magnet-rect",
            shape: "rect",
            preset_key: "rect-20x10x2",
            diameter_mm: null,
            width_mm: 20,
            height_mm: 10,
            thickness_mm: 2,
            center_x_mm: 40,
            center_y_mm: 18,
          },
        ],
      });

      const recipe = exportConverterRecipe(state, makeSettings(), "fp");

      expect(recipe.geometry.spacer_thick).toBe(1.1);
      expect(recipe.fridge_magnet?.enable_fridge_magnet).toBe(true);
      expect(recipe.fridge_magnet?.fridge_magnets).toEqual(state.fridge_magnets);
      expect(JSON.stringify(recipe)).not.toContain("base_spacer_thick");
    });

    it("does NOT include UI-only state fields", () => {
      const state = makeState();
      const recipe = exportConverterRecipe(state, makeSettings(), "fp");
      const json = JSON.stringify(recipe);

      // These UI-only fields should NOT appear in the recipe
      expect(json).not.toContain("sessionId");
      expect(json).not.toContain("isLoading");
      expect(json).not.toContain("isGenerating");
      expect(json).not.toContain("previewGlbUrl");
      expect(json).not.toContain("batchMode");
      expect(json).not.toContain("cropModalOpen");
      expect(json).not.toContain("base_spacer_thick");
    });
  });
});
