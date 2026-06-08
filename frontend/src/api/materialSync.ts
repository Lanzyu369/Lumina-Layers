import apiClient from "./client";
import type {
  MaterialSyncRefreshResponse,
  MaterialSyncStatusResponse,
} from "./types";

/**
 * Fetch local material sync-index status.
 * 获取本地耗材同步索引状态。
 */
export async function fetchMaterialSyncStatus(): Promise<MaterialSyncStatusResponse> {
  const response = await apiClient.get<MaterialSyncStatusResponse>(
    "/material-sync/status",
    { timeout: 30_000 },
  );
  return response.data;
}

/**
 * Pull read-only material package updates from the configured Registry.
 * 从已配置的只读 Registry 拉取耗材包更新。
 */
export async function refreshMaterialSyncFromRegistry(): Promise<MaterialSyncRefreshResponse> {
  const response = await apiClient.post<MaterialSyncRefreshResponse>(
    "/material-sync/refresh",
    {},
    { timeout: 3_600_000 },
  );
  return response.data;
}
