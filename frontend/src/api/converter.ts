import apiClient from "./client";
import type {
  ConvertPreviewRequest,
  ConvertGenerateRequest,
  PreviewResponse,
  GenerateResponse,
  LargeFormatGenerateRequest,
  LargeFormatGenerateResponse,
  PuzzleGenerateRequest,
  PuzzleGenerateResponse,
  PuzzleLayoutPreviewRequest,
  PuzzleLayoutPreviewResponse,
  LutListResponse,
  BedSizeListResponse,
  HeightmapUploadResponse,
  LutColorsResponse,
  BatchConvertParams,
  BatchResponse,
  ColorReplaceResponse,
  ColorHighlightResponse,
  GradientGroupsResponse,
  RegionDetectResponse,
  RegionReplaceResponse,
  RecipePredictRequest,
  RecipePredictResponse,
  RecipeOverrideApplyRequest,
  RecipeOverrideApplyResponse,
  RegionRecipeRequest,
  RegionRecipeResponse,
  AutoDetectColorsResponse,
} from "./types";

/** 上传图片 + 参数，获取 2D 预览（返回 JSON，含 session_id 和 preview_url） */
export async function convertPreview(
  image: File,
  params: ConvertPreviewRequest,
  signal?: AbortSignal,
): Promise<PreviewResponse> {
  const fd = new FormData();
  fd.append("image", image);
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) {
      continue;
    }
    if (Array.isArray(value)) {
      fd.append(key, JSON.stringify(value));
      continue;
    }
    fd.append(key, String(value));
  }

  const response = await apiClient.post<PreviewResponse>(
    "/convert/preview",
    fd,
    {
      timeout: 0,
      signal,
    },
  );
  return response.data;
}

/** 使用 session_id + 全部参数，生成 3MF 模型 */
export async function convertGenerate(
  sessionId: string,
  params: ConvertGenerateRequest,
): Promise<GenerateResponse> {
  const response = await apiClient.post<GenerateResponse>(
    "/convert/generate",
    { session_id: sessionId, params },
    { timeout: 0 },
  );
  return response.data;
}

/** 大画幅模式：切割图片并生成多片 3MF 压缩包 */
export async function convertGenerateLargeFormat(
  sessionId: string,
  params: LargeFormatGenerateRequest,
): Promise<LargeFormatGenerateResponse> {
  const response = await apiClient.post<LargeFormatGenerateResponse>(
    "/convert/generate-large-format",
    { session_id: sessionId, params },
    { timeout: 0 },
  );
  return response.data;
}

