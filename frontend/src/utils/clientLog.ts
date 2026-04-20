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

const _lastPostAt: Map<string, number> = new Map();

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

function roundNumber(value: number, digits: number = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
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

export function postClientLog(
  label: string,
  options: ClientLogOptions = {},
): void {
  const dedupeKey = `${options.scope ?? ""}:${options.phase ?? label}`;
  if (_shouldSkipForDedupe(dedupeKey, options.dedupeMs)) {
    return;
  }

  const elapsedMs = options.elapsedMs ?? resolveClientElapsedMs(options.startTime);
  const hasDetails =
    options.details != null && Object.keys(options.details).length > 0;
  const payload: Record<string, unknown> = {
    label,
    elapsed_ms: elapsedMs,
  };

  if (options.scope) {
    payload.scope = options.scope;
  }
  if (options.phase) {
    payload.phase = options.phase;
  }
  if (hasDetails) {
    payload.details = options.details;
  }

  const message = elapsedMs != null
    ? `${label} (+${elapsedMs.toFixed(0)}ms)`
    : label;
  const logger = options.method === "error"
    ? console.error
    : options.method === "warn"
      ? console.warn
      : console.log;
  if (hasDetails) {
    logger(`[LUMINA] ${message}`, options.details);
  } else {
    logger(`[LUMINA] ${message}`);
  }

  if (typeof fetch !== "function") {
    return;
  }

  fetch("/api/client-log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).catch(() => {});
}
