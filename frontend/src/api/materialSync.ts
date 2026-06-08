import apiClient from "./client";
import type {
  MaterialRegistryPackageMutationResponse,
  MaterialSyncRefreshResponse,
  MaterialSyncRollbackResponse,
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

/**
 * Roll a synced local material back to a previous revision.
 * 将本地已同步耗材回滚到指定历史 revision。
 */
export async function rollbackMaterialSyncRevision(
  materialId: string,
  revisionId: string,
): Promise<MaterialSyncRollbackResponse> {
  const response = await apiClient.post<MaterialSyncRollbackResponse>(
    "/material-sync/rollback",
    { material_id: materialId, revision_id: revisionId },
    { timeout: 60_000 },
  );
  return response.data;
}

/**
 * Upload one material package ZIP to the server-side Registry review queue.
 * 上传一个耗材包 ZIP 到服务器端 Registry 待审核队列。
 */
export async function uploadMaterialRegistryPackage(
  file: File,
): Promise<MaterialRegistryPackageMutationResponse> {
  const formData = new FormData();
  formData.append("archive", file);
  const response = await apiClient.post<MaterialRegistryPackageMutationResponse>(
    "/material-registry/v1/packages/upload",
    formData,
    {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 3_600_000,
    },
  );
  return response.data;
}

const encodePackagePathForRoute = (packagePath: string): string =>
  packagePath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");

/**
 * Approve a pending Registry package into the public official channel.
 * 将待审核 Registry 耗材包审批为公开 official 频道。
 */
export async function approveMaterialRegistryPackage(
  packagePath: string,
  officialPassword: string,
): Promise<MaterialRegistryPackageMutationResponse> {
  const response = await apiClient.post<MaterialRegistryPackageMutationResponse>(
    `/material-registry/v1/packages/${encodePackagePathForRoute(packagePath)}/approve`,
    { official_password: officialPassword },
    { timeout: 60_000 },
  );
  return response.data;
}
