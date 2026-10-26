/**
 * Action History Store — complete in-memory history of user actions and
 * session ids that feed the reproducible bug-report bundle.
 * 操作历史 Store：保留用户动作与会话的完整历史，供反馈复现包使用。
 *
 * Design constraints (see `.kiro/specs/reproducible-bug-reports/design.md`):
 *   - Store creation MUST NOT touch `sessionStorage` (SLO 7, no startup I/O).
 *   - `pushAction` stays synchronous; persistence is deferred.
 *   - sessionStorage writes MUST be debounced 100ms (SLO 9) and wrapped in
 *     try/catch so the UI never sees an exception (SLO 3).
 *   - To avoid circular imports back into `converterStore` / `widgetStore`,
 *     the current workflow snapshot is pulled through an injectable reader.
 *
 * 创建 store 时不得访问 sessionStorage、pushAction 同步记录、
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
export const ACTION_HISTORY_FLUSH_DEBOUNCE_MS = 100;

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
 * Merge complete persisted history without replaying cached occurrences.
 * Keep different actions in the same millisecond and repeated identical actions.
 * Never throws; returns the current history on any failure.
 * 合并完整持久化历史，保留同毫秒的不同动作与重复动作，避免重复加载。
 */
function mergeHistory(
  current: ActionEntry[],
  persisted: unknown,
): ActionEntry[] {
  if (!Array.isArray(persisted)) return current;
  const merged: ActionEntry[] = [];
  const persistedCounts = new Map<string, number>();
  const currentCounts = new Map<string, number>();
  for (const entry of persisted) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Partial<ActionEntry>;
    if (typeof e.timestamp !== "number" || typeof e.action_type !== "string") {
      continue;
    }
    const key = JSON.stringify(entry);
    persistedCounts.set(key, (persistedCounts.get(key) ?? 0) + 1);
    merged.push(entry as ActionEntry);
  }
  for (const entry of current) {
    const key = JSON.stringify(entry);
    const count = (currentCounts.get(key) ?? 0) + 1;
    currentCounts.set(key, count);
    if (count > (persistedCounts.get(key) ?? 0)) merged.push(entry);
  }
  return merged.sort((a, b) => a.timestamp - b.timestamp);
}

/**
 * Merge persisted session ring entries with the current ring. Dedupe by
 * (workstream, session_id) keeping the latest `last_seen_at`, sort by
 * `last_seen_at` descending, retaining every session.
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
  return sorted;
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
      const next = [...get().history, full];
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
        const entry: SessionRingEntry = {
          workstream,
          session_id: sessionId,
          first_seen_at: now,
          last_seen_at: now,
        };
        // Keep every session, with the newest observation first.
        next = [entry, ...existing];
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
 * overflow, retain all in-memory history and disable persistence for the
 * session and emit a single client_log warning.
 * 把历史与会话落盘；配额满时保留全部内存历史，停用持久化并记一条警告。
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
      set({ _persistDisabled: true });
      postClientLog("actionHistoryStore: sessionStorage flush failed", {
        method: "warn",
        details: { error_message: String(e) },
      });
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
