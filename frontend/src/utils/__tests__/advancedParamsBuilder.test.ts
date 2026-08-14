import { describe, expect, it } from "vitest";

import { DEFAULT_STATE } from "../../stores/converter";
import type { ConverterState } from "../../stores/converter/store";
import type {
  ColorReplacementItem,
  FridgeMagnetItem,
} from "../../api/types";
import type {
  AdvancedParams,
  AdvancedParamsFull,
  AdvancedParamsSizeTrimmed,
} from "../../types/actionHistory";
import { buildAdvancedParams } from "../advancedParamsBuilder";

/**
 * Unit tests for the shared advanced-params builder.
 *
 * Validates: Requirements 2.3, 2.4, 2.5, 2.7, 2.8, 9.1, 9.2, 9.3, 9.4, 9.5,
 * 10.3, 10.4, 10.11, 10.12
 */

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function byteLen(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).length;
}

/**
 * Build a `ConverterState` by merging `overrides` on top of `DEFAULT_STATE`.
 * Cast once at the boundary so individual tests stay readable.
 */
function makeState(overrides: Partial<ConverterState> = {}): ConverterState {
  return {
    ...(DEFAULT_STATE as ConverterState),
    ...overrides,
  } as ConverterState;
}

function makeFridgeMagnet(index: number): FridgeMagnetItem {
  return {
    id: `fm-${index}`,
    shape: index % 2 === 0 ? "round" : "rect",
    preset_key: `preset-${index}`,
    diameter_mm: index % 2 === 0 ? 25 : null,
    width_mm: index % 2 === 0 ? null : 30,
    height_mm: index % 2 === 0 ? null : 30,
    thickness_mm: 1.5,
    center_x_mm: index * 1.25,
    center_y_mm: index * 2.5,
  };
}

function makeReplacementRegion(index: number): ColorReplacementItem {
  const hex = (n: number) =>
    `#${((n * 2654435761) >>> 0).toString(16).padStart(8, "0").slice(0, 6)}`;
  return {
    quantized_hex: hex(index),
    matched_hex: hex(index + 1000),
    replacement_hex: hex(index + 2000),
  };
}

function makeColorHeightMap(count: number): Record<string, number> {
  const map: Record<string, number> = {};
  for (let i = 0; i < count; i += 1) {
    const hex = `#${i.toString(16).padStart(6, "0")}`;
    map[hex] = 0.1 + (i % 30) / 10;
  }
  return map;
}

/**
 * Heavy converter state that exercises every feature group + the three
 * length caps (64 / 20 / 32). Used as the baseline for tiered-trim tests.
 */
function makeHeavyState(): ConverterState {
  return makeState({
    enable_fridge_magnet: true,
    fridge_magnets: Array.from({ length: 25 }, (_, i) => makeFridgeMagnet(i)),
    selectedFridgeMagnetId: "fm-0",
    enable_relief: true,
    color_height_map: makeColorHeightMap(100),
    heightmap_max_height: 4.5,
    autoHeightMode: "lighter-higher",
    heightmapFile: new File([new Uint8Array(2048)], "height.png", {
      type: "image/png",
    }),
    heightmapThumbnailUrl: "/static/thumb.png",
    enable_outline: true,
    outline_width: 2.5,
    enable_cloisonne: true,
    wire_width_mm: 0.5,
    wire_height_mm: 0.6,
    enable_coating: true,
    coating_height_mm: 0.12,
    add_loop: true,
    loop_width: 4.5,
    loop_length: 9,
    loop_hole: 2.5,
    loop_angle: 30,
    loop_offset_x: 1,
    loop_offset_y: -2,
    loop_position_preset: "top-right",
    puzzleEnabled: true,
    largeFormatEnabled: true,
    regionReplacementCount: 9,
    replacement_regions: Array.from({ length: 50 }, (_, i) =>
      makeReplacementRegion(i),
    ),
    free_color_set: new Set(
      Array.from(
        { length: 80 },
        (_, i) => i.toString(16).padStart(6, "0"),
      ),
    ),
    recipe_overrides: Array.from({ length: 40 }, (_, i) => ({
      region_id: `region-${i}`,
      recipe: [0, 1, 2, 4],
      layer_order: "Top2Bottom",
      virtual_materials: [{ name: `Virtual ${i}`, hex: "#101010" }],
    })),
  });
}

/**
 * Manually apply the builder's tier-N transformation to a full snapshot so
 * we can measure intermediate serialized sizes without re-running the
 * builder's search loop. Mirrors `applyTier` in advancedParamsBuilder.ts.
 */
function applyTiersInOrder(
  full: AdvancedParamsFull,
  tiers: number[],
): AdvancedParamsFull {
  const next: AdvancedParamsFull = JSON.parse(JSON.stringify(full));
  for (const tier of tiers) {
    if (tier === 1) {
      next.fridge_magnet.fridge_magnets = null;
    } else if (tier === 2) {
      next.relief.color_height_map = null;
    } else if (tier === 3) {
      next.color_replacement.replacement_regions = null;
      next.color_replacement.free_color_set = null;
      next.color_replacement.recipe_overrides = null;
    } else if (tier === 4) {
      next.puzzle.puzzleStyle = null;
      next.puzzle.puzzleSizingMode = null;
      next.puzzle.pieceWidthMm = null;
      next.puzzle.pieceHeightMm = null;
      next.puzzle.puzzleRows = null;
      next.puzzle.puzzleCols = null;
      next.puzzle.targetPieceCount = null;
      next.puzzle.connectorStyle = null;
      next.puzzle.labelsEnabled = null;
      next.puzzle.engraveBackLabels = null;
      next.puzzle.irregularityStrength = null;
      next.puzzle.minNeckWidthMm = null;
      next.large_format.tileWidthMm = null;
      next.large_format.tileHeightMm = null;
    }
  }
  return next;
}

// ---------------------------------------------------------------------------
// Active-tab guard
// ---------------------------------------------------------------------------

