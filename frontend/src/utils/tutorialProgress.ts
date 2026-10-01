/**
 * Beginner tutorial progress record kept in the viewer's browser storage.
 * 新手引导进度记录，保存在当前浏览器的本地存储中。
 *
 * The record only decides whether the first-run welcome may auto-open. It is a
 * per-device convenience, so a missing or unreadable record simply means "not
 * offered yet" and storage failures never block the app.
 * 该记录只用于判断首次启动时是否自动弹出欢迎窗；属于单设备便利状态，
 * 读不到记录即视为「尚未弹出过」，存储失败不会影响软件使用。
 */
import { nowBeijingIso } from "./beijingTime";

export const TUTORIAL_STORAGE_KEY = "lumina-beginner-tutorial";
/** Workspace the running tour must restore, kept across reloads. 进行中的引导需恢复的工作区，跨刷新保留。 */
export const TUTORIAL_WORKSPACE_STORAGE_KEY = "lumina-beginner-tutorial-workspace";

/** Outcome of the latest tutorial offer. 最近一次引导的结果。 */
export type TutorialOutcome = "offered" | "skipped" | "completed";

export interface TutorialProgressRecord {
  outcome: TutorialOutcome;
  updatedAt: string;
}

const KNOWN_OUTCOMES: ReadonlySet<string> = new Set<TutorialOutcome>([
  "offered",
  "skipped",
  "completed",
]);

/**
 * Read the stored tutorial record.
 * 读取已保存的引导记录。
 *
 * Returns:
 *     TutorialProgressRecord | null: Parsed record, or null when absent/invalid.
 *     解析后的记录；不存在或格式无效时返回 null。
 */
export function readTutorialProgress(): TutorialProgressRecord | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(TUTORIAL_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as { outcome?: unknown; updatedAt?: unknown };
    if (typeof parsed.outcome !== "string" || !KNOWN_OUTCOMES.has(parsed.outcome)) {
      return null;
    }
    return {
      outcome: parsed.outcome as TutorialOutcome,
      updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : "",
    };
  } catch {
    return null;
  }
}

/**
 * Persist the latest tutorial outcome.
 * 保存最近一次引导结果。
 *
 * Args:
 *     outcome (TutorialOutcome): Outcome to store. 要保存的结果。
 */
export function writeTutorialProgress(outcome: TutorialOutcome): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    const record: TutorialProgressRecord = { outcome, updatedAt: nowBeijingIso() };
    window.localStorage.setItem(TUTORIAL_STORAGE_KEY, JSON.stringify(record));
  } catch {
    // Ignore storage write failures such as private mode or quota errors.
  }
}

/**
 * Whether the first-run welcome was already offered on this device.
 * 当前设备是否已经弹出过首次欢迎窗。
 */
export function hasTutorialBeenOffered(): boolean {
  return readTutorialProgress() !== null;
}

/**
 * Read the raw workspace snapshot left by a tour that has not exited yet.
 * 读取尚未退出的引导留下的原始工作区快照。
 *
 * Returns:
 *     unknown: Parsed JSON, or null when absent/unreadable. The caller
 *     validates the shape. 解析后的 JSON；不存在或无法读取时为 null，由调用方校验结构。
 */
export function readTutorialWorkspaceSnapshot(): unknown {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(TUTORIAL_WORKSPACE_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as unknown) : null;
  } catch {
    return null;
  }
}

/**
 * Persist the running tour's workspace snapshot, or clear it with null.
 * 保存进行中引导的工作区快照；传入 null 时清除。
 *
 * Args:
 *     snapshot (unknown): JSON-serialisable snapshot, or null. 可序列化的快照或 null。
 */
export function writeTutorialWorkspaceSnapshot(snapshot: unknown): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (snapshot === null) {
      window.localStorage.removeItem(TUTORIAL_WORKSPACE_STORAGE_KEY);
    } else {
      window.localStorage.setItem(TUTORIAL_WORKSPACE_STORAGE_KEY, JSON.stringify(snapshot));
    }
  } catch {
    // Ignore storage failures; restoring then only covers the current page load.
  }
}
