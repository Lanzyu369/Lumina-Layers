import apiClient from "./client";
import type {
  MaterialColorSuggestionsResponse,
  MaterialSolverCacheBuildResponse,
  MaterialSolverCacheDeleteResponse,
  MaterialSolverCacheDetailsResponse,
  MaterialSolverCacheListResponse,
  MaterialSolverCacheStatusResponse,
  MaterialSolverRuntimeBuildResponse,
  MaterialSolverRuntimeDeleteResponse,
  MaterialSolverRuntimeDetailsResponse,
  MaterialSolverRuntimeStatusResponse,
} from "./types";

/**
 * Material solver-cache client.
 * 耗材求解器缓存客户端。
 *
 * These endpoints are part of the local main-app development baseline.
 * 这些端点属于本地主应用开发基线。
 */

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

/**
 * User-facing bounded-runtime candidate budgets.
 * 面向用户的有界运行时候选预算档位。
 */
export type MaterialSolverRuntimeCandidateBudget =
  | 1_048_576
  | 4_194_304
  | 8_388_608
  | 33_554_432
  | 67_108_864;

export const MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGETS: readonly MaterialSolverRuntimeCandidateBudget[] =
  [1_048_576, 4_194_304, 8_388_608, 33_554_432, 67_108_864] as const;

export const DEFAULT_MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGET: MaterialSolverRuntimeCandidateBudget =
  33_554_432;

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
  options?: { gridResolution?: number },
): Promise<MaterialSolverCacheStatusResponse> {
  const extra: Record<string, string> = {};
  if (options?.gridResolution != null) {
    extra.grid_resolution = String(options.gridResolution);
  }
  const response = await apiClient.post<MaterialSolverCacheStatusResponse>(
    "/extractor/material-solver-cache/status",
    _formData(key, extra),
    { timeout: 3_600_000 },
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
    { timeout: options?.timeoutMs ?? 3_600_000 },
  );
  return response.data;
}

/**
 * Delete a persisted solver-cache entry.
 * 删除已持久化的求解器缓存条目。
 */
