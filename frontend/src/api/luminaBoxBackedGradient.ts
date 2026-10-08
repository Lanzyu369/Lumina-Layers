import apiClient, { buildApiResourceUrl } from "./client";
import type { LuminaBoxMeasurement } from "./luminaBoxSerial";

export type BackedGradientSymbol = "R" | "Y" | "B" | "W" | "K" | "C" | "M" | "G" | "material";
export type BackedGradientBacking = "W" | "K";
export type BackedGradientRole = "coated" | "bare_backing";
export type BackedGradientXYZ = [number, number, number];
export const BACKED_GRADIENT_THICKNESSES = [0.08, 0.16, 0.24, 0.32, 0.64, 1.28, 2] as const;
export const BACKED_GRADIENT_SYMBOLS: BackedGradientSymbol[] = ["R", "Y", "B", "W", "K", "C", "M", "G"];
export const BACKED_GRADIENT_CAPTURE_SYMBOLS: BackedGradientSymbol[] = [...BACKED_GRADIENT_SYMBOLS, "material"];
export const BACKED_GRADIENT_PRIORITY_SYMBOLS: BackedGradientSymbol[] = ["R", "Y", "B", "W", "K"];

export interface BackedGradientCaptureRequest {
  capture_id: string;
  material_symbol: BackedGradientSymbol;
  backing: BackedGradientBacking;
  sample_role: BackedGradientRole;
  overlay_mm: number;
  measurement?: LuminaBoxMeasurement;
  reflectance_percent_xyz?: BackedGradientXYZ;
  measurement_id?: string;
  received_at?: string;
  sample_name?: string;
  notes?: string;
}

export interface BackedGradientCapture {
  record_id: string;
  dataset_id: string;
  capture_id: string;
  measurement_id: string;
  created_at: string;
  received_at: string;
  material_symbol: BackedGradientSymbol;
  backing: BackedGradientBacking;
  sample_role: BackedGradientRole;
  overlay_mm: number;
  backing_mm: number;
  total_mm: 3;
  reflectance_percent_xyz: BackedGradientXYZ;
  device_measurement: LuminaBoxMeasurement | null;
  source: "device" | "manual" | "import";
  sample_name: string;
  notes: string;
  capture_context: Record<string, unknown>;
  selected: boolean;
}

export interface BackedGradientDataset {
  schema_version: "1.0";
  kind: "lumina_box_backed_gradient";
  dataset_id: string;
  name: string;
  brand: string;
  material_type: string;
  batch: string;
  notes: string;
  materials: Partial<Record<BackedGradientSymbol, string>>;
  created_at: string;
  updated_at: string;
  revision: number;
  total_mm: 3;
  observation_face: "bed_contact";
  thicknesses_mm: number[];
  captures: BackedGradientCapture[];
  selected_capture_ids: Record<string, string>;
}

export interface BackedGradientDatasetRequest {
  name: string;
  brand?: string;
  material_type?: string;
  batch?: string;
  notes?: string;
  materials?: Partial<Record<BackedGradientSymbol, string>>;
}

export interface BackedGradientExport {
  schema_version: "1.0";
  kind: "lumina_box_backed_gradient_export";
  dataset: BackedGradientDataset;
}

export interface BackedGradientFitRun {
  fit_id: string;
  dataset_id: string;
  dataset_revision: number;
  input_hash: string;
  fit_mode: "frozen_six" | "full_seven";
  status: "queued" | "running" | "complete" | "failed";
  progress: number;
  stage: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface BackedGradientPrediction {
  record_id: string;
  material_symbol: BackedGradientSymbol;
  backing: BackedGradientBacking;
  overlay_mm: number;
  sample_role: BackedGradientRole;
  is_training?: boolean;
  observed_percent_xyz: BackedGradientXYZ;
  predicted_percent_xyz: BackedGradientXYZ;
  residual_percent_xyz: BackedGradientXYZ;
}

const endpoint = "/extractor/lumina-box/backed-gradient";
const options = { timeout: 15_000 };
const datasetUrl = (id: string) => `${endpoint}/datasets/${encodeURIComponent(id)}`;

/** Resolve a trusted backend export only at the download boundary.
 * 仅在下载出口解析可信的后端导出地址。 */
export function getBackedGradientExportUrl(id: string): string {
  return buildApiResourceUrl(`${datasetUrl(id)}/export`);
}

/** List independent reflection-gradient datasets. / 列出独立反射梯度数据集。 */
export async function listBackedGradientDatasets(): Promise<BackedGradientDataset[]> {
  return (await apiClient.get<{ datasets: BackedGradientDataset[] }>(`${endpoint}/datasets`, options)).data.datasets;
}

/** Create immutable dataset metadata. / 创建元数据固定的数据集。 */
export async function createBackedGradientDataset(data: BackedGradientDatasetRequest): Promise<BackedGradientDataset> {
  return (await apiClient.post<{ dataset: BackedGradientDataset }>(`${endpoint}/datasets`, data, options)).data.dataset;
}

/** Load records and their active selections. / 读取记录及当前选用项。 */
export async function loadBackedGradientDataset(id: string): Promise<BackedGradientDataset> {
  return (await apiClient.get<{ dataset: BackedGradientDataset }>(datasetUrl(id), options)).data.dataset;
}

/** Save one stable capture without altering its raw device frame. / 保存单条采集并保留设备原帧。 */
export async function saveBackedGradientCapture(id: string, data: BackedGradientCaptureRequest) {
  return (await apiClient.post<{ record: BackedGradientCapture; deduplicated: boolean; dataset: BackedGradientDataset }>(
    `${datasetUrl(id)}/captures`, data, options,
  )).data;
}

/** Choose an existing reading for its material/backing/thickness slot. / 为对应测量格选择已有读数。 */
export async function selectBackedGradientCapture(id: string, recordId: string): Promise<BackedGradientDataset> {
  return (await apiClient.post<{ dataset: BackedGradientDataset }>(`${datasetUrl(id)}/selection`, { record_id: recordId }, options)).data.dataset;
}

/** Delete only one capture. / 仅删除一条采集记录。 */
export async function deleteBackedGradientCapture(id: string, recordId: string): Promise<BackedGradientDataset> {
  return (await apiClient.delete<{ dataset: BackedGradientDataset }>(`${datasetUrl(id)}/captures/${encodeURIComponent(recordId)}`, options)).data.dataset;
}

/** Export the complete portable dataset. / 导出完整可移植数据集。 */
export async function exportBackedGradientDataset(id: string): Promise<BackedGradientExport> {
  return (await apiClient.get<BackedGradientExport>(`${datasetUrl(id)}/export`, options)).data;
}

/** Merge an exported dataset without removing existing records. / 合并导入数据集，保留已有记录。 */
export async function importBackedGradientDataset(data: BackedGradientExport): Promise<BackedGradientDataset> {
  return (await apiClient.post<{ dataset: BackedGradientDataset }>(`${endpoint}/import`, data, options)).data.dataset;
}
