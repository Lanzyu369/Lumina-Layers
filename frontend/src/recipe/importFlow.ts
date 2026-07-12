/**
 * Recipe import orchestration: coordinates parsing, restore, and store updates.
 * 配方导入编排：协调解析、恢复和 store 更新。
 */

import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { useWidgetStore } from "../stores/widgetStore";
import { getPrinters } from "../api/system";
import type { PrinterInfo } from "../api/types";
import { parseRecipeFile, restoreConverterRecipe } from "./importRecipe";
import { hasLuminaRecipe } from "./pngMetadata";
import type { LuminaRecipe } from "./types";
import type { RestoreResult } from "./importRecipe";
import {
  normalizeSlicerOptionId,
  resolveDeviceProfileOptionId,
  resolvePrinterOptionId,
} from "../utils/settingsOptionIds";

// ========== Share card detection ==========

/**
 * Check if a dropped/selected file is a Lumina share card or sidecar.
 * 检查拖放/选择的文件是否为 Lumina 分享卡或 sidecar。
 *
 * @returns true if the file contains a Lumina recipe.
 */
export async function isShareCardFile(file: File): Promise<boolean> {
  const name = file.name.toLowerCase();

  // .lumina.json sidecar
  if (name.endsWith(".lumina.json")) return true;

  // PNG with Lumina metadata
  if (name.endsWith(".png")) {
    try {
      return await hasLuminaRecipe(file);
    } catch {
      return false;
    }
  }

  return false;
}

// ========== Import orchestration ==========

export interface ImportPreview {
  recipe: LuminaRecipe;
  restoreResult: RestoreResult;
  /** Blob URL for the cover image preview (must be revoked after use). */
  coverUrl: string | null;
  /** Printer registry snapshot used to reconcile older share cards. */
  printerOptions?: PrinterInfo[];
}

/**
 * Parse a share card file and prepare a preview for the confirmation dialog.
 * 解析分享卡文件，为确认对话框准备预览。
 *
 * This does NOT apply changes to the store — call `applyImport` after user confirms.
 */
export async function prepareImport(file: File): Promise<ImportPreview> {
  const { recipe, source } = await parseRecipeFile(file);

  const converterState = useConverterStore.getState();
  const lutListFull = converterState.lutListFull;

  // Build fingerprint map from local LUT list
  const localFingerprints: Record<string, string> = {};
  for (const lut of lutListFull) {
    if (lut.fingerprint) {
      localFingerprints[lut.name] = lut.fingerprint;
    }
  }

  const restoreResult = restoreConverterRecipe(recipe, lutListFull, localFingerprints);

  // Build cover preview URL
  let coverUrl: string | null = null;
  if (source === "png") {
    // For PNG share cards, the file itself is the cover image
    coverUrl = URL.createObjectURL(file);
  }

  let printerOptions: PrinterInfo[] = [];
  try {
    printerOptions = await getPrinters();
  } catch {
    printerOptions = [];
  }

  return { recipe, restoreResult, coverUrl, printerOptions };
}

/**
 * Revoke a cover URL created during import preview.
 * 释放导入预览时创建的封面 URL。
 */
export function revokeImportCoverUrl(coverUrl: string | null): void {
  if (coverUrl) {
    URL.revokeObjectURL(coverUrl);
  }
}

/**
 * Apply a prepared import to the converter store.
 * 将准备好的导入应用到 converter store。
 *
 * This restores all parameters and sets the image file, triggering the
 * normal preview pipeline.
 */
