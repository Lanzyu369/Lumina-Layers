import fc from "fast-check";
import { describe, expect, it } from "vitest";

import {
  recognizeBeadPattern,
  suggestGrid,
} from "../workshop/modules/bead/recognition";
import type { RgbColor } from "../workshop/modules/bead/types";
import { makeHardPixelFixture } from "./helpers/beadFixtures";

describe("bead recognition properties", () => {
  it("always returns a bounded valid matrix for calibrated hard-pixel charts", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 8 }),
        fc.integer({ min: 1, max: 8 }),
        fc.array(
          fc.tuple(
            fc.integer({ min: 0, max: 255 }),
            fc.integer({ min: 0, max: 255 }),
            fc.integer({ min: 0, max: 255 }),
          ),
          { minLength: 1, maxLength: 64 },
        ),
        (rows, columns, generatedColors) => {
          const required = rows * columns;
          const colors: Array<RgbColor | null> = Array.from(
            { length: required },
            (_, index) =>
              index === 0
                ? null
                : (generatedColors[index % generatedColors.length] as RgbColor),
          );
          const source = makeHardPixelFixture({
            rows,
            columns,
            scale: 8,
            cellColors: colors,
          });
          const geometry = suggestGrid(source, "hard-pixel").geometry;

          const result = recognizeBeadPattern({
            source,
            mode: "hard-pixel",
            rows,
            columns,
            geometry,
            emptySelection: { kind: "sample", cellIndex: 0 },
            transparentSupportSampleCellIndex: null,
            orientation: {
              rotation: 0,
              flipHorizontal: false,
              flipVertical: false,
            },
          });

          expect(result.cells).toHaveLength(required);
          for (const cell of result.cells) {
            if (cell.kind === "color") {
              expect(cell.paletteIndex).toBeGreaterThanOrEqual(0);
              expect(cell.paletteIndex).toBeLessThan(result.palette.length);
            }
          }
        },
      ),
      { numRuns: 50 },
    );
  });
});