export async function deleteMaterialSolverCache(
  key: MaterialSolverCacheKey,
  options?: { gridResolution?: number },
): Promise<MaterialSolverCacheDeleteResponse> {
  const extra: Record<string, string> = {};
  if (options?.gridResolution != null) {
    extra.grid_resolution = String(options.gridResolution);
  }
  const response = await apiClient.post<MaterialSolverCacheDeleteResponse>(
    "/extractor/material-solver-cache/delete",
    _formData(key, extra),
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Query whether a bounded hybrid runtime is persisted for the given key.
 * 查询指定组合的有界 hybrid runtime 是否已持久化。
 */
export async function fetchMaterialSolverRuntimeStatus(
  key: MaterialSolverCacheKey,
  options?: { candidateBudget?: number },
): Promise<MaterialSolverRuntimeStatusResponse> {
  const extra: Record<string, string> = {};
  if (options?.candidateBudget != null) {
    extra.candidate_budget = String(options.candidateBudget);
  }
  const response = await apiClient.post<MaterialSolverRuntimeStatusResponse>(
    "/extractor/material-solver-runtime/status",
    _formData(key, extra),
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Build and persist a bounded hybrid runtime.
 * 构建并持久化有界 hybrid runtime。
 */
export async function buildMaterialSolverRuntime(
  key: MaterialSolverCacheKey,
  options?: { candidateBudget?: number; timeoutMs?: number },
): Promise<MaterialSolverRuntimeBuildResponse> {
  const extra: Record<string, string> = {};
  if (options?.candidateBudget != null) {
    extra.candidate_budget = String(options.candidateBudget);
  }
  const response = await apiClient.post<MaterialSolverRuntimeBuildResponse>(
    "/extractor/material-solver-runtime/build",
    _formData(key, extra),
    { timeout: options?.timeoutMs ?? 3_600_000 },
  );
  return response.data;
}

/**
 * Delete a persisted bounded hybrid runtime entry.
 * 删除已持久化的有界 hybrid runtime 条目。
 */
export async function deleteMaterialSolverRuntime(
  key: MaterialSolverCacheKey,
  options?: { candidateBudget?: number },
): Promise<MaterialSolverRuntimeDeleteResponse> {
  const extra: Record<string, string> = {};
  if (options?.candidateBudget != null) {
    extra.candidate_budget = String(options.candidateBudget);
  }
  const response = await apiClient.post<MaterialSolverRuntimeDeleteResponse>(
    "/extractor/material-solver-runtime/delete",
    _formData(key, extra),
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Fetch the LUT-details-shaped color-distribution payload for a runtime.
 * 拉取有界 hybrid runtime 的色彩分布图载荷（结构与 LUT 详情同构）。
 */
export async function fetchMaterialSolverRuntimeDetails(
  key: MaterialSolverCacheKey,
  options?: {
    candidateBudget?: number;
    maxPoints?: number;
    signal?: AbortSignal;
  },
): Promise<MaterialSolverRuntimeDetailsResponse> {
  const extra: Record<string, string> = {};
  if (options?.candidateBudget != null) {
    extra.candidate_budget = String(options.candidateBudget);
  }
  if (options?.maxPoints != null) {
    extra.max_points = String(options.maxPoints);
  }
  const response = await apiClient.post<MaterialSolverRuntimeDetailsResponse>(
    "/extractor/material-solver-runtime/details",
    _formData(key, extra),
    { timeout: 3_600_000, signal: options?.signal },
  );
  return response.data;
}

/**
 * List all persisted solver caches with metadata.
 * 列出所有已持久化的求解器缓存及其元数据。
 */
export async function listMaterialSolverCaches(): Promise<MaterialSolverCacheListResponse> {
  const response = await apiClient.get<MaterialSolverCacheListResponse>(
    "/extractor/material-solver-caches",
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Fetch the LUT-details-shaped color-distribution payload for a built cache.
 * 拉取已构建缓存的色彩分布图载荷（结构与 LUT 详情同构）。
 *
 * Used by :class:`MaterialSolverCacheStatusCard` to render the four scatter
 * charts (Lab a-b plane, RGB isometric projection, Hue x Lightness, Hue x
 * Saturation) verbatim from the existing LUT-details components.
 *
 * 由 :class:`MaterialSolverCacheStatusCard` 调用，复用 LUT 详情组件渲染四张散点图。
 */
export async function fetchMaterialSolverCacheDetails(
  key: MaterialSolverCacheKey,
  options?: { gridResolution?: number; maxPoints?: number; signal?: AbortSignal },
): Promise<MaterialSolverCacheDetailsResponse> {
  const extra: Record<string, string> = {};
  if (options?.gridResolution != null) {
    extra.grid_resolution = String(options.gridResolution);
  }
  if (options?.maxPoints != null) {
    extra.max_points = String(options.maxPoints);
  }
  const response = await apiClient.post<MaterialSolverCacheDetailsResponse>(
    "/extractor/material-solver-cache/details",
    _formData(key, extra),
    { timeout: 3_600_000, signal: options?.signal },
  );
  return response.data;
}

/**
 * Options for :func:`fetchMaterialColorSuggestions`.
 * :func:`fetchMaterialColorSuggestions` 的可选参数。
 */
export interface MaterialColorSuggestOptions {
  /** Max number of suggestions to return. Defaults to backend's 20. (返回上限) */
  topK?: number;
  /** Minimum Lab ΔE between neighbours (perceptual dedup). (最小间距) */
  minSpacing?: number;
  /** Hard cap on ``M ** N`` for the MITM fallback. (MITM 回退上限) */
  maxCombinations?: number;
  /**
   * Lab grid resolution (buckets per axis) to target. Defaults to the
   * backend's low-tier value; callers must pass this when the user opts
   * in to a denser cache so the lookup and the build target the same
   * on-disk file.
   * Lab 网格分辨率（每轴桶数）；默认走后端低档，用户启用更
   * 密的缓存时调用方必须传对应值，否则查询与构建会不匹配。
   */
  gridResolution?: number;
  /** ``AbortSignal`` to cancel the in-flight request. (用于取消请求) */
  signal?: AbortSignal;
  /** Request timeout. Defaults to 60 s to allow MITM fallback runs. (超时) */
  timeoutMs?: number;
}

/**
 * Suggest achievable colors close to ``targetHex`` for a given material palette.
 * 为指定目标颜色返回可达近似色建议。
 *
 * The backend prefers the persisted solver cache when available (microsecond
 * lookups) and transparently falls back to the MITM enumeration otherwise.
 * The ``source`` field on the response tells the UI which path ran so it can
 * nudge the user to build a cache for instant future queries.
 */
export async function fetchMaterialColorSuggestions(
  key: MaterialSolverCacheKey,
  targetHex: string,
  options?: MaterialColorSuggestOptions,
): Promise<MaterialColorSuggestionsResponse> {
  const extra: Record<string, string> = { target_hex: targetHex };
  if (options?.topK != null) extra.top_k = String(options.topK);
  if (options?.minSpacing != null) {
    extra.min_spacing = String(options.minSpacing);
  }
  if (options?.maxCombinations != null) {
    extra.max_combinations = String(options.maxCombinations);
  }
  if (options?.gridResolution != null) {
    extra.grid_resolution = String(options.gridResolution);
  }
  const response = await apiClient.post<MaterialColorSuggestionsResponse>(
    "/extractor/material-solver-cache/suggest-colors",
    _formData(key, extra),
    {
      timeout: options?.timeoutMs ?? 3_600_000,
      signal: options?.signal,
    },
  );
  return response.data;
}
