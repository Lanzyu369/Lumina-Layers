import apiClient from "./client";
import type {
  CompareRequest,
  CompareResponse,
  LutCatalogResponse,
  LutInfoResponse,
  MergeRequest,
  MergeResponse,
  RecipeColorPredictRequest,
  RecipeColorPredictResponse,
  RecipeSearchRequest,
  RecipeSearchResponse,
} from "./types";

/** 获取指定 LUT 的颜色模式和颜色数量 */
export async function fetchLutInfo(
  lutName: string
): Promise<LutInfoResponse> {
  const response = await apiClient.get<LutInfoResponse>(
    `/lut/${encodeURIComponent(lutName)}/info`
  );
  return response.data;
}

/**
 * 获取当前会话所绑定 LUT 的通道调色板与能力信息。
 * Fetches the channel palette bound to a converter session, which works for
 * material-archive / native-bundle sessions that have no globally-known LUT
 * name. Used by the custom recipe editor to show channel-ordered materials.
 */
export async function fetchSessionLutInfo(
  sessionId: string,
): Promise<LutInfoResponse> {
  const response = await apiClient.get<LutInfoResponse>(
    `/lut/session/${encodeURIComponent(sessionId)}/info`,
  );
  return response.data;
}

/** 执行 LUT 合并操作 */
export async function mergeLuts(
  request: MergeRequest
): Promise<MergeResponse> {
  const response = await apiClient.post<MergeResponse>(
    "/lut/merge",
    request,
    { timeout: 600_000 }
  );
  return response.data;
}

/** Compare two LUTs by shared recipe */
export async function compareLuts(
  request: CompareRequest
): Promise<CompareResponse> {
  const response = await apiClient.post<CompareResponse>(
    "/lut/compare",
    request,
    { timeout: 600_000 }
  );
  return response.data;
}

/** 获取旧版 LUT 与新版品牌包目录 */
export async function fetchLutCatalog(): Promise<LutCatalogResponse> {
  const response = await apiClient.get<LutCatalogResponse>("/lut/catalog");
  return response.data;
}

/** Predict a custom recipe color for a predictive source. */
export async function predictRecipeColor(
  lutName: string,
  request: RecipeColorPredictRequest,
): Promise<RecipeColorPredictResponse> {
  const response = await apiClient.post<RecipeColorPredictResponse>(
    `/lut/${encodeURIComponent(lutName)}/predict-recipe-color`,
    request,
    { timeout: 120_000 },
  );
  return response.data;
}

/** Search predictive candidate recipes by layer pattern. */
export async function searchRecipes(
  lutName: string,
  request: RecipeSearchRequest,
): Promise<RecipeSearchResponse> {
  const response = await apiClient.post<RecipeSearchResponse>(
    `/lut/${encodeURIComponent(lutName)}/search-recipes`,
    request,
    { timeout: 120_000 },
  );
  return response.data;
}
