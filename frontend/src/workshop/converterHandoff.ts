import { ColorMode, StructureMode } from "../api/types";
import {
  resolveConverterSourceSelection,
  useConverterStore,
} from "../stores/converter";
import { useWidgetStore } from "../stores/widgetStore";
import type {
  WorkshopImageHandoff as SdkWorkshopImageHandoff,
} from "./contracts";
import {
  WorkshopProjectStorageError,
  assertWorkshopRecipeEnvelopeWithinQuota,
} from "./projectStorage";
import {
  buildWorkshopColorLibrary,
  getWorkshopColorLibrarySelectionKey,
} from "./colorLibrary";
import { rememberWorkshopHandoffColorLibraryId } from "./handoffMetadata";

export const WORKSHOP_HANDOFF_MAX_BINARY_BYTES = 64 * 1024 * 1024;
export const WORKSHOP_HANDOFF_MAX_EDGE = 16_384;
export const WORKSHOP_HANDOFF_MAX_PIXELS = 64_000_000;

export type WorkshopHandoffResult =
  | { status: "needs-confirmation" }
  | { status: "completed" };

export interface WorkshopHandoffOptions {
  replaceExisting?: boolean;
}

const WORKSHOP_HANDOFF_MIN_MM = 0.5;
const WORKSHOP_HANDOFF_MAX_MM = 9_999;
const WORKSHOP_GRID_MIN_PITCH_MM = 0.01;
const WORKSHOP_GRID_MAX_PITCH_MM = 9_999;
const WORKSHOP_HANDOFF_MIN_THICKNESS_MM = 0.2;
const WORKSHOP_HANDOFF_MAX_THICKNESS_MM = 50;
const BACKING_LAYER_HEIGHT_MM = 0.08;
const BACKING_MIN_THICKNESS_MM = 0.24;
const BACKING_MAX_THICKNESS_MM = 10;
const PHYSICAL_SIZE_TOLERANCE_MM = 1e-6;
const SVG_ASPECT_RATIO_TOLERANCE = 1e-6;
const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10] as const;

function physicalSvgLength(value: number): string {
  const rounded = Number(value.toFixed(6));
  return `${Object.is(rounded, -0) ? 0 : rounded}mm`;
}

