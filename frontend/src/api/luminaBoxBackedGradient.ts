import apiClient, { buildApiResourceUrl } from "./client";
import type { LuminaBoxMeasurement } from "./luminaBoxSerial";

export type BackedGradientSymbol = "R" | "Y" | "B" | "W" | "K" | "C" | "M" | "G" | "material";
export type BackedGradientBacking = "W" | "K";
export type BackedGradientRole = "coated" | "bare_backing";
export type BackedGradientXYZ = [number, number, number];
export type BackedGradientModelKey = "affine" | "two_flux";
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

export interface BackedGradientMetrics {
  overall_rmse_pp: number;
  per_material_rmse_pp: Partial<Record<BackedGradientSymbol, number>>;
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

export interface BackedGradientStability {
  status: "stable" | "unstable" | "not_available" | "incomplete";
  per_backing?: Partial<Record<BackedGradientBacking, {
    xyz_width_p95_pp: number;
    xyz_width_max_pp: number;
    delta_e00_p95: number;
    delta_e00_max: number;
  }>>;
  accepted_parameter_sets?: number;
  profile_evaluations?: number;
}

export interface BackedGradientModelResult {
  status: "converged" | "failed" | "exploratory";
  model_id: string;
  parameters: Record<string, unknown> | null;
  cv: BackedGradientMetrics | null;
  sample_predictions: BackedGradientPrediction[];
  stability: BackedGradientStability;
  error?: string | null;
}

export interface BackedGradientValidation {
  status: "frozen_and_scored" | "not_available" | "included_in_training";
  used_for_training: boolean;
  selected_model_before_validation?: BackedGradientModelKey | null;
  prediction_hash?: string;
  predictions?: Partial<Record<BackedGradientModelKey, BackedGradientPrediction[]>>;
  metrics?: Partial<Record<BackedGradientModelKey, BackedGradientMetrics>>;
  passed: boolean | null;
  source_fit_input_hash?: string;
  current_validation_input_hash?: string;
}

export interface BackedGradientRecipeColor {
  xyz: BackedGradientXYZ;
  rgb: [number, number, number];
  hex: string;
}

export interface BackedGradientComparisonRow {
  id: number;
  row: number;
  column: number;
  recipe_visible_to_back: string;
  backings: Record<BackedGradientBacking, {
    affine: BackedGradientRecipeColor | null;
    two_flux: BackedGradientRecipeColor | null;
    delta_e00: number | null;
    stability: Partial<Record<BackedGradientModelKey, { xyz_width_pp: BackedGradientXYZ; delta_e00_width: number }>>;
  }>;
}

export interface BackedGradientBlindRecipe {
  recipe_visible_to_back: string;
  backing: BackedGradientBacking;
  layer_mm: number;
  backing_mm: number;
  total_mm: number;
  predictions: Partial<Record<BackedGradientModelKey, BackedGradientXYZ>>;
}

export interface BackedGradientFitResult {
  models: Record<BackedGradientModelKey, BackedGradientModelResult>;
  recommendation: {
    model: BackedGradientModelKey | null;
    status: "recommended" | "exploratory";
    reason: string;
    failure_stage?: "frozen_six" | "frozen_validation_024" | "full_refit";
    failure_reason?: string;
  };
  validation_024: BackedGradientValidation;
  controls: {
    rows: Array<Record<string, unknown>>;
    count: number;
    max_abs_deviation_pp: number;
    rms_deviation_pp: number;
  };
  comparison: {
    model_ids?: Partial<Record<BackedGradientModelKey, string>>;
    geometry: { total_mm: 3; upper_layers: 5; layer_mm: 0.08; backing_mm: 2.6 };
    rows: BackedGradientComparisonRow[];
    blind_recipes: BackedGradientBlindRecipe[];
  } | null;
}

const endpoint = "/extractor/lumina-box/backed-gradient";
const options = { timeout: 15_000 };
const datasetUrl = (id: string) => `${endpoint}/datasets/${encodeURIComponent(id)}`;
const runUrl = (id: string) => `${endpoint}/fit-runs/${encodeURIComponent(id)}`;

/** Resolve a trusted backend export only at the download boundary.
 * 仅在下载出口解析可信的后端导出地址。 */
export function getBackedGradientExportUrl(id: string): string {
  return buildApiResourceUrl(`${datasetUrl(id)}/export`);
}

/** Resolve a generated fit attachment for the desktop download handler.
 * 为桌面下载处理器解析已生成的拟合附件地址。 */
export function getBackedGradientFitExportUrl(id: string, format: "json" | "csv" | "png"): string {
  return buildApiResourceUrl(`${runUrl(id)}/exports/${format}`);
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

/** Start a separate frozen-input fit. / 启动独立的冻结输入拟合。 */
export async function startBackedGradientFit(id: string, includeValidationThickness: boolean): Promise<BackedGradientFitRun> {
  return (await apiClient.post<{ run: BackedGradientFitRun }>(`${datasetUrl(id)}/fit-runs`, {
    include_validation_thickness: includeValidationThickness,
  }, options)).data.run;
}

/** Read asynchronous fit progress. / 读取异步拟合进度。 */
export async function loadBackedGradientFit(id: string): Promise<BackedGradientFitRun> {
  return (await apiClient.get<{ run: BackedGradientFitRun }>(runUrl(id), options)).data.run;
}

/** List every independent fit for this dataset. / 列出数据集的各次独立拟合。 */
export async function listBackedGradientFits(id: string): Promise<BackedGradientFitRun[]> {
  return (await apiClient.get<{ runs: BackedGradientFitRun[] }>(`${datasetUrl(id)}/fit-runs`, options)).data.runs;
}

/** Read a finished result and its unclipped color predictions. / 读取完成的结果及未裁切颜色预测。 */
export async function loadBackedGradientFitResult(id: string): Promise<BackedGradientFitResult> {
  return (await apiClient.get<{ result: BackedGradientFitResult }>(`${runUrl(id)}/result`, options)).data.result;
}

/** Score later 0.24 mm samples against frozen parameters. / 用冻结参数检验后补的0.24毫米样本。 */
export async function validateBackedGradient024(id: string): Promise<BackedGradientValidation> {
  return (await apiClient.post<{ validation: BackedGradientValidation }>(`${runUrl(id)}/validate-024`, {}, options)).data.validation;
}

/** Reload the latest independent 0.24 mm validation. / 重新读取独立的0.24毫米验证结果。 */
export async function loadBackedGradientValidation(id: string): Promise<BackedGradientValidation | null> {
  return (await apiClient.get<{ validation: BackedGradientValidation | null }>(`${runUrl(id)}/validation-024`, options)).data.validation;
}

/** Download a generated fit artifact. / 下载已生成的拟合产物。 */
export async function downloadBackedGradientFit(id: string, format: "json" | "csv" | "png"): Promise<Blob> {
  return (await apiClient.get<Blob>(`${runUrl(id)}/exports/${format}`, { ...options, responseType: "blob" })).data;
}