describe("buildAdvancedParams — active-tab guard", () => {
  it("returns null when activeTab is not 'converter'", () => {
    const state = makeState();
    expect(buildAdvancedParams(state, "settings", { maxBytes: 8192 })).toBeNull();
    expect(buildAdvancedParams(state, "extractor", { maxBytes: 8192 })).toBeNull();
    expect(buildAdvancedParams(state, "", { maxBytes: 8192 })).toBeNull();
  });

  it("returns an AdvancedParamsFull object when activeTab is 'converter'", () => {
    const result = buildAdvancedParams(makeState(), "converter", {
      maxBytes: 8192,
    });
    expect(result).not.toBeNull();
    expect(typeof result).toBe("object");
    expect(result).toHaveProperty("dimensions");
    expect(result).toHaveProperty("generation");
  });
});

// ---------------------------------------------------------------------------
// Group population
// ---------------------------------------------------------------------------

describe("buildAdvancedParams — groups populated when toggles enabled", () => {
  it("captures dynamic material generation settings", () => {
    const result = buildAdvancedParams(
      makeState({
        source_version: "material",
        materialDynamicLayerCountEnabled: true,
        materialMinLayerCount: 5,
        materialMaxLayerCount: 9,
        materialBackingMaterialDirName: "brand/white",
      }),
      "converter",
      { maxBytes: 8192, materialDeltaE00Tolerance: 0.4 },
    ) as AdvancedParamsFull;
    const generation = result.generation as unknown as Record<string, unknown>;

    expect(generation.material_dynamic_layer_count_enabled).toBe(true);
    expect(generation.material_min_layer_count).toBe(5);
    expect(generation.material_max_layer_count).toBe(9);
    expect(generation.material_backing_material_dir_name).toBe("brand/white");
    expect(generation.material_delta_e00_tolerance).toBe(0.4);
  });

  it("populates all 12 groups with detail data when every toggle is on", () => {
    const state = makeState({
      modelSurfaceEnabled: true,
      modelSurfaceFile: new File(["mesh"], "plate.stl", {
        type: "application/octet-stream",
      }),
      modelSurfaceModelFileId: "model-file-1",
      modelSurfaceSelectionId: "surface-selection-1",
      modelSurfaceSelection: {
        face_indices: [1, 2, 3],
      },
      modelSurfaceFootprint: {
        bounds_width_mm: 197,
        bounds_height_mm: 197,
        hole_count: 85,
      },
      modelSurfacePlacement: {
        mode: "edge_to_edge",
        offset_x_mm: 3,
        offset_y_mm: -4,
        scale: 1.25,
        rotation_deg: 90,
        inset_mm: 0,
      },
      modelSurfaceModelRotation: {
        x_deg: 180,
        y_deg: 0,
        z_deg: 90,
      },
      enable_fridge_magnet: true,
      fridge_magnets: [makeFridgeMagnet(0), makeFridgeMagnet(1)],
      selectedFridgeMagnetId: "fm-0",
      enable_relief: true,
      color_height_map: { "#112233": 1.0, "#445566": 2.0 },
      heightmap_max_height: 3.5,
      autoHeightMode: "darker-higher",
      heightmapThumbnailUrl: "/static/thumb.png",
      enable_outline: true,
      outline_width: 1.5,
      enable_cloisonne: true,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: true,
      coating_height_mm: 0.1,
      add_loop: true,
      puzzleEnabled: true,
      largeFormatEnabled: true,
      replacement_regions: [makeReplacementRegion(0), makeReplacementRegion(1)],
      free_color_set: new Set(["ff0000", "#00ff00"]),
      recipe_overrides: [
        {
          region_id: "region-a",
          recipe: [0, 1, 2, 4],
          layer_order: "Top2Bottom",
          virtual_materials: [{ name: "Matte Black", hex: "#101010" }],
        },
      ],
    });

    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 8192,
    }) as AdvancedParamsFull;

    // Exactly the 12 functional groups (no trim flags when under budget).
    expect(Object.keys(result).sort()).toEqual(
      [
        "cloisonne",
        "coating",
        "color_replacement",
        "dimensions",
        "fridge_magnet",
        "generation",
        "large_format",
        "loop",
        "model_surface",
        "outline",
        "puzzle",
        "relief",
      ].sort(),
    );

    // Dimensions / generation are always present and scalar-filled.
    expect(result.dimensions.target_width_mm).toBe(state.target_width_mm);
    expect(result.dimensions.backing_infill_density_percent).toBe(
      state.backing_infill_density_percent,
    );
    expect(result.generation.structure_mode).toBe(state.structure_mode);
    expect(result.model_surface).toEqual({
      enabled: true,
      model_file: {
        name: "plate.stl",
        size: 4,
        type: "application/octet-stream",
      },
      model_file_id: "model-file-1",
      selection_id: "surface-selection-1",
      selected_face_count: 3,
      footprint: {
        width_mm: 197,
        height_mm: 197,
        hole_count: 85,
      },
      placement: {
        mode: "edge_to_edge",
        offset_x_mm: 3,
        offset_y_mm: -4,
        scale: 1.25,
        rotation_deg: 90,
        inset_mm: 0,
      },
      model_rotation: {
        x_deg: 180,
        y_deg: 0,
        z_deg: 90,
      },
    });

    // Relief with enable=true keeps the details and the color_height_map.
    expect(result.relief.enable_relief).toBe(true);
    expect(result.relief.color_height_map).toEqual({
      "#112233": 1.0,
      "#445566": 2.0,
    });
    expect(result.relief.hasHeightmapThumbnail).toBe(true);

    // Outline / cloisonne / coating / loop keep their details.
    expect(result.outline).toEqual({ enable_outline: true, outline_width: 1.5 });
    expect(result.cloisonne).toEqual({
      enable_cloisonne: true,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
    });
    expect(result.coating).toEqual({
      enable_coating: true,
      coating_height_mm: 0.1,
    });
    expect(result.loop.add_loop).toBe(true);
    expect(result.loop.loop_width).toBe(state.loop_width);

    // Fridge magnets preserved (2 < 20 cap, no truncation flag).
    expect(result.fridge_magnet.enable_fridge_magnet).toBe(true);
    expect(result.fridge_magnet.fridge_magnets).toHaveLength(2);
    expect(result.fridge_magnet).not.toHaveProperty("fridge_magnets_truncated");

    // Puzzle / large_format details preserved.
    expect(result.puzzle.puzzleEnabled).toBe(true);
    expect(result.puzzle.puzzleStyle).toBe(state.puzzleStyle);
    expect(result.large_format.largeFormatEnabled).toBe(true);
    expect(result.large_format.tileWidthMm).toBe(state.tileWidthMm);

    // Color replacement regions preserved.
    expect(result.color_replacement.replacement_regions).toHaveLength(2);
    expect(result.color_replacement.free_color_set).toEqual([
      "#ff0000",
      "#00ff00",
    ]);
    expect(result.color_replacement.recipe_overrides).toEqual([
      {
        region_id: "region-a",
        recipe: [0, 1, 2, 4],
        layer_order: "Top2Bottom",
        virtual_materials: [{ name: "Matte Black", hex: "#101010" }],
      },
    ]);
    expect(result.color_replacement).not.toHaveProperty(
      "replacement_regions_truncated",
    );
  });

  it("keeps spatial edit count separate while merging true global remaps", () => {
    const storedGlobal = makeReplacementRegion(0);
    const state = makeState({
      replacement_regions: [storedGlobal],
      colorRemapMap: { aabbcc: "ddeeff" },
      palette: [
        {
          quantized_hex: "112233",
          matched_hex: "aabbcc",
          pixel_count: 42,
          percentage: 1,
        },
      ],
      regionReplacementCount: 4,
    });

    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 8192,
    }) as AdvancedParamsFull;

    expect(result.color_replacement.spatial_edit_count).toBe(4);
    expect(result.color_replacement.replacement_regions).toEqual([
      storedGlobal,
      {
        quantized_hex: "#112233",
        matched_hex: "#aabbcc",
        replacement_hex: "#ddeeff",
      },
    ]);
  });

  it("deduplicates normalized global sources and lets the live remap win", () => {
    const untouched = makeReplacementRegion(8);
    const state = makeState({
      replacement_regions: [
        {
          quantized_hex: "#111111",
          matched_hex: "#AaBbCc",
          replacement_hex: "#000000",
        },
        {
          quantized_hex: "#222222",
          matched_hex: "aabbcc",
          replacement_hex: "#333333",
        },
        untouched,
      ],
      colorRemapMap: { aabbcc: "ddeeff" },
      palette: [
        {
          quantized_hex: "445566",
          matched_hex: "aabbcc",
          pixel_count: 42,
          percentage: 1,
        },
      ],
    });

    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 8192,
    }) as AdvancedParamsFull;

    expect(result.color_replacement.replacement_regions).toEqual([
      {
        quantized_hex: "#445566",
        matched_hex: "#aabbcc",
        replacement_hex: "#ddeeff",
      },
      untouched,
    ]);
    expect(result.color_replacement).not.toHaveProperty(
      "replacement_regions_truncated",
    );
  });

  it("normalizes an invalid negative spatial edit count without inventing a global mapping", () => {
    const state = makeState({
      regionReplacementCount: -3,
      replacement_regions: [],
      colorRemapMap: {},
    });

    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 8192,
    }) as AdvancedParamsFull;

    expect(result.color_replacement.spatial_edit_count).toBe(0);
    expect(result.color_replacement.replacement_regions).toBeNull();
  });

  it("nulls detail fields when toggles are off", () => {
    const result = buildAdvancedParams(makeState(), "converter", {
      maxBytes: 8192,
    }) as AdvancedParamsFull;

    expect(result.relief).toEqual({
      enable_relief: false,
      color_height_map: null,
      heightmap_max_height: null,
      autoHeightMode: null,
      heightmapFile: null,
      hasHeightmapThumbnail: false,
    });
    expect(result.outline).toEqual({
      enable_outline: false,
      outline_width: null,
    });
    expect(result.cloisonne).toEqual({
      enable_cloisonne: false,
      wire_width_mm: null,
      wire_height_mm: null,
    });
    expect(result.coating).toEqual({
      enable_coating: false,
      coating_height_mm: null,
    });
    expect(result.loop).toEqual({
      add_loop: false,
      loop_width: null,
      loop_length: null,
      loop_hole: null,
      loop_angle: null,
      loop_offset_x: null,
      loop_offset_y: null,
      loop_position_preset: null,
    });
    expect(result.fridge_magnet).toEqual({
      enable_fridge_magnet: false,
      selectedFridgeMagnetId: null,
      fridge_magnets: null,
    });
    expect(result.puzzle.puzzleEnabled).toBe(false);
    expect(result.puzzle.puzzleStyle).toBeNull();
    expect(result.puzzle.minNeckWidthMm).toBeNull();
    expect(result.large_format).toEqual({
      largeFormatEnabled: false,
      tileWidthMm: null,
      tileHeightMm: null,
    });
  });
});

