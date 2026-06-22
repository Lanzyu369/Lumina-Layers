import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  _clearClientLogBufferForTests,
  getRecentClientLogs,
  installGlobalClientLogCapture,
  loadPersistedLogs,
  postClientLog,
} from "../clientLog";

// Mirrors constants from clientLog.ts; kept local so tests stay self-contained.
const CLIENT_LOG_SESSION_STORAGE_KEY = "lumina-client-logs-v1";
const CLIENT_LOG_FLUSH_PUSH_THRESHOLD = 20;
const CLIENT_LOG_FLUSH_DEBOUNCE_MS = 5000;

interface MockStorage extends Storage {
  _map: Map<string, string>;
  _setItemSpy: ReturnType<typeof vi.fn>;
}

function createMockStorage(overrides?: {
  throwOnSet?: unknown;
}): MockStorage {
  const map = new Map<string, string>();
  const setSpy = vi.fn((key: string, value: string) => {
    if (overrides?.throwOnSet) {
      throw overrides.throwOnSet;
    }
    map.set(key, value);
  });
  const storage: MockStorage = {
    _map: map,
    _setItemSpy: setSpy,
    get length() {
      return map.size;
    },
    key(index: number) {
      return Array.from(map.keys())[index] ?? null;
    },
    getItem(key: string) {
      return map.get(key) ?? null;
    },
    setItem(key: string, value: string) {
      setSpy(key, value);
    },
    removeItem(key: string) {
      map.delete(key);
    },
    clear() {
      map.clear();
    },
  };
  return storage;
}

let _storage: MockStorage;

