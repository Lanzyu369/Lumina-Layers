import {
  BACKED_GRADIENT_SYMBOLS, BACKED_GRADIENT_CAPTURE_SYMBOLS, BACKED_GRADIENT_THICKNESSES,
  type BackedGradientBacking, type BackedGradientCapture, type BackedGradientCaptureRequest,
  type BackedGradientDataset, type BackedGradientExport, type BackedGradientRole, type BackedGradientSymbol, type BackedGradientXYZ,
} from "../api/luminaBoxBackedGradient";
import { parseLuminaBoxFrame, type LuminaBoxCaptureResult, type LuminaBoxMeasurement } from "../api/luminaBoxSerial";
import type { LuminaBoxMaterialDataset } from "../api/luminaBoxMaterials";

export const BACKED_GRADIENT_DRAFT_KEY = "lumina-box-backed-gradient-draft-v1";
export const BACKED_GRADIENT_JOURNAL_KEY = "lumina-box-backed-gradient-journal-v1";
export const BACKED_GRADIENT_MAX_IMPORT_BYTES = 10 * 1024 * 1024;

export interface BackedGradientTarget {
  material_symbol: BackedGradientSymbol;
  backing: BackedGradientBacking;
  sample_role: BackedGradientRole;
}

export interface BackedGradientDraft {
  datasetId: string;
  target: BackedGradientTarget;
  manualThickness: string;
  manualXYZ: [string, string, string];
  sampleName: string;
  notes: string;
}

export interface BackedGradientArmedScope {
  captureId: string;
  datasetId: string;
  target: BackedGradientTarget;
}

export interface BackedGradientJournalEntry {
  key: string;
  datasetId: string;
  measurementId: string;
  receivedAt: string;
  outcome: "pending" | "saved" | "abandoned" | "rejected";
  rejection?: Exclude<LuminaBoxCaptureResult, "applied">;
  request: BackedGradientCaptureRequest | null;
  recordId?: string;
}

export interface BackedGradientJournal {
  scope: BackedGradientArmedScope | null;
  entries: BackedGradientJournalEntry[];
}

const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);

/** List real saved materials, excluding unused historical color placeholders.
 * 列出实际保存的耗材，排除历史表格中未使用的颜色占位。 */
export function savedBackedGradientMaterialSymbols(dataset: LuminaBoxMaterialDataset): BackedGradientSymbol[] {
  if (dataset.workflow?.kind === "material" || dataset.workflow?.kind === "backing_material") return [dataset.workflow.material_symbol];
  if (dataset.workflow?.kind === "backing_reference") return ["K"];
  return BACKED_GRADIENT_CAPTURE_SYMBOLS.filter((symbol) => {
    const name = dataset.materials[symbol]?.trim();
    return (!!name && name !== symbol)
      || dataset.captures.some((record) => record.sample_role === "coated" && record.material_symbol === symbol);
  });
}

/** Validate a visible capture target. / 校验页面采集目标。 */
export function isBackedGradientTarget(value: unknown): value is BackedGradientTarget {
  if (!isObject(value)) return false;
  return BACKED_GRADIENT_CAPTURE_SYMBOLS.includes(value.material_symbol as BackedGradientSymbol)
    && (value.backing === "W" || value.backing === "K")
    && (value.sample_role === "coated" || value.sample_role === "bare_backing")
    && (value.sample_role !== "bare_backing" || value.material_symbol === value.backing);
}

/** Identify a dataset/material/backing capture context. / 标识数据集、材料和底色采集上下文。 */
export function backedGradientTargetKey(datasetId: string, target: BackedGradientTarget): string {
  return JSON.stringify([datasetId, target.material_symbol, target.backing, target.sample_role]);
}

/** Use the backend's canonical reading-slot key. / 使用后端规范的读数格标识。 */
export function backedGradientSlotKey(target: BackedGradientTarget, thickness: number): string {
  return target.sample_role === "bare_backing" ? `bare:${target.backing}`
    : `${target.material_symbol}:${target.backing}:${thickness.toFixed(2)}`;
}

/** Resolve the slot occupied by an existing capture. / 读取已有采集所属的测量格。 */
export function backedGradientCaptureSlot(record: BackedGradientCapture): string {
  return backedGradientSlotKey(record, record.overlay_mm);
}

/** Parse uncropped reflection percentages. / 解析未经裁切的反射百分数。 */
export function backedGradientManualXYZ(values: readonly string[]): BackedGradientXYZ | null {
  if (values.length !== 3 || values.some((value) => !value.trim())) return null;
  const numbers = values.map(Number);
  return numbers.every((value) => Number.isFinite(value) && value >= 0)
    ? [numbers[0], numbers[1], numbers[2]] : null;
}

