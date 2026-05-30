import apiClient from "./client";
import type { SolverCacheListResponse } from "./types";

const PREFIX = "/mls/solver-cache";

/** 列出所有已持久化的求解器缓存条目 */
export async function fetchSolverCaches(): Promise<SolverCacheListResponse> {
  const response = await apiClient.get<SolverCacheListResponse>(PREFIX);
  return response.data;
}

/** 删除指定参数组合的求解器缓存 */
export async function deleteSolverCache(params: {
  materialDirectoryNames: string[];
  layerCount: number;
  layerHeightMm: number;
  substrate: string;
  gridResolution: number;
}): Promise<{ status: string; message: string; deleted: boolean }> {
  const form = new FormData();
  form.append(
    "material_directory_names",
    JSON.stringify(params.materialDirectoryNames),
  );
  form.append("layer_count", String(params.layerCount));
  form.append("layer_height_mm", String(params.layerHeightMm));
  form.append("substrate", params.substrate);
  form.append("grid_resolution", String(params.gridResolution));
  const response = await apiClient.post(`${PREFIX}/delete`, form);
  return response.data;
}
