import { describe, it, expect } from "vitest";
import {
  detectRecipeFileType,
  matchLut,
  restoreConverterRecipe,
  RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE,
  RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LARGE_FORMAT,
  RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LOOP,
  RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_PUZZLE,
  RECIPE_IMPORT_WARNING_LUT_DEGRADED,
  RECIPE_IMPORT_WARNING_LUT_MISSING,
  RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LARGE_FORMAT,
  RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LOOP,
} from "../recipe/importRecipe";
import { migrateRecipe } from "../recipe/migration";
import type { LuminaRecipe } from "../recipe/types";
import type { LutInfo } from "../api/types";
import { ColorMode } from "../api/types";

// ========== Helpers ==========

function createTestRecipe(overrides?: Partial<LuminaRecipe>): LuminaRecipe {
  return {
    format: "lumina-recipe",
    schema_version: 1,
    app_version: "0.0.0",
    created_at: "2025-01-01T00:00:00.000Z",
    source: "converter",
    cover: { width: 100, height: 75, mime_type: "image/png" },
    asset: {
      primary: {
        filename: "photo.png",
        mime_type: "image/png",
        byte_size: 4,
        sha256: "abcd",
        encoding: "base64",
        payload_b64: "dGVzdA==", // "test"
      },
    },
    recipe: {
      converter: {
        base: {
          lut: { name: "MyLUT", color_mode: "4-Color (RYBW)", fingerprint: "fp123" },
          color_mode: "4-Color (RYBW)",
          modeling_mode: "high-fidelity",
          target_width_mm: 80,
          target_height_mm: 60,
          auto_bg: true,
          bg_tol: 30,
          quantize_colors: 32,
          enable_cleanup: true,
          hue_enable: false,
          chroma_gate: 0,
        },
        geometry: {
          spacer_thick: 0.6,
          structure_mode: "single-sided",
          separate_backing: false,
          add_loop: false,
          loop_width: 5,
          loop_length: 8,
          loop_hole: 3,
          loop_angle: 45,
          loop_offset_x: 1,
          loop_offset_y: -2,
          loop_position_preset: "top-right",
        },
        relief: {
          enable_relief: true,
          auto_height_mode: "darker-higher",
          color_height_map: { "#ff0000": 0.3, "#00ff00": 0.5 },
          heightmap_max_height: 0.8,
        },
        outline: { enable_outline: true, outline_width: 0.5 },
        cloisonne: { enable_cloisonne: false, wire_width_mm: 0.4, wire_height_mm: 0.3 },
        coating: { enable_coating: true, coating_height_mm: 0.15 },
        color_ops: {
          replacement_regions: [
            { quantized_hex: "#aa0000", matched_hex: "#bb0000", replacement_hex: "#cc0000" },
          ],
          free_color_set: ["#ff0000", "#00ff00"],
        },
        large_format: { large_format_enabled: false, tile_width_mm: 150, tile_height_mm: 120 },
        puzzle: {
          puzzle_enabled: true,
          puzzle_style: "irregular",
          puzzle_sizing_mode: "grid",
          piece_width_mm: 20,
          piece_height_mm: 20,
          puzzle_rows: 4,
          puzzle_cols: 5,
          target_piece_count: 20,
          puzzle_seed: 42,
          connector_style: "classic",
          labels_enabled: true,
          engrave_back_labels: false,
          irregularity_strength: 0.35,
          min_neck_width_mm: 1.2,
        },
        fridge_magnet: {
          enable_fridge_magnet: false,
          fridge_magnets: [],
        },
        device: { printer_id: "bambu-h2d", slicer: "BambuStudio" },
      },
    },
    integrity: {
      recipe_sha256: "0".repeat(64),
      asset_checksums: { primary: "abcd" },
    },
    compat: { min_schema_version: 1 },
    warnings: [],
    ...overrides,
  };
}

