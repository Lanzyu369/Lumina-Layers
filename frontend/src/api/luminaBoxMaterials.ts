import apiClient from "./client";
import type { SavedMaterialLibraryItem } from "./types";
import type {
  BackedGradientDataset, BackedGradientDatasetRequest, BackedGradientFitRun,
  BackedGradientPrediction, BackedGradientSymbol,
} from "./luminaBoxBackedGradient";

export const LUMINA_BOX_PRODUCTION_MODEL_ID = "backed_gradient_spectral_four_flux_smooth/v3" as const;

export interface LuminaBoxBackingReference {
  reference_id: string;
  backing_id?: string;
  version?: number;
  name: string;
  created_at: string;
  white_name?: string;
  black_name?: string;
  source_dataset_id?: string | null;
  brand?: string;
  material_type?: string;
}

export interface LuminaBoxBackingMaterial {
  material_id: string;
  version_id?: string;
  role: "W" | "K";
  name: string;
  brand?: string;
  material_type?: string;
  dataset_id?: string;
  dataset_revision?: number;
  active_dataset_id?: string;
  source?: string;
  opposite_material_id?: string;
  status: "draft" | "measured" | "ready";
  reference_id?: string;
}

export type LuminaBoxDatasetWorkflow = {
  kind: "material";
  material_symbol: BackedGradientSymbol;
  reference_id: string;
  backing_id?: string;
  backing_reference?: LuminaBoxBackingReference;
  backing_materials?: { W: LuminaBoxBackingMaterial; K: LuminaBoxBackingMaterial };
} | { kind: "backing_reference" } | {
  kind: "backing_material";
  material_symbol: "W" | "K";
  backing_material_id: string;
  opposite_material_id: string;
  opposite_name?: string;
};

export interface LuminaBoxMaterialDataset extends BackedGradientDataset {
  workflow?: LuminaBoxDatasetWorkflow;
}

export interface LuminaBoxMaterialRequest extends Omit<BackedGradientDatasetRequest, "materials"> {
  material_symbol?: BackedGradientSymbol;
  reference_id?: string;
  white_backing_id?: string;
  black_backing_id?: string;
}

export interface LuminaBoxBackingMaterialRequest extends Pick<BackedGradientDatasetRequest, "name" | "brand" | "material_type"> {
  role: "W" | "K";
  opposite_material_id?: string;
  material_id?: string;
}

export interface LuminaBoxBackingRequest extends Pick<BackedGradientDatasetRequest, "name" | "brand" | "material_type"> {
  white_name: string;
  black_name: string;
}

export interface LuminaBoxBlackWhitePairRequest {
  white: Pick<BackedGradientDatasetRequest, "name" | "brand" | "material_type">;
  black: Pick<BackedGradientDatasetRequest, "name" | "brand" | "material_type">;
}

export interface LuminaBoxMaterialFitRun extends Omit<BackedGradientFitRun, "fit_mode"> {
  fit_mode: "material" | "backing_reference" | "backing_material" | BackedGradientFitRun["fit_mode"];
  material_symbol?: BackedGradientSymbol;
  reference_id?: string;
  capture_reference_id?: string;
  fitted_reference_id?: string;
  backing_id?: string;
}

export interface LuminaBoxMaterialFitResult {
  status: string;
  selected_record_ids?: string[];
  estimated_rgb?: number[];
  rmse_pp?: number;
  material_symbol?: BackedGradientSymbol;
  reference_id?: string;
  capture_reference_id?: string;
  backing_id?: string;
  predictions?: BackedGradientPrediction[];
  backing_material_id?: string;
}

export interface LuminaBoxSavedMaterial {
  status: string;
  message: string;
  material: SavedMaterialLibraryItem;
}

const endpoint = "/extractor/lumina-box/backed-gradient";
const options = { timeout: 15_000 };
const idPath = (id: string) => encodeURIComponent(id);

/** Register the first black/white materials together. / 同时登记首组黑白耗材。 */
export async function createLuminaBoxBlackWhitePair(payload: LuminaBoxBlackWhitePairRequest): Promise<LuminaBoxMaterialDataset> {
  return (await apiClient.post<{ dataset: LuminaBoxMaterialDataset }>(`${endpoint}/black-white-pairs`, payload, options)).data.dataset;
}

/** List independently saved backing materials. / 列出分别保存的背板耗材资料。 */
export async function listLuminaBoxBackingMaterials(): Promise<LuminaBoxBackingMaterial[]> {
  return (await apiClient.get<{ backings: LuminaBoxBackingMaterial[] }>(`${endpoint}/backing-materials`, options)).data.backings;
}

