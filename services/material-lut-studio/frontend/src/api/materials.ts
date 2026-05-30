import apiClient from "./client";
import type {
  MaterialBulkExportResponse,
  MaterialBulkImportResponse,
  MaterialDeleteResponse,
  MaterialLibraryResponse,
} from "./types";

const PREFIX = "/mls/materials";

/** 列出已保存的耗材档案 */
export async function fetchMaterials(): Promise<MaterialLibraryResponse> {
  const response = await apiClient.get<MaterialLibraryResponse>(PREFIX);
  return response.data;
}

/** 删除指定耗材档案 */
export async function deleteMaterial(
  directoryName: string,
): Promise<MaterialDeleteResponse> {
  const response = await apiClient.delete<MaterialDeleteResponse>(
    `${PREFIX}/${encodeURIComponent(directoryName)}`,
  );
  return response.data;
}

/** 批量导出选中的耗材为一个 ZIP */
export async function exportMaterials(
  directoryNames: string[],
): Promise<MaterialBulkExportResponse> {
  const response = await apiClient.post<MaterialBulkExportResponse>(
    `${PREFIX}/export`,
    { directory_names: directoryNames },
  );
  return response.data;
}

/** 导入一个或多个耗材 ZIP 归档 */
export async function importMaterials(
  files: File[],
): Promise<MaterialBulkImportResponse> {
  const form = new FormData();
  for (const file of files) {
    form.append("archives", file);
  }
  const response = await apiClient.post<MaterialBulkImportResponse>(
    `${PREFIX}/import`,
    form,
  );
  return response.data;
}
