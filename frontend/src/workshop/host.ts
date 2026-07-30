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

const HANDOFF_PIXELS_PER_CELL = 32;
const MAX_HANDOFF_GRID_SIZE = 128;
const MIN_HANDOFF_SIZE_MM = 0.5;
const MAX_HANDOFF_SIZE_MM = 400;

export class WorkshopHostError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "WorkshopHostError";
    this.code = code;
  }
}

function failHandoff(code: string, message: string): never {
  throw new WorkshopHostError(code, message);
}

function isFiniteInRange(
  value: unknown,
  minimum: number,
  maximum: number,
): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= minimum &&
    value <= maximum
  );
}

function nearlyEqual(left: number, right: number): boolean {
  return (
    Math.abs(left - right) <=
    Number.EPSILON * 16 * Math.max(1, Math.abs(left), Math.abs(right))
  );
}

async function validateImageHandoff(
  manifest: WorkshopModuleManifest,
  dependencies: WorkshopHostDependencies,
  handoff: WorkshopImageHandoff,
): Promise<void> {
  if (
    handoff.moduleId !== manifest.id ||
    handoff.moduleVersion !== manifest.version ||
    handoff.recipeSource.moduleId !== manifest.id ||
    handoff.recipeSource.moduleVersion !== manifest.version
  ) {
    failHandoff(
      "invalid-handoff-identity",
      "Workshop handoff identity does not match the active module.",
    );
  }
  if (
    !(handoff.file instanceof File) ||
    handoff.file.type.toLowerCase() !== "image/png"
  ) {
    failHandoff(
      "invalid-handoff-image",
      "Workshop handoff must contain a PNG file.",
    );
  }
  if (
    !Number.isInteger(handoff.rows) ||
    !Number.isInteger(handoff.columns) ||
    handoff.rows < 1 ||
    handoff.columns < 1 ||
    handoff.rows > MAX_HANDOFF_GRID_SIZE ||
    handoff.columns > MAX_HANDOFF_GRID_SIZE
  ) {
    failHandoff(
      "invalid-handoff-grid",
      "Workshop handoff grid dimensions are invalid.",
    );
  }
  if (
    !Number.isInteger(handoff.pixelWidth) ||
    !Number.isInteger(handoff.pixelHeight) ||
    handoff.pixelWidth !==
      handoff.columns * HANDOFF_PIXELS_PER_CELL ||
    handoff.pixelHeight !== handoff.rows * HANDOFF_PIXELS_PER_CELL
  ) {
    failHandoff(
      "invalid-handoff-pixels",
      "Workshop handoff must contain exactly 32 pixels per grid cell.",
    );
  }
  if (
    !isFiniteInRange(handoff.beadPitchMm, 0.5, 10) ||
    !isFiniteInRange(
      handoff.recommendedWidthMm,
      MIN_HANDOFF_SIZE_MM,
      MAX_HANDOFF_SIZE_MM,
    ) ||
    !isFiniteInRange(
      handoff.recommendedHeightMm,
      MIN_HANDOFF_SIZE_MM,
      MAX_HANDOFF_SIZE_MM,
    ) ||
    handoff.preserveCanvasBounds !== true ||
    !nearlyEqual(
      handoff.recommendedWidthMm,
      handoff.columns * handoff.beadPitchMm,
    ) ||
    !nearlyEqual(
      handoff.recommendedHeightMm,
      handoff.rows * handoff.beadPitchMm,
    )
  ) {
    failHandoff(
      "invalid-handoff-size",
      "Workshop handoff physical dimensions are invalid.",
    );
  }

  let raster: Awaited<
    ReturnType<WorkshopFileServices["decodeImage"]>
  >;
  try {
    raster = await dependencies.files.decodeImage(handoff.file);
  } catch {
    failHandoff(
      "invalid-handoff-image",
      "Workshop handoff PNG could not be decoded.",
    );
  }
  if (
    raster.width !== handoff.pixelWidth ||
    raster.height !== handoff.pixelHeight ||
    raster.data.length !== raster.width * raster.height * 4
  ) {
    failHandoff(
      "invalid-handoff-pixels",
      "Workshop handoff PNG dimensions do not match its metadata.",
    );
  }
  let hasVisiblePixel = false;
  for (let index = 3; index < raster.data.length; index += 4) {
    if (raster.data[index] !== 0) {
      hasVisiblePixel = true;
      break;
    }
  }
  if (!hasVisiblePixel) {
    failHandoff(
      "empty-handoff-image",
      "Workshop handoff PNG contains no visible colored beads.",
    );
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
      await validateImageHandoff(manifest, dependencies, handoff);
      return dependencies.handoffImage(handoff, options);
    },
  };
}