/** Match one of the seven physical overlay thicknesses. / 匹配七档实际覆层厚度之一。 */
export function backedGradientThickness(value: number): number | null {
  return BACKED_GRADIENT_THICKNESSES.find((thickness) => Math.abs(value - thickness) < 0.000001) ?? null;
}

/** Freeze a received frame against the armed target without rewriting device metadata.
 * 将设备原帧绑定至已固定目标，不改写设备元数据。 */
export function routeBackedGradientMeasurement(
  target: BackedGradientTarget,
  captureId: string,
  measurement: LuminaBoxMeasurement,
  receivedAt: string,
  metadata: { sampleName: string; notes: string },
): { result: "ready"; request: BackedGradientCaptureRequest } | { result: Exclude<LuminaBoxCaptureResult, "applied"> } {
  if (!isBackedGradientTarget(target)) return { result: "invalid_recipe" };
  if (measurement.mode === "transmit") return { result: "unsupported_mode" };
  const overlay = target.sample_role === "bare_backing" ? 0 : backedGradientThickness(measurement.thickness_mm);
  if (overlay === null) return { result: "thickness_missing" };
  return { result: "ready", request: {
    capture_id: captureId, ...target, overlay_mm: overlay,
    measurement: JSON.parse(JSON.stringify(measurement)) as LuminaBoxMeasurement,
    received_at: receivedAt, sample_name: metadata.sampleName.trim(), notes: metadata.notes,
  } };
}

/** Restore only this workflow's input draft. / 仅恢复本流程的输入草稿。 */
export function restoreBackedGradientDraft(): BackedGradientDraft {
  const draft: BackedGradientDraft = { datasetId: "", target: { material_symbol: "R", backing: "W", sample_role: "coated" },
    manualThickness: "0.08", manualXYZ: ["", "", ""], sampleName: "", notes: "" };
  try {
    const value: unknown = JSON.parse(localStorage.getItem(BACKED_GRADIENT_DRAFT_KEY) ?? "null");
    if (!isObject(value)) return draft;
    if (typeof value.datasetId === "string") draft.datasetId = value.datasetId;
    if (isBackedGradientTarget(value.target)) draft.target = value.target;
    if (typeof value.manualThickness === "string" && backedGradientThickness(Number(value.manualThickness)) !== null) draft.manualThickness = value.manualThickness;
    if (Array.isArray(value.manualXYZ) && value.manualXYZ.length === 3 && value.manualXYZ.every((item) => typeof item === "string")) draft.manualXYZ = value.manualXYZ as [string, string, string];
    if (typeof value.sampleName === "string") draft.sampleName = value.sampleName;
    if (typeof value.notes === "string") draft.notes = value.notes;
  } catch { /* A damaged draft must not block a new acquisition. */ }
  return draft;
}

function isJournalEntry(value: unknown): value is BackedGradientJournalEntry {
  if (!isObject(value) || typeof value.key !== "string" || typeof value.datasetId !== "string"
    || typeof value.measurementId !== "string" || typeof value.receivedAt !== "string"
    || !["pending", "saved", "abandoned", "rejected"].includes(String(value.outcome))) return false;
  if (value.outcome === "rejected") return value.request === null;
  const request = value.request;
  if (!isObject(request) || !isBackedGradientTarget(request) || typeof request.capture_id !== "string"
    || typeof request.overlay_mm !== "number" || typeof request.received_at !== "string") return false;
  if (request.sample_role === "bare_backing" ? request.overlay_mm !== 0 : backedGradientThickness(request.overlay_mm) === null) return false;
  if (request.measurement) {
    const frame = parseLuminaBoxFrame(JSON.stringify(request.measurement));
    return frame.kind === "measurement" && frame.measurement.mode !== "transmit"
      && frame.measurement.measurement_id === value.measurementId;
  }
  return request.measurement_id === value.measurementId && Array.isArray(request.reflectance_percent_xyz)
    && request.reflectance_percent_xyz.length === 3 && request.reflectance_percent_xyz.every((item) => typeof item === "number" && Number.isFinite(item) && item >= 0);
}

/** Restore frozen pending payloads and their scope ownership. / 恢复冻结的待保存请求及采集批次归属。 */
export function restoreBackedGradientJournal(): BackedGradientJournal {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(BACKED_GRADIENT_JOURNAL_KEY) ?? "null");
    if (!isObject(value)) return { scope: null, entries: [] };
    const scope = isObject(value.scope) && typeof value.scope.captureId === "string" && typeof value.scope.datasetId === "string"
      && isBackedGradientTarget(value.scope.target) ? value.scope as unknown as BackedGradientArmedScope : null;
    return { scope, entries: Array.isArray(value.entries) ? value.entries.filter(isJournalEntry) : [] };
  } catch { return { scope: null, entries: [] }; }
}

