import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { createBeadProject } from "../workshop/modules/bead/project";
import { renderBeadProject } from "../workshop/modules/bead/renderer";
import type { BeadCell } from "../workshop/modules/bead/types";

const PALETTE = [
  [230, 40, 50],
  [20, 120, 210],
  [245, 185, 30],
] as const;

function cellFromSeed(seed: number): BeadCell {
  if (seed % 5 === 0) {
    return { kind: "empty" };
  }
  if (seed % 5 === 1) {
    return { kind: "transparent-support" };
  }
  return {
    kind: "color",
    paletteIndex: seed % PALETTE.length,
  };
}

describe("bead pressure renderer properties", () => {
  it("is deterministic and never invents colors or partial alpha", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 5 }),
        fc.integer({ min: 1, max: 5 }),
        fc.array(fc.nat(), { minLength: 1, maxLength: 25 }),
        fc.integer({ min: 0, max: 100 }),
        (rows, columns, seeds, compression) => {
          const cells = Array.from(
            { length: rows * columns },
            (_, index) => cellFromSeed(seeds[index % seeds.length]),
          );
          const project = createBeadProject({
            projectId: "renderer-property",
            moduleVersion: "1.0.0",
            now: "2026-07-30T00:00:00.000Z",
            rows,
            columns,
            palette: PALETTE.map((color) => [...color]),
            cells,
          });

          const first = renderBeadProject(project, {
            compression,
            pixelsPerCell: 8,
          });
          const second = renderBeadProject(project, {
            compression,
            pixelsPerCell: 8,
          });

          expect(first.data).toEqual(second.data);
          expect(first).toMatchObject({
            width: columns * 8,
            height: rows * 8,
            compression,
            pixelsPerCell: 8,
          });

          const allowed = new Set(
            project.palette.map((color) => color.join(",")),
          );
          for (let offset = 0; offset < first.data.length; offset += 4) {
            const alpha = first.data[offset + 3];
            expect(alpha === 0 || alpha === 255).toBe(true);
            if (alpha === 255) {
              expect(
                allowed.has(
                  [
                    first.data[offset],
                    first.data[offset + 1],
                    first.data[offset + 2],
                  ].join(","),
                ),
              ).toBe(true);
            }
          }
        },
      ),
      { numRuns: 50 },
    );
  });
});
