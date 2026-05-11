/**
 * Action History Store — bounded in-memory ring of recent user actions and
 * session ids that feed the reproducible bug-report bundle.
 * 操作历史 Store：用户近期动作与会话的有界环形缓存，供反馈复现包使用。
 *
 * Design constraints (see `.kiro/specs/reproducible-bug-reports/design.md`):
 *   - Store creation MUST NOT touch `sessionStorage` (SLO 7, no startup I/O).
 *   - `pushAction` MUST be O(1) and stay under 0.5ms p95 (SLO 1).
 *   - sessionStorage writes MUST be debounced 100ms (SLO 9) and wrapped in
 *     try/catch so the UI never sees an exception (SLO 3).
 *   - To avoid circular imports back into `converterStore` / `widgetStore`,
 *     the current workflow snapshot is pulled through an injectable reader.
 *
 * 创建 store 时不得访问 sessionStorage、pushAction 保持常数时间、
 * sessionStorage 写入 100ms 合并 + try/catch 兜底，并使用快照读取器
 * 注入模式避免与其他 store 的循环引用。
 */

import { create } from "zustand";

import { postClientLog } from "../utils/clientLog";
import type {
  ActionEntry,
  ActionErrorInfo,
  ActionHistoryExport,
  ActionType,
  SessionRingEntry,
  WorkflowSnapshot,
  Workstream,
} from "../types/actionHistory";

export const ACTION_HISTORY_STORAGE_KEY = "lumina-action-history-v1";
export const ACTION_HISTORY_MAX_ENTRIES = 100;
export const ACTION_HISTORY_MAX_AGE_MS = 30 * 60 * 1000; // 30 minutes.
export const ACTION_HISTORY_FLUSH_DEBOUNCE_MS = 100;
export const SESSION_RING_MAX_ENTRIES = 5;

/**
 * Default snapshot returned before a real reader is installed. Keeping it
 * all-nulls means the store still works at app bootstrap without needing to
 * import the real workflow stores.
 * 未安装真实快照读取器之前返回的占位值。
 */
const DEFAULT_SNAPSHOT: WorkflowSnapshot = {
  color_mode: null,
  lut_name: null,
  source_version: null,
  selected_native_db_names: [],
  selected_material_dir_names: [],
  material_layer_count: null,
  material_layer_height_mm: null,
  material_backing_material_dir_name: null,
  active_tab: "unknown",
  advanced_params: null,
};

let _snapshotReader: () => WorkflowSnapshot = () => DEFAULT_SNAPSHOT;

/**
 * Input shape of `pushAction`. The store fills in `timestamp` and
 * `snapshot` automatically, so callers only describe the action itself.
 * pushAction 的入参形状：调用方只描述动作本身，store 自动填入时间和快照。
 */
export interface PushActionInput {
  action_type: ActionType;
  changed_fields?: Record<string, { from: unknown; to: unknown }>;
  error?: ActionErrorInfo;
}

interface ActionHistoryState {
  history: ActionEntry[];
  sessionRing: SessionRingEntry[];
  /** setTimeout handle for the pending sessionStorage flush, or null. */
  _pendingFlushTimer: number | null;
  /** Once true, sessionStorage is considered permanently unavailable. */
  _persistDisabled: boolean;

  pushAction: (entry: PushActionInput) => void;
  observeSession: (workstream: Workstream, sessionId: string | null) => void;
  exportForReport: () => ActionHistoryExport;
  loadPersistedHistory: () => void;
  scheduleFlush: () => void;
  setSnapshotReader: (reader: () => WorkflowSnapshot) => void;
  _resetForTests: () => void;
}

/**
 * Drop oldest entries until both limits hold:
 *   - history length <= MAX_ENTRIES
 *   - oldest entry is within MAX_AGE_MS of `now`
 * Pure / O(N) at worst, N = history length.
 * 丢弃最老的条目直到条数与时间窗都满足限制。
 */
function trimHistory(history: ActionEntry[], now: number): ActionEntry[] {
  let start = 0;
  const excess = history.length - ACTION_HISTORY_MAX_ENTRIES;
  if (excess > 0) {
    start = excess;
  }
  while (
    start < history.length &&
    now - history[start].timestamp > ACTION_HISTORY_MAX_AGE_MS
  ) {
    start += 1;
  }
  return start === 0 ? history : history.slice(start);
}

/**
 * Heuristic test for storage quota exhaustion across browser variants.
 * 跨浏览器检测配额耗尽错误。
 */
function isQuotaError(e: unknown): boolean {
  if (e == null) return false;
  const name = typeof (e as { name?: unknown }).name === "string" ? (e as { name: string }).name : "";
  const message = typeof (e as { message?: unknown }).message === "string"
    ? (e as { message: string }).message
    : String(e);
  return name.includes("Quota") || /quota/i.test(message);
}

