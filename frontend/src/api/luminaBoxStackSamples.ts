import apiClient from "./client";
import type { LuminaBoxMeasurement } from "./luminaBoxSerial";
import type { LuminaBoxXYZ } from "./types";

export interface LuminaBoxStackSampleRequest {
  recipe_top_to_bottom: string;
  capture_id: string;
  measurement: LuminaBoxMeasurement;
  received_at?: string | null;
  sample_name?: string;
  notes?: string;
  material_batch?: string;
  reference_directory_name?: string | null;
  measurement_backing_percent_xyz?: LuminaBoxXYZ | null;
}

export interface LuminaBoxStackSampleRecord {
  schema_version: "1.0";
  kind: "lumina_box_stack_sample";
  data_role: "actual_measured_multimaterial_reflectance";
  record_id: string;
  created_at: string;
  received_at?: string;
  capture_id: string;
  recipe_top_to_bottom: string;
  sample_name: string;
  notes: string;
  material_batch: string;
  reference_directory_name: string | null;
  measurement_backing_percent_xyz: LuminaBoxXYZ | null;
  geometry: {
    upper_layer_count: number;
    upper_layer_height_mm: 0.08;
    first_layer_height_mm: 0.2;
    total_layer_count: 36;
    upper_mm: number;
    white_base_mm: number;
    total_mm: 3;
    full_recipe_top_to_bottom: string;
    layer_heights_mm_top_to_bottom: number[];
  };
  reflectance_percent_xyz: LuminaBoxXYZ;
  reflectance_relative_xyz: LuminaBoxXYZ;
  display_rgb: [number, number, number];
  display_hex: string;
  device_measurement: LuminaBoxMeasurement;
  reference_context: {
    status: "not_selected" | "captured" | "unavailable";
    archive_id: string | null;
    revision_id: string | null;
    reference_id: string | null;
    sidecar_sha256: Record<string, string>;
  };
}

export interface LuminaBoxStackSampleResponse {
  status: "success";
  record: LuminaBoxStackSampleRecord;
  deduplicated: boolean;
}

export interface LuminaBoxStackSampleExport {
  schema_version: "1.0";
  kind: "lumina_box_stack_samples_export";
  exported_at: string;
  records: LuminaBoxStackSampleRecord[];
}

const endpoint = "/extractor/lumina-box/stack-samples";
const requestOptions = { timeout: 15_000 };

/** Save one measured stack with a stable capture identity.
 * 使用稳定的采集标识保存一条叠色实测记录。 */
export async function saveLuminaBoxStackSample(data: LuminaBoxStackSampleRequest): Promise<LuminaBoxStackSampleResponse> {
  const response = await apiClient.post<LuminaBoxStackSampleResponse>(endpoint, data, requestOptions);
  return response.data;
}

/** List stored stack measurements, newest first.
 * 按新到旧列出已保存的叠色样片。 */
export async function listLuminaBoxStackSamples(): Promise<LuminaBoxStackSampleRecord[]> {
  const response = await apiClient.get<{ status: "success"; records: LuminaBoxStackSampleRecord[] }>(endpoint, requestOptions);
  return response.data.records;
}

/** Read one saved record without changing the capture form.
 * 读取一条历史记录，不改变待采配方。 */
export async function loadLuminaBoxStackSample(recordId: string): Promise<LuminaBoxStackSampleRecord> {
  const response = await apiClient.get<LuminaBoxStackSampleResponse>(
    `${endpoint}/${encodeURIComponent(recordId)}`, requestOptions,
  );
  return response.data.record;
}

/** Delete only the selected stack record.
 * 仅删除指定的叠色样片记录。 */
export async function deleteLuminaBoxStackSample(recordId: string): Promise<void> {
  await apiClient.delete(`${endpoint}/${encodeURIComponent(recordId)}`, requestOptions);
}

/** Export measured stacks as portable JSON.
 * 导出可供后续分析使用的叠色实测 JSON。 */
export async function exportLuminaBoxStackSamples(): Promise<LuminaBoxStackSampleExport> {
  const response = await apiClient.get<LuminaBoxStackSampleExport>(`${endpoint}/export`, requestOptions);
  return response.data;
}
