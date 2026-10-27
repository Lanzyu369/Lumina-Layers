import type {
  WorkshopRaster,
} from "./contracts";

export type {
  WorkshopRaster,
  WorkshopRecipeSource,
} from "./contracts";

export interface WorkshopPickedImage {
  file: File;
  raster: WorkshopRaster;
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

export interface WorkshopFileServices {
  pickImage(): Promise<WorkshopPickedImage | null>;
  decodeImage(file: Blob): Promise<WorkshopRaster>;
  encodePng(raster: WorkshopRaster, filename: string): Promise<File>;
}
