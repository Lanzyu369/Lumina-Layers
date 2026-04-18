import { describe, it, expect } from "vitest";
import { embedRecipeInPng, extractRecipeFromPng, hasLuminaRecipe } from "../recipe/pngMetadata";
import type { LuminaRecipe } from "../recipe/types";

// Minimal valid 1x1 white PNG (67 bytes)
function createMinimalPng(): Blob {
  const data = new Uint8Array([
    // PNG signature
    137, 80, 78, 71, 13, 10, 26, 10,
    // IHDR chunk (13 bytes data)
    0, 0, 0, 13, // length
    73, 72, 68, 82, // "IHDR"
    0, 0, 0, 1, // width = 1
    0, 0, 0, 1, // height = 1
    8, 2, 0, 0, 0, // bit depth=8, color type=2 (RGB), compression, filter, interlace
    144, 119, 83, 222, // CRC
    // IDAT chunk (minimal deflate for 1x1 RGB pixel)
    0, 0, 0, 12, // length
    73, 68, 65, 84, // "IDAT"
    8, 215, 99, 248, 207, 192, 0, 0, 0, 4, 0, 1, // compressed data
    2, 127, 225, 72, // CRC
    // IEND chunk
    0, 0, 0, 0, // length
    73, 69, 78, 68, // "IEND"
    174, 66, 96, 130, // CRC
  ]);
  return new Blob([data], { type: "image/png" });
}

function createTestRecipe(): LuminaRecipe {
  return {
    format: "lumina-recipe",
    schema_version: 1,
    app_version: "0.0.0",
    created_at: "2025-01-01T00:00:00.000Z",
    source: "converter",
    cover: { width: 1, height: 1, mime_type: "image/png" },
    asset: {
      primary: {
        filename: "test.png",
        mime_type: "image/png",
        byte_size: 10,
        sha256: "abc123",
        encoding: "base64",
        payload_b64: "dGVzdA==",
      },
    },
    recipe: {
      converter: {
        base: {
          lut: { name: "Test LUT", color_mode: "4-Color (RYBW)", fingerprint: "abcdef1234567890" },
          color_mode: "4-Color (RYBW)",
          modeling_mode: "high-fidelity",
          target_width_mm: 80,
          target_height_mm: 60,
          auto_bg: true,
          bg_tol: 30,
          quantize_colors: 32,
          enable_cleanup: true,
          hue_enable: true,
          chroma_gate: 15,
        },
        geometry: {
          spacer_thick: 0.6,
          structure_mode: "single-sided",
          separate_backing: false,
          add_loop: false,
          loop_width: 5,
          loop_length: 8,
          loop_hole: 3,
          loop_angle: 0,
          loop_offset_x: 0,
          loop_offset_y: 0,
          loop_position_preset: "top-center",
        },
        relief: {
          enable_relief: false,
          auto_height_mode: "darker-higher",
          color_height_map: {},
          heightmap_max_height: 0.5,
        },
        outline: { enable_outline: false, outline_width: 0.4 },
        cloisonne: { enable_cloisonne: false, wire_width_mm: 0.4, wire_height_mm: 0.3 },
        coating: { enable_coating: false, coating_height_mm: 0.1 },
        color_ops: { replacement_regions: [], free_color_set: [] },
        large_format: { large_format_enabled: false, tile_width_mm: 200, tile_height_mm: 200 },
        puzzle: {
          puzzle_enabled: false,
          puzzle_style: "regular",
          puzzle_sizing_mode: "piece_size",
          piece_width_mm: 20,
          piece_height_mm: 20,
          puzzle_rows: 3,
          puzzle_cols: 3,
          target_piece_count: 12,
          puzzle_seed: 0,
          connector_style: "classic",
          labels_enabled: false,
          engrave_back_labels: false,
          irregularity_strength: 0.35,
          min_neck_width_mm: 1.2,
        },
        device: { printer_id: "bambu-h2d", slicer: "BambuStudio", nozzle_size: "0.2" },
      },
    },
    integrity: {
      recipe_sha256: "0000000000000000000000000000000000000000000000000000000000000000",
      asset_checksums: { primary: "abc123" },
    },
    compat: { min_schema_version: 1 },
    warnings: [],
  };
}

describe("recipe/pngMetadata", () => {
  describe("embedRecipeInPng + extractRecipeFromPng round-trip", () => {
    it("embeds and extracts a recipe from a PNG", async () => {
      const png = createMinimalPng();
      const recipe = createTestRecipe();

      const embedded = await embedRecipeInPng(png, recipe, "test-sha256");
      expect(embedded).toBeInstanceOf(Blob);
      expect(embedded.size).toBeGreaterThan(png.size);

      const extracted = await extractRecipeFromPng(embedded);
      expect(extracted).not.toBeNull();
      expect(extracted!.format).toBe("lumina-recipe");
      expect(extracted!.schema_version).toBe(1);
      expect(extracted!.recipe.converter!.base.lut.name).toBe("Test LUT");
      expect(extracted!.recipe.converter!.base.target_width_mm).toBe(80);
    });

    it("preserves all recipe fields through round-trip", async () => {
      const png = createMinimalPng();
      const recipe = createTestRecipe();

      const embedded = await embedRecipeInPng(png, recipe, "sha");
      const extracted = await extractRecipeFromPng(embedded);

      // Deep equality on the recipe section
      expect(extracted!.recipe).toEqual(recipe.recipe);
      expect(extracted!.asset).toEqual(recipe.asset);
      expect(extracted!.cover).toEqual(recipe.cover);
    });
  });

  describe("hasLuminaRecipe", () => {
    it("returns true for a PNG with embedded recipe", async () => {
      const png = createMinimalPng();
      const recipe = createTestRecipe();
      const embedded = await embedRecipeInPng(png, recipe, "sha");

      expect(await hasLuminaRecipe(embedded)).toBe(true);
    });

    it("returns false for a plain PNG", async () => {
      const png = createMinimalPng();
      expect(await hasLuminaRecipe(png)).toBe(false);
    });

    it("returns false for a non-PNG file", async () => {
      const notPng = new Blob(["not a png"], { type: "text/plain" });
      expect(await hasLuminaRecipe(notPng)).toBe(false);
    });
  });

  describe("extractRecipeFromPng", () => {
    it("returns null for a plain PNG", async () => {
      const png = createMinimalPng();
      const result = await extractRecipeFromPng(png);
      expect(result).toBeNull();
    });

    it("returns null for non-PNG data", async () => {
      const notPng = new Blob(["hello world"], { type: "application/octet-stream" });
      const result = await extractRecipeFromPng(notPng);
      expect(result).toBeNull();
    });
  });
});