/** Measure one backing material against its actual sample backing. / 单独采集一种背板及其实际样片底材信息。 */
export async function createLuminaBoxBackingMaterialDataset(payload: LuminaBoxBackingMaterialRequest): Promise<LuminaBoxMaterialDataset> {
  return (await apiClient.post<{ dataset: LuminaBoxMaterialDataset }>(`${endpoint}/backing-material-datasets`, payload, options)).data.dataset;
}

/** List reusable backing calibrations. / 列出可以复用的背板标定。 */
export async function listLuminaBoxBackingReferences(): Promise<LuminaBoxBackingReference[]> {
  const references = (await apiClient.get<{ references: LuminaBoxBackingReference[] }>(`${endpoint}/references`, options)).data.references;
  const latest = new Map<string, LuminaBoxBackingReference>();
  for (const reference of references) {
    const group = reference.backing_id || reference.reference_id;
    const previous = latest.get(group);
    if (!previous || (reference.version ?? 0) > (previous.version ?? 0)
      || ((reference.version ?? 0) === (previous.version ?? 0) && reference.created_at > previous.created_at)) latest.set(group, reference);
  }
  return [...latest.values()];
}

/** Start collection for one material. / 创建单种耗材的采集记录。 */
export async function createLuminaBoxMaterialDataset(payload: LuminaBoxMaterialRequest): Promise<LuminaBoxMaterialDataset> {
  return (await apiClient.post<{ dataset: LuminaBoxMaterialDataset }>(`${endpoint}/material-datasets`, payload, options)).data.dataset;
}

/** Start collection for a reusable backing pair. / 创建可复用黑白背板的采集记录。 */
export async function createLuminaBoxBackingDataset(payload: LuminaBoxBackingRequest): Promise<LuminaBoxMaterialDataset> {
  return (await apiClient.post<{ dataset: LuminaBoxMaterialDataset }>(`${endpoint}/backing-datasets`, payload, options)).data.dataset;
}

/** Fit only the selected material or backing pair. / 拟合选定耗材或背板组合。 */
export async function startLuminaBoxMaterialFit(
  datasetId: string, backing: boolean | "backing_material", materialSymbol: BackedGradientSymbol, referenceId: string,
): Promise<LuminaBoxMaterialFitRun> {
  const family = backing === "backing_material" ? "backing-material-datasets" : backing ? "backing-datasets" : "material-datasets";
  const payload = backing ? {} : { material_symbol: materialSymbol, reference_id: referenceId };
  return (await apiClient.post<{ run: LuminaBoxMaterialFitRun }>(`${endpoint}/${family}/${idPath(datasetId)}/fit-runs`, payload, options)).data.run;
}

/** Read a collection's saved fit jobs. / 读取采集记录的已保存计算任务。 */
export async function listLuminaBoxMaterialFits(datasetId: string): Promise<LuminaBoxMaterialFitRun[]> {
  return (await apiClient.get<{ runs: LuminaBoxMaterialFitRun[] }>(`${endpoint}/datasets/${idPath(datasetId)}/fit-runs`, options)).data.runs;
}

/** Read a fit job's current state. / 读取计算任务的当前状态。 */
export async function loadLuminaBoxMaterialFit(fitId: string): Promise<LuminaBoxMaterialFitRun> {
  return (await apiClient.get<{ run: LuminaBoxMaterialFitRun }>(`${endpoint}/fit-runs/${idPath(fitId)}`, options)).data.run;
}

/** Read the generated material summary. / 读取生成的耗材结果摘要。 */
export async function loadLuminaBoxMaterialFitResult(fitId: string): Promise<LuminaBoxMaterialFitResult> {
  return (await apiClient.get<{ result: LuminaBoxMaterialFitResult }>(`${endpoint}/fit-runs/${idPath(fitId)}/result`, options)).data.result;
}

/** Save a generated material into the library. / 将生成的耗材档案保存到耗材库。 */
export async function saveLuminaBoxMaterialArchive(
  fitId: string, payload: { name: string; brand: string; material_type: string; notes: string; overwrite: boolean },
): Promise<LuminaBoxSavedMaterial> {
  return (await apiClient.post<LuminaBoxSavedMaterial>(`${endpoint}/material-fit-runs/${idPath(fitId)}/archive`, payload, options)).data;
}
