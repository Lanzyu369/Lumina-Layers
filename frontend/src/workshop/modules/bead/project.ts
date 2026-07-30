import {
  WORKSHOP_MANIFEST_SCHEMA_VERSION,
  type WorkshopRecipeSource,
} from "../../types";
import {
  BEAD_MODULE_ID,
  BEAD_PROJECT_SCHEMA_VERSION,
  BEAD_RECIPE_PAYLOAD_VERSION,
  BEAD_RENDER_SCHEMA_VERSION,
  DEFAULT_BEAD_COMPRESSION,
  DEFAULT_BEAD_PITCH_MM,
  MAX_BEAD_GRID_SIZE,
  type BeadCalibration,
  type BeadCell,
  type BeadCellRun,
  type BeadConfidenceIssue,
  type BeadInputMode,
  type BeadOrientation,
  type BeadProject,
  type CreateBeadProjectInput,
  type RestoreBeadProjectOptions,
  type RgbColor,
} from "./types";

const SEMVER_PATTERN = /^\d+\.\d+\.\d+$/;
const INPUT_MODES = new Set<BeadInputMode>([
  "numbered-grid",
  "hard-pixel",
  "ring-preview",
]);
const ROTATIONS = new Set([0, 90, 180, 270]);
const CONFIDENCE_REASONS = new Set([
  "high-color-variance",
  "occupancy-color-conflict",
  "grid-misalignment",
  "overlay-obstruction",
  "jpeg-near-tie",
]);

export class BeadProjectValidationError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "BeadProjectValidationError";
    this.code = code;
  }
}

