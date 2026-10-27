import { installFeedbackSourceCapture } from "./sourceFileOrigins";

export interface ClientLogOptions {
  startTime?: number | null;
  elapsedMs?: number | null;
  details?: Record<string, unknown> | null;
  scope?: string;
  phase?: string;
  method?: "log" | "warn" | "error";
  /**
   * When set, suppresses repeated posts with the same (scope, phase or label)
   * key if the previous post happened within the given millisecond window.
   * Intended for effect-driven logs so React Strict Mode double-fires and
   * rapid dependency churn do not flood `/api/client-log`.
   */
  dedupeMs?: number;
}

export interface ClientLogEntry {
  timestamp: string;
  method: "log" | "warn" | "error";
  label: string;
  elapsed_ms: number | null;
  scope?: string;
  phase?: string;
  details?: unknown;
}

const CLIENT_LOG_EXPORT_LIMIT = Number.POSITIVE_INFINITY;
const CLIENT_LOG_RELAY_FAILURE_BACKOFF_MS = 10_000;

/**
 * Session-storage key backing the optional persistence layer for the
 * in-memory client-log ring. The ``v1`` suffix lets us evolve the stored
 * schema later without silently replaying incompatible payloads.
 * 前端日志环形缓冲的 sessionStorage 键；带 ``v1`` 便于后续不破坏升级。
 */
const CLIENT_LOG_SESSION_STORAGE_KEY = "lumina-client-logs-v1";

/**
 * Number of entries that can accumulate before we force a sessionStorage
 * flush, independent of the time-based debounce. Keeps the persistence
 * layer up to date during bursty logging (e.g. a tight error loop) so a
 * page reload right after the burst still recovers the recent history.
 * 无论时间节流如何，每累计 20 条就强制刷一次，保证爆发日志期间仍有持久化。
 */
const CLIENT_LOG_FLUSH_PUSH_THRESHOLD = 20;

/**
 * Time-based sessionStorage flush debounce. Batches steady-state logs
 * so we only pay the serialization cost once every 5 s, never per log
 * line. Combined with the push-threshold above, whichever trigger fires
 * first will schedule the write.
 * 每 5 秒最多一次 flush；与条数阈值取先到者触发。
 */
const CLIENT_LOG_FLUSH_DEBOUNCE_MS = 5000;

const _lastPostAt: Map<string, number> = new Map();
const _recentClientLogs: ClientLogEntry[] = [];
let _globalCaptureInstalled = false;

/**
 * Number of pushes accumulated since the last sessionStorage flush.
 * Reset to 0 after a flush. Combined with the time-based debounce
 * below, this triggers a flush as soon as ``CLIENT_LOG_FLUSH_PUSH_THRESHOLD``
 * entries queue up even if the user has only been on the page a moment.
 * 自上次 flush 以来累计的 push 数，达到阈值或时间窗到达时触发落盘。
 */
let _pendingFlushCount = 0;
/** setTimeout handle for the pending sessionStorage flush, or null. */
let _pendingFlushTimer: number | null = null;
/** Once true, sessionStorage is considered permanently unavailable. */
let _sessionStorageDisabled = false;
/** Have we attempted to load persisted logs during this session yet? */
let _persistedLogsLoaded = false;
/** Wall-clock deadline before retrying the optional backend relay. */
let _clientLogRelayBackoffUntilMs = 0;

function _shouldSkipForDedupe(key: string, dedupeMs?: number): boolean {
  if (!dedupeMs || dedupeMs <= 0) {
    return false;
  }
  const now = typeof performance !== "undefined" ? performance.now() : Date.now();
  const previous = _lastPostAt.get(key);
  if (previous != null && now - previous < dedupeMs) {
    return true;
  }
  _lastPostAt.set(key, now);
  return false;
}

