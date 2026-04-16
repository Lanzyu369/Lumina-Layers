import apiClient from "./client";
import type {
  ConfirmPaletteRequest,
  ExtractResponse,
  GradientCardMaterialDeleteResponse,
  GradientCardMaterialLibraryResponse,
  GradientCardMaterialSaveResponse,
  GradientCardStageAExtractResponse,
  ManualFixResponse,
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
    { timeout: 600_000 },
  );
  return response.data;
}

export async function extractGradientCardStageA(params: {
  datasetZip: File;
  whiteImage: File;
  blackImage: File;
  whiteCornerPoints: Array<[number, number]>;
  blackCornerPoints: Array<[number, number]>;
}): Promise<GradientCardStageAExtractResponse> {
  const fd = new FormData();
  fd.append("dataset_zip", params.datasetZip);
  fd.append("white_image", params.whiteImage);
  fd.append("black_image", params.blackImage);
  fd.append("white_corner_points", JSON.stringify(params.whiteCornerPoints));
  fd.append("black_corner_points", JSON.stringify(params.blackCornerPoints));
  const response = await apiClient.post<GradientCardStageAExtractResponse>(
    "/extractor/extract-gradient-card-stage-a",
    fd,
    { timeout: 600_000 },
  );
  return response.data;
}

export async function saveGradientCardMaterial(params: {
  sessionId: string;
  materialName: string;
  targetDirectoryName?: string | null;
}): Promise<GradientCardMaterialSaveResponse> {
  const fd = new FormData();
  fd.append("session_id", params.sessionId);
  fd.append("material_name", params.materialName);
  if (params.targetDirectoryName) {
    fd.append("target_directory_name", params.targetDirectoryName);
  }
  const response = await apiClient.post<GradientCardMaterialSaveResponse>(
    "/extractor/save-gradient-card-material",
    fd,
    { timeout: 600_000 },
  );
  return response.data;
}

export async function deleteGradientCardMaterial(
  directoryName: string,
): Promise<GradientCardMaterialDeleteResponse> {
  const response = await apiClient.delete<GradientCardMaterialDeleteResponse>(
    `/extractor/gradient-card-materials/${encodeURIComponent(directoryName)}`,
    { timeout: 60_000 },
  );
  return response.data;
}

export async function listGradientCardMaterials(): Promise<GradientCardMaterialLibraryResponse> {
  const response = await apiClient.get<GradientCardMaterialLibraryResponse>(
    "/extractor/gradient-card-materials",
    { timeout: 60_000 },
  );
  return response.data;
}

/** 手动修正 LUT 单元格 - JSON */
export async function manualFixCell(
  sessionId: string,
  cellCoord: [number, number],
  overrideColor: string,
): Promise<ManualFixResponse> {
  const response = await apiClient.post<ManualFixResponse>(
    "/extractor/manual-fix",
    {
      session_id: sessionId,
      cell_coord: cellCoord,
      override_color: overrideColor,
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
    { timeout: 600_000 },
  );
  return response.data;
}

/** 合并 5 色扩展双页 LUT */
export async function mergeFiveColorExtended(): Promise<ExtractResponse> {
  const response = await apiClient.post<ExtractResponse>(
    "/extractor/merge-5color-extended",
    {},
    { timeout: 600_000 },
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
  }>("/extractor/preview-wb", fd, { timeout: 60_000 });
  return response.data;
}

/** 旋转图片 90°（后端处理） */
export async function rotateExtractorImage(
  image: File | Blob,
  filename: string = "image.png",
): Promise<{ preview_url: string; width: number; height: number }> {
  const fd = new FormData();
  fd.append("image", image, filename);
  const response = await apiClient.post<{
    preview_url: string;
    width: number;
    height: number;
  }>("/extractor/rotate", fd, { timeout: 60_000 });
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
    { timeout: 600_000 },
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
    { timeout: 600_000 },
  );
  return response.data;
}