export type WorkshopHandoffValidationErrorCode =
  | "handoff-invalid-payload"
  | "handoff-binary-too-large"
  | "handoff-invalid-png"
  | "handoff-invalid-svg"
  | "handoff-dimensions-invalid"
  | "handoff-image-empty"
  | "handoff-layout-invalid"
  | "handoff-physical-size-invalid"
  | "handoff-recipe-invalid"
  | "handoff-recipe-too-large";

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
  if (
    handoff.recommendedTotalThicknessMm !== undefined &&
    !finiteInRange(
      handoff.recommendedTotalThicknessMm,
      WORKSHOP_HANDOFF_MIN_THICKNESS_MM,
      WORKSHOP_HANDOFF_MAX_THICKNESS_MM,
    )
  ) {
    handoffError(
      "handoff-physical-size-invalid",
      "Workshop handoff total thickness is out of range.",
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

function roundToBackingLayer(value: number): number {
  return Number(
    (Math.round(value / BACKING_LAYER_HEIGHT_MM) *
      BACKING_LAYER_HEIGHT_MM).toFixed(2),
  );
}

function recommendedBackingThicknessMm(
  totalThicknessMm: number,
): number {
  const converter = useConverterStore.getState();
  const sourceSelection = resolveConverterSourceSelection(converter);
  const colorLayers = Math.max(
    1,
    Math.round(
      converter.color_layers ??
        sourceSelection.color_layers ??
        converter.selectedLutInfo?.max_color_layers ??
        5,
    ),
  );
  const layerHeightMm =
    converter.layer_height_mm ??
    sourceSelection.layer_height_mm ??
    converter.selectedLutInfo?.layer_height_mm ??
    BACKING_LAYER_HEIGHT_MM;
  const colorPasses =
    converter.structure_mode === StructureMode.DOUBLE_SIDED &&
    converter.color_mode !== ColorMode.FIVE_COLOR_EXT
      ? 2
      : 1;
  const unquantizedBacking =
    totalThicknessMm - colorLayers * layerHeightMm * colorPasses;
  const clampedBacking = Math.min(
    BACKING_MAX_THICKNESS_MM,
    Math.max(BACKING_MIN_THICKNESS_MM, unquantizedBacking),
  );
  return roundToBackingLayer(clampedBacking);
}

function applyRecommendedTotalThickness(
  totalThicknessMm: number | undefined,
): void {
  if (totalThicknessMm === undefined) return;
  useConverterStore
    .getState()
    .setSpacerThick(recommendedBackingThicknessMm(totalThicknessMm));
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
  extension: "png" | "svg" = "png",
): string {
  const safeModule = handoff.moduleId.replace(
    /[^A-Za-z0-9._-]+/g,
    "-",
  );
  const safeProject = handoff.projectId
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .slice(0, 96);
  return `${safeModule}-${safeProject}.${extension}`;
}

const FORBIDDEN_SVG_ELEMENTS = new Set([
  "script",
  "foreignobject",
  "iframe",
  "object",
  "embed",
  "image",
  "audio",
  "video",
  "link",
  "meta",
  "style",
  "animate",
  "animatemotion",
  "animatetransform",
  "set",
  "mask",
  "clippath",
  "filter",
  "pattern",
]);

function decodeAndValidateSvg(
  bytes: ArrayBuffer,
  expectedAspectRatio: number,
  physicalWidthMm: number,
  physicalHeightMm: number,
): string {
  if (
    bytes.byteLength === 0 ||
    bytes.byteLength > WORKSHOP_HANDOFF_MAX_BINARY_BYTES
  ) {
    return handoffError(
      "handoff-binary-too-large",
      "Workshop SVG is empty or exceeds the 64 MiB limit.",
    );
  }
  let source: string;
  try {
    source = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return handoffError(
      "handoff-invalid-svg",
      "Workshop SVG is not valid UTF-8.",
    );
  }
  if (source.includes("\0")) {
    return handoffError(
      "handoff-invalid-svg",
      "Workshop SVG contains invalid null bytes.",
    );
  }

  const documentNode = new DOMParser().parseFromString(
    source,
    "image/svg+xml",
  );
  const root = documentNode.documentElement;
  if (
    root.localName.toLowerCase() !== "svg" ||
    root.namespaceURI !== "http://www.w3.org/2000/svg" ||
    documentNode.querySelector("parsererror") !== null
  ) {
    return handoffError(
      "handoff-invalid-svg",
      "Workshop SVG markup is invalid.",
    );
  }

  const viewBox = (root.getAttribute("viewBox") ?? "")
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  if (
    viewBox.length !== 4 ||
    viewBox.some((value) => !Number.isFinite(value)) ||
    viewBox[2] <= 0 ||
    viewBox[3] <= 0
  ) {
    return handoffError(
      "handoff-invalid-svg",
      "Workshop SVG must declare a finite positive viewBox.",
    );
  }
  const svgAspectRatio = viewBox[2] / viewBox[3];
  if (
    Math.abs(svgAspectRatio - expectedAspectRatio) >
    SVG_ASPECT_RATIO_TOLERANCE *
      Math.max(1, svgAspectRatio, expectedAspectRatio)
  ) {
    return handoffError(
      "handoff-dimensions-invalid",
      "Workshop SVG viewBox does not match the PNG fallback dimensions.",
    );
  }

  for (const element of documentNode.querySelectorAll("*")) {
    if (FORBIDDEN_SVG_ELEMENTS.has(element.localName.toLowerCase())) {
      return handoffError(
        "handoff-invalid-svg",
        "Workshop SVG contains active, embedded, or unsupported content.",
      );
    }
    for (const attribute of element.attributes) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim();
      if (
        name.startsWith("on") ||
        ((name === "href" || name.endsWith(":href")) &&
          !value.startsWith("#")) ||
        /@import/i.test(value) ||
        /url\((?!\s*['"]?#)/i.test(value) ||
        /javascript\s*:/i.test(value)
      ) {
        return handoffError(
          "handoff-invalid-svg",
          "Workshop SVG contains an external or executable reference.",
        );
      }
    }
  }
  const printableElements = root.querySelectorAll(
    "path,rect,circle,ellipse,polygon,polyline,use",
  );
  const hasPrintableGeometry = [...printableElements].some(
    (element) =>
      element.closest("defs,mask,clipPath,symbol") === null &&
      (element.localName.toLowerCase() !== "path" ||
        (element.getAttribute("d") ?? "").trim().length > 0),
  );
  if (!hasPrintableGeometry) {
    return handoffError(
      "handoff-image-empty",
      "Workshop SVG does not contain printable geometry.",
    );
  }
  root.setAttribute("width", physicalSvgLength(physicalWidthMm));
  root.setAttribute("height", physicalSvgLength(physicalHeightMm));
  return new XMLSerializer().serializeToString(root);
}

export async function handoffWorkshopPngToConverter(
  handoff: SdkWorkshopImageHandoff,
  options?: WorkshopHandoffOptions,
  dependencies: WorkshopPngHandoffDependencies = {},
): Promise<WorkshopHandoffResult> {
  return handoffWorkshopPayloadToConverter(
    handoff,
    options,
    dependencies,
  );
}

/**
 * Loads the safest available Workshop source into the converter while keeping
 * the PNG fallback, physical size, recipe, and material identity aligned.
 *
 * 将创意工坊提供的最安全图源载入转换器，同时保持 PNG 回退、物理尺寸、
 * 配方与耗材身份一致。
 */
export async function handoffWorkshopPayloadToConverter(
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

  const svgSource =
    handoff.svgBytes instanceof ArrayBuffer
      ? decodeAndValidateSvg(
          handoff.svgBytes,
          handoff.pixelWidth / handoff.pixelHeight,
          handoff.recommendedWidthMm,
          handoff.recommendedHeightMm,
        )
      : null;

  const converter = useConverterStore.getState();
  const occupied =
    converter.imageFile !== null || converter.batchFiles.length > 0;
  if (occupied && !options?.replaceExisting) {
    return { status: "needs-confirmation" };
  }
  const file =
    svgSource === null
      ? new File(
          [handoff.pngBytes],
          safeHandoffFilename(handoff),
          { type: "image/png" },
        )
      : new File(
          [svgSource],
          safeHandoffFilename(handoff, "svg"),
          { type: "image/svg+xml" },
        );
  rememberWorkshopHandoffColorLibraryId(
    handoff.recipeSource,
    handoff.colorLibraryId,
    buildWorkshopColorLibrary(converter),
    getWorkshopColorLibrarySelectionKey(converter),
  );
  converter.loadWorkshopImageIntoConverter({
    file,
    pixelWidth: handoff.pixelWidth,
    pixelHeight: handoff.pixelHeight,
    targetWidthMm: handoff.recommendedWidthMm,
    targetHeightMm: handoff.recommendedHeightMm,
    source: handoff.recipeSource,
  });
  applyRecommendedTotalThickness(
    handoff.recommendedTotalThicknessMm,
  );
  useWidgetStore.getState().setActiveTab("converter");
  return { status: "completed" };
}
