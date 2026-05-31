import mlsClient from "./mlsClient";
import type { SavedMaterialLibraryItem } from "./types";

/**
 * Material-archive list client (read-only, for the converter's picker).
 * 耗材档案列表客户端（只读，供转换器选材选择器使用）。
 *
 * Route B / 做法一: material management lives in the standalone Material-LUT
 * Studio (MLS) service. The converter only needs to *list* saved materials so
 * the user can pick a palette for material-archive mode; that list is fetched
 * from MLS via ``GET /api/mls/materials``. Creating/editing/deleting materials
 * happens in the MLS UI.
 * 耗材管理在独立 MLS 服务。转换器只需*列出*已保存耗材供用户在耗材档案模式下
 * 选择，列表经 ``GET /api/mls/materials`` 获取；增改删在 MLS 界面完成。
 */

interface MlsMaterialLibraryResponse {
  status: string;
  message: string;
  materials: SavedMaterialLibraryItem[];
}

/**
 * List saved material archives from the MLS service.
 * 从 MLS 服务列出已保存的耗材档案。
 */
export async function listMaterials(): Promise<MlsMaterialLibraryResponse> {
  const response = await mlsClient.get<MlsMaterialLibraryResponse>(
    "/api/mls/materials",
    { timeout: 3_600_000 },
  );
  return response.data;
}
