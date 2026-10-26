import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { isCardModeAvailable } from "../utils/cardUtils";

// ========== Generators ==========

/** Color mode string that is "Merged" in various casings. */
const mergedMode = fc.constantFrom("Merged", "merged", "MERGED");

/** Color mode string that is NOT "merged" (case-insensitive) and not empty. */
const nonMergedMode = fc
  .constantFrom(
    "BW (Black & White)",
    "4-Color",
    "6-Color (CMYWGK 1296)",
    "8-Color Max",
  );

// ========== Tests ==========

describe("Feature: swatch-style-toggle, Property 3: card mode availability", () => {
  /**
   * **Validates: Requirements 4.5**
   *
   * For any color mode containing "merged" (case-insensitive),
   * isCardModeAvailable must return false.
   */
  it("colorMode 为 'Merged' 时始终返回 false", () => {
    fc.assert(
      fc.property(mergedMode, (colorMode) => {
        expect(isCardModeAvailable(colorMode)).toBe(false);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.5**
   *
   * For empty color mode, isCardModeAvailable must return false.
   */
  it("colorMode 为空字符串时返回 false", () => {
    expect(isCardModeAvailable("")).toBe(false);
  });

  /**
   * **Validates: Requirements 4.5**
   *
   * For any standard (non-merged, non-empty) color mode,
   * isCardModeAvailable must return true.
   */
  it("标准颜色模式（非 Merged）时返回 true", () => {
    fc.assert(
      fc.property(nonMergedMode, (colorMode) => {
        expect(isCardModeAvailable(colorMode)).toBe(true);
      }),
      { numRuns: 100 },
    );
  });
});
