import { useConverterStore } from "../stores/converter";
import { useWidgetStore } from "../stores/widgetStore";
import type {
  WorkshopHandoffOptions,
  WorkshopHandoffResult,
  WorkshopImageHandoff,
} from "./types";
import type {
  WorkshopImageHandoff as SdkWorkshopImageHandoff,
} from "./contracts";
import { buildWorkshopColorLibrary } from "./colorLibrary";
import {
  WorkshopProjectStorageError,
  assertWorkshopRecipeEnvelopeWithinQuota,
} from "./projectStorage";

export const WORKSHOP_HANDOFF_MAX_BINARY_BYTES = 64 * 1024 * 1024;
export const WORKSHOP_HANDOFF_MAX_EDGE = 16_384;
export const WORKSHOP_HANDOFF_MAX_PIXELS = 64_000_000;

const WORKSHOP_HANDOFF_MIN_MM = 0.5;
const WORKSHOP_HANDOFF_MAX_MM = 9_999;
const WORKSHOP_GRID_MIN_PITCH_MM = 0.01;
const WORKSHOP_GRID_MAX_PITCH_MM = 9_999;
const PHYSICAL_SIZE_TOLERANCE_MM = 1e-6;
const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10] as const;

export type WorkshopHandoffValidationErrorCode =
  | "handoff-invalid-payload"
  | "handoff-binary-too-large"
  | "handoff-invalid-png"
  | "handoff-dimensions-invalid"
  | "handoff-image-empty"
  | "handoff-layout-invalid"
  | "handoff-physical-size-invalid"
  | "handoff-recipe-invalid"
  | "handoff-recipe-too-large"
  | "handoff-color-library-changed";

export class WorkshopHandoffValidationError extends Error {
  readonly code: WorkshopHandoffValidationErrorCode;

  constructor(
    code: WorkshopHandoffValidationErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "WorkshopHandoffValidationError";
    this.code = code;
  }
}

export interface WorkshopPngDecodeResult {
  width: number;
  height: number;
  hasVisiblePixels: boolean;
}

export interface WorkshopPngDecoder {
  decode(bytes: ArrayBuffer): Promise<WorkshopPngDecodeResult>;
}

export interface WorkshopPngHandoffDependencies {
  decoder?: WorkshopPngDecoder;
}

function handoffError(
  code: WorkshopHandoffValidationErrorCode,
  message: string,
): never {
  throw new WorkshopHandoffValidationError(code, message);
}

function isRecord(
  value: unknown,
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function boundedString(
  value: unknown,
  maximum: number,
): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= maximum &&
    !value.includes("\0")
  );
}