const LOCAL_LUTS: LutInfo[] = [
  { name: "MyLUT", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/luts/my.json", fingerprint: "fp123" },
  { name: "OtherLUT", color_mode: ColorMode.SIX_COLOR, path: "/luts/other.json", fingerprint: "fpOther" },
];

const LOCAL_FINGERPRINTS: Record<string, string> = {
  MyLUT: "fp123",
  OtherLUT: "fpOther",
};

// ========== Tests ==========

describe("recipe/importRecipe", () => {
  describe("detectRecipeFileType", () => {
    it("detects .lumina.json", () => {
      const file = new File(["{}"], "card.lumina.json", { type: "application/json" });
      expect(detectRecipeFileType(file)).toBe("json");
    });

    it("detects .png", () => {
      const file = new File([""], "share.png", { type: "image/png" });
      expect(detectRecipeFileType(file)).toBe("png");
    });

    it("returns null for unsupported types", () => {
      const file = new File([""], "photo.jpg", { type: "image/jpeg" });
      expect(detectRecipeFileType(file)).toBeNull();
    });
  });

  describe("matchLut", () => {
    it("matches by fingerprint", () => {
      const result = matchLut({ name: "SomeName", fingerprint: "fp123" }, LOCAL_LUTS, LOCAL_FINGERPRINTS);
      expect(result.matched).toBe(true);
      if (result.matched) {
        expect(result.lutName).toBe("MyLUT");
        expect(result.matchType).toBe("fingerprint");
      }
    });

    it("falls back to name match", () => {
      const result = matchLut({ name: "OtherLUT", fingerprint: "wrongFP" }, LOCAL_LUTS, LOCAL_FINGERPRINTS);
      expect(result.matched).toBe(true);
      if (result.matched) {
        expect(result.lutName).toBe("OtherLUT");
        expect(result.matchType).toBe("name");
      }
    });

    it("returns not matched when LUT is missing", () => {
      const result = matchLut({ name: "NonExistent", fingerprint: "nope" }, LOCAL_LUTS, LOCAL_FINGERPRINTS);
      expect(result.matched).toBe(false);
      if (!result.matched) {
        expect(result.originalName).toBe("NonExistent");
      }
    });
  });

  describe("restoreConverterRecipe", () => {
    it("restores all converter parameters", () => {
      const recipe = createTestRecipe();
      const { state, assetFile, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FINGERPRINTS);

      // Base params
      expect(state.lut_name).toBe("MyLUT");
      expect(state.target_width_mm).toBe(80);
      expect(state.target_height_mm).toBe(60);
      expect(state.auto_bg).toBe(true);
      expect(state.hue_enable).toBe(false);

      // Geometry
      expect(state.spacer_thick).toBe(0.6);
      expect(state.add_loop).toBe(false);
      expect(state.loop_angle).toBe(45);
      expect(state.loop_position_preset).toBe("top-right");

      // Relief
      expect(state.enable_relief).toBe(true);
      // Hex keys should have '#' stripped for store
      expect(state.color_height_map).toEqual({ ff0000: 0.3, "00ff00": 0.5 });

      // Color ops — hex stripped
      expect(state.replacement_regions).toHaveLength(1);
      expect(state.replacement_regions![0].quantized_hex).toBe("aa0000");
      expect(state.free_color_set).toEqual(new Set(["ff0000", "00ff00"]));

      // Large format
      expect(state.largeFormatEnabled).toBe(false);
      expect(state.tileWidthMm).toBe(150);

      // Puzzle
      expect(state.puzzleEnabled).toBe(true);
      expect(state.puzzleStyle).toBe("irregular");
      expect(state.puzzleSizingMode).toBe("grid");
      expect(state.puzzleRows).toBe(4);
      expect(state.puzzleCols).toBe(5);
      expect(state.connectorStyle).toBe("classic");
      expect(state.labelsEnabled).toBe(true);
      expect(state.enable_fridge_magnet).toBe(false);
      expect(state.fridge_magnets).toEqual([]);
      expect(state.base_spacer_thick).toBe(0.6);

      // Asset
      expect(assetFile).toBeInstanceOf(File);
      expect(assetFile.name).toBe("photo.png");

      // No warnings for fingerprint match
      expect(warnings).toHaveLength(0);
    });

    it("normalizes puzzle-specific mutually exclusive settings from imported recipes", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.geometry.add_loop = true;
      recipe.recipe.converter!.large_format.large_format_enabled = true;
      recipe.recipe.converter!.puzzle!.labels_enabled = false;
      recipe.recipe.converter!.puzzle!.engrave_back_labels = true;

      const { state, warnings } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
        LOCAL_FINGERPRINTS,
      );

      expect(state.puzzleEnabled).toBe(true);
      expect(state.largeFormatEnabled).toBe(false);
      expect(state.add_loop).toBe(false);
      expect(state.labelsEnabled).toBe(false);
      expect(state.engraveBackLabels).toBe(false);
      expect(
        warnings,
      ).toContain(RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LARGE_FORMAT);
      expect(
        warnings,
      ).toContain(RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LOOP);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE);
    });

    it("disables imported back-label engraving even when piece labels are enabled", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.puzzle!.labels_enabled = true;
      recipe.recipe.converter!.puzzle!.engrave_back_labels = true;

      const { state, warnings } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
        LOCAL_FINGERPRINTS,
      );

      expect(state.labelsEnabled).toBe(true);
      expect(state.engraveBackLabels).toBe(false);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE);
    });

    it("keeps fridge magnet mode and disables puzzle, large format, and loop conflicts from imported recipes", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.geometry.structure_mode = "Double-sided";
      recipe.recipe.converter!.geometry.spacer_thick = 1.1;
      recipe.recipe.converter!.geometry.add_loop = true;
      recipe.recipe.converter!.large_format.large_format_enabled = true;
      recipe.recipe.converter!.puzzle!.puzzle_enabled = true;
      recipe.recipe.converter!.fridge_magnet = {
        enable_fridge_magnet: true,
        fridge_magnets: [
          {
            id: "magnet-round",
            shape: "round",
            preset_key: "round-d12x3",
            diameter_mm: 12,
            width_mm: null,
            height_mm: null,
            thickness_mm: 3,
            center_x_mm: 40,
            center_y_mm: 20,
          },
        ],
      };

      const { state, warnings } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
        LOCAL_FINGERPRINTS,
      );

      expect(state.enable_fridge_magnet).toBe(true);
      expect(state.fridge_magnets).toHaveLength(1);
      expect(state.puzzleEnabled).toBe(false);
      expect(state.largeFormatEnabled).toBe(false);
      expect(state.add_loop).toBe(false);
      expect(state.structure_mode).toBe("Single-sided");
      expect(state.base_spacer_thick).toBe(1.1);
      expect(state.spacer_thick).toBe(3.44);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_PUZZLE);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LARGE_FORMAT);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LOOP);
    });

    it("normalizes imported fridge magnets before restoring them", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.geometry.spacer_thick = 0.7;
      recipe.recipe.converter!.fridge_magnet = {
        enable_fridge_magnet: true,
        fridge_magnets: [
          {
            id: "bad-round",
            shape: "round",
            preset_key: "rect-20x10x2",
            diameter_mm: 0.2,
            width_mm: 8,
            height_mm: 9,
            thickness_mm: 9,
            center_x_mm: 5,
            center_y_mm: 6,
          },
          {
            id: "bad-rect",
            shape: "rect",
            preset_key: "round-d6x2",
            diameter_mm: 7,
            width_mm: 0.2,
            height_mm: 0.1,
            thickness_mm: 0.05,
            center_x_mm: -2,
            center_y_mm: -3,
          },
        ],
      };

      const { state } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
        LOCAL_FINGERPRINTS,
      );

      expect(state.fridge_magnets).toEqual([
        {
          id: "bad-round",
          shape: "round",
          preset_key: "custom",
          diameter_mm: 1,
          width_mm: null,
          height_mm: null,
          thickness_mm: 3.1,
          center_x_mm: 5,
          center_y_mm: 6,
        },
        {
          id: "bad-rect",
          shape: "rect",
          preset_key: "custom",
          diameter_mm: null,
          width_mm: 1,
          height_mm: 1,
          thickness_mm: 0.1,
          center_x_mm: -2,
          center_y_mm: -3,
        },
      ]);
      expect(state.base_spacer_thick).toBe(0.7);
      expect(state.spacer_thick).toBe(3.5);
    });

    it("adds warning for name-only LUT match", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.base.lut.fingerprint = "differentFP";
      const { warnings, state } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FINGERPRINTS);

      expect(state.lut_name).toBe("MyLUT"); // Still matches by name
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_LUT_DEGRADED);
    });

    it("adds warning for missing LUT", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.base.lut.name = "GoneLUT";
      recipe.recipe.converter!.base.lut.fingerprint = "gone";
      const { state, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FINGERPRINTS);

      expect(state.lut_name).toBe(""); // Empty — user must select manually
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_LUT_MISSING);
    });

    it("clears session and preview state", () => {
      const recipe = createTestRecipe();
      const { state } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FINGERPRINTS);

      expect(state.sessionId).toBeNull();
      expect(state.previewImageUrl).toBeNull();
      expect(state.modelUrl).toBeNull();
      expect(state.hasManualPreview).toBe(false);
    });

    it("restores heightmap asset when present", () => {
      const recipe = createTestRecipe();
      recipe.asset.heightmap = {
        filename: "height.png",
        mime_type: "image/png",
        byte_size: 4,
        sha256: "hmhash",
        encoding: "base64",
        payload_b64: "AAAA",
      };
      const { heightmapFile } = restoreConverterRecipe(recipe, LOCAL_LUTS, LOCAL_FINGERPRINTS);
      expect(heightmapFile).toBeInstanceOf(File);
      expect(heightmapFile!.name).toBe("height.png");
    });
  });
});

describe("recipe/migration", () => {
  it("passes through V1 recipe unchanged", () => {
    const recipe = createTestRecipe();
    const migrated = migrateRecipe(recipe);
    expect(migrated.schema_version).toBe(1);
    expect(migrated.recipe.converter).toEqual(recipe.recipe.converter);
  });

  it("rejects invalid format", () => {
    expect(() => migrateRecipe({ format: "not-lumina" })).toThrow("Invalid recipe format");
  });

  it("rejects schema version 0", () => {
    expect(() => migrateRecipe({ format: "lumina-recipe", schema_version: 0 })).toThrow(
      "Unsupported recipe schema version",
    );
  });

  it("adds warning for future schema version", () => {
    const future = createTestRecipe({ schema_version: 99 });
    const migrated = migrateRecipe(future);
    expect(migrated.warnings.some((w) => w.includes("schema version 99"))).toBe(true);
  });

  it("rejects non-object input", () => {
    expect(() => migrateRecipe(null)).toThrow("not an object");
    expect(() => migrateRecipe("string")).toThrow("not an object");
  });
});
