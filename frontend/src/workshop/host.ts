import type {
  WorkshopCapability,
  WorkshopDiagnosticSummary,
  WorkshopFileServices,
  WorkshopHandoffOptions,
  WorkshopHandoffResult,
  WorkshopHostServices,
  WorkshopImageHandoff,
  WorkshopModuleManifest,
  WorkshopProgressUpdate,
  WorkshopProjectStorage,
  WorkshopVisibleError,
} from "./types";

export class WorkshopHostError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "WorkshopHostError";
    this.code = code;
  }
}

export interface WorkshopHostDependencies {
  storage: WorkshopProjectStorage;
  files: WorkshopFileServices;
  getLocale(): "zh" | "en";
  getTheme(): "light" | "dark";
  translate(key: string): string;
  onProgress(update: WorkshopProgressUpdate | null): void;
  onError(error: WorkshopVisibleError | null): void;
  onDiagnostics(
    moduleId: string,
    moduleVersion: string,
    summary: WorkshopDiagnosticSummary | null,
  ): void;
  onProjectSaved?(moduleId: string, projectId: string): void;
  handoffImage(
    handoff: WorkshopImageHandoff,
    options?: WorkshopHandoffOptions,
  ): Promise<WorkshopHandoffResult>;
}

function assertCapability(
  manifest: WorkshopModuleManifest,
  capability: WorkshopCapability,
): void {
  if (!manifest.capabilities.includes(capability)) {
    throw new WorkshopHostError(
      "capability-denied",
      `Workshop module ${manifest.id} did not request ${capability}.`,
    );
  }
}

export function createWorkshopHostServices(
  manifest: WorkshopModuleManifest,
  dependencies: WorkshopHostDependencies,
): WorkshopHostServices {
  return {
    files: {
      pickImage: async () => {
        assertCapability(manifest, "file.pick-image");
        return dependencies.files.pickImage();
      },
      decodeImage: async (file) => {
        assertCapability(manifest, "file.pick-image");
        return dependencies.files.decodeImage(file);
      },
      encodePng: async (raster, filename) => {
        assertCapability(manifest, "handoff.image");
        return dependencies.files.encodePng(raster, filename);
      },
    },
    projects: {
      save: async (record) => {
        assertCapability(manifest, "project.read-write");
        await dependencies.storage.save({
          ...record,
          moduleId: manifest.id,
        });
        dependencies.onProjectSaved?.(
          manifest.id,
          record.projectId,
        );
      },
      load: async (projectId) => {
        assertCapability(manifest, "project.read-write");
        return dependencies.storage.load(manifest.id, projectId);
      },
      latest: async () => {
        assertCapability(manifest, "project.read-write");
        return dependencies.storage.latest(manifest.id);
      },
      remove: async (projectId) => {
        assertCapability(manifest, "project.read-write");
        return dependencies.storage.remove(manifest.id, projectId);
      },
    },
    ui: {
      getLocale: () => {
        assertCapability(manifest, "ui.locale");
        return dependencies.getLocale();
      },
      getTheme: () => {
        assertCapability(manifest, "ui.theme");
        return dependencies.getTheme();
      },
      translate: (key) => {
        assertCapability(manifest, "ui.locale");
        return dependencies.translate(key);
      },
    },
    status: {
      reportProgress: (update) => {
        assertCapability(manifest, "status.progress");
        dependencies.onProgress(update);
      },
      reportError: (error) => {
        assertCapability(manifest, "status.error");
        dependencies.onError(error);
      },
      reportDiagnostics: (summary) => {
        assertCapability(manifest, "status.error");
        dependencies.onDiagnostics(
          manifest.id,
          manifest.version,
          summary,
        );
      },
    },
    handoffImage: async (handoff, options) => {
      assertCapability(manifest, "handoff.image");
      return dependencies.handoffImage(handoff, options);
    },
  };
}
