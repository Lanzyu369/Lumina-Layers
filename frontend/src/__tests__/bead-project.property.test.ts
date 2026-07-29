import fc from "fast-check";
import { describe, expect, it } from "vitest";

import {
  createBeadProject,
  decodeBeadCellsRle,
  encodeBeadCellsRle,
  validateBeadProject,
} from "../workshop/modules/bead/project";
import type {
  BeadCell,
  RgbColor,
} from "../workshop/modules/bead/types";

const PALETTE: RgbColor[] = [
  [0, 0, 0],
  [255, 255, 255],
];

function byteToCell(value: number): BeadCell {
  switch (value % 4) {
    case 0:
      return { kind: "empty" };
    case 1:
      return { kind: "transparent-support" };
    case 2:
      return { kind: "color", paletteIndex: 0 };
    default:
      return { kind: "color", paletteIndex: 1 };
  }
}

describe("bead project properties", () => {
  it("round-trips arbitrary square-grid cell states up to 128 by 128", () => {
    fc.assert(
      fc.property(
        fc
          .record({
            rows: fc.integer({ min: 1, max: 128 }),
            columns: fc.integer({ min: 1, max: 128 }),
          })
          .chain(({ rows, columns }) =>
            fc
              .uint8Array({
                minLength: rows * columns,
                maxLength: rows * columns,
              })
              .map((bytes) => ({ rows, columns, bytes })),
          ),
        ({ rows, columns, bytes }) => {
          const cells = [...bytes].map(byteToCell);
          const encoded = encodeBeadCellsRle(cells);

          expect(decodeBeadCellsRle(encoded, rows * columns)).toEqual(cells);

          const project = createBeadProject({
            projectId: `${rows}x${columns}`,
            moduleVersion: "1.0.0",
            now: "2026-07-30T00:00:00.000Z",
            rows,
            columns,
            palette: PALETTE,
            cells,
          });
          expect(validateBeadProject(project)).toBe(project);
        },
      ),
      { numRuns: 40 },
    );
  });

  it("accepts the maximum 128 by 128 matrix without truncation", () => {
    const cells: BeadCell[] = Array.from(
      { length: 128 * 128 },
      (_, index) =>
        index % 3 === 0
          ? { kind: "color", paletteIndex: index % PALETTE.length }
          : { kind: "empty" },
    );

    const project = createBeadProject({
      projectId: "maximum",
      moduleVersion: "1.0.0",
      now: "2026-07-30T00:00:00.000Z",
      rows: 128,
      columns: 128,
      palette: PALETTE,
      cells,
    });

    expect(project.cells).toHaveLength(128 * 128);
    expect(validateBeadProject(project)).toBe(project);
  });
});
