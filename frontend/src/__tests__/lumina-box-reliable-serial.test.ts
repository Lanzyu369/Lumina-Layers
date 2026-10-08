import { afterEach, describe, expect, it, vi } from "vitest";
import { createLuminaBoxSerialStore } from "../stores/luminaBoxSerialStore";
import { parseLuminaBoxFrame, type LuminaBoxCaptureResult } from "../api/luminaBoxSerial";

const measurement = {
  protocol: "lumina-box", version: 2, type: "measurement", measurement_id: "box-boot-1",
  thickness_mm: 0.32, mode: "auto", reflectance_xyz: [103.25, 22, 23], transmittance_xyz: [0, 31, 32],
};
const stores: ReturnType<typeof createLuminaBoxSerialStore>[] = [];
const flush = async () => { for (let i = 0; i < 20; ++i) await Promise.resolve(); };

function device(storageNamespace?: string) {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  let stream!: ReadableStream<Uint8Array>;
  let writes!: WritableStream<Uint8Array>;
  const commands: Record<string, unknown>[] = [];
  let heldWrite: { type: string; promise: Promise<void> } | null = null;
  const renew = () => {
    stream = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
    writes = new WritableStream<Uint8Array>({ write(chunk) {
      const command = JSON.parse(new TextDecoder().decode(chunk)) as Record<string, unknown>;
      commands.push(command);
      const held = heldWrite;
      if (held && held.type === command.type) {
        heldWrite = null;
        return held.promise;
      }
    } });
  };
  renew();
  const port = {
    get readable() { return stream; }, get writable() { return writes; },
    open: vi.fn().mockImplementation(async () => { if (stream.locked || writes.locked) throw new Error("competing_port_open"); }),
    close: vi.fn().mockImplementation(async () => renew()),
  };
  const send = (frame: unknown) => controller.enqueue(new TextEncoder().encode(`${JSON.stringify(frame)}\n`));
  const store = createLuminaBoxSerialStore(() => ({ requestPort: async () => port }), { storageNamespace });
  stores.push(store);
  store.getState().resetCapture();
  const pong = (patch: Record<string, unknown> = {}) => send({ protocol: "lumina-box", version: 3,
    type: "pong", capture_id: store.getState().captureId, boot_id: "box-boot", pending_count: 1, dropped_count: 0, ...patch });
  const deliver = (patch: Record<string, unknown> = {}) => send({ protocol: "lumina-box", version: 3,
    type: "delivery", capture_id: store.getState().captureId, measurement, ...patch });
  return { store, port, send, pong, deliver, commands, holdNextWrite: (type: string) => {
    let release!: () => void;
    heldWrite = { type, promise: new Promise<void>((resolve) => { release = resolve; }) };
    return release;
  }, replaceAfterError: () => {
    const old = controller; renew(); old.error(new DOMException("framing", "NetworkError"));
  } };
}

afterEach(async () => {
  for (const store of stores.splice(0)) {
    const closing = store.getState().disconnect();
    if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(3000);
    await closing;
  }
  vi.useRealTimers();
});

