import apiClient from "./client";
import type {
  ConfirmPaletteRequest,
  ExtractResponse,
  GradientCardMaterialBulkExportResponse,
  GradientCardMaterialBulkImportResponse,
  GradientCardMaterialDeleteResponse,
  GradientCardMaterialLibraryResponse,
  GradientCardMaterialSaveResponse,
  GradientCardMaterialUpdateResponse,
  GradientCardStageAExtractResponse,
  LutPreviewResolvedCell,
  ManualFixResponse,
  ManualOrientationLabel,
  MaterialRecipePreviewRequest,
  MaterialRecipePreviewResponse,
  MaterialRecipeSwatchRequest,
  MaterialRecipeSwatchResponse,
  SingleStageExtractResponse,
  StageAFitResponse,
} from "./types";

/** 提取颜色 - multipart/form-data */
export async function extractColors(
  image: File,
  params: {
    corner_points: Array<[number, number]>;
    color_mode: string;
    page: string;
    eight_color_full_export: boolean;
    offset_x: number;
    offset_y: number;
    zoom: number;
    distortion: number;
    vignette_correction: boolean;
    auto_wb: boolean;
  },
): Promise<ExtractResponse> {
  const fd = new FormData();
  fd.append("image", image);
  fd.append("corner_points", JSON.stringify(params.corner_points));
  fd.append("color_mode", params.color_mode);
  fd.append("page", params.page);
  fd.append("eight_color_full_export", String(params.eight_color_full_export));
  fd.append("offset_x", String(params.offset_x));
  fd.append("offset_y", String(params.offset_y));
  fd.append("zoom", String(params.zoom));
  fd.append("distortion", String(params.distortion));
  fd.append("vignette_correction", String(params.vignette_correction));
  fd.append("auto_wb", String(params.auto_wb));

  const response = await apiClient.post<ExtractResponse>(
    "/extractor/extract",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Warp preview response (step 1) */
export interface ColorcheckerPoint {
  x: number;
  y: number;
}

export interface ColorcheckerDeltaSummary {
  mean: number | null;
  median: number | null;
  p95: number | null;
  max: number | null;
}

export interface ColorcheckerWorstPatch {
  index: number;
  label: string;
  deltaE00: number;
  referenceSrgb?: number[] | null;
  correctedSrgb?: number[] | null;
}

export interface ColorcheckerLuminancePoint {
  index: number;
  label: string;
  reference: number | null;
  captured: number | null;
  normalized: number | null;
  corrected: number | null;
  fitUsed: boolean;
  grayPatch: boolean;
}

export interface ColorcheckerDisplaySummary {
  deltaE00: ColorcheckerDeltaSummary;
  worstPatch: ColorcheckerWorstPatch | null;
  luminanceCurve: ColorcheckerLuminancePoint[];
  warnings: string[];
}

export interface ColorcheckerDetectResponse {
  detected: boolean;
  corners: ColorcheckerPoint[];
  patchOrientation: string;
  confidence: number;
  score: number | null;
  mode: string;
  reason: string;
  candidateCount: number;
}

export interface ColorcheckerWarpPreviewResponse {
  preview_url: string;
  preview_width: number;
  preview_height: number;
  auto_patch_points: ColorcheckerPoint[];
}

/** Automatically locate the ColorChecker chart corners */
export async function colorcheckerDetectChart(
  image: File,
  patchLayout: string = "4x6",
  assistPoint: ColorcheckerPoint | null = null,
): Promise<ColorcheckerDetectResponse> {
  const fd = new FormData();
  fd.append("image", image);
  fd.append("patch_layout", patchLayout);
  if (assistPoint) {
    fd.append("assist_point", JSON.stringify(assistPoint));
  }
  const response = await apiClient.post<ColorcheckerDetectResponse>(
    "/extractor/colorchecker-detect-chart",
    fd,
    { timeout: 120_000 },
  );
  return response.data;
}

/** Warp the ColorChecker region and return preview + auto 24 patch points */
export async function colorcheckerWarpPreview(
  image: File,
  cornerPoints: Array<[number, number]>,
  patchLayout: string = "4x6",
): Promise<ColorcheckerWarpPreviewResponse> {
  const fd = new FormData();
  fd.append("image", image);
  fd.append("corner_points", JSON.stringify(cornerPoints));
  fd.append("patch_layout", patchLayout);
  const response = await apiClient.post<ColorcheckerWarpPreviewResponse>(
    "/extractor/colorchecker-warp-preview",
    fd,
    { timeout: 120_000 },
  );
  return response.data;
}

/** Calibration response (step 2) */
export interface ColorcheckerCalibrateResponse {
  calibrated_url: string;
  overlay_url: string;
  width: number;
  height: number;
  patch_points: ColorcheckerPoint[];
  display_summary: ColorcheckerDisplaySummary;
}

/** Compute CCM and return calibrated image + overlay */
export async function colorcheckerCalibrate(
  image: File,
  cornerPoints: Array<[number, number]>,
  patchPoints: ColorcheckerPoint[] | null = null,
  patchLayout: string = "4x6",
): Promise<ColorcheckerCalibrateResponse> {
  const fd = new FormData();
  fd.append("image", image);
  fd.append("corner_points", JSON.stringify(cornerPoints));
  if (patchPoints) {
    fd.append("patch_points", JSON.stringify(patchPoints));
  }
  fd.append("patch_layout", patchLayout);
  const response = await apiClient.post<ColorcheckerCalibrateResponse>(
    "/extractor/colorchecker-calibrate",
    fd,
    { timeout: 120_000 },
  );
  return response.data;
}

/** Capture-origin tag forwarded as the ``image_source`` form field.
 * 上传给后端的输入图像来源标签。
 */
export type GradientCardImageSourceLabel = "raw" | "restored";

export async function extractGradientCardStageA(params: {
  datasetZip: File;
  whiteImage: File;
  blackImage: File;
  whiteCornerPoints: Array<[number, number]>;
  blackCornerPoints: Array<[number, number]>;
  manualWhiteOrientation?: ManualOrientationLabel | null;
  manualBlackOrientation?: ManualOrientationLabel | null;
  imageSource?: GradientCardImageSourceLabel | null;
}): Promise<GradientCardStageAExtractResponse> {
  const fd = new FormData();
  fd.append("dataset_zip", params.datasetZip);
  fd.append("white_image", params.whiteImage);
  fd.append("black_image", params.blackImage);
  fd.append("white_corner_points", JSON.stringify(params.whiteCornerPoints));
  fd.append("black_corner_points", JSON.stringify(params.blackCornerPoints));
  if (params.manualWhiteOrientation) {
    fd.append("manual_white_orientation", params.manualWhiteOrientation);
  }
  if (params.manualBlackOrientation) {
    fd.append("manual_black_orientation", params.manualBlackOrientation);
  }
  if (params.imageSource) {
    fd.append("image_source", params.imageSource);
  }
  const response = await apiClient.post<GradientCardStageAExtractResponse>(
    "/extractor/extract-gradient-card-stage-a",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

export async function saveGradientCardMaterial(params: {
  sessionId: string;
  materialName: string;
  targetDirectoryName?: string | null;
  saveMode?: "merge" | "override";
  brand?: string | null;
}): Promise<GradientCardMaterialSaveResponse> {
  const fd = new FormData();
  fd.append("session_id", params.sessionId);
  fd.append("material_name", params.materialName);
  if (params.targetDirectoryName) {
    fd.append("target_directory_name", params.targetDirectoryName);
  }
  if (params.saveMode) {
    fd.append("save_mode", params.saveMode);
  }
  if (params.brand && params.brand.trim()) {
    fd.append("brand", params.brand.trim());
  }
  const response = await apiClient.post<GradientCardMaterialSaveResponse>(
    "/extractor/save-gradient-card-material",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Encode each ``/``-separated segment of a saved-material directory_name so
 * the multi-segment path survives URL routing while still escaping spaces
 * and non-ASCII characters.
 * 对多段相对路径 directory_name 按 "/" 分段编码，保留分隔符。
 */
function encodeDirectoryNameForPath(directoryName: string): string {
  return directoryName
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

export async function deleteGradientCardMaterial(
  directoryName: string,
): Promise<GradientCardMaterialDeleteResponse> {
  const response = await apiClient.delete<GradientCardMaterialDeleteResponse>(
    `/extractor/gradient-card-materials/${encodeDirectoryNameForPath(directoryName)}`,
    { timeout: 3_600_000 },
  );
  return response.data;
}

export async function updateGradientCardMaterial(
  directoryName: string,
  payload: {
    materialName: string;
    brand?: string | null;
    estimatedRgb?: [number, number, number] | null;
  },
): Promise<GradientCardMaterialUpdateResponse> {
  const body: {
    material_name: string;
    brand: string | null;
    estimated_rgb?: [number, number, number];
  } = {
    material_name: payload.materialName.trim(),
    brand: payload.brand?.trim() || null,
  };
  if (Array.isArray(payload.estimatedRgb) && payload.estimatedRgb.length === 3) {
    body.estimated_rgb = [
      Math.max(0, Math.min(255, Math.round(payload.estimatedRgb[0]))),
      Math.max(0, Math.min(255, Math.round(payload.estimatedRgb[1]))),
      Math.max(0, Math.min(255, Math.round(payload.estimatedRgb[2]))),
    ];
  }
  const response = await apiClient.patch<GradientCardMaterialUpdateResponse>(
    `/extractor/gradient-card-materials/${encodeDirectoryNameForPath(directoryName)}`,
    body,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Forward-simulate a stacked material recipe. 正向模拟叠层耗材的预测颜色。 */
export async function previewMaterialRecipe(
  payload: MaterialRecipePreviewRequest,
): Promise<MaterialRecipePreviewResponse> {
  const response = await apiClient.post<MaterialRecipePreviewResponse>(
    "/extractor/material-recipe-preview",
    payload,
  );
  return response.data;
}

export async function listGradientCardMaterials(): Promise<GradientCardMaterialLibraryResponse> {
  const response = await apiClient.get<GradientCardMaterialLibraryResponse>(
    "/extractor/gradient-card-materials",
    { timeout: 3_600_000 },
  );
  return response.data;
}

export async function exportGradientCardMaterials(
  directoryNames: string[],
): Promise<GradientCardMaterialBulkExportResponse> {
  const response = await apiClient.post<GradientCardMaterialBulkExportResponse>(
    "/extractor/gradient-card-materials/export",
    { directory_names: directoryNames },
    { timeout: 3_600_000 },
  );
  return response.data;
}

export async function importGradientCardMaterials(
  archives: File[],
): Promise<GradientCardMaterialBulkImportResponse> {
  const fd = new FormData();
  archives.forEach((archive) => {
    fd.append("archives", archive);
  });
  const response = await apiClient.post<GradientCardMaterialBulkImportResponse>(
    "/extractor/gradient-card-materials/import",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 手动修正 LUT 单元格 - JSON */
export async function manualFixCell(
  sessionId: string,
  rowIndex: number,
  overrideColor: string,
): Promise<ManualFixResponse> {
  const response = await apiClient.post<ManualFixResponse>(
    "/extractor/manual-fix",
    {
      session_id: sessionId,
      row_index: rowIndex,
      override_color: overrideColor,
    },
  );
  return response.data;
}

export async function resolveLutPreviewCell(
  sessionId: string,
  x: number,
  y: number,
  cardIndex = 0,
): Promise<LutPreviewResolvedCell> {
  const response = await apiClient.post<LutPreviewResolvedCell>(
    "/extractor/resolve-cell",
    {
      session_id: sessionId,
      x,
      y,
      card_index: cardIndex,
    },
  );
  return response.data;
}

/** 合并 8 色分页 LUT */
export async function mergeEightColor(
  eightColorFullExport: boolean,
): Promise<ExtractResponse> {
  const response = await apiClient.post<ExtractResponse>(
    "/extractor/merge-8color",
    { eight_color_full_export: eightColorFullExport },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 合并 5 色扩展双页 LUT */
export async function mergeFiveColorExtended(): Promise<ExtractResponse> {
  const response = await apiClient.post<ExtractResponse>(
    "/extractor/merge-5color-extended",
    {},
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 自动白平衡预览（后端处理） */
export async function previewAutoWb(
  image: File | Blob,
  filename: string = "image.png",
): Promise<{ preview_url: string; width: number; height: number }> {
  const fd = new FormData();
  fd.append("image", image, filename);
  const response = await apiClient.post<{
    preview_url: string;
    width: number;
    height: number;
  }>("/extractor/preview-wb", fd, { timeout: 3_600_000 });
  return response.data;
}

export type ExtractorRotationDirection = "cw" | "ccw";

/**
 * 旋转图片 90°（后端处理）。
 * Rotate the supplied image by 90 degrees on the backend.
 *
 * @param image    File or Blob to rotate. (待旋转图片)
 * @param filename Display name for the upload payload. (上传时的文件名)
 * @param direction "cw" for clockwise or "ccw" for counter-clockwise; defaults
 *                  to "ccw" for backwards compatibility with existing callers.
 *                  ("cw" 顺时针 / "ccw" 逆时针；缺省 "ccw" 保持兼容)
 */
export async function rotateExtractorImage(
  image: File | Blob,
  filename: string = "image.png",
  direction: ExtractorRotationDirection = "ccw",
): Promise<{ preview_url: string; width: number; height: number }> {
  const fd = new FormData();
  fd.append("image", image, filename);
  const response = await apiClient.post<{
    preview_url: string;
    width: number;
    height: number;
  }>("/extractor/rotate", fd, {
    timeout: 3_600_000,
    params: { direction },
  });
  return response.data;
}

/** 确认调色板 */
export async function confirmPalette(
  payload: ConfirmPaletteRequest,
): Promise<{ status: string; message: string }> {
  const response = await apiClient.post<{ status: string; message: string }>(
    "/extractor/confirm-palette",
    payload,
  );
  return response.data;
}

/** Extract a single-stage dataset zip into 1_single_stage.json */
export async function extractSingleStageDataset(
  datasetZip: File,
): Promise<SingleStageExtractResponse> {
  const fd = new FormData();
  fd.append("dataset_zip", datasetZip);
  const response = await apiClient.post<SingleStageExtractResponse>(
    "/extractor/extract-single-stage",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Fit Stage A from either an extraction session or a raw stage JSON file. */
export async function fitStageA(params: {
  sessionId?: string | null;
  stageJsonFile?: File | null;
}): Promise<StageAFitResponse> {
  const fd = new FormData();
  if (params.sessionId) {
    fd.append("session_id", params.sessionId);
  }
  if (params.stageJsonFile) {
    fd.append("stage_json", params.stageJsonFile);
  }
  const response = await apiClient.post<StageAFitResponse>(
    "/extractor/fit-stage-a",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Generate a 3MF swatch file from collected material-archive recipes. */
export async function generateMaterialRecipeSwatch(
  request: MaterialRecipeSwatchRequest,
): Promise<MaterialRecipeSwatchResponse> {
  const response = await apiClient.post<MaterialRecipeSwatchResponse>(
    "/extractor/generate-material-swatch",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}