/** Bound receipts without removing any pending reading. / 限制历史回执数量，同时保留全部待读数。 */
export function compactBackedGradientJournal(journal: BackedGradientJournal): BackedGradientJournal {
  const pending = journal.entries.filter((entry) => entry.outcome === "pending");
  const receipts = journal.entries.filter((entry) => entry.outcome !== "pending").slice(-512);
  return { ...journal, entries: [...receipts, ...pending] };
}

/** Check an imported envelope before sending it for full server validation.
 * 导入前校验文件外层格式，完整数据仍交后端校验。 */
export function isBackedGradientExport(value: unknown): value is BackedGradientExport {
  return isObject(value) && value.kind === "lumina_box_backed_gradient_export" && value.schema_version === "1.0"
    && isObject(value.dataset) && typeof value.dataset.dataset_id === "string" && Array.isArray(value.dataset.captures);
}

/** Find saved and missing samples for the full collection.
 * 统计完整采集的已保存样片与缺失样片。 */
export function backedGradientReadiness(dataset: BackedGradientDataset | null) {
  const symbols = BACKED_GRADIENT_SYMBOLS.filter((symbol) => ["R", "Y", "B", "W", "K"].includes(symbol)
    || dataset?.captures.some((record) => record.material_symbol === symbol));
  const selected = new Set(Object.entries(dataset?.selected_capture_ids ?? {})
    .filter(([, id]) => dataset?.captures.some((record) => record.record_id === id)).map(([slot]) => slot));
  const training = ["bare:W", "bare:K"];
  const validation: string[] = [];
  const targets: Array<{ target: BackedGradientTarget; thickness: number; slot: string }> =
    (["W", "K"] as const).map((backing) => ({
      target: { material_symbol: backing, backing, sample_role: "bare_backing" },
      thickness: 0, slot: `bare:${backing}`,
    }));
  for (const symbol of symbols) for (const backing of ["W", "K"] as const) {
    for (const thickness of BACKED_GRADIENT_THICKNESSES) {
      const target: BackedGradientTarget = { material_symbol: symbol, backing, sample_role: "coated" };
      const slot = backedGradientSlotKey(target, thickness);
      targets.push({ target, thickness, slot });
      (thickness === .24 ? validation : training).push(slot);
    }
  }
  const perBacking = Object.fromEntries((["W", "K"] as const).map((backing) => {
    const side = targets.filter((item) => item.target.backing === backing);
    return [backing, { count: side.filter((item) => selected.has(item.slot)).length, total: side.length }];
  })) as Record<BackedGradientBacking, { count: number; total: number }>;
  return { symbols, count: targets.filter((item) => selected.has(item.slot)).length, total: targets.length,
    perBacking, missingTargets: targets.filter((item) => !selected.has(item.slot)),
    trainingCount: training.filter((slot) => selected.has(slot)).length, trainingTotal: training.length,
    validationCount: validation.filter((slot) => selected.has(slot)).length, validationTotal: validation.length };
}

function backendErrorText(error: unknown): string {
  if (typeof error === "string") return error;
  if (!isObject(error)) return "";
  const response = isObject(error.response) ? error.response : null;
  const body = response && isObject(response.data) ? response.data : null;
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (isObject(detail)) return String(detail.message ?? detail.error ?? detail.code ?? "");
  return typeof error.message === "string" ? error.message : "";
}

/** Choose an actionable translated message without exposing server internals.
 * 选择可操作的本地化提示，避免将服务端内部说明显示给用户。 */
export function backedGradientErrorKey(error: unknown, fallbackKey: string): string {
  const text = backendErrorText(error);
  const rules: Array<[RegExp, string]> = [
    [/backings use different measurement calibrations/i, "backing_calibration_mismatch"],
    [/missing reference readings|needs measured bare|bare (?:white|black) references/i, "missing_references"],
    [/bare white.*(?:exceed|higher)|white anchors.*exceed|reference.*(?:range|invert)/i, "invalid_references"],
    [/missing backed.gradient readings|required.*complete.*data|complete R\/Y\/B\/W\/K|paired.*background|needs at least.*thickness/i, "missing_samples"],
    [/interrupted|backend restarted|cancelled|canceled/i, "calculation_interrupted"],
    [/timed? out|timeout/i, "calculation_timeout"],
    [/fit is already running|experiment fit is already running/i, "calculation_busy"],
    [/not found|no longer exists/i, "record_missing"],
    [/different (?:data|target)|belongs to different|conflict|measurement (?:was deleted|ID belongs)/i, "record_conflict"],
    [/only available from the local/i, "local_only"],
    [/nonnegative|finite.*(?:XYZ|values)|numeric.*XYZ|unsupported fields|sample is incomplete/i, "invalid_input"],
  ];
  const matched = rules.find(([pattern]) => pattern.test(text));
  return matched ? `lumina_box_bg_error_${matched[1]}` : fallbackKey;
}
