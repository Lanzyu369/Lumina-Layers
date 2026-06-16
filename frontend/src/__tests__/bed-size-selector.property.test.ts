import { describe, it, beforeEach, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import * as fc from "fast-check";
import { useConverterStore } from "../stores/converter";

const STORE_MOJIBAKE_MARKERS: ReadonlyArray<{ char: string; why: string }> = [
  { char: "脳", why: "known corruption of multiplication sign in bed label" },
  { char: "锟", why: "classic GBK-as-UTF-8 replacement glyph" },
  { char: "锛", why: "classic GBK-as-UTF-8 punctuation corruption" },
  { char: "鎷", why: "classic GBK-as-UTF-8 replacement glyph" },
  { char: "鍙", why: "classic GBK-as-UTF-8 replacement glyph" },
  { char: "涓", why: "classic GBK-as-UTF-8 replacement glyph" },
];

// ========== Helpers ==========

/** Reset store to default state before each test */
function resetStore(): void {
  useConverterStore.setState({
    bed_label: "256×256 mm",
    bedSizes: [],
    bedSizesLoading: false,
    target_width_mm: 60,
    target_height_mm: 60,
    aspectRatio: null,
  });
}

// ========== Tests ==========

describe("Bed size source encoding", () => {
  it("keeps converter store defaults free of known mojibake", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(
      resolve(here, "../stores/converter/store.ts"),
      "utf-8",
    );

    const hits = STORE_MOJIBAKE_MARKERS.filter((m) =>
      source.includes(m.char),
    );
    expect(
      hits,
      `Mojibake markers found in store.ts: ${hits
        .map((h) => `${h.char} (${h.why})`)
        .join(", ")}`,
    ).toEqual([]);
    expect(source).toContain('bed_label: "256×256 mm"');
  });
});

describe("BedSizeSelector Property-Based Tests", () => {
  beforeEach(() => {
    resetStore();
  });

  // **Validates: Requirements 2.2, 5.1**
  describe("Property 2: setBedLabel 状态隔离性", () => {
    it("setBedLabel updates bed_label without changing target_width_mm or target_height_mm", () => {
      fc.assert(
        fc.property(
          fc.string({ minLength: 1, maxLength: 100 }),
          fc.integer({ min: 10, max: 400 }),
          fc.integer({ min: 10, max: 400 }),
          (label, initialWidth, initialHeight) => {
            resetStore();

            // Set initial target values
            useConverterStore.setState({
              target_width_mm: initialWidth,
              target_height_mm: initialHeight,
            });

            // Call setBedLabel
            useConverterStore.getState().setBedLabel(label);

            const state = useConverterStore.getState();

            // bed_label should be updated
            if (state.bed_label !== label) return false;

            // target values should remain unchanged
            if (state.target_width_mm !== initialWidth) return false;
            if (state.target_height_mm !== initialHeight) return false;

            return true;
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
