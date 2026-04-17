import apiClient from "./client";
import type {
  MaterialSolverCacheBuildResponse,
  MaterialSolverCacheDeleteResponse,
  MaterialSolverCacheListResponse,
  MaterialSolverCacheStatusResponse,
} from "./types";

/**
 * Parameters identifying a specific solver-cache combination.
 * 用于唯一标识求解器缓存组合的参数。
 */
export interface MaterialSolverCacheKey {
  materialDirectoryNames: string[];
  layerCount: number;
  layerHeightMm: number;
  substrate: "white" | "black";
}

function _formData(
  key: MaterialSolverCacheKey,
  extra?: Record<string, string>,
): FormData {
  const fd = new FormData();
  fd.append(
    "material_directory_names",
    JSON.stringify(key.materialDirectoryNames),
  );
  fd.append("layer_count", String(key.layerCount));
  fd.append("layer_height_mm", String(key.layerHeightMm));
  fd.append("substrate", key.substrate);
  if (extra) {
    for (const [k, v] of Object.entries(extra)) {
      fd.append(k, v);
    }
  }
  return fd;
}

/**
 * Query whether a solver cache is persisted for the given key.
 * 查询指定组合的求解器缓存是否已持久化。
 */
export async function fetchMaterialSolverCacheStatus(
  key: MaterialSolverCacheKey,
): Promise<MaterialSolverCacheStatusResponse> {
  const response = await apiClient.post<MaterialSolverCacheStatusResponse>(
    "/extractor/material-solver-cache/status",
    _formData(key),
    { timeout: 30_000 },
  );
  return response.data;
}

/**
 * Build and persist a solver cache. This is a long-running request — for 10
 * materials × 10 layers it can take 30-180 seconds — so callers should raise
 * the timeout and surface progress to the user.
 * 构建并持久化求解器缓存；长耗时请求，10 材料 × 10 层大约 30-180 秒。
 */
export async function buildMaterialSolverCache(
  key: MaterialSolverCacheKey,
  options?: { gridResolution?: number; timeoutMs?: number },
): Promise<MaterialSolverCacheBuildResponse> {
  const extra: Record<string, string> = {};
  if (options?.gridResolution != null) {
    extra.grid_resolution = String(options.gridResolution);
  }
  const response = await apiClient.post<MaterialSolverCacheBuildResponse>(
    "/extractor/material-solver-cache/build",
    _formData(key, extra),
    { timeout: options?.timeoutMs ?? 10 * 60_000 },
  );
  return response.data;
}

/**
 * Delete a persisted solver-cache entry.
 * 删除已持久化的求解器缓存条目。
 */
export async function deleteMaterialSolverCache(
  key: MaterialSolverCacheKey,
): Promise<MaterialSolverCacheDeleteResponse> {
  const response = await apiClient.post<MaterialSolverCacheDeleteResponse>(
    "/extractor/material-solver-cache/delete",
    _formData(key),
    { timeout: 30_000 },
  );
  return response.data;
}

/**
 * List all persisted solver caches with metadata.
 * 列出所有已持久化的求解器缓存及其元数据。
 */
export async function listMaterialSolverCaches(): Promise<
  MaterialSolverCacheListResponse
> {
  const response = await apiClient.get<MaterialSolverCacheListResponse>(
    "/extractor/material-solver-caches",
    { timeout: 30_000 },
  );
  return response.data;
}