// ---------------------------------------------------------------------------
// Length-cap truncation
// ---------------------------------------------------------------------------

describe("buildAdvancedParams — length cap truncation", () => {
  it("caps color_height_map at 64 entries and sets color_height_map_truncated", () => {
    const state = makeState({
      enable_relief: true,
      color_height_map: makeColorHeightMap(100),
    });
    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    }) as AdvancedParamsFull;

    expect(result.relief.color_height_map).not.toBeNull();
    expect(Object.keys(result.relief.color_height_map!)).toHaveLength(64);
    expect(result.relief.color_height_map_truncated).toBe(true);

    // Preserves insertion order (first 64 keys of the original).
    const originalKeys = Object.keys(makeColorHeightMap(100));
    expect(Object.keys(result.relief.color_height_map!)).toEqual(
      originalKeys.slice(0, 64),
    );
  });

  it("caps fridge_magnets at 20 items and sets fridge_magnets_truncated", () => {
    const state = makeState({
      enable_fridge_magnet: true,
      fridge_magnets: Array.from({ length: 25 }, (_, i) => makeFridgeMagnet(i)),
    });
    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    }) as AdvancedParamsFull;

    expect(result.fridge_magnet.fridge_magnets).not.toBeNull();
    expect(result.fridge_magnet.fridge_magnets).toHaveLength(20);
    expect(result.fridge_magnet.fridge_magnets_truncated).toBe(true);

    // First 20 items in insertion order.
    const ids = result.fridge_magnet.fridge_magnets!.map((m) => m.id);
    expect(ids).toEqual(
      Array.from({ length: 20 }, (_, i) => `fm-${i}`),
    );
  });

  it("caps replacement_regions at 32 items and sets replacement_regions_truncated", () => {
    const state = makeState({
      replacement_regions: Array.from({ length: 50 }, (_, i) =>
        makeReplacementRegion(i),
      ),
    });
    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    }) as AdvancedParamsFull;

    expect(result.color_replacement.replacement_regions).not.toBeNull();
    expect(result.color_replacement.replacement_regions).toHaveLength(32);
    expect(result.color_replacement.replacement_regions_truncated).toBe(true);
  });

  it("deduplicates before capping more than 32 unique global sources", () => {
    const stored = Array.from({ length: 31 }, (_, i) =>
      makeReplacementRegion(i),
    );
    const duplicateSource = stored[0].matched_hex;
    const state = makeState({
      replacement_regions: stored,
      colorRemapMap: {
        [duplicateSource]: "#fefefe",
        aa0001: "bb0001",
        aa0002: "bb0002",
      },
      palette: [
        {
          quantized_hex: "#010101",
          matched_hex: duplicateSource,
          pixel_count: 1,
          percentage: 1,
        },
        {
          quantized_hex: "aa0001",
          matched_hex: "aa0001",
          pixel_count: 1,
          percentage: 1,
        },
        {
          quantized_hex: "aa0002",
          matched_hex: "aa0002",
          pixel_count: 1,
          percentage: 1,
        },
      ],
      regionReplacementCount: 7,
    });

    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    }) as AdvancedParamsFull;
    const regions = result.color_replacement.replacement_regions!;
    const normalizedDuplicateSource = duplicateSource
      .replace(/^#/, "")
      .toLowerCase();

    expect(regions).toHaveLength(32);
    expect(
      regions.filter(
        (item) =>
          item.matched_hex.replace(/^#/, "").toLowerCase() ===
          normalizedDuplicateSource,
      ),
    ).toEqual([
      {
        quantized_hex: "#010101",
        matched_hex: duplicateSource,
        replacement_hex: "#fefefe",
      },
    ]);
    expect(regions.some((item) => item.matched_hex === "#aa0001")).toBe(true);
    expect(regions.some((item) => item.matched_hex === "#aa0002")).toBe(false);
    expect(result.color_replacement.replacement_regions_truncated).toBe(true);
    expect(result.color_replacement.spatial_edit_count).toBe(7);
  });

  it("caps free_color_set at 64 items and sets free_color_set_truncated", () => {
    const state = makeState({
      free_color_set: new Set(
        Array.from(
          { length: 80 },
          (_, i) => i.toString(16).padStart(6, "0"),
        ),
      ),
    });
    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    }) as AdvancedParamsFull;

    expect(result.color_replacement.free_color_set).not.toBeNull();
    expect(result.color_replacement.free_color_set).toHaveLength(64);
    expect(result.color_replacement.free_color_set![0]).toBe("#000000");
    expect(result.color_replacement.free_color_set_truncated).toBe(true);
  });

  it("caps recipe_overrides at 32 items and sets recipe_overrides_truncated", () => {
    const state = makeState({
      recipe_overrides: Array.from({ length: 40 }, (_, i) => ({
        region_id: `region-${i}`,
        recipe: [0, 1, 2, 4],
        layer_order: "Top2Bottom",
        virtual_materials: [{ name: `Virtual ${i}`, hex: "#101010" }],
      })),
    });
    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    }) as AdvancedParamsFull;

    expect(result.color_replacement.recipe_overrides).not.toBeNull();
    expect(result.color_replacement.recipe_overrides).toHaveLength(32);
    expect(result.color_replacement.recipe_overrides![0]).toEqual({
      region_id: "region-0",
      recipe: [0, 1, 2, 4],
      layer_order: "Top2Bottom",
      virtual_materials: [{ name: "Virtual 0", hex: "#101010" }],
    });
    expect(result.color_replacement.recipe_overrides_truncated).toBe(true);
  });

  it("does not set truncation flags when collections are at or under the caps", () => {
    const state = makeState({
      enable_relief: true,
      color_height_map: makeColorHeightMap(64),
      enable_fridge_magnet: true,
      fridge_magnets: Array.from({ length: 20 }, (_, i) => makeFridgeMagnet(i)),
      replacement_regions: Array.from({ length: 32 }, (_, i) =>
        makeReplacementRegion(i),
      ),
      free_color_set: new Set(
        Array.from(
          { length: 64 },
          (_, i) => i.toString(16).padStart(6, "0"),
        ),
      ),
      recipe_overrides: Array.from({ length: 32 }, (_, i) => ({
        region_id: `region-${i}`,
        recipe: [0, 1, 2],
        layer_order: "Top2Bottom",
      })),
    });
    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    }) as AdvancedParamsFull;

    expect(result.relief).not.toHaveProperty("color_height_map_truncated");
    expect(result.fridge_magnet).not.toHaveProperty("fridge_magnets_truncated");
    expect(result.color_replacement).not.toHaveProperty(
      "replacement_regions_truncated",
    );
    expect(result.color_replacement).not.toHaveProperty(
      "free_color_set_truncated",
    );
    expect(result.color_replacement).not.toHaveProperty(
      "recipe_overrides_truncated",
    );
  });
});

