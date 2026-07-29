import type { ComponentType } from "react";

export const WORKSHOP_MANIFEST_SCHEMA_VERSION = 1 as const;

export type WorkshopCapability =
  | "file.pick-image"
  | "project.read-write"
  | "handoff.image"
  | "ui.theme"
  | "ui.locale"
  | "status.progress"
  | "status.error";

export interface WorkshopLocalizedText {
  zh: string;
  en: string;
}

export interface WorkshopModuleManifest {
  manifestSchemaVersion: typeof WORKSHOP_MANIFEST_SCHEMA_VERSION;
  id: string;
  name: WorkshopLocalizedText;
  description: WorkshopLocalizedText;
  author: string;
  version: string;
  icon: string;
  minLuminaVersion: string;
  inputKinds: string[];
  outputKinds: string[];
  capabilities: WorkshopCapability[];
}

export interface WorkshopRaster {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

export interface WorkshopPickedImage {
  file: File;
  raster: WorkshopRaster;
}

export interface WorkshopRecipeSource {
  manifestSchemaVersion: typeof WORKSHOP_MANIFEST_SCHEMA_VERSION;
  moduleId: string;
  moduleVersion: string;
  projectSchemaVersion: string;
  renderSchemaVersion: string;
  payload: Record<string, unknown>;
}

export interface WorkshopImageHandoff {
  moduleId: string;
  moduleVersion: string;
  projectId: string;
  file: File;
  pixelWidth: number;
  pixelHeight: number;
  recommendedWidthMm: number;
  recommendedHeightMm: number;
  rows: number;
  columns: number;
  beadPitchMm: number;
  preserveCanvasBounds: true;
  recipeSource: WorkshopRecipeSource;
}

export interface WorkshopDiagnosticSummary {
  projectSchemaVersion: string;
  inputMode: string | null;
  rows: number | null;
  columns: number | null;
  compression: number | null;
  errorCode: string | null;
}

export interface WorkshopProjectRecord<TProject = unknown> {
  moduleId: string;
  projectId: string;
  schemaVersion: string;
  createdAt: string;
  updatedAt: string;
  project: TProject;
}

export interface WorkshopProjectStorage {
  save<TProject>(record: WorkshopProjectRecord<TProject>): Promise<void>;
  load<TProject>(
    moduleId: string,
    projectId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null>;
  latest<TProject>(
    moduleId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null>;
  remove(moduleId: string, projectId: string): Promise<void>;
}

export interface WorkshopScopedProjects {
  save<TProject>(
    record: Omit<WorkshopProjectRecord<TProject>, "moduleId">,
  ): Promise<void>;
  load<TProject>(
    projectId: string,
  ): Promise<WorkshopProjectRecord<TProject> | null>;
  latest<TProject>(): Promise<WorkshopProjectRecord<TProject> | null>;
  remove(projectId: string): Promise<void>;
}

export interface WorkshopFileServices {
  pickImage(): Promise<WorkshopPickedImage | null>;
  decodeImage(file: Blob): Promise<WorkshopRaster>;
  encodePng(raster: WorkshopRaster, filename: string): Promise<File>;
}

export interface WorkshopUiServices {
  getLocale(): "zh" | "en";
  getTheme(): "light" | "dark";
}

export interface WorkshopProgressUpdate {
  phase: string;
  completed: number;
  total: number;
}

export interface WorkshopVisibleError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface WorkshopStatusServices {
  reportProgress(update: WorkshopProgressUpdate | null): void;
  reportError(error: WorkshopVisibleError | null): void;
  reportDiagnostics(summary: WorkshopDiagnosticSummary | null): void;
}

export type WorkshopHandoffResult =
  | { status: "needs-confirmation" }
  | { status: "completed" };

export interface WorkshopHandoffOptions {
  replaceExisting?: boolean;
}

export interface WorkshopHostServices {
  files: WorkshopFileServices;
  projects: WorkshopScopedProjects;
  ui: WorkshopUiServices;
  status: WorkshopStatusServices;
  handoffImage(
    handoff: WorkshopImageHandoff,
    options?: WorkshopHandoffOptions,
  ): Promise<WorkshopHandoffResult>;
}

export interface WorkshopModuleProps {
  manifest: WorkshopModuleManifest;
  host: WorkshopHostServices;
  pendingRecipeSource: WorkshopRecipeSource | null;
  clearPendingRecipe(): void;
}

export interface WorkshopModuleDefinition {
  manifest: WorkshopModuleManifest;
  Component: ComponentType<WorkshopModuleProps>;
}
