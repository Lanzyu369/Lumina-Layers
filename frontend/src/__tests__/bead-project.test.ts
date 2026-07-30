import { describe, expect, it } from "vitest";

import {
  BeadProjectValidationError,
  calculatePhysicalSize,
  createBeadProject,
  createBeadRecipeSource,
  decodeBeadCellsRle,
  encodeBeadCellsRle,
  restoreBeadProjectFromRecipeSource,
  trimEmptyBorder,
  validateBeadProject,
} from "../workshop/modules/bead/project";
import type {
  BeadCell,
  BeadProject,
  RgbColor,
} from "../workshop/modules/bead/types";

const NOW = "2026-07-30T00:00:00.000Z";
const PALETTE: RgbColor[] = [
  [230, 40, 50],
  [20, 120, 210],
];

function makeProject(
  overrides: Partial<BeadProject> = {},
): BeadProject {
  return createBeadProject({
    projectId: "project-1",
    moduleVersion: "1.0.0",
    now: NOW,
    rows: 2,
    columns: 3,
    palette: PALETTE,
    cells: [
      { kind: "empty" },
      { kind: "color", paletteIndex: 0 },
      { kind: "transparent-support" },
      { kind: "color", paletteIndex: 1 },
      { kind: "empty" },
      { kind: "empty" },
    ],
    ...overrides,
  });
}

function expectInvalid(
  project: unknown,
  code: string,
): void {
  try {
    validateBeadProject(project);
    throw new Error("expected project validation to fail");
  } catch (error) {
    expect(error).toBeInstanceOf(BeadProjectValidationError);
    expect((error as BeadProjectValidationError).code).toBe(code);
  }
}