// ---------------------------------------------------------------------------
// Heightmap file + thumbnail
// ---------------------------------------------------------------------------

describe("buildAdvancedParams — heightmap file and thumbnail", () => {
  it("converts heightmapFile to FileMetadata {name, size, type}", () => {
    const file = new File([new Uint8Array(4096)], "relief.png", {
      type: "image/png",
    });
    const state = makeState({
      enable_relief: true,
      heightmapFile: file,
      heightmapThumbnailUrl: "/static/thumb.png",
    });

    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 8192,
    }) as AdvancedParamsFull;

    expect(result.relief.heightmapFile).toEqual({
      name: "relief.png",
      size: 4096,
      type: "image/png",
    });

    // Explicit guard: no Blob / File reference should survive the serialization.
    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain("data:");
  });

  it("sets hasHeightmapThumbnail = true when heightmapThumbnailUrl is non-null, regardless of enable_relief", () => {
    // Enabled relief + thumbnail → true
    const enabled = buildAdvancedParams(
      makeState({
        enable_relief: true,
        heightmapThumbnailUrl: "/static/thumb.png",
      }),
      "converter",
      { maxBytes: 8192 },
    ) as AdvancedParamsFull;
    expect(enabled.relief.hasHeightmapThumbnail).toBe(true);

    // Disabled relief + thumbnail present → still reports true (the thumbnail is a fact,
    // independent of whether relief is currently engaged).
    const disabled = buildAdvancedParams(
      makeState({
        enable_relief: false,
        heightmapThumbnailUrl: "/static/thumb.png",
      }),
      "converter",
      { maxBytes: 8192 },
    ) as AdvancedParamsFull;
    expect(disabled.relief.hasHeightmapThumbnail).toBe(true);

    // Null thumbnail → false
    const noThumb = buildAdvancedParams(
      makeState({ heightmapThumbnailUrl: null }),
      "converter",
      { maxBytes: 8192 },
    ) as AdvancedParamsFull;
    expect(noThumb.relief.hasHeightmapThumbnail).toBe(false);
  });

  it("nulls heightmapFile when enable_relief is false even if a file is attached", () => {
    const state = makeState({
      enable_relief: false,
      heightmapFile: new File([new Uint8Array(10)], "x.png", {
        type: "image/png",
      }),
    });
    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 8192,
    }) as AdvancedParamsFull;
    expect(result.relief.heightmapFile).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Tiered size trimming
