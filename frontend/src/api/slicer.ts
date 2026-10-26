import apiClient from "./client";
import type {
  SlicerCustomPathRequest,
  SlicerCustomPathResponse,
  SlicerDetectResponse,
  SlicerLaunchRequest,
  SlicerLaunchResponse,
} from "./types";

/** 检测系统已安装的切片软件 */
export async function detectSlicers(): Promise<SlicerDetectResponse> {
  const response = await apiClient.get<SlicerDetectResponse>("/slicer/detect");
  return response.data;
}

/** 启动指定切片软件打开 3MF 文件 */
export async function launchSlicer(
  request: SlicerLaunchRequest
): Promise<SlicerLaunchResponse> {
  const response = await apiClient.post<SlicerLaunchResponse>(
    "/slicer/launch",
    request
  );
  return response.data;
}

/** 校验用户手动提供的切片软件路径 */
export async function validateCustomSlicerPath(
  request: SlicerCustomPathRequest
): Promise<SlicerCustomPathResponse> {
  const response = await apiClient.post<SlicerCustomPathResponse>(
    "/slicer/custom-path/validate",
    request
  );
  return response.data;
}
