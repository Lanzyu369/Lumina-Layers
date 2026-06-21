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

const CLIENT_LOG_BUFFER_LIMIT = 500;
const CLIENT_LOG_EXPORT_LIMIT = 500;
const CLIENT_LOG_MAX_DEPTH = 4;
const CLIENT_LOG_MAX_ARRAY_ITEMS = 20;
const CLIENT_LOG_MAX_OBJECT_KEYS = 24;
const CLIENT_LOG_MAX_STRING_LENGTH = 1200;
const CLIENT_LOG_REDACTED_LOCAL_PATH = "<redacted:local-path>";
const CLIENT_LOG_SENSITIVE_PATH_KEYS = new Set([
  "absolutepath",
  "diskpath",
  "filepath",
  "inputpath",
  "localpath",
  "modelpath",
  "outputpath",
  "previewpath",
  "sourcepath",
  "targetpath",
  "threemfdiskpath",
]);
const CLIENT_LOG_WINDOWS_LOCAL_PATH_PATTERN = /\b[A-Za-z]:[\\/][^\s"'<>),:;]*/g;
const CLIENT_LOG_POSIX_LOCAL_PATH_PATTERN =
  /(^|[^A-Za-z0-9._~%-])(\/(?:Users|private|tmp|var|Volumes|home|opt|mnt|workspace|workspaces|app|data|output)(?:\/[^\s"'<>),:;]*)?)(?=$|[\s"'<>),:;])/g;

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

function truncateString(value: string, limit: number = CLIENT_LOG_MAX_STRING_LENGTH): string {
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, limit)}...<truncated>`;
}

function roundNumber(value: number, digits: number = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function normalizeClientLogKey(key: string): string {
  return key.replace(/[\s_-]/g, "").toLowerCase();
}

function isSensitiveClientPathKey(key: string | null | undefined): boolean {
  return key != null && CLIENT_LOG_SENSITIVE_PATH_KEYS.has(normalizeClientLogKey(key));
}

function redactClientLogLocalPathFragments(value: string): string {
  return value
    .replace(CLIENT_LOG_WINDOWS_LOCAL_PATH_PATTERN, CLIENT_LOG_REDACTED_LOCAL_PATH)
    .replace(CLIENT_LOG_POSIX_LOCAL_PATH_PATTERN, (_match, prefix: string) => (
      `${prefix}${CLIENT_LOG_REDACTED_LOCAL_PATH}`
    ));
}

function redactSensitiveClientPathValue(value: unknown): unknown {
  if (value == null || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string" && value.length === 0) {
    return value;
  }
  return CLIENT_LOG_REDACTED_LOCAL_PATH;
}

function sanitizeClientLogValue(
  value: unknown,
  depth: number = 0,
  seen: WeakSet<object> = new WeakSet(),
  key?: string,
): unknown {
  if (value == null || typeof value === "boolean") {
    return value;
  }
  if (isSensitiveClientPathKey(key)) {
    return redactSensitiveClientPathValue(value);
  }
  if (typeof value === "string") {
    return truncateString(redactClientLogLocalPathFragments(value));
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : String(value);
  }
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (typeof value === "symbol") {
    return value.toString();
  }
  if (typeof value === "function") {
    return `[function ${value.name || "anonymous"}]`;
  }
  if (value instanceof Error) {
    return sanitizeClientLogValue(summarizeErrorForLog(value), depth + 1, seen);
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (typeof File !== "undefined" && value instanceof File) {
    return summarizeFileForLog(value);
  }
  if (typeof Blob !== "undefined" && value instanceof Blob) {
    return {
      type: value.type || null,
      size_bytes: value.size,
      size_mb: roundNumber(value.size / (1024 * 1024)),
    };
  }
  if (depth >= CLIENT_LOG_MAX_DEPTH) {
    return "<truncated:depth>";
  }
  if (typeof value !== "object") {
    return String(value);
  }
  if (seen.has(value)) {
    return "<circular>";
  }
  seen.add(value);

  if (Array.isArray(value)) {
    const items = value
      .slice(0, CLIENT_LOG_MAX_ARRAY_ITEMS)
      .map((item) => sanitizeClientLogValue(item, depth + 1, seen));
    if (value.length > CLIENT_LOG_MAX_ARRAY_ITEMS) {
      items.push(`<truncated:${value.length - CLIENT_LOG_MAX_ARRAY_ITEMS}>`);
    }
    return items;
  }

  const entries = Object.entries(value as Record<string, unknown>);
  const sanitized: Record<string, unknown> = {};
  for (const [rawKey, rawValue] of entries.slice(0, CLIENT_LOG_MAX_OBJECT_KEYS)) {
    sanitized[truncateString(rawKey, 120)] = sanitizeClientLogValue(
      rawValue,
      depth + 1,
      seen,
      rawKey,
    );
  }
  if (entries.length > CLIENT_LOG_MAX_OBJECT_KEYS) {
    sanitized.__truncated_keys = entries.length - CLIENT_LOG_MAX_OBJECT_KEYS;
  }
  return sanitized;
}

function pushRecentClientLog(entry: ClientLogEntry): void {
  _recentClientLogs.push(entry);
  if (_recentClientLogs.length > CLIENT_LOG_BUFFER_LIMIT) {
    _recentClientLogs.splice(0, _recentClientLogs.length - CLIENT_LOG_BUFFER_LIMIT);
  }
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

  // Quota exhaustion: drop the oldest half and retry once. If retry still
  // fails, give up on persistence for the rest of the session so we never
  // spin on a doomed write.
  // 配额不足：丢弃最老的一半再试一次；仍失败则停用持久化。
  const halfIdx = Math.floor(_recentClientLogs.length / 2);
  if (halfIdx > 0) {
    _recentClientLogs.splice(0, halfIdx);
  }
  try {
    storage.setItem(
      CLIENT_LOG_SESSION_STORAGE_KEY,
      JSON.stringify(_recentClientLogs),
    );
  } catch {
    _sessionStorageDisabled = true;
  }
}

function sanitizeClientLogEntry(entry: Partial<ClientLogEntry>): ClientLogEntry {
  const method = entry.method === "warn" || entry.method === "error"
    ? entry.method
    : "log";
  const elapsedMs = typeof entry.elapsed_ms === "number" && Number.isFinite(entry.elapsed_ms)
    ? roundNumber(entry.elapsed_ms, 2)
    : null;
  const sanitized: ClientLogEntry = {
    timestamp: entry.timestamp ?? new Date().toISOString(),
    method,
    label: truncateString(entry.label ?? "", 256),
    elapsed_ms: elapsedMs,
  };
  if (typeof entry.scope === "string") {
    sanitized.scope = truncateString(entry.scope, 80);
  }
  if (typeof entry.phase === "string") {
    sanitized.phase = truncateString(entry.phase, 120);
  }
  if (entry.details != null) {
    sanitized.details = sanitizeClientLogValue(entry.details);
  }
  return sanitized;
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

  // Merge persisted + live, dedupe by (timestamp, label, scope, phase),
  // sort ascending by timestamp, cap to the buffer limit.
  // 合并持久化 + 内存；按 (timestamp, label, scope, phase) 去重后按时间
  // 升序排序，最后裁剪到容量上限。
  const merged = new Map<string, ClientLogEntry>();
  for (const candidate of [...(parsed as unknown[]), ..._recentClientLogs]) {
    if (!candidate || typeof candidate !== "object") continue;
    const entry = candidate as Partial<ClientLogEntry>;
    if (typeof entry.timestamp !== "string" || typeof entry.label !== "string") {
      continue;
    }
    const sanitizedEntry = sanitizeClientLogEntry(entry);
    const scope = sanitizedEntry.scope ?? "";
    const phase = sanitizedEntry.phase ?? "";
    const key = `${sanitizedEntry.timestamp}|${sanitizedEntry.label}|${scope}|${phase}`;
    merged.set(key, sanitizedEntry);
  }
  const sorted = [...merged.values()].sort((a, b) =>
    a.timestamp < b.timestamp ? -1 : a.timestamp > b.timestamp ? 1 : 0,
  );
  const capped = sorted.length > CLIENT_LOG_BUFFER_LIMIT
    ? sorted.slice(sorted.length - CLIENT_LOG_BUFFER_LIMIT)
    : sorted;
  _recentClientLogs.length = 0;
  _recentClientLogs.push(...capped);
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
}

export function postClientLog(
  label: string,
  options: ClientLogOptions = {},
): void {
  const dedupeKey = `${options.scope ?? ""}:${options.phase ?? label}`;
  if (_shouldSkipForDedupe(dedupeKey, options.dedupeMs)) {
    return;
  }

  const elapsedMs = options.elapsedMs ?? resolveClientElapsedMs(options.startTime);
  const sanitizedDetails =
    options.details != null && Object.keys(options.details).length > 0
      ? sanitizeClientLogValue(options.details)
      : undefined;
  const entry: ClientLogEntry = {
    timestamp: new Date().toISOString(),
    method: options.method ?? "log",
    label: truncateString(label, 256),
    elapsed_ms: elapsedMs == null ? null : roundNumber(elapsedMs, 2),
  };

  if (options.scope) {
    entry.scope = truncateString(options.scope, 80);
  }
  if (options.phase) {
    entry.phase = truncateString(options.phase, 120);
  }
  if (sanitizedDetails != null) {
    entry.details = sanitizedDetails;
  }
  pushRecentClientLog(entry);

  const message = elapsedMs != null
    ? `${label} (+${elapsedMs.toFixed(0)}ms)`
    : label;
  const logger = options.method === "error"
    ? console.error
    : options.method === "warn"
      ? console.warn
      : console.log;
  if (sanitizedDetails != null) {
    logger(`[LUMINA] ${message}`, sanitizedDetails);
  } else {
    logger(`[LUMINA] ${message}`);
  }

  if (typeof fetch !== "function") {
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
      void (maybePromise as Promise<unknown>).catch(() => {});
    }
  } catch {
    // Client-log relay is diagnostic only and must never replace the
    // user-facing error that triggered it.
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
      },
    });
  };

  window.addEventListener("error", handleError);
  window.addEventListener("unhandledrejection", handleUnhandledRejection);
  _globalCaptureInstalled = true;

  return () => {
    window.removeEventListener("error", handleError);
    window.removeEventListener("unhandledrejection", handleUnhandledRejection);
    _globalCaptureInstalled = false;
  };
}