// ---------------------------------------------------------------------------

describe("buildAdvancedParams — tiered size trimming", () => {
  it("does not mark _size_trimmed when the full object fits within maxBytes", () => {
    const state = makeState();
    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 8192,
    }) as AdvancedParamsFull;
    expect(result).not.toHaveProperty("_size_trimmed");
    expect(result).not.toHaveProperty("_dropped_tiers");
  });

  it("fires tiers 1 → 2 → 3 → 4 in order as maxBytes decreases", () => {
    const state = makeHeavyState();
    const full = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    }) as AdvancedParamsFull;

    // Simulate what the builder's candidate objects look like after each
    // tier, including the `_size_trimmed` / `_dropped_tiers` bookkeeping
    // flags. These are the exact byte budgets below which each tier must
    // fire, so using them as `maxBytes` gives a deterministic selection.
    // 模拟构建器每一层裁剪后的候选对象（含标记字段），以其精确字节数作为
    // 预算，确保每层触发是确定性的、不依赖手工估算的 flag 开销。
    const candidateBytes = (tiers: number[]): number => {
      const obj = applyTiersInOrder(full, tiers) as AdvancedParamsFull;
      obj._size_trimmed = true;
      obj._dropped_tiers = tiers;
      return byteLen(obj);
    };

    const r1Bytes = candidateBytes([1]);
    const r2Bytes = candidateBytes([1, 2]);
    const r3Bytes = candidateBytes([1, 2, 3]);
    const r4Bytes = candidateBytes([1, 2, 3, 4]);

    // Sanity: each tier must actually shrink the candidate by at least one
    // byte so the next tier is reachable. Tier 4 drops only a handful of
    // puzzle/large_format scalars, so expect a small but non-zero delta.
    expect(byteLen(full)).toBeGreaterThan(r1Bytes);
    expect(r1Bytes).toBeGreaterThan(r2Bytes);
    expect(r2Bytes).toBeGreaterThan(r3Bytes);
    expect(r3Bytes).toBeGreaterThan(r4Bytes);

    // Pick maxBytes = exact candidate size: the n-th candidate fits by `<=`,
    // the (n-1)-th does not. This selects tier n precisely.
    const r1 = buildAdvancedParams(state, "converter", {
      maxBytes: r1Bytes,
    }) as AdvancedParamsFull;
    const r2 = buildAdvancedParams(state, "converter", {
      maxBytes: r2Bytes,
    }) as AdvancedParamsFull;
    const r3 = buildAdvancedParams(state, "converter", {
      maxBytes: r3Bytes,
    }) as AdvancedParamsFull;
    const r4 = buildAdvancedParams(state, "converter", {
      maxBytes: r4Bytes,
    }) as AdvancedParamsFull;

    expect(r1._size_trimmed).toBe(true);
    expect(r1._dropped_tiers).toEqual([1]);
    expect(byteLen(r1)).toBeLessThanOrEqual(r1Bytes);

    expect(r2._dropped_tiers).toEqual([1, 2]);
    expect(byteLen(r2)).toBeLessThanOrEqual(r2Bytes);

    expect(r3._dropped_tiers).toEqual([1, 2, 3]);
    expect(r3.color_replacement.spatial_edit_count).toBe(9);
    expect(byteLen(r3)).toBeLessThanOrEqual(r3Bytes);

    expect(r4._dropped_tiers).toEqual([1, 2, 3, 4]);
    expect(byteLen(r4)).toBeLessThanOrEqual(r4Bytes);
  });

  it("returns AdvancedParamsSizeTrimmed fallback when every tier still overflows", () => {
    const state = makeHeavyState();

    // 200 bytes is far below the fully-stripped base object yet generous
    // enough to hold the ~60-byte fallback. Guarantees tier-4 + flags still
    // overflow and the fallback path executes.
    const result = buildAdvancedParams(state, "converter", {
      maxBytes: 200,
    }) as AdvancedParamsSizeTrimmed;

    expect(result).toEqual({
      _size_trimmed: true,
      _original_byte_length: expect.any(Number),
    });

    // Pre-trim length must be the untrimmed full object's UTF-8 byte count.
    const full = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    });
    expect(result._original_byte_length).toBe(byteLen(full));

    // Fallback may exceed the tiny maxBytes (the minimal shape is ~80 bytes
    // and is the lowest the builder will ever emit). That is acceptable
    // because the fallback is the defined "cannot fit" state.
    // No _dropped_tiers on the fallback shape.
    expect(result).not.toHaveProperty("_dropped_tiers");
  });
});

// ---------------------------------------------------------------------------
// Determinism
// ---------------------------------------------------------------------------

describe("buildAdvancedParams — determinism", () => {
  it("produces byte-identical JSON for identical (state, activeTab, maxBytes) inputs", () => {
    const state = makeHeavyState();

    const a = buildAdvancedParams(state, "converter", { maxBytes: 8192 });
    const b = buildAdvancedParams(state, "converter", { maxBytes: 8192 });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));

    // Even through trimming, the builder must still be deterministic.
    const tA = buildAdvancedParams(state, "converter", { maxBytes: 4096 });
    const tB = buildAdvancedParams(state, "converter", { maxBytes: 4096 });
    expect(JSON.stringify(tA)).toBe(JSON.stringify(tB));
  });
});

