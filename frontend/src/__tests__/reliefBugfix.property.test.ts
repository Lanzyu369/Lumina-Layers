import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useConverterStore } from "../stores/converter";

// ========== Generators ==========

/** Generate a valid 6-character hex string (lowercase, no '#' prefix) */
const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

/** Generate a PaletteEntry with random hex colors and stats */
const paletteEntry = fc.record({
  quantized_hex: hexColor,
  matched_hex: hexColor,
  pixel_count: fc.integer({ min: 1, max: 10000 }),
  percentage: fc.float({
    min: Math.fround(0.01),
    max: Math.fround(100),
    noNaN: true,
  }),
});

/** Generate a non-empty palette with unique matched_hex values */
const uniquePalette = fc
  .array(paletteEntry, { minLength: 1, maxLength: 12 })
  .map((entries) => {
    const seen = new Set<string>();
    return entries.filter((e) => {
      if (seen.has(e.matched_hex)) return false;
      seen.add(e.matched_hex);
      return true;
    });
  })
  .filter((arr) => arr.length > 0);

// ========== Helpers ==========

function resetStore(overrides: Record<string, unknown> = {}): void {
  useConverterStore.setState({
    sessionId: null,
    enable_relief: false,
    enable_cloisonne: false,
    color_height_map: {},
    heightmap_max_height: 5.0,
    palette: [],
    isLoading: false,
    error: null,
    structure_mode: "Double-sided" as never,
    threemfDiskPath: null,
    downloadUrl: null,
    ...overrides,
  });
}

// ========== Tests ==========

describe("Feature: relief-mode-bugfix — Property 3: 浮雕开关正确更新状态", () => {
  beforeEach(() => {
    resetStore();
  });

  /**
   * Property 3: 浮雕开关正确更新状态
   * **Validates: Requirements 2.1, 2.2, 2.3**
   *
   * setEnableRelief should update enable_relief state and initialize
   * color_height_map with luminance-based heights when enabling.
   * This is a pure state update — no backend calls are triggered.
   */
  describe("setEnableRelief updates state correctly", () => {
    it("sets enable_relief to true and initializes color_height_map with varied heights", () => {
      fc.assert(
        fc.property(uniquePalette, (palette) => {
          resetStore({ palette });

          useConverterStore.getState().setEnableRelief(true);

          const state = useConverterStore.getState();
          expect(state.enable_relief).toBe(true);

          // color_height_map should have entries for all palette colors
          for (const entry of palette) {
            expect(state.color_height_map).toHaveProperty(entry.matched_hex);
          }

          // Heights should be within valid range
          for (const h of Object.values(state.color_height_map)) {
            expect(h).toBeGreaterThanOrEqual(0.08);
            expect(h).toBeLessThanOrEqual(state.heightmap_max_height);
          }
        }),
        { numRuns: 100 },
      );
    });

    it("sets enable_relief to false", () => {
      fc.assert(
        fc.property(uniquePalette, (palette) => {
          resetStore({ palette, enable_relief: true });

          useConverterStore.getState().setEnableRelief(false);

          expect(useConverterStore.getState().enable_relief).toBe(false);
        }),
        { numRuns: 100 },
      );
    });

    it("random boolean sequence: state always reflects last toggle", () => {
      fc.assert(
        fc.property(
          uniquePalette,
          fc.array(fc.boolean(), { minLength: 1, maxLength: 20 }),
          (palette, toggleSequence) => {
            resetStore({ palette });

            for (const enabled of toggleSequence) {
              useConverterStore.getState().setEnableRelief(enabled);
            }

            const lastValue = toggleSequence[toggleSequence.length - 1];
            expect(useConverterStore.getState().enable_relief).toBe(lastValue);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});

describe("Feature: relief-mode-bugfix — Property 4: 颜色高度修改正确更新状态", () => {
  beforeEach(() => {
    resetStore();
  });

  /**
   * Property 4: 颜色高度修改正确更新状态
   * **Validates: Requirements 3.1**
   *
   * updateColorHeight should update the specific color's height in
   * color_height_map without triggering any backend calls.
   */
  describe("updateColorHeight updates state correctly", () => {
    it("updates the height for the specified color", () => {
      fc.assert(
        fc.property(
          hexColor,
          fc.float({ min: Math.fround(0.1), max: Math.fround(50), noNaN: true }),
          (hex, height) => {
            resetStore();

            useConverterStore.getState().updateColorHeight(hex, height);

            expect(useConverterStore.getState().color_height_map[hex]).toBe(height);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("preserves other colors when updating one", () => {
      fc.assert(
        fc.property(
          hexColor,
          hexColor,
          fc.float({ min: Math.fround(0.1), max: Math.fround(50), noNaN: true }),
          fc.float({ min: Math.fround(0.1), max: Math.fround(50), noNaN: true }),
          (hex1, hex2, h1, h2) => {
            resetStore();

            useConverterStore.getState().updateColorHeight(hex1, h1);
            useConverterStore.getState().updateColorHeight(hex2, h2);

            const map = useConverterStore.getState().color_height_map;
            expect(map[hex2]).toBe(h2);
            // hex1 should still be present (unless hex1 === hex2)
            if (hex1 !== hex2) {
              expect(map[hex1]).toBe(h1);
            }
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});

describe("Feature: relief-mode-bugfix — Property 5: 自动高度模式正确更新状态", () => {
  beforeEach(() => {
    resetStore();
  });

  /**
   * Property 5: 自动高度模式正确更新状态
   * **Validates: Requirements 3.2**
   *
   * applyAutoHeight should compute luminance-based heights and update
   * color_height_map without triggering any backend calls.
   */
  describe("applyAutoHeight updates color_height_map correctly", () => {
    it("populates color_height_map with heights for all palette colors", () => {
      fc.assert(
        fc.property(
          fc.constantFrom("darker-higher" as const, "lighter-higher" as const),
          uniquePalette,
          (mode, palette) => {
            resetStore({ palette });

            useConverterStore.getState().applyAutoHeight(mode);

            const map = useConverterStore.getState().color_height_map;
            for (const entry of palette) {
              expect(map).toHaveProperty(entry.matched_hex);
              expect(map[entry.matched_hex]).toBeGreaterThanOrEqual(0.08);
            }
          },
        ),
        { numRuns: 100 },
      );
    });

    it("darker-higher and lighter-higher produce inverse height ordering", () => {
      fc.assert(
        fc.property(uniquePalette, (palette) => {
          resetStore({ palette });

          useConverterStore.getState().applyAutoHeight("darker-higher");
          const darkerMap = { ...useConverterStore.getState().color_height_map };

          useConverterStore.getState().applyAutoHeight("lighter-higher");
          const lighterMap = { ...useConverterStore.getState().color_height_map };

          // For each color, darker-higher + lighter-higher heights should
          // approximately sum to maxHeight + minHeight
          const maxH = useConverterStore.getState().heightmap_max_height;
          const minH = 0.08;
          for (const entry of palette) {
            const hex = entry.matched_hex;
            if (darkerMap[hex] !== undefined && lighterMap[hex] !== undefined) {
              const sum = darkerMap[hex] + lighterMap[hex];
              expect(sum).toBeCloseTo(maxH + minH, 3);
            }
          }
        }),
        { numRuns: 100 },
      );
    });
  });
});
