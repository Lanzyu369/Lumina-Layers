/**
 * Tests for the action history store feeding the reproducible bug-report
 * bundle. Covers pushAction performance, throttled sessionStorage flush,
 * quota-exhaustion fallback, session ring eviction, and persisted-history
 * merge paths.
 * 操作历史 Store 的单元测试，覆盖性能、节流、配额降级、会话环淘汰与合并路径。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ACTION_HISTORY_FLUSH_DEBOUNCE_MS,
  ACTION_HISTORY_STORAGE_KEY,
  useActionHistoryStore,
} from "../actionHistoryStore";
import type { WorkflowSnapshot } from "../../types/actionHistory";

// Mock postClientLog so flush failures do not hit /api/client-log during tests
// and we can assert on warning emissions.
// 通过 mock 拦截反馈日志调用，同时便于断言警告次数。
vi.mock("../../utils/clientLog", () => ({
  postClientLog: vi.fn(),
}));

import { postClientLog } from "../../utils/clientLog";

const postClientLogMock = vi.mocked(postClientLog);

function buildSnapshot(overrides: Partial<WorkflowSnapshot> = {}): WorkflowSnapshot {
  return {
    color_mode: "4-Color RYBW",
    lut_name: "Lumina_Default",
    source_version: "legacy",
    selected_native_db_names: [],
    selected_material_dir_names: [],
    material_layer_count: null,
    material_layer_height_mm: null,
    material_backing_material_dir_name: null,
    advanced_params: null,
    active_tab: "converter",
    ...overrides,
  };
}

// jsdom's window.sessionStorage is a special getter-backed object that
// rejects property spying in some versions. We therefore stand up a plain
// in-memory storage impl backed by ``vi.fn`` spies, and install it via
// Object.defineProperty over the built-in. Every test swaps in a fresh
// instance so assertions do not leak across cases.
// jsdom 的 window.sessionStorage 是特殊的 getter-backed 对象，部分版本下
// 无法被 vi.spyOn 正确拦截；这里用一个纯内存 storage 完全替换它，方便断言。

interface MockStorage {
  getItem: ReturnType<typeof vi.fn>;
  setItem: ReturnType<typeof vi.fn>;
  removeItem: ReturnType<typeof vi.fn>;
  clear: ReturnType<typeof vi.fn>;
  key: ReturnType<typeof vi.fn>;
  readonly length: number;
}

function createMockStorage(): MockStorage {
  const backing = new Map<string, string>();
  const storage = {
    getItem: vi.fn((k: string) => (backing.has(k) ? backing.get(k)! : null)),
    setItem: vi.fn((k: string, v: string) => {
      backing.set(k, String(v));
    }),
    removeItem: vi.fn((k: string) => {
      backing.delete(k);
    }),
    clear: vi.fn(() => {
      backing.clear();
    }),
    key: vi.fn((i: number) => Array.from(backing.keys())[i] ?? null),
    get length() {
      return backing.size;
    },
  } as unknown as MockStorage;
  return storage;
}

let _currentMockStorage: MockStorage = createMockStorage();

function getItemSpy() {
  return _currentMockStorage.getItem;
}

function setItemSpy() {
  return _currentMockStorage.setItem;
}

describe("actionHistoryStore", () => {
  beforeEach(() => {
    _currentMockStorage = createMockStorage();
    Object.defineProperty(window, "sessionStorage", {
      value: _currentMockStorage,
      configurable: true,
      writable: true,
    });
    useActionHistoryStore.getState()._resetForTests();
    postClientLogMock.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    useActionHistoryStore.getState()._resetForTests();
  });

  it("creating the store does not touch sessionStorage (SLO 7)", () => {
    const getSpy = getItemSpy();
    // Reading from the store should not trigger persistence reads.
    const { history, sessionRing } = useActionHistoryStore.getState();
    expect(history).toEqual([]);
    expect(sessionRing).toEqual([]);
    expect(
      getSpy.mock.calls.some(
        ([key]) => key === ACTION_HISTORY_STORAGE_KEY,
      ),
    ).toBe(false);
  });

  it("pushAction appends entry with correct action_type and snapshot", () => {
    const snapshot = buildSnapshot({
      color_mode: "8-Color CMYKWGKB",
      lut_name: "Lumina_MaterialArchive_v2",
    });
    useActionHistoryStore.getState().setSnapshotReader(() => snapshot);

    useActionHistoryStore
      .getState()
      .pushAction({ action_type: "color_mode_change" });

    const { history } = useActionHistoryStore.getState();
    expect(history).toHaveLength(1);
    expect(history[0].action_type).toBe("color_mode_change");
    expect(history[0].snapshot).toEqual(snapshot);
    expect(typeof history[0].timestamp).toBe("number");
  });

  it("preserves every action beyond the former count limit", () => {
    useActionHistoryStore
      .getState()
      .setSnapshotReader(() => buildSnapshot());

    for (let i = 0; i < 150; i += 1) {
      useActionHistoryStore
        .getState()
        .pushAction({ action_type: "preview" });
    }

    const { history } = useActionHistoryStore.getState();
    expect(history).toHaveLength(150);
    // Newest timestamp should be greater than or equal to oldest kept.
    expect(history[history.length - 1].timestamp).toBeGreaterThanOrEqual(
      history[0].timestamp,
    );
  });

  it("preserves actions older than the former time window", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-11T10:00:00Z"));
    useActionHistoryStore
      .getState()
      .setSnapshotReader(() => buildSnapshot());

    useActionHistoryStore
      .getState()
      .pushAction({ action_type: "upload_image" });
    expect(useActionHistoryStore.getState().history).toHaveLength(1);

    // Advance 31 minutes — older than the 30-minute window.
    vi.setSystemTime(new Date(Date.now() + 31 * 60_000));

    useActionHistoryStore.getState().pushAction({ action_type: "generate" });

    const { history } = useActionHistoryStore.getState();
    expect(history).toHaveLength(2);
    expect(history.map((entry) => entry.action_type)).toEqual(["upload_image", "generate"]);
  });

  it("pushAction p95 stays under the SLO target (SLO 1)", () => {
    useActionHistoryStore
      .getState()
      .setSnapshotReader(() => buildSnapshot());

    const samples: number[] = [];
    // Warmup — JIT and cold branches should not contaminate the sample set.
    for (let i = 0; i < 20; i += 1) {
      useActionHistoryStore
        .getState()
        .pushAction({ action_type: "preview" });
    }
    useActionHistoryStore.getState()._resetForTests();
    useActionHistoryStore
      .getState()
      .setSnapshotReader(() => buildSnapshot());

    for (let i = 0; i < 100; i += 1) {
      const start = performance.now();
      useActionHistoryStore
        .getState()
        .pushAction({ action_type: "preview" });
      samples.push(performance.now() - start);
    }
    samples.sort((a, b) => a - b);
    const p95 = samples[Math.floor(samples.length * 0.95)];
    // Local M1 target is 0.5ms; CI machines (GitHub Actions linux runners)
    // sit on shared hardware, so the spec allows a looser 2ms safety net.
    // 本地 M1 使用 0.5ms；CI 环境允许 2ms 以避免抖动导致 flake。
    const threshold = process.env.CI ? 2 : 0.5;
    expect(p95).toBeLessThanOrEqual(threshold);
  });

  it("pushAction returns before sessionStorage is written (SLO 2)", () => {
    const spy = setItemSpy();
    useActionHistoryStore
      .getState()
      .setSnapshotReader(() => buildSnapshot());

    useActionHistoryStore
      .getState()
      .pushAction({ action_type: "preview" });

    expect(spy).not.toHaveBeenCalled();
    expect(
      window.sessionStorage.getItem(ACTION_HISTORY_STORAGE_KEY),
    ).toBeNull();
  });

  it("scheduleFlush throttles multiple pushes within 100ms into one write (SLO 9)", () => {
    vi.useFakeTimers();
    const spy = setItemSpy();
    useActionHistoryStore
      .getState()
      .setSnapshotReader(() => buildSnapshot());

    for (let i = 0; i < 10; i += 1) {
      useActionHistoryStore
        .getState()
        .pushAction({ action_type: "material_selection_change" });
    }

    // Before the debounce elapses nothing should have been flushed.
    expect(
      spy.mock.calls.filter(([k]) => k === ACTION_HISTORY_STORAGE_KEY),
    ).toHaveLength(0);
    // Exactly one pending flush timer should be scheduled regardless of
    // how many pushes fell inside the debounce window.
    // 不管合并多少次 push，只能调度一次 flush。
    expect(useActionHistoryStore.getState()._pendingFlushTimer).not.toBeNull();

    vi.runAllTimers();

    const flushCalls = spy.mock.calls.filter(
      ([k]) => k === ACTION_HISTORY_STORAGE_KEY,
    );
    expect(flushCalls).toHaveLength(1);
    expect(useActionHistoryStore.getState()._pendingFlushTimer).toBeNull();
  });

  it("handles sessionStorage quota exceeded gracefully and warns", () => {
    vi.useFakeTimers();
    const setItem = setItemSpy();
    setItem.mockImplementation(() => {
      const err = new Error("quota exhausted") as Error & { name: string };
      err.name = "QuotaExceededError";
      throw err;
    });
    useActionHistoryStore
      .getState()
      .setSnapshotReader(() => buildSnapshot());

    expect(() => {
      useActionHistoryStore
        .getState()
        .pushAction({ action_type: "generate" });
    }).not.toThrow();

    vi.advanceTimersByTime(ACTION_HISTORY_FLUSH_DEBOUNCE_MS + 1);

    expect(useActionHistoryStore.getState()._persistDisabled).toBe(true);
    expect(useActionHistoryStore.getState().history).toHaveLength(1);
    expect(postClientLogMock).toHaveBeenCalled();
    const warnCall = postClientLogMock.mock.calls.find(
      ([, opts]) => opts?.method === "warn",
    );
    expect(warnCall).toBeDefined();
  });

  it("pushAction survives JSON.stringify circular references in snapshot", () => {
    vi.useFakeTimers();
    type CircularSnapshot = WorkflowSnapshot & { self?: unknown };
    const circular: CircularSnapshot = buildSnapshot();
    circular.self = circular;
    useActionHistoryStore
      .getState()
      .setSnapshotReader(() => circular);

    expect(() => {
      useActionHistoryStore
        .getState()
        .pushAction({ action_type: "preview" });
    }).not.toThrow();

    // The synchronous push succeeded; the async flush will silently fail
    // because JSON.stringify cannot serialize the cycle.
    // pushAction 同步成功；后续异步 flush 对循环引用无法序列化，静默降级。
    expect(() => {
      vi.advanceTimersByTime(ACTION_HISTORY_FLUSH_DEBOUNCE_MS + 1);
    }).not.toThrow();

    expect(useActionHistoryStore.getState().history).toHaveLength(1);
  });

  it("preserves every observed session beyond the former ring limit", () => {
    const store = useActionHistoryStore.getState();
    for (let i = 0; i < 6; i += 1) {
      store.observeSession("converter", `sess-${i}`);
    }

    const { sessionRing } = useActionHistoryStore.getState();
    expect(sessionRing).toHaveLength(6);
    const ids = sessionRing.map((e) => e.session_id);
    expect(ids).toContain("sess-0");
    expect(ids).toContain("sess-5");
  });

  it("observeSession updates last_seen_at on repeat calls for same pair", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-11T10:00:00Z"));
    const store = useActionHistoryStore.getState();

    store.observeSession("converter", "sess-a");
    const firstSeen =
      useActionHistoryStore.getState().sessionRing[0].first_seen_at;

    vi.setSystemTime(new Date(Date.now() + 5_000));
    store.observeSession("converter", "sess-a");

    const ring = useActionHistoryStore.getState().sessionRing;
    expect(ring).toHaveLength(1);
    expect(ring[0].first_seen_at).toBe(firstSeen);
    expect(ring[0].last_seen_at).toBeGreaterThan(firstSeen);
  });

  it("observeSession ignores null and empty session_id", () => {
    const store = useActionHistoryStore.getState();
    store.observeSession("converter", null);
    store.observeSession("single_stage", "");

    expect(useActionHistoryStore.getState().sessionRing).toEqual([]);
  });

  it("loadPersistedHistory reads and merges from sessionStorage", () => {
    const persisted = {
      history: [
        {
          timestamp: 1_700_000_000_000,
          action_type: "upload_image",
          snapshot: buildSnapshot(),
        },
      ],
      sessionRing: [
        {
          workstream: "converter" as const,
          session_id: "sess-persisted",
          first_seen_at: 1_700_000_000_000,
          last_seen_at: 1_700_000_000_500,
        },
      ],
    };
    window.sessionStorage.setItem(
      ACTION_HISTORY_STORAGE_KEY,
      JSON.stringify(persisted),
    );

    useActionHistoryStore.getState().loadPersistedHistory();

    const state = useActionHistoryStore.getState();
    expect(state.history).toHaveLength(1);
    expect(state.history[0].action_type).toBe("upload_image");
    expect(state.sessionRing).toHaveLength(1);
    expect(state.sessionRing[0].session_id).toBe("sess-persisted");
  });

  it("loadPersistedHistory handles malformed JSON silently", () => {
    window.sessionStorage.setItem(
      ACTION_HISTORY_STORAGE_KEY,
      "not-valid-json{",
    );

    expect(() => {
      useActionHistoryStore.getState().loadPersistedHistory();
    }).not.toThrow();

    const state = useActionHistoryStore.getState();
    expect(state.history).toEqual([]);
    expect(state.sessionRing).toEqual([]);
  });

  it("preserves distinct actions in the same millisecond across persistence reload", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-10T00:00:00Z"));
    const store = useActionHistoryStore.getState();
    store.pushAction({ action_type: "preview", changed_fields: { width: { from: 10, to: 20 } } });
    store.pushAction({ action_type: "preview", changed_fields: { width: { from: 20, to: 30 } } });
    store.pushAction({ action_type: "preview", changed_fields: { width: { from: 20, to: 30 } } });
    vi.advanceTimersByTime(ACTION_HISTORY_FLUSH_DEBOUNCE_MS + 1);
    store.loadPersistedHistory();
    store.loadPersistedHistory();
    expect(useActionHistoryStore.getState().history.map((entry) => entry.changed_fields)).toEqual([
      { width: { from: 10, to: 20 } },
      { width: { from: 20, to: 30 } },
      { width: { from: 20, to: 30 } },
    ]);
  });

  it("loadPersistedHistory handles missing or unexpected shapes silently", () => {
    window.sessionStorage.setItem(
      ACTION_HISTORY_STORAGE_KEY,
      JSON.stringify({ history: "not-an-array" }),
    );

    expect(() => {
      useActionHistoryStore.getState().loadPersistedHistory();
    }).not.toThrow();

    const state = useActionHistoryStore.getState();
    expect(state.history).toEqual([]);
    expect(state.sessionRing).toEqual([]);
  });

  it("exportForReport returns shallow copies, not live references", () => {
    useActionHistoryStore
      .getState()
      .setSnapshotReader(() => buildSnapshot());
    useActionHistoryStore
      .getState()
      .pushAction({ action_type: "generate" });
    useActionHistoryStore
      .getState()
      .observeSession("converter", "sess-abc");

    const exported = useActionHistoryStore.getState().exportForReport();
    exported.history.push({
      timestamp: 0,
      action_type: "preview",
      snapshot: buildSnapshot(),
    });
    exported.session_history.pop();

    const state = useActionHistoryStore.getState();
    expect(state.history).toHaveLength(1);
    expect(state.sessionRing).toHaveLength(1);
  });
});