function fail(code: string, message: string): never {
  throw new BeadProjectValidationError(code, message);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isGridDimension(value: unknown): value is number {
  return (
    Number.isInteger(value) &&
    (value as number) >= 1 &&
    (value as number) <= MAX_BEAD_GRID_SIZE
  );
}

function isByte(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0 && (value as number) <= 255;
}

function validatePalette(palette: unknown): asserts palette is RgbColor[] {
  if (
    !Array.isArray(palette) ||
    palette.length === 0 ||
    palette.length > 256 ||
    !palette.every(
      (color) =>
        Array.isArray(color) &&
        color.length === 3 &&
        color.every(isByte),
    )
  ) {
    fail("invalid-palette", "Palette must contain 1–256 integer RGB colors.");
  }
}

function validateCell(
  cell: unknown,
  paletteLength: number,
): asserts cell is BeadCell {
  if (typeof cell !== "object" || cell === null || !("kind" in cell)) {
    fail("invalid-cell", "Every matrix entry must be a bead cell.");
  }

  const candidate = cell as Record<string, unknown>;
  if (candidate.kind === "empty" || candidate.kind === "transparent-support") {
    return;
  }
  if (
    candidate.kind === "color" &&
    Number.isInteger(candidate.paletteIndex) &&
    (candidate.paletteIndex as number) >= 0 &&
    (candidate.paletteIndex as number) < paletteLength
  ) {
    return;
  }
  if (candidate.kind === "color") {
    fail(
      "invalid-palette-index",
      "Color cell palette index is outside the project palette.",
    );
  }
  fail("invalid-cell", "Unknown bead cell kind.");
}

function validateOrientation(
  orientation: unknown,
): asserts orientation is BeadOrientation {
  if (typeof orientation !== "object" || orientation === null) {
    fail("invalid-calibration", "Calibration orientation is missing.");
  }
  const candidate = orientation as Record<string, unknown>;
  if (
    !ROTATIONS.has(candidate.rotation as number) ||
    typeof candidate.flipHorizontal !== "boolean" ||
    typeof candidate.flipVertical !== "boolean"
  ) {
    fail("invalid-calibration", "Calibration orientation is invalid.");
  }
}

function validateCalibration(
  calibration: unknown,
  cellCount: number,
): asserts calibration is BeadCalibration {
  if (typeof calibration !== "object" || calibration === null) {
    fail("invalid-calibration", "Calibration is missing.");
  }
  const candidate = calibration as Record<string, unknown>;
  if (!INPUT_MODES.has(candidate.inputMode as BeadInputMode)) {
    fail("invalid-calibration", "Calibration input mode is invalid.");
  }

  if (candidate.crop !== null) {
    if (typeof candidate.crop !== "object" || candidate.crop === null) {
      fail("invalid-calibration", "Crop must be null or a rectangle.");
    }
    const crop = candidate.crop as Record<string, unknown>;
    if (
      !isFiniteNumber(crop.x) ||
      !isFiniteNumber(crop.y) ||
      !isFiniteNumber(crop.width) ||
      !isFiniteNumber(crop.height) ||
      crop.x < 0 ||
      crop.y < 0 ||
      crop.width <= 0 ||
      crop.height <= 0
    ) {
      fail("invalid-calibration", "Crop rectangle is invalid.");
    }
  }

  if (typeof candidate.origin !== "object" || candidate.origin === null) {
    fail("invalid-calibration", "Grid origin is missing.");
  }
  const origin = candidate.origin as Record<string, unknown>;
  if (!isFiniteNumber(origin.x) || !isFiniteNumber(origin.y)) {
    fail("invalid-calibration", "Grid origin is invalid.");
  }
  validateOrientation(candidate.orientation);

  if (
    typeof candidate.emptySelection !== "object" ||
    candidate.emptySelection === null
  ) {
    fail("invalid-calibration", "Empty-cell selection is missing.");
  }
  const emptySelection = candidate.emptySelection as Record<string, unknown>;
  if (emptySelection.kind === "sample") {
    if (
      !Number.isInteger(emptySelection.cellIndex) ||
      (emptySelection.cellIndex as number) < 0 ||
      (emptySelection.cellIndex as number) >= cellCount
    ) {
      fail("invalid-calibration", "Empty-cell sample is outside the grid.");
    }
  } else if (emptySelection.kind !== "none") {
    fail("invalid-calibration", "Empty-cell selection is invalid.");
  }

  if (
    candidate.transparentSupportSampleCellIndex !== null &&
    (!Number.isInteger(candidate.transparentSupportSampleCellIndex) ||
      (candidate.transparentSupportSampleCellIndex as number) < 0 ||
      (candidate.transparentSupportSampleCellIndex as number) >= cellCount)
  ) {
    fail("invalid-calibration", "Support sample is outside the grid.");
  }
}

function validateConfidenceIssues(
  issues: unknown,
  cellCount: number,
): asserts issues is BeadConfidenceIssue[] {
  if (!Array.isArray(issues)) {
    fail("invalid-confidence-issues", "Confidence issues must be an array.");
  }
  for (const issue of issues) {
    if (typeof issue !== "object" || issue === null) {
      fail("invalid-confidence-issues", "Confidence issue is invalid.");
    }
    const candidate = issue as Record<string, unknown>;
    if (
      !Number.isInteger(candidate.cellIndex) ||
      (candidate.cellIndex as number) < 0 ||
      (candidate.cellIndex as number) >= cellCount ||
      !isFiniteNumber(candidate.confidence) ||
      candidate.confidence < 0 ||
      candidate.confidence > 1 ||
      !Array.isArray(candidate.reasons) ||
      candidate.reasons.length === 0 ||
      !candidate.reasons.every(
        (reason) =>
          typeof reason === "string" && CONFIDENCE_REASONS.has(reason),
      ) ||
      typeof candidate.resolved !== "boolean"
    ) {
      fail("invalid-confidence-issues", "Confidence issue is invalid.");
    }
  }
}

function validateSource(source: unknown): void {
  if (source === null) {
    return;
  }
  if (typeof source !== "object" || source === null) {
    fail("invalid-source", "Project source is invalid.");
  }
  const candidate = source as Record<string, unknown>;
  if (
    typeof candidate.fileName !== "string" ||
    typeof candidate.mimeType !== "string" ||
    !(candidate.blob instanceof Blob) ||
    !Number.isInteger(candidate.pixelWidth) ||
    (candidate.pixelWidth as number) <= 0 ||
    !Number.isInteger(candidate.pixelHeight) ||
    (candidate.pixelHeight as number) <= 0
  ) {
    fail("invalid-source", "Project source is invalid.");
  }
}

export function validateBeadProject(value: unknown): BeadProject {
  if (typeof value !== "object" || value === null) {
    return fail("invalid-project", "Bead project must be an object.");
  }
  const project = value as Record<string, unknown>;
  if (
    project.schemaVersion !== BEAD_PROJECT_SCHEMA_VERSION ||
    project.renderSchemaVersion !== BEAD_RENDER_SCHEMA_VERSION ||
    project.moduleId !== BEAD_MODULE_ID ||
    typeof project.projectId !== "string" ||
    project.projectId.length === 0 ||
    typeof project.moduleVersion !== "string" ||
    !SEMVER_PATTERN.test(project.moduleVersion) ||
    typeof project.createdAt !== "string" ||
    !Number.isFinite(Date.parse(project.createdAt)) ||
    typeof project.updatedAt !== "string" ||
    !Number.isFinite(Date.parse(project.updatedAt))
  ) {
    return fail("invalid-project", "Project identity or schema is invalid.");
  }
  if (!isGridDimension(project.rows) || !isGridDimension(project.columns)) {
    return fail(
      "invalid-dimensions",
      `Grid dimensions must be integers from 1 to ${MAX_BEAD_GRID_SIZE}.`,
    );
  }

  validatePalette(project.palette);
  const expectedCellCount = project.rows * project.columns;
  if (
    !Array.isArray(project.cells) ||
    project.cells.length !== expectedCellCount
  ) {
    return fail(
      "cell-count-mismatch",
      "Cell count must equal rows multiplied by columns.",
    );
  }
  for (const cell of project.cells) {
    validateCell(cell, project.palette.length);
  }

  validateSource(project.source);
  validateCalibration(project.calibration, expectedCellCount);
  validateConfidenceIssues(project.confidenceIssues, expectedCellCount);

  if (
    !isFiniteNumber(project.beadPitchMm) ||
    project.beadPitchMm < 0.5 ||
    project.beadPitchMm > 10
  ) {
    return fail("invalid-pitch", "Bead pitch must be from 0.5 to 10 mm.");
  }
  if (
    !Number.isInteger(project.compression) ||
    (project.compression as number) < 0 ||
    (project.compression as number) > 100
  ) {
    return fail(
      "invalid-compression",
      "Compression must be an integer from 0 to 100.",
    );
  }

  return value as BeadProject;
}

function defaultCalibration(): BeadCalibration {
  return {
    inputMode: "hard-pixel",
    crop: null,
    origin: { x: 0, y: 0 },
    orientation: {
      rotation: 0,
      flipHorizontal: false,
      flipVertical: false,
    },
    emptySelection: { kind: "none" },
    transparentSupportSampleCellIndex: null,
  };
}

export function createBeadProject(
  input: CreateBeadProjectInput,
): BeadProject {
  const project: BeadProject = {
    schemaVersion: BEAD_PROJECT_SCHEMA_VERSION,
    renderSchemaVersion: BEAD_RENDER_SCHEMA_VERSION,
    projectId: input.projectId,
    moduleId: BEAD_MODULE_ID,
    moduleVersion: input.moduleVersion,
    createdAt: input.now,
    updatedAt: input.now,
    source: input.source ?? null,
    calibration: input.calibration ?? defaultCalibration(),
    rows: input.rows,
    columns: input.columns,
    palette: input.palette ?? [[0, 0, 0]],
    cells:
      input.cells ??
      Array.from({ length: input.rows * input.columns }, () => ({
        kind: "empty" as const,
      })),
    confidenceIssues: input.confidenceIssues ?? [],
    beadPitchMm: input.beadPitchMm ?? DEFAULT_BEAD_PITCH_MM,
    compression: input.compression ?? DEFAULT_BEAD_COMPRESSION,
  };
  return validateBeadProject(project);
}

export function trimEmptyBorder(project: BeadProject): BeadProject {
  validateBeadProject(project);

  let minRow = project.rows;
  let maxRow = -1;
  let minColumn = project.columns;
  let maxColumn = -1;

  for (let row = 0; row < project.rows; row += 1) {
    for (let column = 0; column < project.columns; column += 1) {
      const index = row * project.columns + column;
      if (project.cells[index]?.kind !== "empty") {
        minRow = Math.min(minRow, row);
        maxRow = Math.max(maxRow, row);
        minColumn = Math.min(minColumn, column);
        maxColumn = Math.max(maxColumn, column);
      }
    }
  }

  if (
    maxRow < 0 ||
    (minRow === 0 &&
      minColumn === 0 &&
      maxRow === project.rows - 1 &&
      maxColumn === project.columns - 1)
  ) {
    return project;
  }

  const rows = maxRow - minRow + 1;
  const columns = maxColumn - minColumn + 1;
  const cells: BeadCell[] = [];
  for (let row = minRow; row <= maxRow; row += 1) {
    for (let column = minColumn; column <= maxColumn; column += 1) {
      cells.push(project.cells[row * project.columns + column]);
    }
  }

  const confidenceIssues = project.confidenceIssues
    .filter(({ cellIndex }) => {
      const row = Math.floor(cellIndex / project.columns);
      const column = cellIndex % project.columns;
      return (
        row >= minRow &&
        row <= maxRow &&
        column >= minColumn &&
        column <= maxColumn
      );
    })
    .map((issue) => {
      const oldRow = Math.floor(issue.cellIndex / project.columns);
      const oldColumn = issue.cellIndex % project.columns;
      return {
        ...issue,
        cellIndex:
          (oldRow - minRow) * columns + (oldColumn - minColumn),
      };
    });

  return validateBeadProject({
    ...project,
    rows,
    columns,
    cells,
    confidenceIssues,
  });
}

function roundMillimeters(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}

export function calculatePhysicalSize(
  project: Pick<BeadProject, "rows" | "columns">,
  beadPitchMm: number,
): { widthMm: number; heightMm: number } {
  if (
    !isFiniteNumber(beadPitchMm) ||
    beadPitchMm < 0.5 ||
    beadPitchMm > 10
  ) {
    return fail("invalid-pitch", "Bead pitch must be from 0.5 to 10 mm.");
  }
  return {
    widthMm: roundMillimeters(project.columns * beadPitchMm),
    heightMm: roundMillimeters(project.rows * beadPitchMm),
  };
}

function cellToken(cell: BeadCell): number {
  if (cell.kind === "empty") {
    return -1;
  }
  if (cell.kind === "transparent-support") {
    return -2;
  }
  return cell.paletteIndex;
}

export function encodeBeadCellsRle(
  cells: readonly BeadCell[],
): BeadCellRun[] {
  if (cells.length === 0) {
    return [];
  }

  const runs: BeadCellRun[] = [];
  let token = cellToken(cells[0]);
  let count = 1;
  for (let index = 1; index < cells.length; index += 1) {
    const nextToken = cellToken(cells[index]);
    if (nextToken === token) {
      count += 1;
    } else {
      runs.push([token, count]);
      token = nextToken;
      count = 1;
    }
  }
  runs.push([token, count]);
  return runs;
}

export function decodeBeadCellsRle(
  value: unknown,
  expectedLength: number,
): BeadCell[] {
  if (!Array.isArray(value) || !Number.isInteger(expectedLength) || expectedLength < 0) {
    return fail("invalid-rle", "Cell RLE is invalid.");
  }

  const cells: BeadCell[] = [];
  for (const run of value) {
    if (
      !Array.isArray(run) ||
      run.length !== 2 ||
      !Number.isInteger(run[0]) ||
      (run[0] as number) < -2 ||
      !Number.isInteger(run[1]) ||
      (run[1] as number) <= 0 ||
      cells.length + (run[1] as number) > expectedLength
    ) {
      return fail("invalid-rle", "Cell RLE contains an invalid run.");
    }
    const token = run[0] as number;
    const cell: BeadCell =
      token === -1
        ? { kind: "empty" }
        : token === -2
          ? { kind: "transparent-support" }
          : { kind: "color", paletteIndex: token };
    for (let count = 0; count < (run[1] as number); count += 1) {
      cells.push(cell);
    }
  }
  if (cells.length !== expectedLength) {
    return fail("invalid-rle", "Cell RLE does not match the grid size.");
  }
  return cells;
}

interface BeadRecipePayload {
  payloadVersion: typeof BEAD_RECIPE_PAYLOAD_VERSION;
  rows: number;
  columns: number;
  palette: RgbColor[];
  cellsRle: BeadCellRun[];
  calibration: {
    inputMode: BeadInputMode;
    orientation: BeadOrientation;
  };
  beadPitchMm: number;
  compression: number;
}

export function createBeadRecipeSource(
  project: BeadProject,
): WorkshopRecipeSource {
  validateBeadProject(project);
  const payload: BeadRecipePayload = {
    payloadVersion: BEAD_RECIPE_PAYLOAD_VERSION,
    rows: project.rows,
    columns: project.columns,
    palette: project.palette.map((color) => [...color] as RgbColor),
    cellsRle: encodeBeadCellsRle(project.cells),
    calibration: {
      inputMode: project.calibration.inputMode,
      orientation: { ...project.calibration.orientation },
    },
    beadPitchMm: project.beadPitchMm,
    compression: project.compression,
  };
  return {
    manifestSchemaVersion: WORKSHOP_MANIFEST_SCHEMA_VERSION,
    moduleId: project.moduleId,
    moduleVersion: project.moduleVersion,
    projectSchemaVersion: project.schemaVersion,
    renderSchemaVersion: project.renderSchemaVersion,
    payload: payload as unknown as Record<string, unknown>,
  };
}

function generatedProjectId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `bead-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function restoreBeadProjectFromRecipeSource(
  source: WorkshopRecipeSource,
  options: RestoreBeadProjectOptions = {},
): BeadProject {
  if (
    source.manifestSchemaVersion !== WORKSHOP_MANIFEST_SCHEMA_VERSION ||
    source.moduleId !== BEAD_MODULE_ID ||
    source.projectSchemaVersion !== BEAD_PROJECT_SCHEMA_VERSION ||
    source.renderSchemaVersion !== BEAD_RENDER_SCHEMA_VERSION ||
    typeof source.moduleVersion !== "string" ||
    !SEMVER_PATTERN.test(source.moduleVersion) ||
    typeof source.payload !== "object" ||
    source.payload === null
  ) {
    return fail("invalid-recipe-source", "Workshop recipe source is not a bead project.");
  }

  const payload = source.payload;
  if (payload.payloadVersion !== BEAD_RECIPE_PAYLOAD_VERSION) {
    return fail("invalid-recipe-source", "Bead recipe payload version is unsupported.");
  }
  if (!isGridDimension(payload.rows) || !isGridDimension(payload.columns)) {
    return fail("invalid-dimensions", "Bead recipe grid is invalid.");
  }
  if (
    typeof payload.calibration !== "object" ||
    payload.calibration === null
  ) {
    return fail("invalid-recipe-source", "Bead recipe calibration is missing.");
  }
  const calibrationPayload = payload.calibration as Record<string, unknown>;
  const rows = payload.rows;
  const columns = payload.columns;
  const cells = decodeBeadCellsRle(payload.cellsRle, rows * columns);
  const now = options.now ?? new Date().toISOString();

  return createBeadProject({
    projectId: options.projectId ?? generatedProjectId(),
    moduleVersion: source.moduleVersion,
    now,
    rows,
    columns,
    palette: payload.palette as RgbColor[],
    cells,
    source: null,
    calibration: {
      inputMode: calibrationPayload.inputMode as BeadInputMode,
      crop: null,
      origin: { x: 0, y: 0 },
      orientation: calibrationPayload.orientation as BeadOrientation,
      emptySelection: { kind: "none" },
      transparentSupportSampleCellIndex: null,
    },
    confidenceIssues: [],
    beadPitchMm: payload.beadPitchMm as number,
    compression: payload.compression as number,
  });
}
