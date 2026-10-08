import { create } from "zustand";
import {
  getLuminaBoxSerialApi, LuminaBoxLineDecoder,
  type LuminaBoxCaptureResult, type LuminaBoxFrame, type LuminaBoxMeasurement,
  type LuminaBoxSerialApi, type LuminaBoxSerialPort,
} from "../api/luminaBoxSerial";
import { LuminaBoxSerialTimeout, serialDeadline } from "../api/luminaBoxSerialDeadline";

export type LuminaBoxSerialIssue = Exclude<LuminaBoxCaptureResult, "applied">
  | "unsupported" | "connection_failed" | "connection_lost" | "invalid_measurement" | "material_changed"
  | "operation_timeout" | "delivery_overflow" | "wrong_device";
type Receiver = (measurement: LuminaBoxMeasurement) => LuminaBoxCaptureResult | Promise<LuminaBoxCaptureResult>;
export interface LuminaBoxSerialStoreOptions {
  storageNamespace?: string;
}
type Mode = "unknown" | "handshaking" | "legacy" | "reliable";
type Status = "disconnected" | "connecting" | "handshaking" | "connected" | "recovering" | "disconnecting";
type Trace = { at: number; event: string; measurementId?: string; detail?: string };
interface SerialState {
  status: Status; mode: Mode; issue: LuminaBoxSerialIssue | null;
  captureId: string; pendingCount: number; receivedBytes: number;
  receivedCount: number; lastMeasurement: LuminaBoxMeasurement | null;
  lastHeartbeatAt: number | null; lastError: string | null; trace: Trace[];
  connect: (receive: Receiver) => void;
  disconnect: (issue?: LuminaBoxSerialIssue) => Promise<void>;
  resetCapture: () => void;
  replay: () => void;
}
export type LuminaBoxSerialDiagnosticSnapshot = Pick<SerialState,
  "status" | "mode" | "captureId" | "receivedBytes" | "receivedCount" | "pendingCount"
  | "lastHeartbeatAt" | "issue" | "lastError" | "trace">;
interface Connection {
  cancelled: boolean;
  reader: ReadableStreamDefaultReader<Uint8Array> | null;
  writer: WritableStreamDefaultWriter<Uint8Array> | null;
  task: Promise<void> | null;
  writes: Promise<void>;
  timer: ReturnType<typeof setInterval> | null;
  openedAt: number;
  heartbeatAt: number;
  mode: Mode;
  fault: LuminaBoxSerialIssue | null;
  faultMessage: string | null;
  helloAttempts: number;
  stopped: Promise<void>;
  stop: () => void;
  wasReliable: boolean;
  applyingIds: Set<string>;
  receiverFaults: number;
}
const SCOPE_KEY = "lumina-box-capture-scope-v1";
const RECEIPT_KEY = "lumina-box-applied-receipts-v1";
const OPERATION_MS = 2500;
const HEARTBEAT_MS = 6000;
const developmentStores = new Set<{ getState: () => Pick<SerialState, "disconnect"> }>();
const newScope = () => crypto.randomUUID();
const makeConnection = (): Connection => {
  let stop!: () => void;
  const stopped = new Promise<void>((resolve) => { stop = resolve; });
  return { cancelled: false, reader: null, writer: null, task: null, writes: Promise.resolve(),
    timer: null, openedAt: 0, heartbeatAt: 0, mode: "unknown", fault: null, faultMessage: null, helloAttempts: 0, stopped, stop,
    wasReliable: false, applyingIds: new Set<string>(), receiverFaults: 0 };
};
const initialScope = (scopeKey: string) => {
  try {
    const scope = localStorage.getItem(scopeKey);
    if (scope && /^[A-Za-z0-9_-]{1,64}$/.test(scope)) return scope;
  } catch { /* In-memory capture remains usable when storage is unavailable. */ }
  return newScope();
};

/** Own one authorized port, scoped delivery acknowledgements and link health.
 * 管理一个已授权串口、按采集批次确认数据及连接健康状态。
 * Async receivers acknowledge only committed captures without blocking link health.
 * 异步接收方仅在采集数据保存成功后确认，不阻塞连接心跳。
 */