/**
 * Merge persisted entries into the current history, dedupe by
 * (timestamp, action_type), sort ascending by timestamp, cap to MAX_ENTRIES.
 * Never throws; returns the current history on any failure.
 * 合并持久化历史，去重并保留最近 MAX_ENTRIES 条，异常时返回原 history。
 */
function mergeHistory(
  current: ActionEntry[],
  persisted: unknown,
): ActionEntry[] {
  if (!Array.isArray(persisted)) return current;
  const merged = new Map<string, ActionEntry>();
  for (const entry of [...persisted, ...current]) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Partial<ActionEntry>;
    if (typeof e.timestamp !== "number" || typeof e.action_type !== "string") {
      continue;
    }
    const key = `${e.timestamp}:${e.action_type}`;
    merged.set(key, entry as ActionEntry);
  }
  const sorted = [...merged.values()].sort(
    (a, b) => a.timestamp - b.timestamp,
  );
  if (sorted.length <= ACTION_HISTORY_MAX_ENTRIES) return sorted;
  return sorted.slice(sorted.length - ACTION_HISTORY_MAX_ENTRIES);
}

/**
 * Merge persisted session ring entries with the current ring. Dedupe by
 * (workstream, session_id) keeping the latest `last_seen_at`, sort by
 * `last_seen_at` descending, cap to `SESSION_RING_MAX_ENTRIES`.
 * 合并持久化的会话环，按最后观察时间保留最新版本。
 */
function mergeSessionRing(
  current: SessionRingEntry[],
  persisted: unknown,
): SessionRingEntry[] {
  if (!Array.isArray(persisted)) return current;
  const merged = new Map<string, SessionRingEntry>();
  for (const entry of [...current, ...persisted]) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Partial<SessionRingEntry>;
    if (
      typeof e.session_id !== "string" ||
      typeof e.workstream !== "string" ||
      typeof e.first_seen_at !== "number" ||
      typeof e.last_seen_at !== "number"
    ) {
      continue;
    }
    const key = `${e.workstream}:${e.session_id}`;
    const existing = merged.get(key);
    if (!existing || existing.last_seen_at < e.last_seen_at) {
      merged.set(key, entry as SessionRingEntry);
    }
  }
  const sorted = [...merged.values()].sort(
    (a, b) => b.last_seen_at - a.last_seen_at,
  );
  return sorted.slice(0, SESSION_RING_MAX_ENTRIES);
}

export const useActionHistoryStore = create<ActionHistoryState>((set, get) => ({
  history: [],
  sessionRing: [],
  _pendingFlushTimer: null,
  _persistDisabled: false,

  pushAction: (entry) => {
    try {
      const now = Date.now();
      let snapshot: WorkflowSnapshot;
      try {
        snapshot = _snapshotReader();
      } catch {
        snapshot = DEFAULT_SNAPSHOT;
      }
      const full: ActionEntry = {
        timestamp: now,
        action_type: entry.action_type,
        snapshot,
      };
      if (entry.changed_fields) {
        full.changed_fields = entry.changed_fields;
      }
      if (entry.error) {
        full.error = entry.error;
      }
      const next = trimHistory([...get().history, full], now);
      set({ history: next });
      get().scheduleFlush();
    } catch {
      // SLO 3: never throw from an input handler path.
    }
  },

  observeSession: (workstream, sessionId) => {
    try {
      if (sessionId == null || sessionId === "") return;
      const now = Date.now();
      const existing = get().sessionRing;
      const idx = existing.findIndex(
        (e) => e.workstream === workstream && e.session_id === sessionId,
      );
      let next: SessionRingEntry[];
      if (idx >= 0) {
        next = existing.slice();
        next[idx] = { ...next[idx], last_seen_at: now };
      } else {
        // Append to the tail; the head of the array is the oldest entry by
        // insertion order. This gives a stable FIFO eviction policy even
        // when multiple synchronous observeSession calls land in the same
        // millisecond (first_seen_at would be equal, so timestamps alone
        // cannot discriminate).
        // 追加到尾部；当多次同步调用落在同一毫秒时，插入顺序作为稳定的
        // 二级排序键，保证 FIFO 淘汰。
        const entry: SessionRingEntry = {
          workstream,
          session_id: sessionId,
          first_seen_at: now,
          last_seen_at: now,
        };
        // Prepend so the newest observation sits at index 0; then drop
        // anything past the ring cap (oldest entries fall off the tail).
        // 新观察置顶；超过容量时从末尾（最老）淘汰。
        next = [entry, ...existing];
        if (next.length > SESSION_RING_MAX_ENTRIES) {
          next = next.slice(0, SESSION_RING_MAX_ENTRIES);
        }
      }
      set({ sessionRing: next });
      get().scheduleFlush();
    } catch {
      // SLO 3: swallow.
    }
  },

  exportForReport: () => {
    const { history, sessionRing } = get();
    return {
      history: [...history],
      session_history: [...sessionRing],
    };
  },

  loadPersistedHistory: () => {
    try {
      if (typeof window === "undefined" || !window.sessionStorage) return;
      const raw = window.sessionStorage.getItem(ACTION_HISTORY_STORAGE_KEY);
      if (raw == null) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        return;
      }
      if (!parsed || typeof parsed !== "object") return;
      const obj = parsed as { history?: unknown; sessionRing?: unknown };
      if (!Array.isArray(obj.history) || !Array.isArray(obj.sessionRing)) {
        return;
      }
      const { history, sessionRing } = get();
      const mergedHistory = mergeHistory(history, obj.history);
      const mergedRing = mergeSessionRing(sessionRing, obj.sessionRing);
      set({ history: mergedHistory, sessionRing: mergedRing });
    } catch {
      // SLO 3: swallow.
    }
  },

  scheduleFlush: () => {
    try {
      if (get()._persistDisabled) return;
      if (get()._pendingFlushTimer != null) return;
      if (typeof setTimeout === "undefined") return;
      // Use the global setTimeout (not window.setTimeout) so vitest's fake
      // timers reliably intercept the schedule in tests — happy-dom's
      // window.setTimeout is not always the same reference vitest hooks.
      // 使用全局 setTimeout 而非 window.setTimeout，确保 vitest 的 fake
      // timer 能稳定拦截；happy-dom 里两者不一定是同一个引用。
      const handle = setTimeout(() => {
        set({ _pendingFlushTimer: null });
        flushToSessionStorage(get, set);
      }, ACTION_HISTORY_FLUSH_DEBOUNCE_MS) as unknown as number;
      set({ _pendingFlushTimer: handle });
    } catch {
      // SLO 3: swallow.
    }
  },

  setSnapshotReader: (reader) => {
    _snapshotReader = reader;
  },

  _resetForTests: () => {
    const current = get()._pendingFlushTimer;
    if (current != null) {
      try {
        clearTimeout(current);
      } catch {
        // ignore
      }
    }
    _snapshotReader = () => DEFAULT_SNAPSHOT;
    set({
      history: [],
      sessionRing: [],
      _pendingFlushTimer: null,
      _persistDisabled: false,
    });
  },
}));

