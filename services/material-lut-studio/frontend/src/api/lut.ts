import apiClient from "./client";
import type {
  CompareRequest,
  CompareResponse,
  LutInfoResponse,
  LutListResponse,
  MergeRequest,
  MergeResponse,
} from "./types";

const PREFIX = "/mls/lut";

/** 列出所有可用 LUT 预设 */
export async function fetchLutList(): Promise<LutListResponse> {
  const response = await apiClient.get<LutListResponse>(`${PREFIX}/list`);
  return response.data;
}

/** 获取指定 LUT 的颜色模式、颜色数量与调色板 */
export async function fetchLutInfo(lutName: string): Promise<LutInfoResponse> {
  const response = await apiClient.get<LutInfoResponse>(
    `${PREFIX}/${encodeURIComponent(lutName)}/info`,
  );
  return response.data;
}

/** 执行 LUT 合并操作 */
export async function mergeLuts(request: MergeRequest): Promise<MergeResponse> {
  const response = await apiClient.post<MergeResponse>(`${PREFIX}/merge`, request);
  return response.data;
}

/** 按共享配方对比两个 LUT */
export async function compareLuts(
  request: CompareRequest,
): Promise<CompareResponse> {
  const response = await apiClient.post<CompareResponse>(
    `${PREFIX}/compare`,
    request,
  );
  return response.data;
}

/** 上传 LUT 文件到 Custom 目录 */
export async function uploadLut(file: File): Promise<{ status: string; message: string; name: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await apiClient.post(`${PREFIX}/upload`, form);
  return response.data;
}