// ---------------------------------------------------------------------------
// maxBytes 4096 vs 8192
// ---------------------------------------------------------------------------

describe("buildAdvancedParams — maxBytes 4096 vs 8192", () => {
  it("produces identical output for both budgets when the state fits in 4096 bytes", () => {
    // Light state — default + nothing heavy. Serialized size is well under 4096.
    const state = makeState();

    const at4k = buildAdvancedParams(state, "converter", { maxBytes: 4096 });
    const at8k = buildAdvancedParams(state, "converter", { maxBytes: 8192 });

    expect(byteLen(at4k)).toBeLessThanOrEqual(4096);
    expect(JSON.stringify(at4k)).toBe(JSON.stringify(at8k));
    // Neither budget needed trimming.
    expect(at4k).not.toHaveProperty("_size_trimmed");
    expect(at8k).not.toHaveProperty("_size_trimmed");
  });

  it("diverges only when state exceeds 4096 bytes but fits within 8192", () => {
    // Build a state whose normalized serialized size sits in the 4k-8k window.
    // Heavy fridge magnets + moderate replacement regions + modest height map
    // yields roughly 5-6 KB.
    const state = makeState({
      enable_fridge_magnet: true,
      fridge_magnets: Array.from({ length: 20 }, (_, i) => makeFridgeMagnet(i)),
      selectedFridgeMagnetId: "fm-0",
      enable_relief: true,
      color_height_map: makeColorHeightMap(32),
      replacement_regions: Array.from({ length: 16 }, (_, i) =>
        makeReplacementRegion(i),
      ),
    });

    const full = buildAdvancedParams(state, "converter", {
      maxBytes: 1_000_000,
    }) as AdvancedParamsFull;
    const fullSize = byteLen(full);

    // Precondition check — if this fires, adjust the moderate state above.
    expect(fullSize).toBeGreaterThan(4096);
    expect(fullSize).toBeLessThanOrEqual(8192);

    const at4k = buildAdvancedParams(state, "converter", {
      maxBytes: 4096,
    }) as AdvancedParams;
    const at8k = buildAdvancedParams(state, "converter", {
      maxBytes: 8192,
    }) as AdvancedParamsFull;

    // 8192 fits the full object → no trim flags.
    expect(at8k).not.toHaveProperty("_size_trimmed");
    expect(byteLen(at8k)).toBeLessThanOrEqual(8192);

    // 4096 trims → differs from the 8192 output.
    expect((at4k as Partial<AdvancedParamsFull>)._size_trimmed).toBe(true);
    expect(byteLen(at4k)).toBeLessThanOrEqual(4096);
    expect(JSON.stringify(at4k)).not.toBe(JSON.stringify(at8k));
  });
});

// ===========================================================================
// Property-based tests (fast-check)
// ===========================================================================
//
// Validates: Requirements 2.7, 9.1-9.5, 1.15-1.18
//
// The four properties below correspond to P1/P4/P6/P7 from the design doc.
// They complement the example-based tests above by exercising random
// ConverterState snapshots across the realistic maxBytes envelope (1024–65536
// bytes, bracketing the two production values 4096 / 8192).
//
// maxBytes lower bound (1024) — chosen so the AdvancedParamsSizeTrimmed
// fallback (~80 bytes) always fits within the budget. Values below ~200
// would break P4 because the fallback itself would exceed the budget by
// design. The builder is not required to produce output smaller than its
// own fallback shape.
// ===========================================================================

import fc from "fast-check";

/**
 * Recursively walk a value and collect any File / Blob instances that
 * leaked through. The builder must convert every File into `FileMetadata`
 * before returning, so the result must always be empty.
 * 递归遍历值，收集任何未被转换的 File/Blob 实例。
 */
function collectFileOrBlobInstances(value: unknown): unknown[] {
  const leaks: unknown[] = [];
  const visited = new WeakSet<object>();

  const walk = (node: unknown): void => {
    if (node === null || node === undefined) return;
    if (typeof node !== "object") return;
    // Check before descending: File extends Blob, so `instanceof Blob`
    // catches both. In jsdom, File is also a valid check.
    if (typeof File !== "undefined" && node instanceof File) {
      leaks.push(node);
      return;
    }
    if (typeof Blob !== "undefined" && node instanceof Blob) {
      leaks.push(node);
      return;
    }
    // Guard against cycles (defensive — `AdvancedParams` is a tree).
    if (visited.has(node as object)) return;
    visited.add(node as object);

    if (Array.isArray(node)) {
      for (const item of node) walk(item);
      return;
    }
    for (const key of Object.keys(node as Record<string, unknown>)) {
      walk((node as Record<string, unknown>)[key]);
    }
  };

  walk(value);
  return leaks;
}

// ---------------------------------------------------------------------------
// Arbitraries
// ---------------------------------------------------------------------------

/** Hex color like "#rrggbb". / 形如 #rrggbb 的十六进制颜色。 */
const arbHexColor = fc
  .tuple(
    fc.integer({ min: 0, max: 255 }),
    fc.integer({ min: 0, max: 255 }),
    fc.integer({ min: 0, max: 255 }),
  )
  .map(
    ([r, g, b]) =>
      `#${r.toString(16).padStart(2, "0")}${g
        .toString(16)
        .padStart(2, "0")}${b.toString(16).padStart(2, "0")}`,
  );

/** Finite, non-NaN number useful as a dimension / threshold value. */
const arbFiniteNumber = fc.double({
  min: -1000,
  max: 1000,
  noNaN: true,
  noDefaultInfinity: true,
});

const arbPositiveFinite = fc.double({
  min: 0.01,
  max: 500,
  noNaN: true,
  noDefaultInfinity: true,
});

/**
 * Arbitrary File. Real File instances (not mocks) so the builder's
 * `serializeFileMetadata` sees the actual `name` / `size` / `type` shape.
 * 使用真实 File 实例，确保构建器按真实 API 读取元数据。
 */
