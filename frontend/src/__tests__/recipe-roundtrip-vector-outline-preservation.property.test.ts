/**
 * Recipe round-trip preservation property test for the vector + outline=false branch.
 * Vector + 关闭描边 路径下的配方往返保留属性测试。
 *
 * Spec: SVG vector outline support preservation notes
 * (`progress/svg-vector-outline-preservation-baseline.md`).
 * Task 2.4 — Frontend store 持久化 + recipe round-trip preservation.
 *
 * Property 2 (Preservation, Requirements 3.2): for any input where the bug
 * condition does NOT hold — here narrowed to `modeling_mode = vector AND
 * enable_outline = false` — exporting the converter recipe and importing it
 * back must produce a byte-equal canonical serialization, and the round-trip
 * must preserve all parameter values that survive the existing legacy
 * round-trip contract.
 *
 * The test mirrors the framework of `recipe-roundtrip.property.test.ts`
 * (fast-check + DEFAULT_STATE seed + exportConverterRecipe / restoreConverterRecipe)
 * and adds a vector + enable_outline=false branch assertion. It MUST PASS on
 * current main (preservation baseline).
 */

import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { exportConverterRecipe } from "../recipe/exportRecipe";
import { restoreConverterRecipe } from "../recipe/importRecipe";
import { resolveFridgeMagnetSpacerThick } from "../constants/fridgeMagnets";
import { DEFAULT_STATE } from "../stores/converter";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { ConverterState } from "../stores/converter/store";
import type { LuminaRecipe } from "../recipe/types";
import type { LutInfo } from "../api/types";
import { ColorMode, ModelingMode } from "../api/types";

// ========== Stable canonical serialization ==========

/**
 * Recursively sort object keys so JSON.stringify produces deterministic output.
 * Arrays preserve their original ordering. Required for byte-equal comparison
 * between two semantically-equivalent recipes whose object key ordering may
 * differ between export and re-export paths.
 *
 * 递归地按 key 排序对象，让 JSON.stringify 输出稳定，便于"字节级一致"对比。
 * 数组保持原顺序。
 */
function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const sortedKeys = Object.keys(obj).sort();
    const out: Record<string, unknown> = {};
    for (const k of sortedKeys) {
      out[k] = canonicalize(obj[k]);
    }
    return out;
  }
  return value;
}

