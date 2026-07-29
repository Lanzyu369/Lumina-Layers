export const BEAD_MODULE_ID = "lumina.bead-pattern" as const;
export const BEAD_MODULE_VERSION = "1.0.0" as const;
export const BEAD_PROJECT_SCHEMA_VERSION = "bead-project/v1" as const;
export const BEAD_RENDER_SCHEMA_VERSION = "bead-render/v1" as const;
export const BEAD_RECIPE_PAYLOAD_VERSION = "bead-recipe/v1" as const;
export const DEFAULT_BEAD_PITCH_MM = 2.6;
export const DEFAULT_BEAD_COMPRESSION = 50;
export const MAX_BEAD_GRID_SIZE = 128;

export type RgbColor = [number, number, number];

export type BeadCell =
  | { kind: "empty" }
  | { kind: "color"; paletteIndex: number }
  | { kind: "transparent-support" };

export type BeadInputMode =
  | "numbered-grid"
  | "hard-pixel"
  | "ring-preview";

export interface CropRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type BeadRotation = 0 | 90 | 180 | 270;

export interface BeadOrientation {
  rotation: BeadRotation;
  flipHorizontal: boolean;
  flipVertical: boolean;
}

export type BeadEmptySelection =
  | { kind: "none" }
  | { kind: "sample"; cellIndex: number };

export interface BeadCalibration {
  inputMode: BeadInputMode;
  crop: CropRect | null;
  origin: { x: number; y: number };
  orientation: BeadOrientation;
  emptySelection: BeadEmptySelection;
  transparentSupportSampleCellIndex: number | null;
}

export interface BeadProjectSource {
  fileName: string;
  mimeType: string;
  blob: Blob;
  pixelWidth: number;
  pixelHeight: number;
}

export type BeadConfidenceReason =
  | "high-color-variance"
  | "occupancy-color-conflict"
  | "grid-misalignment"
  | "overlay-obstruction"
  | "jpeg-near-tie";

export interface BeadConfidenceIssue {
  cellIndex: number;
  confidence: number;
  reasons: BeadConfidenceReason[];
  resolved: boolean;
}

export interface BeadProject {
  schemaVersion: typeof BEAD_PROJECT_SCHEMA_VERSION;
  renderSchemaVersion: typeof BEAD_RENDER_SCHEMA_VERSION;
  projectId: string;
  moduleId: typeof BEAD_MODULE_ID;
  moduleVersion: string;
  createdAt: string;
  updatedAt: string;
  source: BeadProjectSource | null;
  calibration: BeadCalibration;
  rows: number;
  columns: number;
  palette: RgbColor[];
  cells: BeadCell[];
  confidenceIssues: BeadConfidenceIssue[];
  beadPitchMm: number;
  compression: number;
}

export type BeadCellRun = readonly [token: number, count: number];

export interface CreateBeadProjectInput {
  projectId: string;
  moduleVersion: string;
  now: string;
  rows: number;
  columns: number;
  palette?: RgbColor[];
  cells?: BeadCell[];
  source?: BeadProjectSource | null;
  calibration?: BeadCalibration;
  confidenceIssues?: BeadConfidenceIssue[];
  beadPitchMm?: number;
  compression?: number;
}

export interface RestoreBeadProjectOptions {
  projectId?: string;
  now?: string;
}

export interface BeadGridGeometry {
  originX: number;
  originY: number;
  cellWidth: number;
  cellHeight: number;
}

export interface PatternClassification {
  mode: BeadInputMode | "ambiguous";
  confidence: number;
  scores: Record<BeadInputMode, number>;
}

export interface GridSuggestion {
  rows: number;
  columns: number;
  geometry: BeadGridGeometry;
  confidence: number;
  validSquareGrid: boolean;
}

export interface RecognitionRequest {
  source: import("../../types").WorkshopRaster;
  mode: BeadInputMode;
  rows: number;
  columns: number;
  geometry: BeadGridGeometry;
  emptySelection: BeadEmptySelection;
  transparentSupportSampleCellIndex: number | null;
  orientation: BeadOrientation;
}

export interface RecognitionResult {
  mode: BeadInputMode;
  rows: number;
  columns: number;
  palette: RgbColor[];
  cells: BeadCell[];
  confidenceIssues: BeadConfidenceIssue[];
}