describe("bead project model", () => {
  it("creates a versioned project with the approved physical defaults", () => {
    const project = makeProject();

    expect(project).toMatchObject({
      schemaVersion: "bead-project/v1",
      renderSchemaVersion: "bead-render/v1",
      moduleId: "lumina.bead-pattern",
      moduleVersion: "1.0.0",
      projectId: "project-1",
      createdAt: NOW,
      updatedAt: NOW,
      beadPitchMm: 2.6,
      compression: 50,
    });
    expect(validateBeadProject(project)).toBe(project);
  });

  it("trims only all-empty outer rows and columns", () => {
    const cells: BeadCell[] = Array.from(
      { length: 4 * 5 },
      () => ({ kind: "empty" }) as const,
    );
    cells[1 * 5 + 1] = { kind: "transparent-support" };
    cells[1 * 5 + 2] = { kind: "color", paletteIndex: 0 };
    cells[2 * 5 + 3] = { kind: "color", paletteIndex: 1 };

    const project = createBeadProject({
      projectId: "trim",
      moduleVersion: "1.0.0",
      now: NOW,
      rows: 4,
      columns: 5,
      palette: PALETTE,
      cells,
      confidenceIssues: [
        {
          cellIndex: 1 * 5 + 2,
          confidence: 0.4,
          reasons: ["overlay-obstruction"],
          resolved: false,
        },
      ],
    });

    const trimmed = trimEmptyBorder(project);

    expect(trimmed.rows).toBe(2);
    expect(trimmed.columns).toBe(3);
    expect(trimmed.cells).toEqual([
      { kind: "transparent-support" },
      { kind: "color", paletteIndex: 0 },
      { kind: "empty" },
      { kind: "empty" },
      { kind: "empty" },
      { kind: "color", paletteIndex: 1 },
    ]);
    expect(trimmed.confidenceIssues[0]?.cellIndex).toBe(1);
    expect(project.rows).toBe(4);
    expect(project.columns).toBe(5);
  });

  it("keeps an all-empty matrix valid for editing", () => {
    const project = createBeadProject({
      projectId: "empty",
      moduleVersion: "1.0.0",
      now: NOW,
      rows: 2,
      columns: 2,
      palette: PALETTE,
    });

    expect(trimEmptyBorder(project)).toBe(project);
  });

  it("calculates exact decimal dimensions from logical grid pitch", () => {
    expect(calculatePhysicalSize(makeProject(), 2.6)).toEqual({
      widthMm: 7.8,
      heightMm: 5.2,
    });
  });

  it("encodes empty, color, and transparent support cells with stable RLE", () => {
    const cells: BeadCell[] = [
      { kind: "empty" },
      { kind: "empty" },
      { kind: "color", paletteIndex: 0 },
      { kind: "color", paletteIndex: 0 },
      { kind: "transparent-support" },
      { kind: "transparent-support" },
      { kind: "color", paletteIndex: 1 },
    ];

    const encoded = encodeBeadCellsRle(cells);

    expect(encoded).toEqual([
      [-1, 2],
      [0, 2],
      [-2, 2],
      [1, 1],
    ]);
    expect(decodeBeadCellsRle(encoded, cells.length)).toEqual(cells);
  });

  it("rejects malformed project dimensions, cells, palette, pitch, and pressure", () => {
    const project = makeProject();

    expectInvalid({ ...project, rows: 129 }, "invalid-dimensions");
    expectInvalid(
      { ...project, cells: project.cells.slice(1) },
      "cell-count-mismatch",
    );
    expectInvalid(
      {
        ...project,
        cells: [
          ...project.cells.slice(0, 1),
          { kind: "color", paletteIndex: 9 },
          ...project.cells.slice(2),
        ],
      },
      "invalid-palette-index",
    );
    expectInvalid(
      { ...project, palette: [[300, 0, 0]] },
      "invalid-palette",
    );
    expectInvalid({ ...project, beadPitchMm: 0.49 }, "invalid-pitch");
    expectInvalid({ ...project, compression: 50.5 }, "invalid-compression");
  });

  it("round-trips an editable matrix through the source-only recipe payload", () => {
    const project = makeProject({
      source: {
        fileName: "private-pattern.png",
        mimeType: "image/png",
        blob: new Blob(["private-source-bytes"], { type: "image/png" }),
        pixelWidth: 120,
        pixelHeight: 80,
      },
      calibration: {
        inputMode: "numbered-grid",
        crop: { x: 4, y: 8, width: 100, height: 60 },
        origin: { x: 0.25, y: 0.5 },
        orientation: {
          rotation: 90,
          flipHorizontal: true,
          flipVertical: false,
        },
        emptySelection: { kind: "sample", cellIndex: 0 },
        transparentSupportSampleCellIndex: 2,
      },
      beadPitchMm: 2.6,
      compression: 84,
    });

    const source = createBeadRecipeSource(project);
    const serialized = JSON.stringify(source);
    const restored = restoreBeadProjectFromRecipeSource(source, {
      projectId: "imported-project",
      now: "2026-07-30T01:00:00.000Z",
    });

    expect(serialized).not.toContain("private-pattern.png");
    expect(serialized).not.toContain("private-source-bytes");
    expect(restored).toMatchObject({
      projectId: "imported-project",
      source: null,
      rows: project.rows,
      columns: project.columns,
      palette: project.palette,
      cells: project.cells,
      beadPitchMm: 2.6,
      compression: 84,
      confidenceIssues: [],
      calibration: {
        inputMode: "numbered-grid",
        orientation: {
          rotation: 90,
          flipHorizontal: true,
          flipVertical: false,
        },
      },
    });
  });

  it("rejects recipe payloads for another module or with incomplete RLE", () => {
    const source = createBeadRecipeSource(makeProject());

    expect(() =>
      restoreBeadProjectFromRecipeSource({
        ...source,
        moduleId: "other.module",
      }),
    ).toThrowError(BeadProjectValidationError);

    expect(() =>
      restoreBeadProjectFromRecipeSource({
        ...source,
        payload: {
          ...source.payload,
          cellsRle: [[0, 1]],
        },
      }),
    ).toThrowError(BeadProjectValidationError);
  });
});