const arbFile: fc.Arbitrary<File> = fc
  .record({
    bytes: fc.uint8Array({ minLength: 0, maxLength: 64 }),
    name: fc
      .stringMatching(/^[a-z0-9_-]{1,12}\.(png|jpg|webp)$/)
      .filter((s) => s.length > 0),
    type: fc.constantFrom("image/png", "image/jpeg", "image/webp"),
  })
  .map(({ bytes, name, type }) => new File([bytes], name, { type }));

/** Scalar-only fridge magnet item matching the store shape. */
const arbFridgeMagnetItem: fc.Arbitrary<FridgeMagnetItem> = fc.record({
  id: fc.stringMatching(/^fm-[a-z0-9]{1,8}$/),
  shape: fc.constantFrom<"round" | "rect">("round", "rect"),
  preset_key: fc.stringMatching(/^preset-[a-z0-9]{1,8}$/),
  diameter_mm: fc.option(arbPositiveFinite, { nil: null }),
  width_mm: fc.option(arbPositiveFinite, { nil: null }),
  height_mm: fc.option(arbPositiveFinite, { nil: null }),
  thickness_mm: arbPositiveFinite,
  center_x_mm: arbFiniteNumber,
  center_y_mm: arbFiniteNumber,
});

/** Scalar-only color-replacement item matching the API shape. */
const arbReplacementRegion: fc.Arbitrary<ColorReplacementItem> = fc.record({
  quantized_hex: arbHexColor,
  matched_hex: arbHexColor,
  replacement_hex: arbHexColor,
});

/**
 * ConverterState arbitrary built by overriding DEFAULT_STATE with a
 * random selection of scalar / File / array fields the builder reads.
 * Only fields the builder actually touches are randomised; everything
 * else stays at its default, which keeps the arbitrary small and the
 * output deterministic.
 * 仅覆盖构建器会读取的字段；其他字段保持默认值，避免影响确定性与判定。
 */
const arbConverterState: fc.Arbitrary<ConverterState> = fc
  .record({
    // Dimensions group.
    target_width_mm: arbPositiveFinite,
    target_height_mm: arbPositiveFinite,
    spacer_thick: arbPositiveFinite,
    base_spacer_thick: arbPositiveFinite,
    backing_infill_density_percent: fc.integer({ min: 5, max: 100 }),

    // Generation group (scalars + booleans).
    color_layers: fc.option(fc.integer({ min: 1, max: 64 }), { nil: null }),
    layer_height_mm: fc.option(arbPositiveFinite, { nil: null }),
    model_enable: fc.boolean(),
    model_only: fc.boolean(),
    model_threshold: fc.option(arbFiniteNumber, { nil: null }),
    model_margin: fc.option(arbFiniteNumber, { nil: null }),
    quantize_colors: fc.integer({ min: 1, max: 256 }),
    quantize_colors_unlocked: fc.boolean(),
    enable_cleanup: fc.boolean(),
    hue_enable: fc.boolean(),
    chroma_gate: fc.integer({ min: 0, max: 100 }),
    use_lut_constrained: fc.boolean(),
    auto_dynamic_range: fc.boolean(),
    separate_backing: fc.boolean(),

    // Toggle groups (each toggle drives the P6 null-consistency property).
    enable_relief: fc.boolean(),
    color_height_map: fc.dictionary(arbHexColor, arbPositiveFinite, {
      maxKeys: 80,
    }),
    heightmap_max_height: arbPositiveFinite,
    autoHeightMode: fc.constantFrom<
      "darker-higher" | "lighter-higher" | "use-heightmap"
    >("darker-higher", "lighter-higher", "use-heightmap"),
    heightmapFile: fc.option(arbFile, { nil: null }),
    heightmapThumbnailUrl: fc.option(fc.stringMatching(/^\/[a-z0-9]{1,16}$/), {
      nil: null,
    }),

    enable_outline: fc.boolean(),
    outline_width: arbPositiveFinite,

    enable_cloisonne: fc.boolean(),
    wire_width_mm: arbPositiveFinite,
    wire_height_mm: arbPositiveFinite,

    enable_coating: fc.boolean(),
    coating_height_mm: arbPositiveFinite,

    add_loop: fc.boolean(),
    loop_width: arbPositiveFinite,
    loop_length: arbPositiveFinite,
    loop_hole: arbPositiveFinite,
    loop_angle: fc.integer({ min: -180, max: 180 }),
    loop_offset_x: arbFiniteNumber,
    loop_offset_y: arbFiniteNumber,
    loop_position_preset: fc.constantFrom(
      "top-center",
      "top-left",
      "top-right",
      "center",
      "bottom-center",
    ),

    enable_fridge_magnet: fc.boolean(),
    fridge_magnets: fc.array(arbFridgeMagnetItem, {
      minLength: 0,
      maxLength: 30,
    }),
    selectedFridgeMagnetId: fc.option(
      fc.stringMatching(/^fm-[a-z0-9]{1,8}$/),
      { nil: null },
    ),

    puzzleEnabled: fc.boolean(),
    pieceWidthMm: arbPositiveFinite,
    pieceHeightMm: arbPositiveFinite,
    puzzleRows: fc.integer({ min: 1, max: 40 }),
    puzzleCols: fc.integer({ min: 1, max: 40 }),
    targetPieceCount: fc.integer({ min: 1, max: 400 }),
    labelsEnabled: fc.boolean(),
    engraveBackLabels: fc.boolean(),
    irregularityStrength: arbPositiveFinite,
    minNeckWidthMm: arbPositiveFinite,

    largeFormatEnabled: fc.boolean(),
    tileWidthMm: arbPositiveFinite,
    tileHeightMm: arbPositiveFinite,

    replacement_regions: fc.array(arbReplacementRegion, {
      minLength: 0,
      maxLength: 50,
    }),
  })
  .map((overrides) => makeState(overrides as Partial<ConverterState>));

/** Realistic maxBytes envelope: the two production values plus a broader
 * sweep for determinism coverage. Lower bound 1024 is safely above the
 * AdvancedParamsSizeTrimmed fallback size (~80 bytes) so P4 remains a
 * meaningful contract at every drawn value.
 */
const arbMaxBytes = fc.oneof(
  fc.constantFrom(4096, 8192),
  fc.integer({ min: 1024, max: 65536 }),
);