describe("reliable LuminaBox delivery", () => {
  it("requires a matching handshake, ACKs applied rows and re-ACKs duplicates without applying twice", async () => {
    const d = device();
    const receive = vi.fn().mockReturnValue("applied");
    d.store.getState().connect(receive);
    await flush();
    expect(d.store.getState().status).toBe("handshaking");
    expect(d.commands[0]).toMatchObject({ type: "hello", capture_id: d.store.getState().captureId });
    d.deliver(); await flush();
    expect(receive).not.toHaveBeenCalled();
    d.pong(); await flush();
    expect(d.store.getState().mode).toBe("reliable");
    d.deliver(); await flush();
    expect(receive).toHaveBeenCalledWith(measurement);
    expect(d.commands.filter(c => c.type === "ack")).toHaveLength(1);
    d.deliver(); await flush();
    expect(receive).toHaveBeenCalledTimes(1);
    expect(d.store.getState().receivedCount).toBe(1);
    expect(d.commands.filter(c => c.type === "ack")).toHaveLength(2);
  });

  it("allows retrying a rejected ID after repairing a thickness row", async () => {
    const d = device();
    const receive = vi.fn().mockReturnValueOnce("thickness_missing").mockReturnValue("applied");
    d.store.getState().connect(receive); await flush(); d.pong(); await flush();
    d.deliver(); await flush();
    expect(d.commands.some(c => c.type === "reject")).toBe(true);
    expect(d.commands.some(c => c.type === "ack")).toBe(false);
    d.store.getState().replay(); await flush();
    expect(d.commands.some(c => c.type === "replay")).toBe(true);
    d.deliver(); await flush();
    expect(receive).toHaveBeenCalledTimes(2);
    expect(d.store.getState().receivedCount).toBe(1);
  });

  it("ignores old-capture frames after clearing and handshakes a new scope", async () => {
    const d = device(); const receive = vi.fn().mockReturnValue("applied");
    d.store.getState().connect(receive); await flush(); d.pong(); await flush();
    const old = d.store.getState().captureId;
    d.store.getState().resetCapture(); await flush();
    expect(d.store.getState().captureId).not.toBe(old);
    d.pong({ capture_id: old }); d.deliver({ capture_id: old }); await flush();
    expect(receive).not.toHaveBeenCalled();
    d.pong(); d.deliver(); await flush();
    expect(receive).toHaveBeenCalledTimes(1);
  });

  it("keeps idle links healthy while heartbeat replies arrive, detects silence and retries only the same port", async () => {
    vi.useFakeTimers();
    const d = device(); d.store.getState().connect(vi.fn().mockReturnValue("applied"));
    await flush(); d.pong(); await flush();
    for (let i = 0; i < 10; ++i) { await vi.advanceTimersByTimeAsync(1000); d.pong(); await flush(); }
    expect(d.store.getState().status).toBe("connected");
    expect(d.store.getState().receivedCount).toBe(0);
    await vi.advanceTimersByTimeAsync(7000); await flush();
    expect(d.port.close).toHaveBeenCalledTimes(1);
    expect(d.port.open).toHaveBeenCalledTimes(2);
    expect(d.store.getState().trace.some(t => t.event === "authorized_port_retry")).toBe(true);
    d.pong(); await flush();
    expect(d.store.getState().status).toBe("connected");
  });

  it("replaces a recoverable reader and retains delivery capability", async () => {
    const d = device(); const receive = vi.fn().mockReturnValue("applied");
    d.store.getState().connect(receive); await flush(); d.pong(); await flush();
    d.replaceAfterError(); await flush(); d.deliver(); await flush();
    expect(receive).toHaveBeenCalledTimes(1);
    expect(d.port.close).not.toHaveBeenCalled();
    expect(d.store.getState().trace.some(t => t.event === "reader_recovered")).toBe(true);
  });

  it("limits automatic recovery and never treats a lost reliable handshake as legacy success", async () => {
    vi.useFakeTimers(); const d = device();
    d.store.getState().connect(vi.fn().mockReturnValue("applied"));
    await flush(); d.pong(); await flush();
    await vi.advanceTimersByTimeAsync(20000); await flush();
    expect(d.port.open).toHaveBeenCalledTimes(3);
    expect(d.port.close).toHaveBeenCalledTimes(3);
    expect(d.store.getState().status).toBe("disconnected");
    expect(d.store.getState().issue).toBe("connection_lost");
    expect(d.store.getState().trace.some(t => t.event === "legacy_mode")).toBe(false);
  });

  it("retains reliable capability when clear replaces the capture identity", async () => {
    vi.useFakeTimers(); const d = device();
    d.store.getState().connect(vi.fn().mockReturnValue("applied"));
    await flush(); d.pong(); d.deliver(); await flush();
    expect(d.store.getState().receivedCount).toBe(1);
    d.store.getState().resetCapture(); await flush();
    expect(d.store.getState().receivedCount).toBe(0);
    await vi.advanceTimersByTimeAsync(4000); await flush();
    expect(d.store.getState().trace.some(t => t.event === "legacy_mode")).toBe(false);
    expect(d.store.getState().receivedCount).toBe(0);
  });

  it("starts a different capture on material change and refuses old batch replay", async () => {
    const d = device(); const receive = vi.fn().mockReturnValue("applied");
    d.store.getState().connect(receive); await flush(); d.pong(); await flush();
    const oldCapture = d.store.getState().captureId;
    await d.store.getState().disconnect("material_changed");
    expect(d.store.getState().captureId).not.toBe(oldCapture);
    d.store.getState().connect(receive); await flush(); d.pong(); await flush();
    d.deliver({ capture_id: oldCapture }); await flush();
    expect(receive).not.toHaveBeenCalled();
    d.deliver(); await flush(); expect(receive).toHaveBeenCalledTimes(1);
  });

  it("does not ACK malformed or wrong-scope data and surfaces cache overflow", async () => {
    const d = device(); const receive = vi.fn().mockReturnValue("applied");
    d.store.getState().connect(receive); await flush(); d.pong({ dropped_count: 2 }); await flush();
    expect(d.store.getState().issue).toBe("delivery_overflow");
    d.deliver({ capture_id: "other" });
    d.deliver({ measurement: { ...measurement, transmittance_xyz: [101, 1, 2] } }); await flush();
    expect(receive).not.toHaveBeenCalled();
    expect(d.commands.some(c => c.type === "ack")).toBe(false);
  });

  it("rejects a different device during the same capture", async () => {
    const d = device(); d.store.getState().connect(vi.fn().mockReturnValue("applied"));
    await flush(); d.pong(); await flush(); d.pong({ boot_id: "other-device" }); await flush();
    expect(d.store.getState().issue).toBe("wrong_device");
    expect(d.store.getState().status).toBe("disconnected");
  });

  it("bounds disconnect while a platform open is stalled and closes a late-opened port", async () => {
    vi.useFakeTimers(); const d = device();
    let open!: () => void;
    d.port.open.mockReturnValueOnce(new Promise<void>(resolve => { open = resolve; }));
    d.store.getState().connect(vi.fn()); await flush();
    const closing = d.store.getState().disconnect();
    await vi.advanceTimersByTimeAsync(3000); await closing;
    expect(d.store.getState().issue).toBe("operation_timeout");
    expect(d.store.getState().status).toBe("disconnecting");
    expect(d.port.close).not.toHaveBeenCalled();
    open(); await flush();
    expect(d.port.close).toHaveBeenCalledTimes(1);
    expect(d.store.getState().status).toBe("disconnected");
  });

  it("reports an immediate close failure as connection loss and retains its platform message", async () => {
    const d = device("close-network-error");
    d.store.getState().connect(vi.fn().mockReturnValue("applied"));
    await flush(); d.pong(); await flush();
    const message = "The device has been lost.";
    d.port.close.mockRejectedValueOnce(new DOMException(message, "NetworkError"));
    await d.store.getState().disconnect();
    expect(d.store.getState().status).toBe("disconnected");
    expect(d.store.getState().issue).toBe("connection_lost");
    expect(d.store.getState().lastError).toContain(message);
    expect(d.store.getState().trace.find((entry) => entry.event === "close_failed")?.detail).toContain(message);
    expect(d.port.open).toHaveBeenCalledTimes(1);
  });

  it("retains the heartbeat failure when closing also rejects and traces the close error", async () => {
    vi.useFakeTimers();
    const d = device("heartbeat-and-close-error");
    d.store.getState().connect(vi.fn().mockReturnValue("applied"));
    await flush(); d.pong(); await flush();
    const message = "The device has been lost during close.";
    d.port.close.mockRejectedValueOnce(new DOMException(message, "NetworkError"));
    await vi.advanceTimersByTimeAsync(4000); await flush();
    const releasePing = d.holdNextWrite("ping");
    await vi.advanceTimersByTimeAsync(3501); await flush();
    expect(d.store.getState().lastError).toBe("heartbeat_timeout");
    expect(d.store.getState().trace.find((entry) => entry.event === "command_failed")?.detail).toContain("serial_operation_timeout");
    releasePing(); await flush();
    expect(d.store.getState().status).toBe("disconnected");
    expect(d.store.getState().issue).toBe("connection_lost");
    expect(d.store.getState().lastError).toBe("heartbeat_timeout");
    expect(d.store.getState().trace.find((entry) => entry.event === "close_failed")?.detail).toContain(message);
    expect(d.port.open).toHaveBeenCalledTimes(1);
  });

  it("keeps a reliable link alive through scoped deliveries and their duplicates without extra pongs", async () => {
    vi.useFakeTimers();
    const d = device("delivery-link-activity");
    const receive = vi.fn().mockReturnValue("applied");
    d.store.getState().connect(receive);
    await flush(); d.pong(); await flush();
    for (let index = 0; index < 10; index++) {
      await vi.advanceTimersByTimeAsync(1000); d.deliver(); await flush();
    }
    expect(d.store.getState().status).toBe("connected");
    expect(d.store.getState().issue).toBeNull();
    expect(d.port.close).not.toHaveBeenCalled();
    expect(receive).toHaveBeenCalledTimes(1);
    expect(d.commands.filter((command) => command.type === "ack")).toHaveLength(10);
  });

  it("recovers a timed-out ACK only after cleanup, re-ACKs its saved row and limits same-port retries", async () => {
    vi.useFakeTimers();
    const d = device("ack-write-timeout");
    const receive = vi.fn().mockResolvedValue("applied");
    d.store.getState().connect(receive);
    await flush(); d.pong(); await flush();
    const releaseAck = d.holdNextWrite("ack");
    d.deliver(); await flush();
    expect(d.store.getState().receivedCount).toBe(1);
    await vi.advanceTimersByTimeAsync(2501); await flush();
    expect(d.store.getState().issue).toBe("operation_timeout");
    expect(d.port.close).not.toHaveBeenCalled();
    expect(d.port.open).toHaveBeenCalledTimes(1);
    releaseAck(); await flush();
    expect(d.port.close).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000); await flush();
    expect(d.port.open).toHaveBeenCalledTimes(2);
    d.pong(); await flush();
    expect(d.store.getState().status).toBe("connected");
    expect(d.store.getState().issue).toBeNull();
    d.deliver(); await flush();
    expect(receive).toHaveBeenCalledTimes(1);
    expect(d.store.getState().receivedCount).toBe(1);
    expect(d.commands.filter((command) => command.type === "ack")).toHaveLength(2);
    for (let index = 0; index < 2; index++) {
      const releasePing = d.holdNextWrite("ping");
      await vi.advanceTimersByTimeAsync(3501); await flush();
      expect(d.store.getState().issue).toBe("operation_timeout");
      releasePing(); await flush();
      await vi.advanceTimersByTimeAsync(1000); await flush();
      if (index === 0) { d.pong(); await flush(); }
    }
    expect(d.port.open).toHaveBeenCalledTimes(3);
    expect(d.port.close).toHaveBeenCalledTimes(3);
    expect(d.store.getState().status).toBe("disconnected");
    expect(d.store.getState().trace.filter((entry) => entry.event === "authorized_port_retry")).toHaveLength(2);
    expect(receive).toHaveBeenCalledTimes(1);
  });

  it("reports a real close deadline and does not reopen before the late close finishes", async () => {
    vi.useFakeTimers();
    const d = device("late-close-timeout");
    d.store.getState().connect(vi.fn().mockReturnValue("applied"));
    await flush(); d.pong(); await flush();
    let finishClose!: () => void;
    const closing = new Promise<void>((resolve) => { finishClose = resolve; });
    const closeNormally = d.port.close.getMockImplementation()!;
    d.port.close.mockImplementationOnce(async () => { await closing; await closeNormally(); });
    await vi.advanceTimersByTimeAsync(6000); await flush();
    expect(d.port.close).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2501); await flush();
    expect(d.store.getState().status).toBe("disconnecting");
    expect(d.store.getState().issue).toBe("connection_lost");
    expect(d.store.getState().lastError).toBe("heartbeat_timeout");
    expect(d.store.getState().trace.find((entry) => entry.event === "close_timeout")?.detail).toContain("serial_cleanup_timeout");
    await vi.advanceTimersByTimeAsync(3000); await flush();
    expect(d.port.open).toHaveBeenCalledTimes(1);
    finishClose(); await flush();
    await vi.advanceTimersByTimeAsync(1000); await flush();
    expect(d.port.open).toHaveBeenCalledTimes(2);
  });

  it("validates reliable envelopes without changing v1/v2 measurement rules", () => {
    expect(parseLuminaBoxFrame(JSON.stringify({ protocol: "lumina-box", version: 3, type: "delivery",
      capture_id: "capture-a", measurement }))).toMatchObject({ kind: "delivery", measurement });
    expect(parseLuminaBoxFrame(JSON.stringify({ protocol: "lumina-box", version: 3, type: "pong",
      capture_id: "capture-a", boot_id: "boot", pending_count: 33, dropped_count: 0 }))).toEqual({ kind: "invalid" });
    const status = { protocol: "lumina-box", version: 3, type: "pong", capture_id: "capture-a",
      boot_id: "boot", pending_count: 0, dropped_count: 0, rx_bytes: 114, rx_dropped_lines: 0 };
    expect(parseLuminaBoxFrame(JSON.stringify(status))).toMatchObject({ kind: "pong", rxStats: { rx_bytes: 114, rx_dropped_lines: 0 } });
    expect(parseLuminaBoxFrame(JSON.stringify({ ...status, rx_dropped_lines: -1 }))).toEqual({ kind: "invalid" });
  });

  it("preserves applied receipts across a page reload so lost ACK replay cannot overwrite manual edits", async () => {
    const d = device(); d.store.getState().connect(vi.fn().mockReturnValue("applied"));
    await flush(); d.pong(); d.deliver(); await flush();
    const capture = d.store.getState().captureId;
    await d.store.getState().disconnect();
    const restored = createLuminaBoxSerialStore(() => ({ requestPort: async () => d.port }));
    stores.push(restored);
    const receive = vi.fn().mockReturnValue("applied");
    restored.getState().connect(receive); await flush();
    expect(restored.getState().captureId).toBe(capture);
    d.send({ protocol: "lumina-box", version: 3, type: "pong", capture_id: capture,
      boot_id: "box-boot", pending_count: 1, dropped_count: 0 });
    d.send({ protocol: "lumina-box", version: 3, type: "delivery", capture_id: capture, measurement }); await flush();
    expect(receive).not.toHaveBeenCalled();
    expect(d.commands.filter(c => c.type === "ack")).toHaveLength(2);
  });

  it("retains a displayed result without ACK when local durable application fails", async () => {
    const d = device(); const receive = vi.fn().mockReturnValueOnce("storage_unavailable").mockReturnValue("applied");
    d.store.getState().connect(receive); await flush(); d.pong(); d.deliver(); await flush();
    expect(d.store.getState().issue).toBe("storage_unavailable");
    expect(d.commands.some(c => c.type === "ack")).toBe(false);
    d.store.getState().replay(); await flush(); d.deliver(); await flush();
    expect(d.commands.some(c => c.type === "ack")).toBe(true);
  });

  it("ACKs an asynchronous database capture only after commit and does not apply pending duplicates twice", async () => {
    const d = device("stack-async-commit");
    let commit!: (value: LuminaBoxCaptureResult) => void;
    const receive = vi.fn(() => new Promise<LuminaBoxCaptureResult>(resolve => { commit = resolve; }));
    d.store.getState().connect(receive); await flush(); d.pong(); d.deliver(); await flush();
    expect(receive).toHaveBeenCalledTimes(1);
    expect(d.store.getState().receivedCount).toBe(0);
    expect(d.commands.some(c => c.type === "ack")).toBe(false);
    d.deliver(); await flush();
    expect(receive).toHaveBeenCalledTimes(1);
    commit("applied"); await flush();
    expect(d.store.getState().receivedCount).toBe(1);
    expect(d.commands.filter(c => c.type === "ack")).toHaveLength(1);
    d.deliver(); await flush();
    expect(receive).toHaveBeenCalledTimes(1);
    expect(d.commands.filter(c => c.type === "ack")).toHaveLength(2);
  });

  it("keeps reading heartbeat replies while an asynchronous capture is waiting for storage", async () => {
    vi.useFakeTimers();
    const d = device("stack-slow-storage");
    let commit!: (value: LuminaBoxCaptureResult) => void;
    d.store.getState().connect(() => new Promise<LuminaBoxCaptureResult>(resolve => { commit = resolve; }));
    await flush(); d.pong(); d.deliver(); await flush();
    for (let index = 0; index < 9; index++) {
      await vi.advanceTimersByTimeAsync(1000); d.pong(); await flush();
    }
    expect(d.store.getState().status).toBe("connected");
    expect(d.port.close).not.toHaveBeenCalled();
    expect(d.commands.some(c => c.type === "ack")).toBe(false);
    commit("applied"); await flush();
    expect(d.store.getState().receivedCount).toBe(1);
  });

  it("rejects a failed asynchronous save and permits replay after storage recovers", async () => {
    const d = device("stack-storage-retry");
    const receive = vi.fn()
      .mockRejectedValueOnce(new Error("database unavailable"))
      .mockResolvedValue("applied");
    d.store.getState().connect(receive); await flush(); d.pong(); d.deliver(); await flush();
    expect(d.store.getState().status).toBe("connected");
    expect(d.store.getState().issue).toBe("storage_unavailable");
    expect(d.commands.some(c => c.type === "ack")).toBe(false);
    expect(d.commands.some(c => c.type === "reject")).toBe(true);
    d.store.getState().replay(); await flush(); d.deliver(); await flush();
    expect(receive).toHaveBeenCalledTimes(2);
    expect(d.commands.filter(c => c.type === "ack")).toHaveLength(1);
  });

  it("does not ACK a late commit into a replacement capture scope", async () => {
    const d = device("stack-scope-replaced");
    let commit!: (value: LuminaBoxCaptureResult) => void;
    d.store.getState().connect(() => new Promise<LuminaBoxCaptureResult>(resolve => { commit = resolve; }));
    await flush(); d.pong(); d.deliver(); await flush();
    d.store.getState().resetCapture(); await flush(); d.pong(); await flush();
    commit("applied"); await flush();
    expect(d.store.getState().receivedCount).toBe(0);
    expect(d.store.getState().lastMeasurement).toBeNull();
    expect(d.commands.some(c => c.type === "ack")).toBe(false);
  });

  it("does not update or acknowledge a capture that completes after leaving its page", async () => {
    const d = device("stack-page-left");
    let commit!: (value: LuminaBoxCaptureResult) => void;
    d.store.getState().connect(() => new Promise<LuminaBoxCaptureResult>(resolve => { commit = resolve; }));
    await flush(); d.pong(); d.deliver(); await flush();
    await d.store.getState().disconnect();
    commit("applied"); await flush();
    expect(d.store.getState().status).toBe("disconnected");
    expect(d.store.getState().receivedCount).toBe(0);
    expect(d.commands.some(c => c.type === "ack")).toBe(false);
  });

  it("keeps stack sample scopes and restored receipts separate from single-material capture", async () => {
    const stack = device("stack-isolated-receipts");
    stack.store.getState().connect(vi.fn().mockReturnValue("applied"));
    await flush(); stack.pong(); stack.deliver(); await flush();
    const stackCapture = stack.store.getState().captureId;
    await stack.store.getState().disconnect();
    const single = device();
    const singleReceive = vi.fn().mockReturnValue("applied");
    single.store.getState().connect(singleReceive); await flush(); single.pong(); single.deliver(); await flush();
    expect(single.store.getState().captureId).not.toBe(stackCapture);
    expect(singleReceive).toHaveBeenCalledTimes(1);
    const restored = createLuminaBoxSerialStore(() => ({ requestPort: async () => stack.port }), {
      storageNamespace: "stack-isolated-receipts",
    });
    stores.push(restored);
    const restoredReceive = vi.fn().mockReturnValue("applied");
    restored.getState().connect(restoredReceive); await flush();
    expect(restored.getState().captureId).toBe(stackCapture);
    stack.send({ protocol: "lumina-box", version: 3, type: "pong", capture_id: stackCapture,
      boot_id: "box-boot", pending_count: 1, dropped_count: 0 });
    stack.send({ protocol: "lumina-box", version: 3, type: "delivery", capture_id: stackCapture, measurement });
    await flush();
    expect(restoredReceive).not.toHaveBeenCalled();
    expect(stack.commands.filter(c => c.type === "ack")).toHaveLength(2);
  });
});
