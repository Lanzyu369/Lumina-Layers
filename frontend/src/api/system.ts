import type { AxiosProgressEvent } from "axios";
import apiClient, { type ApiRequestOptions } from "./client";
import type {
  ClearCacheResponse,
  UserSettings,
  UserSettingsResponse,
  SaveSettingsResponse,
  StatsResponse,
  PrinterInfo,
  PrinterListResponse,
  SlicerOption,
  SlicerListResponse,
} from "./types";

export interface Custom3mfTemplate {
  id: string;
  name: string;
  printer_model: string;
  slicer: string;
  nozzle_diameter: string[];
  filament_count: number;
}

export async function getCustom3mfTemplates(): Promise<Custom3mfTemplate[]> {
  const response = await apiClient.get<{ templates: Custom3mfTemplate[] }>("/system/3mf-templates");
  return response.data.templates;
}

export async function importCustom3mfTemplate(
  file: File,
  name: string,
  slicer?: string,
): Promise<Custom3mfTemplate> {
  const body = new FormData();
  body.append("file", file);
  body.append("name", name.trim());
  if (slicer) body.append("slicer", slicer);
  const response = await apiClient.post<Custom3mfTemplate>("/system/3mf-templates", body);
  return response.data;
}

export async function deleteCustom3mfTemplate(id: string): Promise<void> {
  await apiClient.delete(`/system/3mf-templates/${encodeURIComponent(id)}`);
}

/** Convert a generated machine-registry asset path into a backend URL. */
export function getMachineRegistryAssetUrl(path: string | null | undefined): string {
  const trimmed = path?.trim();
  if (!trimmed) {
    return "";
  }
  const normalized = trimmed.replace(/^\/+/, "");
  const encodedPath = normalized
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  const baseURL = apiClient.defaults.baseURL?.trim() || "/api";
  const normalizedBaseURL = baseURL.replace(/\/+$/, "");
  return `${normalizedBaseURL}/system/machine-registry/assets/${encodedPath}`;
}

/** Resolve the slicer-native build-plate STL for one selected device profile. */
export function getMachineBedModelUrl(deviceProfileId: string): string {
  const trimmed = deviceProfileId.trim();
  if (!trimmed) return "";
  const baseURL = apiClient.defaults.baseURL?.trim() || "/api";
  const normalizedBaseURL = baseURL.replace(/\/+$/, "");
  return (
    `${normalizedBaseURL}/system/machine-registry/bed-model` +
    `?device_profile_id=${encodeURIComponent(trimmed)}`
  );
}

/** 调用后端清除系统缓存，返回清理统计信息 */
export async function clearCache(): Promise<ClearCacheResponse> {
  const response = await apiClient.post<ClearCacheResponse>(
    "/system/clear-cache",
  );
  return response.data;
}

/** 获取用户设置 */
export async function getSettings(
  options: ApiRequestOptions = {},
): Promise<UserSettingsResponse> {
  const response =
    options.suppressClientLog === true
      ? await apiClient.get<UserSettingsResponse>("/system/settings", {
          suppressClientLog: true,
        })
      : await apiClient.get<UserSettingsResponse>("/system/settings");
  return response.data;
}

/** 保存用户设置 */
export async function saveSettings(
  settings: UserSettings,
): Promise<SaveSettingsResponse> {
  const response = await apiClient.post<SaveSettingsResponse>(
    "/system/settings",
    settings,
  );
  return response.data;
}

/** 获取使用统计数据 */
export async function getStats(): Promise<StatsResponse> {
  const response = await apiClient.get<StatsResponse>("/system/stats");
  return response.data;
}

/** 获取所有支持的打印机型号列表 */
export async function getPrinters(): Promise<PrinterInfo[]> {
  const response = await apiClient.get<PrinterListResponse>("/system/printers");
  return response.data.printers;
}

/** 获取所有支持的切片器软件列表 */
export async function getSlicers(): Promise<SlicerOption[]> {
  const response = await apiClient.get<SlicerListResponse>("/system/slicers");
  return response.data.slicers;
}

/** 上传图片至后端，获取 PNG 预览 URL（支持 RAW/HEIC 等浏览器不支持的格式） */
export async function uploadImagePreview(
  file: File,
): Promise<{ preview_url: string; width: number; height: number }> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiClient.post<{
    preview_url: string;
    width: number;
    height: number;
  }>("/system/image-preview", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

export interface PreviewResourceResponse {
  resource_id: string;
  preview_id: string;
  preview_url: string;
  full_width: number;
  full_height: number;
  preview_width: number;
  preview_height: number;
  source_type?: string | null;
}

/** Validate original heightmap bytes without creating a preview or session.
 * 校验高度图原始字节，不创建预览资源或会话。
 */
export async function validateHeightmapImage(
  file: File,
  signal: AbortSignal,
): Promise<{ width: number; height: number }> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiClient.post<{ width: number; height: number }>(
    "/system/validate-heightmap",
    formData,
    { timeout: 30_000, signal },
  );
  return response.data;
}

export interface PreviewResourceUploadProgress {
  loaded: number;
  total: number | null;
  percent: number | null;
}

export interface PreviewResourceOptions {
  timeoutMs?: number;
  onUploadProgress?: (progress: PreviewResourceUploadProgress) => void;
}

const DEFAULT_PREVIEW_RESOURCE_TIMEOUT_MS = 120_000;

function normalizeUploadProgress(
  event: AxiosProgressEvent,
  fallbackTotal: number,
): PreviewResourceUploadProgress {
  const loaded = Math.max(0, event.loaded ?? 0);
  const eventTotal =
    typeof event.total === "number" && Number.isFinite(event.total) && event.total > 0
      ? event.total
      : null;
  const total = eventTotal ?? (fallbackTotal > 0 ? fallbackTotal : null);
  const percent =
    total !== null
      ? Math.max(0, Math.min(100, Math.round((loaded / total) * 100)))
      : null;
  return { loaded, total, percent };
}

/** 上传图片为私有资源，只返回受限尺寸的小预览 URL。 */
export async function createPreviewResource(
  file: File,
  context: string,
  options: PreviewResourceOptions = {},
): Promise<PreviewResourceResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("context", context);
  const response = await apiClient.post<PreviewResourceResponse>(
    "/system/preview-resources",
    formData,
    {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: options.timeoutMs ?? DEFAULT_PREVIEW_RESOURCE_TIMEOUT_MS,
      onUploadProgress: options.onUploadProgress
        ? (event) => {
            options.onUploadProgress?.(normalizeUploadProgress(event, file.size));
          }
        : undefined,
    },
  );
  return response.data;
}