const arbActiveTab = fc.constantFrom("converter", "extractor", "settings", "");

// ---------------------------------------------------------------------------
// P1: Shared builder determinism
// ---------------------------------------------------------------------------

describe("Property P1: shared builder determinism (Validates: Requirements 2.7)", () => {
  it("produces byte-identical JSON for identical (state, activeTab, maxBytes) inputs", () => {
    fc.assert(
      fc.property(
        arbConverterState,
        arbActiveTab,
        arbMaxBytes,
        (state, activeTab, maxBytes) => {
          const a = buildAdvancedParams(state, activeTab, { maxBytes });
          const b = buildAdvancedParams(state, activeTab, { maxBytes });
          expect(JSON.stringify(a)).toBe(JSON.stringify(b));
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ---------------------------------------------------------------------------
// P4: Size limit enforcement
// ---------------------------------------------------------------------------

describe("Property P4: size limit enforcement (Validates: Requirements 9.1-9.5)", () => {
  it("serialized length does not exceed maxBytes when the result is non-null", () => {
    // maxBytes is drawn from realistic values (4096 / 8192) + the
    // broader [1024, 65536] sweep. 1024 is comfortably above the
    // AdvancedParamsSizeTrimmed fallback (~80 bytes), so every non-null
    // result — full, tier-trimmed, or fallback — must respect the budget.
    fc.assert(
      fc.property(
        arbConverterState,
        fc.oneof(
          fc.constantFrom(4096, 8192),
          fc.integer({ min: 1024, max: 65536 }),
        ),
        (state, maxBytes) => {
          const result = buildAdvancedParams(state, "converter", {
            maxBytes,
          });
          if (result === null) return;
          expect(byteLen(result)).toBeLessThanOrEqual(maxBytes);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ---------------------------------------------------------------------------
// P6: Disabled toggle null consistency
// ---------------------------------------------------------------------------

describe("Property P6: disabled toggle null consistency (Validates: Requirements 1.15-1.18)", () => {
  it("every dependent detail field in a disabled group is null", () => {
    fc.assert(
      fc.property(arbConverterState, arbMaxBytes, (state, maxBytes) => {
        const result = buildAdvancedParams(state, "converter", {
          maxBytes,
        });
        if (result === null) return;
        // Fallback has no group sub-objects to check — P6 is vacuous here.
        if ((result as AdvancedParamsFull).dimensions === undefined) return;
        const full = result as AdvancedParamsFull;

        // Each entry lists the detail fields that MUST be null when the
        // named toggle is false. `*_truncated` flags are optional presence
        // markers only surfaced when trimming fires; they are never
        // "detail fields" and stay outside this check.
        if (full.relief.enable_relief === false) {
          expect(full.relief.color_height_map).toBeNull();
          expect(full.relief.heightmap_max_height).toBeNull();
          expect(full.relief.autoHeightMode).toBeNull();
          expect(full.relief.heightmapFile).toBeNull();
        }
        if (full.outline.enable_outline === false) {
          expect(full.outline.outline_width).toBeNull();
        }
        if (full.cloisonne.enable_cloisonne === false) {
          expect(full.cloisonne.wire_width_mm).toBeNull();
          expect(full.cloisonne.wire_height_mm).toBeNull();
        }
        if (full.coating.enable_coating === false) {
          expect(full.coating.coating_height_mm).toBeNull();
        }
        if (full.loop.add_loop === false) {
          expect(full.loop.loop_width).toBeNull();
          expect(full.loop.loop_length).toBeNull();
          expect(full.loop.loop_hole).toBeNull();
          expect(full.loop.loop_angle).toBeNull();
          expect(full.loop.loop_offset_x).toBeNull();
          expect(full.loop.loop_offset_y).toBeNull();
          expect(full.loop.loop_position_preset).toBeNull();
        }
        if (full.fridge_magnet.enable_fridge_magnet === false) {
          expect(full.fridge_magnet.fridge_magnets).toBeNull();
          expect(full.fridge_magnet.selectedFridgeMagnetId).toBeNull();
        }
        if (full.puzzle.puzzleEnabled === false) {
          expect(full.puzzle.puzzleStyle).toBeNull();
          expect(full.puzzle.puzzleSizingMode).toBeNull();
          expect(full.puzzle.pieceWidthMm).toBeNull();
          expect(full.puzzle.pieceHeightMm).toBeNull();
          expect(full.puzzle.puzzleRows).toBeNull();
          expect(full.puzzle.puzzleCols).toBeNull();
          expect(full.puzzle.targetPieceCount).toBeNull();
          expect(full.puzzle.connectorStyle).toBeNull();
          expect(full.puzzle.labelsEnabled).toBeNull();
          expect(full.puzzle.engraveBackLabels).toBeNull();
          expect(full.puzzle.irregularityStrength).toBeNull();
          expect(full.puzzle.minNeckWidthMm).toBeNull();
        }
        if (full.large_format.largeFormatEnabled === false) {
          expect(full.large_format.tileWidthMm).toBeNull();
          expect(full.large_format.tileHeightMm).toBeNull();
        }
      }),
      { numRuns: 100 },
    );
  });
});

// ---------------------------------------------------------------------------
// P7: File safety
// ---------------------------------------------------------------------------

describe("Property P7: file safety (Validates: Requirements 1.15)", () => {
  it("no File / Blob instance survives in the built object", () => {
    fc.assert(
      fc.property(
        arbConverterState,
        arbActiveTab,
        arbMaxBytes,
        (state, activeTab, maxBytes) => {
          const result = buildAdvancedParams(state, activeTab, { maxBytes });
          expect(collectFileOrBlobInstances(result)).toEqual([]);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("no string in the serialized JSON starts with 'data:'", () => {
    fc.assert(
      fc.property(
        arbConverterState,
        arbActiveTab,
        arbMaxBytes,
        (state, activeTab, maxBytes) => {
          const result = buildAdvancedParams(state, activeTab, { maxBytes });
          if (result === null) return;
          // Serialized scan — catches any data URL that might have slipped
          // into a string-typed field (e.g., future thumbnail / preview).
          // 对序列化字符串扫描 "data:"，兜住未来新增字符串字段引入的风险。
          const serialized = JSON.stringify(result);
          expect(serialized.includes("data:")).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });
});