export function applyImport(
  restoreResult: RestoreResult,
  printerOptions: PrinterInfo[] = [],
): void {
  const store = useConverterStore.getState();
  const conv = restoreResult.recipe.recipe.converter;

  const importedTolerance =
    conv?.source?.material_delta_e00_tolerance;
  if (typeof importedTolerance === "number") {
    useSettingsStore
      .getState()
      .setMaterialDeltaE00Tolerance(importedTolerance);
  }

  // 1. Use the named importRecipeState action (handles crop suppression internally)
  store.importRecipeState(
    restoreResult.state,
    restoreResult.assetFile,
    restoreResult.heightmapFile,
  );

  // 2. Apply settings from recipe (printer/slicer) if present
  if (conv) {
    const settingsState = useSettingsStore.getState();
    const nextSlicer = conv.device.slicer
      ? normalizeSlicerOptionId(conv.device.slicer)
      : settingsState.slicerSoftware;
    const nextPrinter = conv.device.printer_id
      ? resolvePrinterOptionId(conv.device.printer_id, printerOptions, nextSlicer)
      : settingsState.printerModel;
    const nextNozzle = conv.device.nozzle_size ?? settingsState.nozzleSize;
    const selectedPrinter = printerOptions.find((printer) => printer.id === nextPrinter);

    if (nextPrinter && nextPrinter !== settingsState.printerModel) {
      settingsState.setPrinterModel(nextPrinter);
    }
    if (nextSlicer && nextSlicer !== settingsState.slicerSoftware) {
      settingsState.setSlicerSoftware(nextSlicer);
    }
    if (nextNozzle && nextNozzle !== settingsState.nozzleSize) {
      settingsState.setNozzleSize(nextNozzle as "0.2" | "0.4");
    }
    const nextDeviceProfileId =
      conv.device.device_profile_id ||
      resolveDeviceProfileOptionId(
        settingsState.deviceProfileId,
        selectedPrinter,
        nextSlicer,
        nextNozzle,
      );
    if (nextDeviceProfileId !== settingsState.deviceProfileId) {
      settingsState.setDeviceProfileId(nextDeviceProfileId);
    } else if (
      !conv.device.device_profile_id &&
      !selectedPrinter?.device_profiles?.some(
        (profile) => profile.device_profile_id === settingsState.deviceProfileId,
      )
    ) {
      settingsState.setDeviceProfileId("");
    }
    if (
      typeof conv.base.svg_pixels_per_mm === "number" &&
      conv.base.svg_pixels_per_mm !== settingsState.svgPixelsPerMm
    ) {
      settingsState.setSvgPixelsPerMm(conv.base.svg_pixels_per_mm);
    }
  }

  // 3. Switch to converter tab
  useWidgetStore.getState().setActiveTab("converter");
}

/**
 * Export the current converter state as a share card PNG (download trigger).
 * 将当前 converter 状态导出为分享卡 PNG（触发下载）。
 */
export async function exportShareCard(): Promise<void> {
  const { exportConverterRecipe, buildFullRecipe, buildRecipeAssets, buildCoverImage } =
    await import("./exportRecipe");
  const { embedRecipeInPng } = await import("./pngMetadata");
  const { sha256String } = await import("./utils");

  const converterState = useConverterStore.getState();
  const settingsState = useSettingsStore.getState();

  // Validate prerequisites
  if (!converterState.imageFile) {
    throw new Error("No image file loaded");
  }
  if (!converterState.previewImageUrl) {
    throw new Error("No preview available — please generate a preview first");
  }

  // Get LUT fingerprint
  const lutInfo = converterState.lutListFull.find(
    (l) => l.name === converterState.lut_name,
  );
  const lutFingerprint = lutInfo?.fingerprint ?? "";

  // 1. Build converter recipe
  const converterRecipe = exportConverterRecipe(
    converterState,
    settingsState,
    lutFingerprint,
  );

  // 2. Build assets
  const assets = await buildRecipeAssets(
    converterState.imageFile,
    converterState.heightmapFile,
  );

  // 3. Build cover image from preview
  const { blob: coverBlob, cover } = await buildCoverImage(
    converterState.previewImageUrl,
  );

  // 4. Build full recipe
  const fullRecipe = await buildFullRecipe(converterRecipe, cover, assets);

  // 5. Compute recipe JSON SHA-256
  const recipeJsonForHash = JSON.stringify(fullRecipe.recipe);
  const recipeSha256 = await sha256String(recipeJsonForHash);

  // 6. Embed into PNG
  const shareCardBlob = await embedRecipeInPng(coverBlob, fullRecipe, recipeSha256);

  // 7. Trigger download
  const filename = converterState.imageFile.name.replace(/\.[^.]+$/, "") + "-share.png";
  triggerDownload(shareCardBlob, filename);
}

/**
 * Export the current converter state as a .lumina.json sidecar file.
 * 将当前 converter 状态导出为 .lumina.json sidecar 文件。
 */
export async function exportSidecar(): Promise<void> {
  const { exportConverterRecipe, buildFullRecipe, buildRecipeAssets, buildCoverImage } =
    await import("./exportRecipe");

  const converterState = useConverterStore.getState();
  const settingsState = useSettingsStore.getState();

  if (!converterState.imageFile) {
    throw new Error("No image file loaded");
  }
  if (!converterState.previewImageUrl) {
    throw new Error("No preview available — please generate a preview first");
  }

  const lutInfo = converterState.lutListFull.find(
    (l) => l.name === converterState.lut_name,
  );
  const lutFingerprint = lutInfo?.fingerprint ?? "";

  const converterRecipe = exportConverterRecipe(
    converterState,
    settingsState,
    lutFingerprint,
  );

  const assets = await buildRecipeAssets(
    converterState.imageFile,
    converterState.heightmapFile,
  );

  const { cover } = await buildCoverImage(converterState.previewImageUrl);
  const fullRecipe = await buildFullRecipe(converterRecipe, cover, assets);

  const json = JSON.stringify(fullRecipe, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const filename = converterState.imageFile.name.replace(/\.[^.]+$/, "") + ".lumina.json";
  triggerDownload(blob, filename);
}

// ========== Helpers ==========

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