function finiteInRange(
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

function readPngHeader(
  bytes: ArrayBuffer,
): { width: number; height: number } {
  if (bytes.byteLength < 24) {
    return handoffError(
      "handoff-invalid-png",
      "Workshop handoff is not a complete PNG header.",
    );
  }
  const data = new Uint8Array(bytes, 0, 24);
  if (
    PNG_SIGNATURE.some(
      (expected, index) => data[index] !== expected,
    ) ||
    new DataView(bytes, 8, 4).getUint32(0) !== 13 ||
    String.fromCharCode(...data.slice(12, 16)) !== "IHDR"
  ) {
    return handoffError(
      "handoff-invalid-png",
      "Workshop handoff does not have a valid PNG signature.",
    );
  }
  const view = new DataView(bytes, 16, 8);
  return {
    width: view.getUint32(0),
    height: view.getUint32(4),
  };
}

function validatePixelDimensions(
  handoff: SdkWorkshopImageHandoff,
  header: { width: number; height: number },
): void {
  if (
    !Number.isInteger(handoff.pixelWidth) ||
    !Number.isInteger(handoff.pixelHeight) ||
    handoff.pixelWidth < 1 ||
    handoff.pixelHeight < 1 ||
    handoff.pixelWidth > WORKSHOP_HANDOFF_MAX_EDGE ||
    handoff.pixelHeight > WORKSHOP_HANDOFF_MAX_EDGE ||
    handoff.pixelWidth * handoff.pixelHeight >
      WORKSHOP_HANDOFF_MAX_PIXELS ||
    header.width !== handoff.pixelWidth ||
    header.height !== handoff.pixelHeight
  ) {
    handoffError(
      "handoff-dimensions-invalid",
      "Workshop PNG dimensions are invalid or inconsistent.",
    );
  }
}

function validatePhysicalDimensions(
  handoff: SdkWorkshopImageHandoff,
): void {
  if (
    !finiteInRange(
      handoff.recommendedWidthMm,
      WORKSHOP_HANDOFF_MIN_MM,
      WORKSHOP_HANDOFF_MAX_MM,
    ) ||
    !finiteInRange(
      handoff.recommendedHeightMm,
      WORKSHOP_HANDOFF_MIN_MM,
      WORKSHOP_HANDOFF_MAX_MM,
    )
  ) {
    handoffError(
      "handoff-physical-size-invalid",
      "Workshop handoff physical dimensions are out of range.",
    );
  }
  const layout = handoff.layout;
  if (layout === undefined) {
    return;
  }
  if (
    layout.kind !== "square-grid" ||
    !Number.isInteger(layout.rows) ||
    !Number.isInteger(layout.columns) ||
    layout.rows < 1 ||
    layout.columns < 1 ||
    layout.rows > WORKSHOP_HANDOFF_MAX_EDGE ||
    layout.columns > WORKSHOP_HANDOFF_MAX_EDGE ||
    !finiteInRange(
      layout.pitchMm,
      WORKSHOP_GRID_MIN_PITCH_MM,
      WORKSHOP_GRID_MAX_PITCH_MM,
    )
  ) {
    handoffError(
      "handoff-layout-invalid",
      "Workshop square-grid layout is invalid.",
    );
  }
  const expectedWidth = layout.columns * layout.pitchMm;
  const expectedHeight = layout.rows * layout.pitchMm;
  if (
    Math.abs(handoff.recommendedWidthMm - expectedWidth) >
      PHYSICAL_SIZE_TOLERANCE_MM ||
    Math.abs(handoff.recommendedHeightMm - expectedHeight) >
      PHYSICAL_SIZE_TOLERANCE_MM
  ) {
    handoffError(
      "handoff-physical-size-invalid",
      "Workshop physical dimensions do not match the grid pitch.",
    );
  }
}

function validateRecipeAndIdentity(
  handoff: SdkWorkshopImageHandoff,
): void {
  if (
    !boundedString(handoff.moduleId, 128) ||
    !boundedString(handoff.moduleVersion, 128) ||
    !boundedString(handoff.projectId, 256) ||
    handoff.preserveCanvasBounds !== true ||
    !isRecord(handoff.recipeSource) ||
    handoff.recipeSource.manifestSchemaVersion !== 1 ||
    handoff.recipeSource.moduleId !== handoff.moduleId ||
    handoff.recipeSource.moduleVersion !== handoff.moduleVersion ||
    !boundedString(
      handoff.recipeSource.projectSchemaVersion,
      128,
    ) ||
    !boundedString(
      handoff.recipeSource.renderSchemaVersion,
      128,
    ) ||
    !isRecord(handoff.recipeSource.payload)
  ) {
    handoffError(
      "handoff-recipe-invalid",
      "Workshop handoff identity or recipe source is invalid.",
    );
  }
  try {
    assertWorkshopRecipeEnvelopeWithinQuota(handoff.recipeSource);
  } catch (error) {
    if (
      error instanceof WorkshopProjectStorageError &&
      error.code === "project-recipe-too-large"
    ) {
      handoffError(
        "handoff-recipe-too-large",
        "Workshop recipe envelope exceeds 1 MiB.",
      );
    }
    handoffError(
      "handoff-recipe-invalid",
      "Workshop recipe envelope is invalid.",
    );
  }
}

function validateColorLibraryIdentity(
  handoff: SdkWorkshopImageHandoff,
): void {
  if (
    !(
      handoff.colorLibraryId === null ||
      boundedString(handoff.colorLibraryId, 256)
    )
  ) {
    handoffError(
      "handoff-invalid-payload",
      "Workshop color-library identity is invalid.",
    );
  }
  const currentLibraryId = buildWorkshopColorLibrary()?.id ?? null;
  if (handoff.colorLibraryId !== currentLibraryId) {
    handoffError(
      "handoff-color-library-changed",
      "The selected print color library changed during editing.",
    );
  }
}

const defaultPngDecoder: WorkshopPngDecoder = {
  async decode(bytes) {
    if (typeof createImageBitmap !== "function") {
      return handoffError(
        "handoff-invalid-png",
        "This runtime cannot decode Workshop PNG images.",
      );
    }
    let bitmap: ImageBitmap;
    try {
      bitmap = await createImageBitmap(
        new Blob([bytes], { type: "image/png" }),
      );
    } catch {
      return handoffError(
        "handoff-invalid-png",
        "Workshop PNG decoding failed.",
      );
    }
    try {
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const context = canvas.getContext("2d", {
        willReadFrequently: true,
      });
      if (context === null) {
        return handoffError(
          "handoff-invalid-png",
          "Workshop PNG inspection is unavailable.",
        );
      }
      context.drawImage(bitmap, 0, 0);
      let hasVisiblePixels = false;
      const rowsPerScan = 256;
      for (
        let startRow = 0;
        startRow < bitmap.height && !hasVisiblePixels;
        startRow += rowsPerScan
      ) {
        const rowCount = Math.min(
          rowsPerScan,
          bitmap.height - startRow,
        );
        const pixels = context.getImageData(
          0,
          startRow,
          bitmap.width,
          rowCount,
        ).data;
        for (let index = 3; index < pixels.length; index += 4) {
          if (pixels[index] !== 0) {
            hasVisiblePixels = true;
            break;
          }
        }
      }
      return {
        width: bitmap.width,
        height: bitmap.height,
        hasVisiblePixels,
      };
    } finally {
      bitmap.close();
    }
  },
};

function safeHandoffFilename(
  handoff: SdkWorkshopImageHandoff,
): string {
  const safeModule = handoff.moduleId.replace(
    /[^A-Za-z0-9._-]+/g,
    "-",
  );
  const safeProject = handoff.projectId
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .slice(0, 96);
  return `${safeModule}-${safeProject}.png`;
}

export async function handoffWorkshopImageToConverter(
  handoff: WorkshopImageHandoff,
  options?: WorkshopHandoffOptions,
): Promise<WorkshopHandoffResult> {
  const converter = useConverterStore.getState();
  const occupied =
    converter.imageFile !== null || converter.batchFiles.length > 0;
  if (occupied && !options?.replaceExisting) {
    return { status: "needs-confirmation" };
  }

  converter.loadWorkshopImageIntoConverter({
    file: handoff.file,
    pixelWidth: handoff.pixelWidth,
    pixelHeight: handoff.pixelHeight,
    targetWidthMm: handoff.recommendedWidthMm,
    targetHeightMm: handoff.recommendedHeightMm,
    source: handoff.recipeSource,
  });
  useWidgetStore.getState().setActiveTab("converter");
  return { status: "completed" };
}

export async function handoffWorkshopPngToConverter(
  handoff: SdkWorkshopImageHandoff,
  options?: WorkshopHandoffOptions,
  dependencies: WorkshopPngHandoffDependencies = {},
): Promise<WorkshopHandoffResult> {
  if (!(handoff.pngBytes instanceof ArrayBuffer)) {
    return handoffError(
      "handoff-invalid-payload",
      "Workshop PNG bytes are missing.",
    );
  }
  if (
    handoff.pngBytes.byteLength === 0 ||
    handoff.pngBytes.byteLength >
      WORKSHOP_HANDOFF_MAX_BINARY_BYTES
  ) {
    return handoffError(
      "handoff-binary-too-large",
      "Workshop PNG exceeds the 64 MiB limit.",
    );
  }
  const header = readPngHeader(handoff.pngBytes);
  validatePixelDimensions(handoff, header);
  validatePhysicalDimensions(handoff);
  validateRecipeAndIdentity(handoff);
  validateColorLibraryIdentity(handoff);

  let decoded: WorkshopPngDecodeResult;
  try {
    decoded = await (
      dependencies.decoder ?? defaultPngDecoder
    ).decode(handoff.pngBytes);
  } catch (error) {
    if (error instanceof WorkshopHandoffValidationError) {
      throw error;
    }
    return handoffError(
      "handoff-invalid-png",
      "Workshop PNG decoding failed.",
    );
  }
  if (
    decoded.width !== handoff.pixelWidth ||
    decoded.height !== handoff.pixelHeight
  ) {
    return handoffError(
      "handoff-dimensions-invalid",
      "Decoded Workshop PNG dimensions do not match its handoff.",
    );
  }
  if (!decoded.hasVisiblePixels) {
    return handoffError(
      "handoff-image-empty",
      "Workshop PNG is entirely transparent.",
    );
  }

  const converter = useConverterStore.getState();
  const occupied =
    converter.imageFile !== null || converter.batchFiles.length > 0;
  if (occupied && !options?.replaceExisting) {
    return { status: "needs-confirmation" };
  }
  const file = new File(
    [handoff.pngBytes],
    safeHandoffFilename(handoff),
    { type: "image/png" },
  );
  converter.loadWorkshopImageIntoConverter({
    file,
    pixelWidth: handoff.pixelWidth,
    pixelHeight: handoff.pixelHeight,
    targetWidthMm: handoff.recommendedWidthMm,
    targetHeightMm: handoff.recommendedHeightMm,
    source: handoff.recipeSource,
  });
  useWidgetStore.getState().setActiveTab("converter");
  return { status: "completed" };
}