/** 拼图模式：生成叠线预览覆盖图 */
export async function convertPuzzleLayoutPreview(
  sessionId: string,
  params: PuzzleLayoutPreviewRequest,
): Promise<PuzzleLayoutPreviewResponse> {
  const response = await apiClient.post<PuzzleLayoutPreviewResponse>(
    "/convert/puzzle-layout-preview",
    { session_id: sessionId, params },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 拼图模式：逐块生成并导出单个 3MF */
export async function convertGeneratePuzzle(
  sessionId: string,
  params: PuzzleGenerateRequest,
): Promise<PuzzleGenerateResponse> {
  const response = await apiClient.post<PuzzleGenerateResponse>(
    "/convert/generate-puzzle",
    { session_id: sessionId, params },
    { timeout: 0 },
  );
  return response.data;
}

/** 获取可用 LUT 列表 */
export async function fetchLutList(): Promise<LutListResponse> {
  const response = await apiClient.get<LutListResponse>("/lut/list", {
    timeout: 3_600_000,
  });
  return response.data;
}

/** 上传 LUT 文件到预设目录 */
export async function uploadLut(
  file: File,
): Promise<{ status: string; message: string; name: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const response = await apiClient.post<{
    status: string;
    message: string;
    name: string;
  }>("/lut/upload", fd, { timeout: 3_600_000 });
  return response.data;
}

/** 根据 file_id 获取文件下载 URL */
export function getFileUrl(fileId: string): string {
  return `/api/files/${fileId}`;
}

/** 获取可用热床尺寸列表 */
export async function fetchBedSizes(): Promise<BedSizeListResponse> {
  const response =
    await apiClient.get<BedSizeListResponse>("/convert/bed-sizes");
  return response.data;
}

/** 获取空热床 3D 预览 GLB URL */
export async function fetchBedPreview(bedLabel: string): Promise<string> {
  const response = await apiClient.get<{ preview_3d_url: string }>(
    "/convert/bed-preview",
    { params: { bed_label: bedLabel } },
  );
  return response.data.preview_3d_url;
}

/** 上传高度图并获取基于高度图的 color_height_map */
export async function uploadHeightmap(
  heightmapFile: File,
  sessionId: string,
): Promise<HeightmapUploadResponse> {
  const fd = new FormData();
  fd.append("heightmap", heightmapFile);
  fd.append("session_id", sessionId);

  const response = await apiClient.post<HeightmapUploadResponse>(
    "/convert/upload-heightmap",
    fd,
    { timeout: 0 },
  );
  return response.data;
}

/** 获取 LUT 中所有可用颜色 */
export async function fetchLutColors(
  lutName: string,
): Promise<LutColorsResponse> {
  const response = await apiClient.get<LutColorsResponse>(
    `/lut/${encodeURIComponent(lutName)}/colors`,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 裁剪响应 */
export interface CropResponse {
  status: string;
  message: string;
  cropped_url: string;
  width: number;
  height: number;
}

/** 发送裁剪坐标到后端，返回裁剪后的图片信息 */
export async function cropImage(
  file: File,
  x: number,
  y: number,
  width: number,
  height: number,
): Promise<CropResponse> {
  const fd = new FormData();
  fd.append("image", file);
  fd.append("x", String(Math.round(x)));
  fd.append("y", String(Math.round(y)));
  fd.append("width", String(Math.round(width)));
  fd.append("height", String(Math.round(height)));
  const response = await apiClient.post<CropResponse>("/convert/crop", fd);
  return response.data;
}

/** 批量转换：上传多张图片 + 共享参数，返回批量处理结果 */
export async function convertBatch(
  images: File[],
  params: BatchConvertParams,
): Promise<BatchResponse> {
  const fd = new FormData();
  for (const file of images) {
    fd.append("images", file);
  }
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) {
      continue;
    }
    fd.append(key, String(value));
  }
  const response = await apiClient.post<BatchResponse>("/convert/batch", fd, {
    timeout: 0,
  });
  return response.data;
}

/** 替换预览中的单个颜色 */
export async function replaceColor(
  sessionId: string,
  selectedColor: string,
  replacementColor: string,
): Promise<ColorReplaceResponse> {
  const response = await apiClient.post<ColorReplaceResponse>(
    "/convert/replace-color",
    {
      session_id: sessionId,
      selected_color: selectedColor,
      replacement_color: replacementColor,
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 分层图片响应 */
export interface LayerImageInfo {
  layer_index: number;
  name: string;
  url: string;
}

export interface LayerImagesResponse {
  session_id: string;
  layers: LayerImageInfo[];
}

/** 获取分层材料预览图 */
export async function fetchLayerImages(
  sessionId: string,
): Promise<LayerImagesResponse> {
  const response = await apiClient.get<LayerImagesResponse>(
    `/convert/layer-images/${sessionId}`,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Optional scope arguments for ``colorHighlight``.
 * colorHighlight 的可选裁剪参数。
 *
 * Prefer ``gradientGroupIndex + gradientRegionIndex`` to restrict the
 * highlight to the exact pixel mask of a single gradient sub-region — this
 * is the correct fix for "clicking a sub-region lights up the whole group"
 * because it consults the cached per-pixel region_id_map on the backend
 * instead of an imprecise bounding rectangle.
 * ``regionBbox`` remains as a legacy fallback for clients that cannot yet
 * supply region identifiers; its accuracy is limited to the region's
 * external rectangle and should be avoided for gradient-region flows.
 */
export interface ColorHighlightScope {
  gradientGroupIndex?: number;
  gradientRegionIndex?: number;
  regionBbox?: [number, number, number, number];
}

/**
 * 高亮指定颜色的所有像素。
 *
 * - 若传入 ``gradientGroupIndex + gradientRegionIndex``，后端使用预览生成
 *   时缓存的每像素 region 编码图精确裁剪，只点亮该子区域的像素。
 * - 否则若传入 ``regionBbox``，按矩形 bbox 回退裁剪。
 * - 两者都未传时，点亮整张预览上所有匹配像素。
 */
export async function colorHighlight(
  sessionId: string,
  colorHexes: string[],
  scope?: ColorHighlightScope,
): Promise<ColorHighlightResponse> {
  const body: Record<string, unknown> = {
    session_id: sessionId,
    color_hexes: colorHexes,
  };
  if (
    scope?.gradientGroupIndex !== undefined &&
    scope?.gradientRegionIndex !== undefined
  ) {
    body.gradient_group_index = scope.gradientGroupIndex;
    body.gradient_region_index = scope.gradientRegionIndex;
  } else if (scope?.regionBbox) {
    body.region_bbox = scope.regionBbox;
  }
  const response = await apiClient.post<ColorHighlightResponse>(
    "/convert/color-highlight",
    body,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 检测点击位置的连通区域 */
export async function detectRegion(
  sessionId: string,
  x: number,
  y: number,
): Promise<RegionDetectResponse> {
  const response = await apiClient.post<RegionDetectResponse>(
    "/convert/region-detect",
    { session_id: sessionId, x, y },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Scope object for :func:`regionReplace` identifying *which* spatial region
 * should be edited. Leave undefined to consume the one-shot mask that
 * :func:`regionDetect` stashed in the session. Provide a
 * :obj:`GradientRegionReplaceScope` to rebuild the mask on the server from
 * the cached per-pixel ``gradient_region_id_map`` — the only way to scope
 * the edit to a single banded sub-region when several disjoint regions
 * share the same quantised hex.
 * :func:`regionReplace` 的区域来源：不传 = 用 click-detected 的一次性
 * mask（legacy）；传 GradientRegionReplaceScope = 服务端从 region_id_map
 * 现场生成 mask。仅传 ``gradientGroupIndex`` = 整组 mask（去海带纹）；
 * 同时传 ``gradientRegionIndex`` = 单子区域 mask。
 */
export interface GradientRegionReplaceScope {
  gradientGroupIndex: number;
  /** 不传时 mask 覆盖整个 group（去海带纹） */
  gradientRegionIndex?: number;
}

/** 替换已选中连通区域的颜色 */
export async function regionReplace(
  sessionId: string,
  replacementColor: string,
  scope?: GradientRegionReplaceScope,
): Promise<RegionReplaceResponse> {
  const body: Record<string, unknown> = {
    session_id: sessionId,
    replacement_color: replacementColor,
  };
  if (scope) {
    body.gradient_group_index = scope.gradientGroupIndex;
    if (scope.gradientRegionIndex !== undefined) {
      body.gradient_region_index = scope.gradientRegionIndex;
    }
  }
  const response = await apiClient.post<RegionReplaceResponse>(
    "/convert/region-replace",
    body,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Predict a custom recipe color against the active preview session/source. */
export async function predictCustomRecipe(
  request: RecipeOverrideApplyRequest | RecipePredictRequest,
): Promise<RecipePredictResponse> {
  const response = await apiClient.post<RecipePredictResponse>(
    "/convert/predict-recipe",
    {
      session_id: request.session_id,
      recipe: request.recipe,
      layer_order: request.layer_order,
      color_layers: request.color_layers,
      layer_height_mm: request.layer_height_mm,
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Apply a custom recipe override to one or more selected regions. */
export async function applyRecipeOverride(
  request: RecipeOverrideApplyRequest,
): Promise<RecipeOverrideApplyResponse> {
  const response = await apiClient.post<RecipeOverrideApplyResponse>(
    "/convert/apply-recipe-override",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Read the current per-layer material stack for one or more selected regions.
 * 读取选中区域当前每层的堆叠材料，用于自定义配方对话框预设下拉。
 *
 * The Custom Recipe dialog calls this on open so the per-layer dropdowns
 * pre-populate with each region's real matched recipe instead of the
 * all-White default. Short timeout (15s) because the backend path is a
 * cheap ``material_matrix[mask]`` sample — not a full solve.
 *
 * 自定义配方对话框打开时调用，让每层下拉预设为该区域真实匹配的配方而
 * 非全白默认。超时取短值（15s），后端只是 ``material_matrix[mask]`` 的
 * 轻量采样，不是完整求解。
 */
export async function fetchRegionRecipe(
  request: RegionRecipeRequest,
): Promise<RegionRecipeResponse> {
  const response = await apiClient.post<RegionRecipeResponse>(
    "/convert/region-recipe",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 预测任意配方的显示颜色 */
export async function predictRecipe(
  payload: RecipePredictRequest,
): Promise<RecipePredictResponse> {
  const response = await apiClient.post<RecipePredictResponse>(
    "/convert/predict-recipe",
    payload,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 重置所有颜色替换响应 */
export interface ResetReplacementsResponse {
  status: string;
  message: string;
  preview_url: string;
  preview_glb_url?: string | null;
}

/** 重置所有颜色替换，恢复原始预览 */
export async function resetReplacements(
  sessionId: string,
): Promise<ResetReplacementsResponse> {
  const response = await apiClient.post<ResetReplacementsResponse>(
    "/convert/reset-replacements",
    { session_id: sessionId },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 清理 session 中间文件（预览、GLB 等），保留指定文件 */
export async function cleanupSessionFiles(
  sessionId: string,
  keepFileIds: string[] = [],
): Promise<void> {
  await apiClient
    .post("/convert/cleanup-session-files", {
      session_id: sessionId,
      keep_file_ids: keepFileIds,
    })
    .catch(() => {
      /* fire-and-forget: ignore cleanup failures */
    });
}

/**
 * Use navigator.sendBeacon to reliably clean up session files when the page
 * is closing (tab close, browser quit, navigation away). sendBeacon survives
 * page unload unlike fetch/XHR.
 */
export function beaconCleanupSessionFiles(
  sessionId: string,
  keepFileIds: string[] = [],
): void {
  const base =
    (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";
  const url = `${base}/convert/cleanup-session-files`;
  const body = JSON.stringify({
    session_id: sessionId,
    keep_file_ids: keepFileIds,
  });
  navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
}

/** 自动检测推荐量化颜色数 */
export async function autoDetectColors(
  image: File,
  targetWidthMm: number,
): Promise<AutoDetectColorsResponse> {
  const fd = new FormData();
  fd.append("image", image);
  fd.append("target_width_mm", String(targetWidthMm));
  const response = await apiClient.post<AutoDetectColorsResponse>(
    "/convert/auto-detect-colors",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 读取 session 预览完成后缓存的"渐变海带纹分组"分析。 */
export async function fetchGradientGroups(
  sessionId: string,
  signal?: AbortSignal,
): Promise<GradientGroupsResponse> {
  const response = await apiClient.get<GradientGroupsResponse>(
    `/convert/gradient-groups/${sessionId}`,
    { timeout: 30_000, signal },
  );
  return response.data;
}