function truncateString(value: string, limit: number = 240): string {
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, limit)}...<truncated>`;
}

function roundNumber(value: number, digits: number = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function clientLogNowMs(): number {
  return Date.now();
}

function markClientLogRelayUnavailable(): void {
  _clientLogRelayBackoffUntilMs =
    clientLogNowMs() + CLIENT_LOG_RELAY_FAILURE_BACKOFF_MS;
}

function canAttemptClientLogRelay(): boolean {
  return clientLogNowMs() >= _clientLogRelayBackoffUntilMs;
}

function isFailedClientLogRelayResponse(response: unknown): boolean {
  return Boolean(
    response &&
      typeof response === "object" &&
      "ok" in response &&
      (response as { ok?: unknown }).ok === false,
  );
}

function readableConsoleDetail(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) {
    return truncateString(value.trim(), 240);
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "boolean") {
    return String(value);
  }
  return null;
}

function buildClientLogConsoleSummary(details: unknown): string | null {
  if (!details || typeof details !== "object" || Array.isArray(details)) {
    return null;
  }
  const record = details as Record<string, unknown>;
  const parts: string[] = [];
  const method = readableConsoleDetail(record.method);
  const url = readableConsoleDetail(record.url);
  if (method && url) {
    parts.push(`${method.toUpperCase()} ${url}`);
  } else if (url) {
    parts.push(url);
  }

  const statusCode = readableConsoleDetail(record.status_code);
  if (statusCode) {
    parts.push(`HTTP ${statusCode}`);
  }

  const errorMessage =
    readableConsoleDetail(record.error_message) ??
    readableConsoleDetail(record.message) ??
    readableConsoleDetail(record.reason) ??
    readableConsoleDetail(record.error);
  if (errorMessage) {
    parts.push(errorMessage);
  }

  const requestId = readableConsoleDetail(record.request_id);
  if (requestId) {
    parts.push(`request_id=${requestId}`);
  }

  return parts.length > 0 ? parts.join(" - ") : null;
}

/** Serialize diagnostics without removing paths, stacks, or data.
 * 序列化完整诊断内容，不删除路径、堆栈或数据。
 */
export function serializeDiagnosticValue(value: unknown, seen = new WeakSet<object>()): unknown {
  if (value == null || typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : String(value);
  if (typeof value !== "object") return String(value);
  if (value instanceof Date) return value.toISOString();
  if (typeof File !== "undefined" && value instanceof File) return summarizeFileForLog(value);
  if (typeof Blob !== "undefined" && value instanceof Blob) return { type: value.type, size_bytes: value.size };
  if (seen.has(value)) return "<circular>";
  seen.add(value);
  try {
    if (value instanceof Error) return serializeDiagnosticValue({
      ...value, ...summarizeErrorForLog(value), ...(value.cause === undefined ? {} : { cause: value.cause }),
    }, seen);
    if (value instanceof Map) return serializeDiagnosticValue(Object.fromEntries(value), seen);
    if (value instanceof Set) return serializeDiagnosticValue([...value], seen);
    if (ArrayBuffer.isView(value)) return serializeDiagnosticValue(Array.from(new Uint8Array(value.buffer, value.byteOffset, value.byteLength)), seen);
    if (Array.isArray(value)) return value.map((item) => serializeDiagnosticValue(item, seen));
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, serializeDiagnosticValue(item, seen)]));
  } finally {
    seen.delete(value);
  }
}

function pushRecentClientLog(entry: ClientLogEntry): void {
  _recentClientLogs.push(entry);
  _pendingFlushCount += 1;
  if (_pendingFlushCount >= CLIENT_LOG_FLUSH_PUSH_THRESHOLD) {
    // Threshold breach: flush immediately instead of waiting for the timer.
    // 达到条数阈值：立即落盘，不再等待时间窗。
    _flushToSessionStorage();
    return;
  }
  _scheduleSessionStorageFlush();
}

/**
 * Fetch the active sessionStorage object or ``null`` when unavailable.
 * Tests can replace ``window.sessionStorage`` with a mock; this helper
 * keeps the access defensive so neither SSR-like environments nor
 * sandboxed contexts crash the logger.
 * 读取当前可用的 sessionStorage；不可用时返回 null，便于测试替换。
 */
function _getSessionStorage(): Storage | null {
  try {
    if (typeof window !== "undefined" && window.sessionStorage) {
      return window.sessionStorage;
    }
    if (typeof globalThis !== "undefined" && "sessionStorage" in globalThis) {
      return (globalThis as { sessionStorage?: Storage }).sessionStorage ?? null;
    }
  } catch {
    // Access to sessionStorage can throw in some restrictive contexts.
    // 某些受限环境访问 sessionStorage 会抛；静默降级。
  }
  return null;
}

/**
 * Detect quota-exhausted SessionStorage errors across browser variants.
 * Every engine uses a slightly different name / code / message, so we
 * check all the known signals instead of a single predicate.
 * 跨浏览器检测 sessionStorage 配额耗尽。
 */
function _isQuotaError(error: unknown): boolean {
  if (error == null) return false;
  const name = typeof (error as { name?: unknown }).name === "string"
    ? (error as { name: string }).name
    : "";
  const message = typeof (error as { message?: unknown }).message === "string"
    ? (error as { message: string }).message
    : String(error);
  return name.includes("Quota") || /quota/i.test(message);
}

function _scheduleSessionStorageFlush(): void {
  if (_sessionStorageDisabled) return;
  if (_pendingFlushTimer != null) return;
  if (typeof setTimeout === "undefined") return;
  _pendingFlushTimer = setTimeout(() => {
    _pendingFlushTimer = null;
    _flushToSessionStorage();
  }, CLIENT_LOG_FLUSH_DEBOUNCE_MS) as unknown as number;
}

function _flushToSessionStorage(): void {
  if (_sessionStorageDisabled) return;
  const storage = _getSessionStorage();
  if (!storage) return;
  _pendingFlushCount = 0;

  let payload: string;
  try {
    payload = JSON.stringify(_recentClientLogs);
  } catch {
    // Circular references or similarly exotic payloads: give up quietly
    // rather than poisoning the ring.
    // 循环引用等异常 payload 时静默放弃，避免破坏缓冲。
    return;
  }

  try {
    storage.setItem(CLIENT_LOG_SESSION_STORAGE_KEY, payload);
    return;
  } catch (error) {
    if (!_isQuotaError(error)) {
      // Non-quota failure → disable persistence to avoid spamming errors.
      // 非配额错误：直接停用持久化。
      _sessionStorageDisabled = true;
      return;
    }
  }

  // Keep the complete in-memory report if browser storage is full.
  _sessionStorageDisabled = true;
}

function serializeClientLogEntry(entry: Partial<ClientLogEntry>): ClientLogEntry {
  const method = entry.method === "warn" || entry.method === "error"
    ? entry.method
    : "log";
  const elapsedMs = typeof entry.elapsed_ms === "number" && Number.isFinite(entry.elapsed_ms)
    ? roundNumber(entry.elapsed_ms, 2)
    : null;
  const serialized: ClientLogEntry = {
    timestamp: entry.timestamp ?? new Date().toISOString(),
    method,
    label: entry.label ?? "",
    elapsed_ms: elapsedMs,
  };
  if (typeof entry.scope === "string") {
    serialized.scope = entry.scope;
  }
  if (typeof entry.phase === "string") {
    serialized.phase = entry.phase;
  }
  if (entry.details != null) {
    serialized.details = serializeDiagnosticValue(entry.details);
  }
  return serialized;
}

/**
 * Load any persisted client-log history from sessionStorage into the
 * in-memory ring. Idempotent: after the first call it becomes a no-op.
 * Called lazily by :func:`getRecentClientLogs` (so boot-time never pays
 * the I/O cost) and eagerly by ``BugReportModal`` when the user opens
 * the feedback dialog.
 * 懒加载持久化日志；幂等，多次调用只在首次真正读取。
 */
export function loadPersistedLogs(): void {
  if (_persistedLogsLoaded) return;
  _persistedLogsLoaded = true;
  const storage = _getSessionStorage();
  if (!storage) return;
  let raw: string | null;
  try {
    raw = storage.getItem(CLIENT_LOG_SESSION_STORAGE_KEY);
  } catch {
    return;
  }
  if (!raw) return;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return;
  }
  if (!Array.isArray(parsed)) return;

  // Preserve every persisted occurrence; avoid replaying matching live entries.
  const merged: ClientLogEntry[] = [];
  const persistedCounts = new Map<string, number>();
  const liveCounts = new Map<string, number>();
  for (const candidate of parsed as unknown[]) {
    if (!candidate || typeof candidate !== "object") continue;
    const entry = candidate as Partial<ClientLogEntry>;
    if (typeof entry.timestamp !== "string" || typeof entry.label !== "string") {
      continue;
    }
    const serialized = serializeClientLogEntry(entry);
    const key = JSON.stringify(serialized);
    persistedCounts.set(key, (persistedCounts.get(key) ?? 0) + 1);
    merged.push(serialized);
  }
  for (const entry of _recentClientLogs) {
    const key = JSON.stringify(entry);
    const count = (liveCounts.get(key) ?? 0) + 1;
    liveCounts.set(key, count);
    if (count > (persistedCounts.get(key) ?? 0)) merged.push(entry);
  }
  merged.sort((a, b) =>
    a.timestamp < b.timestamp ? -1 : a.timestamp > b.timestamp ? 1 : 0,
  );
  _recentClientLogs.length = 0;
  for (const entry of merged) _recentClientLogs.push(entry);
}

export function resolveClientElapsedMs(startTime?: number | null): number | null {
  if (startTime == null || typeof performance === "undefined") {
    return null;
  }
  return performance.now() - startTime;
}

export function summarizeFileForLog(
  file: File | null | undefined,
): Record<string, unknown> | null {
  if (!file) {
    return null;
  }

  return {
    name: file.name,
    type: file.type || null,
    size_bytes: file.size,
    size_mb: roundNumber(file.size / (1024 * 1024)),
    last_modified_ms: file.lastModified || null,
  };
}

export function summarizeErrorForLog(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return {
      error_name: error.name,
      error_message: error.message,
      error_stack: error.stack ?? null,
    };
  }

  return {
    error_message: String(error),
  };
}

export function getRecentClientLogs(limit: number = CLIENT_LOG_EXPORT_LIMIT): ClientLogEntry[] {
  // Lazy: only touch sessionStorage the first time anyone asks for the
  // recent-log export. Boot-time reads of the buffer (none exist today)
  // would therefore pay zero I/O.
  // 懒加载：首次被调用时才读 sessionStorage；启动期零 I/O。
  loadPersistedLogs();
  const requestedLimit = Number.isFinite(limit)
    ? Math.floor(limit)
    : CLIENT_LOG_EXPORT_LIMIT;
  const boundedLimit = Math.max(0, Math.min(CLIENT_LOG_EXPORT_LIMIT, requestedLimit));
  if (boundedLimit === 0) {
    return [];
  }
  return _recentClientLogs.slice(-boundedLimit).map((entry) => ({ ...entry }));
}

export function _clearClientLogBufferForTests(): void {
  _recentClientLogs.length = 0;
  _lastPostAt.clear();
  if (_pendingFlushTimer != null) {
    try {
      clearTimeout(_pendingFlushTimer);
    } catch {
      // ignore
    }
    _pendingFlushTimer = null;
  }
  _pendingFlushCount = 0;
  _sessionStorageDisabled = false;
  _persistedLogsLoaded = false;
  _clientLogRelayBackoffUntilMs = 0;
}

export function postClientLog(
  label: string,
  options: ClientLogOptions = {},
): void {
  const dedupeKey = `${options.scope ?? ""}:${options.phase ?? label}`;
  const skipRelay = _shouldSkipForDedupe(dedupeKey, options.dedupeMs);

  const elapsedMs = options.elapsedMs ?? resolveClientElapsedMs(options.startTime);
  const serializedDetails =
    options.details != null && Object.keys(options.details).length > 0
      ? serializeDiagnosticValue(options.details)
      : undefined;
  const entry: ClientLogEntry = {
    timestamp: new Date().toISOString(),
    method: options.method ?? "log",
    label: label,
    elapsed_ms: elapsedMs == null ? null : roundNumber(elapsedMs, 2),
  };

  if (options.scope) {
    entry.scope = options.scope;
  }
  if (options.phase) {
    entry.phase = options.phase;
  }
  if (serializedDetails != null) {
    entry.details = serializedDetails;
  }
  pushRecentClientLog(entry);
  if (skipRelay) return;

  const message = elapsedMs != null
    ? `${label} (+${elapsedMs.toFixed(0)}ms)`
    : label;
  const consoleSummary = buildClientLogConsoleSummary(serializedDetails);
  const consoleMessage = consoleSummary == null
    ? message
    : `${message} - ${consoleSummary}`;
  const logger = options.method === "error"
    ? console.error
    : options.method === "warn"
      ? console.warn
      : console.log;
  logger(`[LUMINA] ${consoleMessage}`);

  if (typeof fetch !== "function") {
    return;
  }
  if (!canAttemptClientLogRelay()) {
    return;
  }

  const payload: Record<string, unknown> = {
    label: entry.label,
    elapsed_ms: entry.elapsed_ms,
  };
  if (entry.scope) {
    payload.scope = entry.scope;
  }
  if (entry.phase) {
    payload.phase = entry.phase;
  }
  if (entry.details != null) {
    payload.details = entry.details;
  }

  try {
    const maybePromise = fetch("/api/client-log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (
      maybePromise &&
      typeof (maybePromise as Promise<unknown>).catch === "function"
    ) {
      void (maybePromise as Promise<unknown>)
        .then((response) => {
          if (isFailedClientLogRelayResponse(response)) {
            markClientLogRelayUnavailable();
          }
        })
        .catch(() => {
          markClientLogRelayUnavailable();
        });
    } else if (isFailedClientLogRelayResponse(maybePromise)) {
      markClientLogRelayUnavailable();
    }
  } catch {
    // Client-log relay is diagnostic only and must never replace the
    // user-facing error that triggered it.
    markClientLogRelayUnavailable();
  }
}

export function installGlobalClientLogCapture(): () => void {
  if (typeof window === "undefined" || _globalCaptureInstalled) {
    return () => {};
  }

  const handleError = (event: ErrorEvent) => {
    postClientLog("client: uncaught error", {
      scope: "client",
      phase: "uncaught-error",
      method: "error",
      dedupeMs: 500,
      details: {
        ...summarizeErrorForLog(event.error ?? event.message),
        error: event.error ?? event.message,
        filename: event.filename || null,
        lineno: event.lineno || null,
        colno: event.colno || null,
      },
    });
  };

  const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
    postClientLog("client: unhandled rejection", {
      scope: "client",
      phase: "unhandled-rejection",
      method: "error",
      dedupeMs: 500,
      details: {
        ...summarizeErrorForLog(event.reason),
        reason: event.reason,
      },
    });
  };

  const stopSourceCapture = installFeedbackSourceCapture();
  window.addEventListener("error", handleError);
  window.addEventListener("unhandledrejection", handleUnhandledRejection);
  _globalCaptureInstalled = true;

  return () => {
    stopSourceCapture();
    window.removeEventListener("error", handleError);
    window.removeEventListener("unhandledrejection", handleUnhandledRejection);
    _globalCaptureInstalled = false;
  };
}