describe("clientLog", () => {
  beforeEach(() => {
    _clearClientLogBufferForTests();
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      value: vi.fn().mockResolvedValue({ ok: true }),
    });
    _storage = createMockStorage();
    Object.defineProperty(window, "sessionStorage", {
      configurable: true,
      writable: true,
      value: _storage,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    _clearClientLogBufferForTests();
    vi.useRealTimers();
  });

  it("stores and posts sanitized client logs", () => {
    postClientLog("preview: failed", {
      elapsedMs: 12.3456,
      method: "warn",
      scope: "preview",
      phase: "failed",
      details: {
        reason: "x".repeat(1300),
        nested: { keep: true },
      },
    });

    const logs = getRecentClientLogs();

    expect(logs).toHaveLength(1);
    expect(logs[0]).toEqual(
      expect.objectContaining({
        method: "warn",
        label: "preview: failed",
        elapsed_ms: 12.35,
        scope: "preview",
        phase: "failed",
      }),
    );
    expect(logs[0].details).toEqual({
      reason: `${"x".repeat(1200)}...<truncated>`,
      nested: { keep: true },
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/client-log",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("preview: failed"),
      }),
    );
  });

  it("does not propagate synchronous client-log relay failures", () => {
    vi.mocked(fetch).mockImplementationOnce(() => {
      throw new Error("client-log relay unavailable");
    });

    expect(() => {
      postClientLog("api: request failed", {
        method: "error",
        scope: "api",
        phase: "request-failed",
        details: {
          status_code: 500,
          error_message: "The server hit an internal error.",
        },
      });
    }).not.toThrow();

    const logs = getRecentClientLogs();
    expect(logs.at(-1)).toEqual(
      expect.objectContaining({
        method: "error",
        label: "api: request failed",
        scope: "api",
        phase: "request-failed",
      }),
    );
  });

  it("prints a readable console summary without an opaque Object suffix", () => {
    postClientLog("api: request failed", {
      method: "error",
      scope: "api",
      phase: "request-failed",
      details: {
        method: "GET",
        url: "/api/system/settings",
        status_code: null,
        request_id: null,
        error_message:
          "The request did not receive a server response. Make sure the Lumina backend is running.",
      },
    });

    expect(console.error).toHaveBeenCalledWith(
      expect.stringContaining(
        "[LUMINA] api: request failed - GET /api/system/settings - The request did not receive a server response. Make sure the Lumina backend is running.",
      ),
    );
    expect(console.error).toHaveBeenCalledTimes(1);
    expect(vi.mocked(console.error).mock.calls[0]).toHaveLength(1);
    expect(getRecentClientLogs().at(-1)?.details).toEqual(
      expect.objectContaining({
        method: "GET",
        url: "/api/system/settings",
        status_code: null,
      }),
    );
  });

  it("backs off client-log relay after non-OK relay responses", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockResolvedValueOnce({ ok: false } as Response);

    postClientLog("api: request failed", {
      method: "error",
      scope: "api",
      phase: "request-failed",
      details: {
        method: "GET",
        url: "/api/health",
        status_code: null,
        error_message: "The request did not receive a server response.",
      },
    });
    await Promise.resolve();
    await Promise.resolve();

    postClientLog("api: request failed again", {
      method: "error",
      scope: "api",
      phase: "request-failed-again",
      details: {
        method: "GET",
        url: "/api/lut/list",
        status_code: null,
        error_message: "The request did not receive a server response.",
      },
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(getRecentClientLogs()).toHaveLength(2);

    vi.advanceTimersByTime(10_001);
    postClientLog("api: request recovered", {
      method: "warn",
      scope: "api",
      phase: "request-recovered",
      details: {
        method: "GET",
        url: "/api/health",
        status_code: null,
        error_message: "Retrying client-log relay.",
      },
    });

    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("backs off client-log relay after rejected relay requests", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockRejectedValueOnce(new Error("backend offline"));

    postClientLog("api: request failed", {
      method: "error",
      scope: "api",
      phase: "request-failed",
      details: {
        method: "GET",
        url: "/api/health",
        status_code: null,
        error_message: "The request did not receive a server response.",
      },
    });
    await Promise.resolve();
    await Promise.resolve();

    postClientLog("api: request failed again", {
      method: "error",
      scope: "api",
      phase: "request-failed-again",
      details: {
        method: "GET",
        url: "/api/lut/list",
        status_code: null,
        error_message: "The request did not receive a server response.",
      },
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(getRecentClientLogs()).toHaveLength(2);
  });

  it("redacts local file paths from buffered and relayed diagnostics", () => {
    postClientLog("generate: response received", {
      method: "log",
      scope: "generate",
      phase: "response-received",
      details: {
        threemf_disk_path: "/Users/min/CascadeProjects/Lumina-studio/output/model.3mf",
        nested: {
          threemfDiskPath: "E:/tmp/model.3mf",
          disk_path: "/private/tmp/lumina/model.3mf",
          file_path: "/tmp/lumina/upload.png",
        },
        message: "failed while opening /Users/min/CascadeProjects/Lumina-studio/output/model.3mf",
        download_url: "/api/files/output-model",
      },
    });

    const logs = getRecentClientLogs();
    const serializedLog = JSON.stringify(logs[0]);
    const relayBody = String(vi.mocked(fetch).mock.calls[0]?.[1]?.body ?? "");
    const consoleLine = String(vi.mocked(console.log).mock.calls[0]?.[0] ?? "");

    expect(serializedLog).not.toContain("/Users/min");
    expect(serializedLog).not.toContain("E:/tmp");
    expect(serializedLog).not.toContain("/private/tmp");
    expect(serializedLog).not.toContain("/tmp/lumina");
    expect(relayBody).not.toContain("/Users/min");
    expect(relayBody).not.toContain("E:/tmp");
    expect(relayBody).not.toContain("/private/tmp");
    expect(relayBody).not.toContain("/tmp/lumina");
    expect(consoleLine).not.toContain("/Users/min");
    expect(consoleLine).not.toContain("E:/tmp");
    expect(consoleLine).not.toContain("/private/tmp");
    expect(consoleLine).not.toContain("/tmp/lumina");
    expect(serializedLog).toContain("<redacted:local-path>");
    expect(consoleLine).toContain("<redacted:local-path>");
    expect(serializedLog).toContain("/api/files/output-model");
    expect(relayBody).toContain("/api/files/output-model");
  });

  it("exports only the newest bounded logs for bug reports", () => {
    for (let index = 0; index < 600; index += 1) {
      postClientLog(`event-${index}`, { elapsedMs: index });
    }

    // Buffer cap is 500; the 100 oldest are evicted.
    // 缓冲容量 500，最早的 100 条被裁掉。
    const logs = getRecentClientLogs();

    expect(logs).toHaveLength(500);
    expect(logs[0].label).toBe("event-100");
    expect(logs[499].label).toBe("event-599");
  });

  it("captures uncaught browser errors into the same buffer", () => {
    const cleanup = installGlobalClientLogCapture();

    window.dispatchEvent(new ErrorEvent("error", {
      message: "boom",
      error: new Error("boom"),
      filename: "App.tsx",
      lineno: 12,
      colno: 3,
    }));

    const logs = getRecentClientLogs();

    expect(logs).toHaveLength(1);
    expect(logs[0]).toEqual(
      expect.objectContaining({
        method: "error",
        label: "client: uncaught error",
        scope: "client",
        phase: "uncaught-error",
      }),
    );
    expect(logs[0].details).toEqual(
      expect.objectContaining({
        error_message: "boom",
        filename: "App.tsx",
        lineno: 12,
        colno: 3,
      }),
    );

    cleanup();
  });

  // ---- Task 1.6: sessionStorage persistence ----

  it("does not touch sessionStorage on isolated single pushes (time debounce)", () => {
    vi.useFakeTimers();
    postClientLog("single");

    // Under the push threshold (20) and before the 5s debounce; no flush yet.
    // 没到 20 条阈值、也还没到 5 秒窗口，不应落盘。
    expect(_storage._setItemSpy).not.toHaveBeenCalled();

    vi.advanceTimersByTime(CLIENT_LOG_FLUSH_DEBOUNCE_MS + 1);
    expect(_storage._setItemSpy).toHaveBeenCalledTimes(1);
  });

  it("flushes to sessionStorage after CLIENT_LOG_FLUSH_PUSH_THRESHOLD pushes", () => {
    for (let index = 0; index < CLIENT_LOG_FLUSH_PUSH_THRESHOLD; index += 1) {
      postClientLog(`evt-${index}`);
    }

    // Hitting the push threshold flushes immediately, not via the timer.
    // 达到条数阈值即刻 flush，不再等定时器。
    expect(_storage._setItemSpy).toHaveBeenCalled();
    const lastCall = _storage._setItemSpy.mock.calls.at(-1);
    expect(lastCall?.[0]).toBe(CLIENT_LOG_SESSION_STORAGE_KEY);
    const persisted = JSON.parse(lastCall?.[1] as string);
    expect(Array.isArray(persisted)).toBe(true);
    expect(persisted).toHaveLength(CLIENT_LOG_FLUSH_PUSH_THRESHOLD);
  });

  it("getRecentClientLogs is lazy: no sessionStorage reads before first call", () => {
    const getItemSpy = vi.spyOn(_storage, "getItem");

    // Push some entries but never call getRecentClientLogs yet.
    for (let i = 0; i < 3; i += 1) {
      postClientLog(`evt-${i}`);
    }

    expect(getItemSpy).not.toHaveBeenCalled();

    getRecentClientLogs();
    expect(getItemSpy).toHaveBeenCalledWith(CLIENT_LOG_SESSION_STORAGE_KEY);
  });

  it("merges persisted logs with live buffer, dedupes by key, caps to 500", () => {
    const persisted = [
      {
        timestamp: "2026-05-10T10:00:00.000Z",
        method: "log",
        label: "old-event-a",
        elapsed_ms: 1,
      },
      {
        timestamp: "2026-05-10T10:00:01.000Z",
        method: "log",
        label: "old-event-b",
        elapsed_ms: 2,
      },
    ];
    _storage._map.set(
      CLIENT_LOG_SESSION_STORAGE_KEY,
      JSON.stringify(persisted),
    );

    // Live push that should also survive the merge.
    postClientLog("live-event");

    const merged = getRecentClientLogs(500);
    const labels = merged.map((entry) => entry.label);
    expect(labels).toContain("old-event-a");
    expect(labels).toContain("old-event-b");
    expect(labels).toContain("live-event");
    // Persisted logs sort ahead of the live one (their ISO timestamps are
    // strictly earlier than the clock used by postClientLog during the test).
    // 持久化条目的 ISO 时间早于 live push，合并后排在前面。
    expect(labels.indexOf("old-event-a")).toBeLessThan(labels.indexOf("live-event"));
  });

  it("redacts local file paths when importing persisted client logs", () => {
    _storage._map.set(
      CLIENT_LOG_SESSION_STORAGE_KEY,
      JSON.stringify([
        {
          timestamp: "2026-05-12T10:00:00.000Z",
          method: "log",
          label: "generate: response received",
          elapsed_ms: 3,
          details: {
            threemf_disk_path: "/Users/min/output/model.3mf",
            nested: {
              file_path: "C:\\tmp\\upload.png",
            },
            message: "failed while reading /private/tmp/lumina/model.3mf",
          },
        },
      ]),
    );

    const logs = getRecentClientLogs();
    const serializedLog = JSON.stringify(logs[0]);

    expect(serializedLog).not.toContain("/Users/min");
    expect(serializedLog).not.toContain("C:\\tmp");
    expect(serializedLog).not.toContain("/private/tmp");
    expect(serializedLog).toContain("<redacted:local-path>");
  });

  it("dedupes identical persisted+live entries by (timestamp, label, scope, phase)", () => {
    const shared = {
      timestamp: "2026-05-11T10:00:00.000Z",
      method: "warn",
      label: "preview: failed",
      elapsed_ms: 12,
      scope: "preview",
      phase: "failed",
    };
    _storage._map.set(
      CLIENT_LOG_SESSION_STORAGE_KEY,
      JSON.stringify([shared, shared]),
    );

    loadPersistedLogs();
    const merged = getRecentClientLogs(500);

    // Two identical persisted entries collapse to one after merge-dedupe.
    // 两条完全相同的持久化记录会被合并去重。
    const matching = merged.filter((entry) => entry.label === "preview: failed");
    expect(matching).toHaveLength(1);
  });

  it("downgrades gracefully when sessionStorage throws a quota error", () => {
    const quotaError = new DOMException("quota exceeded", "QuotaExceededError");
    _storage._setItemSpy.mockImplementationOnce(() => {
      throw quotaError;
    });

    // First push triggers the flush; the mock throws quota once, then
    // the retry path writes the trimmed buffer successfully.
    // 第一次 setItem 抛配额异常，重试时写入成功。
    for (let i = 0; i < CLIENT_LOG_FLUSH_PUSH_THRESHOLD; i += 1) {
      postClientLog(`q-${i}`);
    }

    expect(_storage._setItemSpy).toHaveBeenCalled();
    // Retry happened at least once, so there are two calls total.
    expect(_storage._setItemSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("disables persistence on non-quota setItem failure and stops retrying", () => {
    const fatalError = new Error("storage disabled");
    _storage._setItemSpy.mockImplementation(() => {
      throw fatalError;
    });

    for (let i = 0; i < CLIENT_LOG_FLUSH_PUSH_THRESHOLD; i += 1) {
      postClientLog(`f-${i}`);
    }

    const firstCallCount = _storage._setItemSpy.mock.calls.length;
    expect(firstCallCount).toBeGreaterThanOrEqual(1);

    // Further pushes should not schedule additional setItem attempts.
    // 再次 push 不应继续尝试 setItem。
    for (let i = 0; i < CLIENT_LOG_FLUSH_PUSH_THRESHOLD; i += 1) {
      postClientLog(`f2-${i}`);
    }

    expect(_storage._setItemSpy.mock.calls.length).toBe(firstCallCount);
  });
});
