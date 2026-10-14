import type { LuminaBoxStackSampleRequest } from "../api/luminaBoxStackSamples";
import { parseLuminaBoxFrame } from "../api/luminaBoxSerial";
import type { LuminaBoxXYZ } from "../api/types";

export const LUMINA_BOX_STACK_DRAFT_KEY = "lumina-box-stack-sample-draft-v1";
export const LUMINA_BOX_STACK_CAPTURE_KEY = "lumina-box-stack-capture-journal-v1";

export interface LuminaBoxStackDraft {
  recipe: string;
  sampleName: string;
  materialBatch: string;
  notes: string;
  referenceDirectoryName: string;
}

export interface LuminaBoxStackCaptureEntry {
  key: string;
  receivedAt: string;
  outcome: "pending" | "saved" | "invalid_recipe" | "unsupported_mode";
  request: LuminaBoxStackSampleRequest | null;
}

export const normalizeStackRecipe = (value: string): string => value.toUpperCase().replace(/\s/g, "");
export const isValidStackRecipe = (value: string): boolean => /^[WRYBCMGK]{1,35}$/.test(value);
export const stackCaptureKey = (captureId: string, measurementId: string): string => JSON.stringify([captureId, measurementId]);

/** Restore input text while leaving the current instrument settings intact.
 * 恢复输入草稿，保留当前仪器设置。 */
export function restoreStackDraft(): LuminaBoxStackDraft {
  const empty: LuminaBoxStackDraft = { recipe: "", sampleName: "", materialBatch: "", notes: "", referenceDirectoryName: "" };
  try {
    const value: unknown = JSON.parse(localStorage.getItem(LUMINA_BOX_STACK_DRAFT_KEY) ?? "null");
    if (!value || typeof value !== "object") return empty;
    const draft = value as Record<string, unknown>;
    for (const key of Object.keys(empty) as Array<keyof LuminaBoxStackDraft>) {
      if (typeof draft[key] === "string" && draft[key].length <= 4000) empty[key] = draft[key];
    }
    return empty;
  } catch { return empty; }
}

/** Read existing per-measurement targets so retries cannot adopt a later recipe.
 * 恢复每条测量原有的采集目标，避免重试时改归后来的配方。 */
export function restoreStackCaptureJournal(): LuminaBoxStackCaptureEntry[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(LUMINA_BOX_STACK_CAPTURE_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((value): value is LuminaBoxStackCaptureEntry => {
      if (!value || typeof value !== "object") return false;
      const entry = value as LuminaBoxStackCaptureEntry;
      if (typeof entry.key !== "string" || typeof entry.receivedAt !== "string"
        || !["pending", "saved", "invalid_recipe", "unsupported_mode"].includes(entry.outcome)) return false;
      if (entry.outcome === "invalid_recipe" || entry.outcome === "unsupported_mode") return entry.request === null;
      const request = entry.request;
      if (!request || typeof request.capture_id !== "string" || !isValidStackRecipe(request.recipe_top_to_bottom)) return false;
      const frame = parseLuminaBoxFrame(JSON.stringify(request.measurement));
      return frame.kind === "measurement" && frame.measurement.mode !== "transmit"
        && entry.key === stackCaptureKey(request.capture_id, frame.measurement.measurement_id);
    });
  } catch { return []; }
}

/** Keep failed captures intact and bound the completed/rejected receipt history.
 * 保留全部待保存读数，并限制已完成或拒收的历史回执数量。 */
export function compactStackCaptureJournal(entries: LuminaBoxStackCaptureEntry[]): LuminaBoxStackCaptureEntry[] {
  const pending = entries.filter((entry) => entry.outcome === "pending");
  const finished = entries.filter((entry) => entry.outcome !== "pending").slice(-512);
  return [...finished, ...pending];
}

/** Parse the currently selected diffuser values without changing settings.
 * 读取当前匀光板数值，不写入或替换设置。 */
export function stackMeasurementBacking(values: readonly string[]): LuminaBoxXYZ | null {
  if (values.length !== 3 || values.some((value) => !value.trim())) return null;
  const parsed = values.map(Number);
  return parsed.every((value) => Number.isFinite(value) && value >= 0 && value <= 100)
    ? [parsed[0], parsed[1], parsed[2]] : null;
}