/**
 * Persist the current history + session ring to sessionStorage. On quota
 * overflow, trim the history to half and retry once; after a final failure,
 * flip `_persistDisabled` to stop hammering the API for the rest of the
 * session and emit a single client_log warning.
 * 把历史+会话环落盘；配额满时砍一半重试，仍失败则停用持久化并记一条警告。
 */
function flushToSessionStorage(
  get: () => ActionHistoryState,
  set: (partial: Partial<ActionHistoryState>) => void,
): void {
  try {
    if (get()._persistDisabled) return;
    // Access sessionStorage defensively; some test environments stub it out.
    // 防御式访问 sessionStorage，部分测试环境可能 stub 掉它。
    const storage =
      typeof window !== "undefined" && window.sessionStorage
        ? window.sessionStorage
        : typeof globalThis !== "undefined" && "sessionStorage" in globalThis
        ? (globalThis as { sessionStorage?: Storage }).sessionStorage
        : undefined;
    if (!storage) return;
    const { history, sessionRing } = get();
    let payload: string;
    try {
      payload = JSON.stringify({ history, sessionRing });
    } catch (e) {
      postClientLog("actionHistoryStore: serialize failed", {
        method: "warn",
        details: { error_message: String(e) },
      });
      return;
    }
    try {
      storage.setItem(ACTION_HISTORY_STORAGE_KEY, payload);
      return;
    } catch (e) {
      if (!isQuotaError(e)) {
        set({ _persistDisabled: true });
        postClientLog("actionHistoryStore: sessionStorage flush failed", {
          method: "warn",
          details: { error_message: String(e) },
        });
        return;
      }
      // Quota overflow: keep the newest half and retry once.
      const trimmed = history.slice(Math.floor(history.length / 2));
      set({ history: trimmed });
      try {
        const retryPayload = JSON.stringify({
          history: trimmed,
          sessionRing: get().sessionRing,
        });
        storage.setItem(ACTION_HISTORY_STORAGE_KEY, retryPayload);
      } catch (retryErr) {
        set({ _persistDisabled: true });
        postClientLog("actionHistoryStore: sessionStorage flush failed", {
          method: "warn",
          details: { error_message: String(retryErr) },
        });
      }
    }
  } catch (e) {
    // Outermost safety net.
    try {
      set({ _persistDisabled: true });
      postClientLog("actionHistoryStore: sessionStorage flush failed", {
        method: "warn",
        details: { error_message: String(e) },
      });
    } catch {
      // ignore
    }
  }
}