function canonicalSerialize(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

// ========== Local LUT registry for round-trip ==========

const LOCAL_LUTS: LutInfo[] = [
  { name: "LUT-A", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/a" },
  { name: "LUT-B", color_mode: ColorMode.EIGHT_COLOR, path: "/b" },
  { name: "LUT-C", color_mode: ColorMode.BW, path: "/c" },
];
const LUT_PATH_BY_NAME: Record<string, string> = {
  "LUT-A": "/a",
  "LUT-B": "/b",
  "LUT-C": "/c",
};

// ========== Recipe wrapper helper ==========

function wrapRecipe(converterRecipe: ReturnType<typeof exportConverterRecipe>): LuminaRecipe {
  return {
    format: "lumina-recipe",
    schema_version: 1,
    app_version: "0.0.0",
    created_at: "2026-05-27T00:00:00.000Z",
    source: "converter",
    cover: { width: 1, height: 1, mime_type: "image/png" },
    asset: {
      primary: {
        filename: "vector-anchor.svg",
        mime_type: "image/svg+xml",
        byte_size: 4,
        encoding: "base64",
        payload_b64: "dGVzdA==",
      },
    },
    recipe: { converter: converterRecipe },
    compat: { min_schema_version: 1 },
    warnings: [],
  };
}

// ========== State builder shared by anchor + property runs ==========

interface StateOverrides {
  lut_name: "LUT-A" | "LUT-B" | "LUT-C";
  color_mode: ColorMode;
  outline_width: number;
  target_width_mm: number;
  target_height_mm: number;
  spacer_thick: number;
  quantize_colors: number;
  enable_cleanup: boolean;
  hue_enable: boolean;
  chroma_gate: number;
  add_loop: boolean;
  loop_angle: number;
  enable_relief: boolean;
  enable_cloisonne: boolean;
  enable_coating: boolean;
}

/**
 * Build a converter state snapshot pinned to vector + enable_outline=false.
 * 构造一个 vector + enable_outline=false 的 converter 状态快照。
 */
function buildVectorNoOutlineState(overrides: StateOverrides): ConverterState {
  return {
    ...DEFAULT_STATE,
    source_version: "legacy",
    modeling_mode: ModelingMode.VECTOR,
    enable_outline: false,
    outline_width: overrides.outline_width,
    lut_name: overrides.lut_name,
    color_mode: overrides.color_mode,
    target_width_mm: overrides.target_width_mm,
    target_height_mm: overrides.target_height_mm,
    spacer_thick: resolveFridgeMagnetSpacerThick(
      overrides.spacer_thick,
      false /* enable_fridge_magnet */,
      [] /* fridge_magnets */,
    ),
    base_spacer_thick: overrides.spacer_thick,
    quantize_colors: overrides.quantize_colors,
    enable_cleanup: overrides.enable_cleanup,
    hue_enable: overrides.hue_enable,
    chroma_gate: overrides.chroma_gate,
    add_loop: overrides.add_loop,
    loop_angle: overrides.loop_angle,
    enable_relief: overrides.enable_relief,
    enable_cloisonne: overrides.enable_cloisonne,
    enable_coating: overrides.enable_coating,
  } as ConverterState;
}

// ========== Anchor (deterministic minimal repro) ==========

/**
 * Canonical bug-adjacent configuration for the LUM-20260527-001 ticket:
 * vector + enable_outline=false + outline_width=2.0 + 8-Color Max.
 * Locks in that the round-trip is byte-stable for this exact preset.
 */
const ANCHOR_OVERRIDES: StateOverrides = {
  lut_name: "LUT-B",
  color_mode: ColorMode.EIGHT_COLOR,
  outline_width: 2.0,
  target_width_mm: 150,
  target_height_mm: 172,
  spacer_thick: 1.2,
  quantize_colors: 190,
  enable_cleanup: true,
  hue_enable: false,
  chroma_gate: 15,
  add_loop: false,
  loop_angle: 0,
  enable_relief: false,
  enable_cloisonne: false,
  enable_coating: false,
};

// ========== fast-check arbitrary ==========

const arbVectorNoOutlineOverrides: fc.Arbitrary<StateOverrides> = fc.record({
  lut_name: fc.constantFrom("LUT-A" as const, "LUT-B" as const, "LUT-C" as const),
  color_mode: fc.constantFrom(
    ColorMode.BW,
    ColorMode.FOUR_COLOR_RYBW,
    ColorMode.EIGHT_COLOR,
  ),
  // outline_width is irrelevant for behavior (enable_outline=false), but it
  // still flows through the recipe and must round-trip byte-equal.
  outline_width: fc.double({ min: 0.5, max: 10.0, noNaN: true }),
  target_width_mm: fc.integer({ min: 10, max: 400 }),
  target_height_mm: fc.integer({ min: 10, max: 400 }),
  spacer_thick: fc.double({ min: 0.2, max: 3.5, noNaN: true }),
  quantize_colors: fc.integer({ min: 2, max: 256 }),
  enable_cleanup: fc.boolean(),
  hue_enable: fc.boolean(),
  chroma_gate: fc.integer({ min: 0, max: 100 }),
  add_loop: fc.boolean(),
  loop_angle: fc.integer({ min: -180, max: 180 }),
  enable_relief: fc.boolean(),
  enable_cloisonne: fc.boolean(),
  enable_coating: fc.boolean(),
}).map((overrides) => ({
  ...overrides,
  color_mode: LOCAL_LUTS.find((lut) => lut.name === overrides.lut_name)!.color_mode,
}));

// ========== Round-trip evaluator ==========

/**
 * Run one full export → restore → re-export cycle and return both serialized
 * recipes for byte-equal comparison plus the restored state for field-level
 * assertions.
 */
function runRoundTrip(state: ConverterState) {
  const lutPath = LUT_PATH_BY_NAME[state.lut_name];
  const recipe1 = exportConverterRecipe(state, DEFAULT_SETTINGS, lutPath);
  const wrapped1 = wrapRecipe(recipe1);
  const { state: restored } = restoreConverterRecipe(
    wrapped1,
    LOCAL_LUTS,
  );

  // Merge restored partial state into DEFAULT_STATE so we can re-export.
  // restoreConverterRecipe returns Partial<ConverterState>; the export adapter
  // reads only the fields it cares about, so merging onto DEFAULT_STATE is safe.
  const merged: ConverterState = { ...DEFAULT_STATE, ...restored } as ConverterState;
  const recipe2 = exportConverterRecipe(merged, DEFAULT_SETTINGS, lutPath);

  return {
    recipe1Serialized: canonicalSerialize(recipe1),
    recipe2Serialized: canonicalSerialize(recipe2),
    restored,
    recipe1,
    recipe2,
  };
}

// ========== Tests ==========

describe("recipe round-trip preservation: vector + enable_outline=false", () => {
  it(
    "anchor: LUM-20260527-001 vector + outline=false + 8-Color Max round-trips byte-equal",
    () => {
      const state = buildVectorNoOutlineState(ANCHOR_OVERRIDES);
      const {
        recipe1Serialized,
        recipe2Serialized,
        restored,
        recipe1,
      } = runRoundTrip(state);

      // The anchor pin: outline disabled, vector mode, ticket-specific values.
      expect(recipe1.base.modeling_mode).toBe(ModelingMode.VECTOR);
      expect(recipe1.outline.enable_outline).toBe(false);
      expect(recipe1.outline.outline_width).toBe(2.0);
      expect(recipe1.base.color_mode).toBe(ColorMode.EIGHT_COLOR);
      expect(recipe1.base.quantize_colors).toBe(190);

      // Restored state preserves both vector mode and the disabled outline flag.
      expect(restored.modeling_mode).toBe(ModelingMode.VECTOR);
      expect(restored.enable_outline).toBe(false);
      expect(restored.outline_width).toBe(2.0);

      // Byte-equal canonical serialization on the second export.
      expect(recipe2Serialized).toBe(recipe1Serialized);
    },
  );

  it(
    "property: any vector + enable_outline=false snapshot round-trips byte-equal",
    () => {
      fc.assert(
        fc.property(arbVectorNoOutlineOverrides, (overrides) => {
          const state = buildVectorNoOutlineState(overrides);
          const {
            recipe1Serialized,
            recipe2Serialized,
            restored,
            recipe1,
          } = runRoundTrip(state);

          // Branch invariants: vector + outline-disabled must survive as-is.
          expect(recipe1.base.modeling_mode).toBe(ModelingMode.VECTOR);
          expect(recipe1.outline.enable_outline).toBe(false);
          expect(restored.modeling_mode).toBe(ModelingMode.VECTOR);
          expect(restored.enable_outline).toBe(false);

          // Round-trip must preserve outline_width verbatim even though the
          // outline is disabled (the recipe schema still carries the value).
          expect(restored.outline_width).toBe(overrides.outline_width);

          // Other selected fields must round-trip too.
          expect(restored.color_mode).toBe(overrides.color_mode);
          expect(restored.target_width_mm).toBe(overrides.target_width_mm);
          expect(restored.target_height_mm).toBe(overrides.target_height_mm);
          expect(restored.quantize_colors).toBe(overrides.quantize_colors);
          expect(restored.enable_cleanup).toBe(overrides.enable_cleanup);
          expect(restored.hue_enable).toBe(overrides.hue_enable);
          expect(restored.chroma_gate).toBe(overrides.chroma_gate);
          expect(restored.add_loop).toBe(overrides.add_loop);
          expect(restored.loop_angle).toBe(overrides.loop_angle);
          expect(restored.enable_relief).toBe(overrides.enable_relief);
          expect(restored.enable_cloisonne).toBe(overrides.enable_cloisonne);
          expect(restored.enable_coating).toBe(overrides.enable_coating);
          expect(restored.base_spacer_thick).toBe(overrides.spacer_thick);

          // Byte-equal canonical serialization: second export must match first.
          expect(recipe2Serialized).toBe(recipe1Serialized);
        }),
        { numRuns: 100 },
      );
    },
  );
});

// **Validates: Requirements 3.2**