export function createLuminaBoxSerialStore(
  getApi: () => LuminaBoxSerialApi | null = getLuminaBoxSerialApi,
  options: LuminaBoxSerialStoreOptions = {},
) {
  const scopeKey = options.storageNamespace ? `${options.storageNamespace}-capture-scope-v1` : SCOPE_KEY;
  const receiptKey = options.storageNamespace ? `${options.storageNamespace}-applied-receipts-v1` : RECEIPT_KEY;
  let connection: Connection | null = null;
  let captureId = initialScope(scopeKey);
  let expectedDevice: string | null = null;
  const appliedIds = new Set<string>();
  let recoveryAttempts = 0;
  try {
    const receipt = JSON.parse(localStorage.getItem(receiptKey) ?? "null") as unknown;
    if (receipt && typeof receipt === "object") {
      const record = receipt as { captureId?: unknown; ids?: unknown; device?: unknown };
      if (record.captureId === captureId && Array.isArray(record.ids) && record.ids.length <= 512
        && record.ids.every(id => typeof id === "string" && id.length > 0 && id.length <= 128)) {
        record.ids.forEach(id => appliedIds.add(id as string));
        if (typeof record.device === "string" && /^[A-Za-z0-9_]{1,32}$/.test(record.device)) expectedDevice = record.device;
      }
    }
  } catch { /* A damaged receipt cache must not prevent capture. */ }

  const store = create<SerialState>((set, get) => {
    const trace = (event: string, measurementId?: string, detail?: string) => {
      set((state) => ({ trace: [...state.trace.slice(-39), { at: Date.now(), event, measurementId, detail }] }));
    };
    const persistReceipts = () => {
      try {
        localStorage.setItem(receiptKey, JSON.stringify({ captureId, ids: [...appliedIds], device: expectedDevice }));
        return true;
      } catch { trace("receipt_storage_failed"); return false; }
    };
    const rotate = () => {
      captureId = newScope();
      appliedIds.clear();
      try { localStorage.setItem(scopeKey, captureId); } catch { /* Best effort. */ }
      set({ captureId, pendingCount: 0, receivedCount: 0, lastMeasurement: null });
      persistReceipts();
      trace("capture_changed", undefined, captureId);
    };
    try { localStorage.setItem(scopeKey, captureId); } catch { /* Best effort. */ }

    const fail = (active: Connection, issue: LuminaBoxSerialIssue, error?: unknown) => {
      if (active.cancelled || active.fault || connection !== active) return;
      active.fault = issue;
      active.faultMessage = error instanceof Error ? error.message : issue;
      active.stop();
      set({ status: "recovering", issue, lastError: active.faultMessage });
      trace("transport_failed", undefined, active.faultMessage);
      void active.reader?.cancel().catch(() => undefined);
    };
    const command = (active: Connection, type: string, measurementId?: string) => {
      const scope = captureId;
      active.writes = active.writes.then(async () => {
        if (active.cancelled || active.fault || !active.writer || scope !== captureId) return;
        const payload = { protocol: "lumina-box", version: 3, type, capture_id: scope,
          ...(measurementId ? { measurement_id: measurementId } : {}) };
        await serialDeadline(active.writer.write(new TextEncoder().encode(`${JSON.stringify(payload)}\n`)), OPERATION_MS);
        if (type !== "ping") trace(`${type}_sent`, measurementId);
      }).catch((error: unknown) => {
        if (!active.cancelled && connection === active) {
          trace("command_failed", measurementId, JSON.stringify({ command: type,
            error: error instanceof Error ? error.message : String(error) }));
        }
        fail(active, error instanceof LuminaBoxSerialTimeout ? "operation_timeout" : "connection_lost", error);
      });
    };
    const handshake = (active: Connection) => {
      active.mode = "handshaking";
      active.openedAt = Date.now();
      active.heartbeatAt = 0;
      active.helloAttempts = 1;
      set({ status: "handshaking", mode: "handshaking", lastHeartbeatAt: null });
      command(active, "hello");
    };

    const accept = (active: Connection, frame: LuminaBoxFrame, receive: Receiver) => {
      if (frame.kind === "invalid") { set({ issue: "invalid_measurement" }); trace("frame_invalid"); return; }
      if (frame.kind === "ignored") return;
      if (frame.kind === "pong") {
        if (frame.captureId !== captureId) { trace("scope_ignored"); return; }
        const peer = frame.bootId.split("-")[0];
        if (expectedDevice && expectedDevice !== peer) { fail(active, "wrong_device"); return; }
        expectedDevice = peer;
        persistReceipts();
        if (active.mode === "handshaking") {
          trace("handshake_received", undefined, JSON.stringify({ bootId: frame.bootId, rxStats: frame.rxStats }));
        }
        const receiverFaults = Object.entries(frame.rxStats ?? {}).reduce((count, [field, value]) =>
          field === "rx_bytes" ? count : count + value, 0);
        if (frame.pendingCount !== get().pendingCount || frame.txFailures || receiverFaults !== active.receiverFaults) {
          trace("device_delivery_status", frame.lastMeasurementId,
            JSON.stringify({ pending: frame.pendingCount, ack: frame.lastAckId, txFailures: frame.txFailures,
              dropped: frame.droppedCount, rxStats: frame.rxStats }));
        }
        active.receiverFaults = receiverFaults;
        active.mode = "reliable";
        active.wasReliable = true;
        active.heartbeatAt = Date.now();
        const recovered = get().issue === "connection_lost" || get().issue === "operation_timeout";
        set({ status: "connected", mode: "reliable", lastHeartbeatAt: active.heartbeatAt,
          pendingCount: frame.pendingCount, issue: frame.droppedCount ? "delivery_overflow" : recovered ? null : get().issue,
          ...(recovered ? { lastError: null } : {}) });
        return;
      }
      const reliable = frame.kind === "delivery";
      if (reliable && (frame.captureId !== captureId || active.mode !== "reliable")) { trace("scope_ignored"); return; }
      if (!reliable && active.mode !== "legacy") { trace("legacy_frame_ignored"); return; }
      if (reliable) {
        active.heartbeatAt = Date.now();
        set({ lastHeartbeatAt: active.heartbeatAt });
      }
      const id = frame.measurement.measurement_id;
      if (appliedIds.has(id)) {
        trace("duplicate_received", id);
        if (reliable) {
          if (persistReceipts()) command(active, "ack", id);
          else { set({ issue: "storage_unavailable" }); command(active, "reject", id); }
        }
        return;
      }
      if (active.applyingIds.has(id)) { trace("duplicate_pending", id); return; }
      active.applyingIds.add(id);
      const applicationScope = captureId;
      const complete = (result: LuminaBoxCaptureResult) => {
        active.applyingIds.delete(id);
        if (active.cancelled || active.fault || connection !== active || captureId !== applicationScope) return;
        if (result !== "applied") {
          set({ issue: result });
          trace("application_rejected", id, result);
          if (reliable) command(active, "reject", id);
          return;
        }
        appliedIds.add(id);
        if (appliedIds.size > 512) appliedIds.delete(appliedIds.values().next().value!);
        set((state) => ({ issue: state.issue === "delivery_overflow" ? state.issue : null,
          receivedCount: state.receivedCount + 1, lastMeasurement: frame.measurement }));
        trace("measurement_applied", id);
        recoveryAttempts = 0;
        if (reliable) {
          if (persistReceipts()) command(active, "ack", id);
          else { set({ issue: "storage_unavailable" }); command(active, "reject", id); }
        }
      };
      // Snapshot the receiver's capture context immediately; keep reading heartbeat frames.
      try {
        const result = receive(frame.measurement);
        if (typeof result === "string") complete(result);
        else void result.then(complete).catch((error: unknown) => {
          trace("application_failed", id, error instanceof Error ? error.message : String(error));
          complete("storage_unavailable");
        });
      } catch (error) {
        trace("application_failed", id, error instanceof Error ? error.message : String(error));
        complete("storage_unavailable");
      }
    };

    const read = async (active: Connection, port: LuminaBoxSerialPort, receive: Receiver) => {
      let readFailures = 0;
      while (!active.cancelled && !active.fault && port.readable) {
        const stream = port.readable;
        const reader = stream.getReader();
        const decoder = new LuminaBoxLineDecoder();
        active.reader = reader;
        let streamEnded = false;
        try {
          while (!active.cancelled && !active.fault) {
            const outcome = await Promise.race([
              reader.read().then((result) => ({ result })),
              active.stopped.then(() => ({ stopped: true as const })),
            ]);
            if ("stopped" in outcome) break;
            const { done, value } = outcome.result;
            if (active.cancelled || active.fault) break;
            if (done) { streamEnded = true; break; }
            set((state) => ({ receivedBytes: state.receivedBytes + value.length }));
            for (const frame of decoder.push(value)) {
              if (active.cancelled || active.fault) break;
              accept(active, frame, receive);
            }
            readFailures = 0;
          }
        } catch (error) {
          const name = error instanceof Error ? error.name : "";
          if (++readFailures > 3 || !port.readable || port.readable === stream) throw error;
          trace("reader_recovered", undefined, name);
        } finally {
          reader.releaseLock();
          active.reader = null;
        }
        if (streamEnded && !active.cancelled && !active.fault) throw new Error("serial_stream_ended");
      }
      if (active.fault) throw new Error(active.fault);
      if (!active.cancelled) throw new Error("serial_stream_unavailable");
    };

    const run = async (active: Connection, api: LuminaBoxSerialApi, receive: Receiver) => {
      let port: LuminaBoxSerialPort | null = null;
      let opened = false;
      let closed = false;
      try {
        port = await api.requestPort(); // Only initial user-authorized selection.
        if (active.cancelled) return;
        const opening = port.open({ baudRate: 115200 });
        try { await serialDeadline(opening, OPERATION_MS); }
        catch (error) {
          // Keep ownership until a late platform open is actually cleaned up.
          if (error instanceof LuminaBoxSerialTimeout) {
            fail(active, "operation_timeout", error);
            await opening;
            opened = true;
            return;
          }
          throw error;
        }
        opened = true;
        if (active.cancelled) return;
        active.writer = port.writable?.getWriter() ?? null;
        if (active.writer) handshake(active);
        else {
          if (expectedDevice) { fail(active, "connection_lost", new Error("serial_write_unavailable")); return; }
          active.mode = "legacy"; set({ status: "connected", mode: "legacy" });
        }
        active.timer = setInterval(() => {
          if (active.cancelled || active.fault) return;
          const now = Date.now();
          if (active.mode === "handshaking" && now - active.openedAt >= OPERATION_MS) {
            if (expectedDevice || active.wasReliable) {
              active.mode = "reliable";
              fail(active, "connection_lost", new Error("handshake_timeout"));
              return;
            }
            active.mode = "legacy";
            set({ status: "connected", mode: "legacy" });
            trace("legacy_mode");
          } else if (active.mode === "handshaking" && active.helloAttempts++ < 2) command(active, "hello");
          else if (active.mode === "reliable") {
            if (now - active.heartbeatAt >= HEARTBEAT_MS) fail(active, "connection_lost", new Error("heartbeat_timeout"));
            else command(active, "ping");
          }
        }, 1000);
        await read(active, port, receive);
      } catch (error) {
        if (!active.cancelled && connection === active) {
          const name = error instanceof Error ? error.name : "";
          const issue = active.fault ?? (error instanceof LuminaBoxSerialTimeout ? "operation_timeout"
            : name === "SecurityError" || name === "NotSupportedError" ? "unsupported"
            : opened ? "connection_lost" : "connection_failed");
          const message = active.faultMessage ?? (error instanceof Error ? error.message : String(error));
          if (name !== "NotFoundError" && !active.fault) {
            active.fault = issue;
            active.faultMessage = message;
          }
          set({ issue: name === "NotFoundError" ? null : issue, lastError: message });
          trace("connection_failed", undefined, message);
        }
      } finally {
        if (active.timer) clearInterval(active.timer);
        if (active.writer) {
          try {
            await serialDeadline(active.writes, OPERATION_MS);
            if (active.fault) await serialDeadline(active.writer.abort(), OPERATION_MS);
          } catch (error) {
            trace(error instanceof LuminaBoxSerialTimeout ? "writer_cleanup_timeout" : "writer_cleanup_failed",
              undefined, error instanceof Error ? error.message : String(error));
          }
          finally { active.writer.releaseLock(); active.writer = null; }
        }
        if (opened && port) {
          const closing = port.close();
          try { await serialDeadline(closing, OPERATION_MS); closed = true; }
          catch (error) {
            if (error instanceof LuminaBoxSerialTimeout) {
              trace("close_timeout", undefined, "serial_cleanup_timeout");
              set({ status: "disconnecting", ...(!active.fault
                ? { issue: "operation_timeout" as const, lastError: "serial_cleanup_timeout" } : {}) });
              try { await closing; closed = true; }
              catch (closeError) { trace("close_failed", undefined, closeError instanceof Error ? closeError.message : String(closeError)); }
            } else {
              const message = error instanceof Error ? error.message : String(error);
              trace("close_failed", undefined, message);
              if (!active.fault) set({ issue: "connection_lost", lastError: message });
            }
          }
        }
        if (connection === active) {
          const retry = !active.cancelled && opened && closed && port && active.mode === "reliable"
            && (active.fault === "connection_lost" || active.fault === "operation_timeout"
              || get().issue === "connection_lost") && recoveryAttempts < 2;
          if (retry && port) {
            recoveryAttempts += 1;
            const authorizedPort = port;
            const next = makeConnection();
            next.wasReliable = true;
            connection = next;
            set({ status: "recovering", mode: "unknown" });
            trace("authorized_port_retry", undefined, String(recoveryAttempts));
            next.task = new Promise<void>((resolve, reject) => {
              setTimeout(() => {
                if (next.cancelled) { if (connection === next) { connection = null; set({ status: "disconnected", mode: "unknown" }); } resolve(); return; }
                void run(next, { requestPort: async () => authorizedPort }, receive).then(resolve, reject);
              }, 1000);
            });
          } else { connection = null; set({ status: "disconnected", mode: "unknown" }); }
        }
      }
    };

    return {
      status: "disconnected", mode: "unknown", issue: null, captureId, pendingCount: 0,
      receivedBytes: 0, receivedCount: 0, lastMeasurement: null, lastHeartbeatAt: null, lastError: null, trace: [],
      connect: (receive) => {
        if (connection) return;
        const api = getApi();
        if (!api) { set({ issue: "unsupported" }); return; }
        recoveryAttempts = 0;
        const active = makeConnection();
        active.wasReliable = expectedDevice !== null;
        connection = active;
        set({ status: "connecting", mode: "unknown", issue: null, receivedBytes: 0,
          receivedCount: 0, lastMeasurement: null, lastError: null });
        trace("connect_started");
        active.task = run(active, api, receive);
      },
      disconnect: async (issue) => {
        if (issue === "material_changed") { expectedDevice = null; rotate(); }
        const active = connection;
        if (!active) { set({ issue: issue ?? null, receivedCount: 0, lastMeasurement: null }); return; }
        active.cancelled = true;
        active.stop();
        if (active.timer) clearInterval(active.timer);
        set({ status: "disconnecting", issue: issue ?? null, receivedCount: 0, lastMeasurement: null });
        void active.reader?.cancel().catch(() => undefined);
        try { await serialDeadline(active.task ?? Promise.resolve(), OPERATION_MS); }
        catch (error) {
          trace("disconnect_wait_failed", undefined, error instanceof Error ? error.message : String(error));
          set({ status: "disconnecting", ...(!active.fault && !get().issue ? {
            issue: error instanceof LuminaBoxSerialTimeout ? "operation_timeout" as const : "connection_lost" as const,
            lastError: error instanceof LuminaBoxSerialTimeout ? "serial_cleanup_timeout"
              : error instanceof Error ? error.message : String(error),
          } : {}) });
        }
      },
      resetCapture: () => {
        const legacyIds = connection?.mode === "legacy" ? [...appliedIds] : [];
        expectedDevice = null;
        rotate();
        legacyIds.forEach((id) => appliedIds.add(id));
        persistReceipts();
        const active = connection;
        if (active && !active.cancelled && active.writer && !active.fault) handshake(active);
      },
      replay: () => {
        const active = connection;
        if (active && !active.cancelled && active.mode === "reliable") command(active, "replay");
      },
    };
  });
  if (import.meta.hot) developmentStores.add(store);
  return store;
}

export const useLuminaBoxSerialStore = createLuminaBoxSerialStore();

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    for (const store of developmentStores) void store.getState().disconnect();
    developmentStores.clear();
  });
}
