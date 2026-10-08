import type { LuminaBoxSerialApi, LuminaBoxSerialPort } from "./luminaBoxSerial";
import { LuminaBoxSerialTimeout } from "./luminaBoxSerialDeadline";

export type LuminaBoxNativeSerialResult = { status: "ok" } | { status: "error"; error: string };
export type LuminaBoxNativeSerialEvent =
  | { connectionId: string; type: "data"; data: Uint8Array }
  | { connectionId: string; type: "error"; error: string }
  | { connectionId: string; type: "closed" };

export interface LuminaBoxNativeSerialApi {
  requestPort(): Promise<{ status: "selected"; connectionId: string }
    | { status: "cancelled" } | { status: "error"; error: string }>;
  open(connectionId: string): Promise<LuminaBoxNativeSerialResult>;
  write(connectionId: string, bytes: Uint8Array): Promise<LuminaBoxNativeSerialResult>;
  close(connectionId: string): Promise<LuminaBoxNativeSerialResult>;
  subscribe(listener: (event: LuminaBoxNativeSerialEvent) => void): () => void;
}

interface StreamSession {
  reader: ReadableStreamDefaultController<Uint8Array> | null;
  writer: WritableStreamDefaultController | null;
  unsubscribe: (() => void) | null;
  closing: Promise<void> | null;
  stopped: boolean;
  error: Error | null;
}

function nativeError(error: string): Error {
  return error === "serial_operation_timeout" ? new LuminaBoxSerialTimeout() : new Error(error);
}

function requireSuccess(result: LuminaBoxNativeSerialResult): void {
  if (result.status === "error") throw nativeError(result.error);
}

/** Adapt the desktop byte transport without interpreting firmware frames.
 * 将桌面字节通道接入采集流，保持固件帧原样。
 */
class DesktopSerialPort implements LuminaBoxSerialPort {
  readable: ReadableStream<Uint8Array> | null = null;
  writable: WritableStream<Uint8Array> | null = null;
  private session: StreamSession | null = null;
  private opening: Promise<void> | null = null;

  constructor(private readonly bridge: LuminaBoxNativeSerialApi, private readonly connectionId: string) {}

  open(options: { baudRate: number }): Promise<void> {
    if (this.opening) return Promise.reject(new DOMException("serial_port_opening", "InvalidStateError"));
    const opening = this.openSession(options);
    this.opening = opening;
    void opening.then(() => { this.opening = null; }, () => { this.opening = null; });
    return opening;
  }

  close(): Promise<void> {
    return this.session ? this.closeSession(this.session) : Promise.resolve();
  }

  private async openSession(options: { baudRate: number }): Promise<void> {
    if (options.baudRate !== 115200) throw new DOMException("serial_baud_rate_unsupported", "NotSupportedError");
    if (this.session) {
      if (!this.session.stopped) throw new DOMException("serial_port_already_open", "InvalidStateError");
      await this.closeSession(this.session);
    }
    const session: StreamSession = {
      reader: null, writer: null, unsubscribe: null, closing: null, stopped: false, error: null,
    };
    this.session = session;
    this.readable = new ReadableStream<Uint8Array>({
      start: (controller) => { session.reader = controller; },
      cancel: () => { session.reader = null; return this.closeSession(session); },
    });
    this.writable = new WritableStream<Uint8Array>({
      start: (controller) => { session.writer = controller; },
      write: async (bytes) => {
        if (session.stopped) throw session.error ?? new Error("serial_port_closed");
        try {
          requireSuccess(await this.bridge.write(this.connectionId, bytes));
        } catch (error) {
          this.failSession(session, error instanceof Error ? error : new Error(String(error)));
          throw error;
        }
      },
      close: () => this.closeSession(session),
      abort: () => this.closeSession(session),
    });
    try {
      session.unsubscribe = this.bridge.subscribe((event) => {
        if (event.connectionId !== this.connectionId || session.stopped) return;
        if (event.type === "data") session.reader?.enqueue(new Uint8Array(event.data));
        else this.failSession(session, nativeError(event.type === "error" ? event.error : "serial_worker_exited"));
      });
      requireSuccess(await this.bridge.open(this.connectionId));
      if (session.stopped) throw session.error ?? new Error("serial_port_closed");
    } catch (error) {
      this.failSession(session, error instanceof Error ? error : new Error(String(error)));
      // Open owns cleanup because the caller cannot yet consider the port open.
      await this.closeSession(session).catch(() => undefined);
      throw error;
    }
  }

  private failSession(session: StreamSession, error: Error): void {
    if (session.stopped) return;
    session.error = error;
    session.stopped = true;
    session.reader?.error(error);
    session.writer?.error(error);
    session.reader = null;
    session.writer = null;
  }

  private closeSession(session: StreamSession): Promise<void> {
    if (session.closing) return session.closing;
    session.stopped = true;
    session.unsubscribe?.();
    session.unsubscribe = null;
    session.reader?.close();
    session.writer?.error(session.error ?? new Error("serial_port_closed"));
    session.reader = null;
    session.writer = null;
    if (this.session === session) { this.readable = null; this.writable = null; }
    // Native close resolves only after the old worker exits; retries must await it.
    session.closing = Promise.resolve().then(async () => {
      requireSuccess(await this.bridge.close(this.connectionId));
    });
    return session.closing;
  }
}

/** Prefer the isolated desktop transport when its preload bridge is present.
 * 存在桌面预加载桥接时优先使用独立串口通道。
 */
export function getLuminaBoxDesktopSerialApi(): LuminaBoxSerialApi | null {
  const bridge = typeof window === "undefined" ? undefined
    : (window as Window & { electronAPI?: { nativeSerial?: LuminaBoxNativeSerialApi } }).electronAPI?.nativeSerial;
  if (!bridge) return null;
  return {
    requestPort: async () => {
      const selected = await bridge.requestPort();
      if (selected.status === "cancelled") throw new DOMException("serial_selection_cancelled", "NotFoundError");
      if (selected.status === "error") throw nativeError(selected.error);
      return new DesktopSerialPort(bridge, selected.connectionId);
    },
  };
}
