import apiClient from "./client";
import type {
  CalibrationGenerateRequest,
  CalibrationResponse,
  SingleStageKitGenerateRequest,
  SingleStageKitResponse,
} from "./types";

/** 提交校准板生成请求，返回下载链接和预览信息 */
export async function calibrationGenerate(
  request: CalibrationGenerateRequest,
): Promise<CalibrationResponse> {
  const response = await apiClient.post<CalibrationResponse>(
    "/calibration/generate",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Generate a single-stage kit aligned with the ChromaPrint3D workflow. */
export async function generateSingleStageKit(
  request: SingleStageKitGenerateRequest,
): Promise<SingleStageKitResponse> {
  const response = await apiClient.post<SingleStageKitResponse>(
    "/calibration/generate-single-stage-kit",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}
