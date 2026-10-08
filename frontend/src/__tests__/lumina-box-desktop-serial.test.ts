import { afterEach, describe, expect, it, vi } from "vitest";
import { getLuminaBoxSerialApi } from "../api/luminaBoxSerial";
import { LuminaBoxSerialTimeout } from "../api/luminaBoxSerialDeadline";
import type { LuminaBoxNativeSerialApi, LuminaBoxNativeSerialEvent,
  LuminaBoxNativeSerialResult } from "../api/luminaBoxDesktopSerial";

const ok: LuminaBoxNativeSerialResult = { status: "ok" };
const flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

function nativeBridge() {
  const listeners = new Set<(event: LuminaBoxNativeSerialEvent) => void>();
  const bridge = {
    requestPort: vi.fn<LuminaBoxNativeSerialApi["requestPort"]>()
      .mockResolvedValue({ status: "selected", connectionId: "selected-port" }),
    open: vi.fn<LuminaBoxNativeSerialApi["open"]>().mockResolvedValue(ok),
    write: vi.fn<LuminaBoxNativeSerialApi["write"]>().mockResolvedValue(ok),
    close: vi.fn<LuminaBoxNativeSerialApi["close"]>().mockResolvedValue(ok),
    subscribe: vi.fn<LuminaBoxNativeSerialApi["subscribe"]>((listener) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    }),
  } satisfies LuminaBoxNativeSerialApi;
  vi.stubGlobal("electronAPI", { nativeSerial: bridge });
  return { bridge, listeners, emit: (event: LuminaBoxNativeSerialEvent) => {
    listeners.forEach((listener) => listener(event));
  } };
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Lumina Box desktop serial adapter", () => {
  it("prefers the native picker, preserves cancellation/errors, and keeps secure browser fallback", async () => {
    const browser = { requestPort: vi.fn() };
    vi.stubGlobal("navigator", { serial: browser });
    vi.stubGlobal("isSecureContext", false);
    const { bridge } = nativeBridge();
    const desktop = getLuminaBoxSerialApi()!;
    await desktop.requestPort();
    expect(bridge.requestPort).toHaveBeenCalledTimes(1);
    expect(browser.requestPort).not.toHaveBeenCalled();
    bridge.requestPort.mockResolvedValueOnce({ status: "cancelled" });
    await expect(desktop.requestPort()).rejects.toMatchObject({ name: "NotFoundError" });
    bridge.requestPort.mockResolvedValueOnce({ status: "error", error: "serial_picker_failed" });
    await expect(desktop.requestPort()).rejects.toThrow("serial_picker_failed");
    vi.stubGlobal("electronAPI", {});
    expect(getLuminaBoxSerialApi()).toBeNull();
    vi.stubGlobal("isSecureContext", true);
    expect(getLuminaBoxSerialApi()).toBe(browser);
  });

  it("subscribes before open, keeps early bytes unchanged, and awaits the native write result", async () => {
    const d = nativeBridge();
    const wire = new TextEncoder().encode('{"reflectance_xyz":[103.25,120.5,99.125],"transmittance_xyz":[0,1,2]}\n');
    d.bridge.open.mockImplementationOnce(async () => {
      expect(d.listeners.size).toBe(1);
      d.emit({ connectionId: "another-port", type: "data", data: Uint8Array.of(99) });
      d.emit({ connectionId: "selected-port", type: "data", data: wire });
      return ok;
    });
    const port = await getLuminaBoxSerialApi()!.requestPort();
    await port.open({ baudRate: 115200 });
    const reader = port.readable!.getReader();
    const writer = port.writable!.getWriter();
    expect(Array.from((await reader.read()).value!)).toEqual(Array.from(wire));
    const writing = deferred<LuminaBoxNativeSerialResult>();
    d.bridge.write.mockReturnValueOnce(writing.promise);
    const command = new TextEncoder().encode('{"type":"ack","measurement_id":"actual-1"}\n');
    let finished = false;
    const pending = writer.write(command).then(() => { finished = true; });
    await flush();
    expect(d.bridge.write).toHaveBeenCalledWith("selected-port", command);
    expect(finished).toBe(false);
    writing.resolve(ok);
    await pending;
    reader.releaseLock(); writer.releaseLock();
    await port.close();
    expect(d.listeners.size).toBe(0);
  });

  it("propagates a native write timeout to both streams using the existing recovery class", async () => {
    const d = nativeBridge();
    const port = await getLuminaBoxSerialApi()!.requestPort();
    await port.open({ baudRate: 115200 });
    const reader = port.readable!.getReader();
    const writer = port.writable!.getWriter();
    const readFailure = expect(reader.read()).rejects.toBeInstanceOf(LuminaBoxSerialTimeout);
    d.bridge.write.mockResolvedValueOnce({ status: "error", error: "serial_operation_timeout" });
    await expect(writer.write(Uint8Array.of(10))).rejects.toBeInstanceOf(LuminaBoxSerialTimeout);
    await readFailure;
    await writer.abort();
    reader.releaseLock(); writer.releaseLock();
    await port.close();
    expect(d.bridge.close).toHaveBeenCalledTimes(1);
    expect(d.listeners.size).toBe(0);
  });

  it("shares cancel/abort/close cleanup and waits for worker exit before reopening fresh streams", async () => {
    const d = nativeBridge();
    const port = await getLuminaBoxSerialApi()!.requestPort();
    await port.open({ baudRate: 115200 });
    const oldReadable = port.readable;
    const oldListener = [...d.listeners][0];
    const reader = port.readable!.getReader();
    const writer = port.writable!.getWriter();
    const exited = deferred<LuminaBoxNativeSerialResult>();
    d.bridge.close.mockReturnValueOnce(exited.promise);
    const cancelling = reader.cancel();
    const aborting = writer.abort();
    const closing = port.close();
    expect(port.close()).toBe(closing);
    let reopened = false;
    const opening = port.open({ baudRate: 115200 }).then(() => { reopened = true; });
    await flush();
    expect(d.bridge.close).toHaveBeenCalledTimes(1);
    expect(d.bridge.open).toHaveBeenCalledTimes(1);
    expect(reopened).toBe(false);
    expect(d.listeners.size).toBe(0);
    exited.resolve(ok);
    await Promise.all([cancelling, aborting, closing, opening]);
    reader.releaseLock(); writer.releaseLock();
    expect(port.readable).not.toBe(oldReadable);
    expect(d.listeners.size).toBe(1);
    oldListener({ connectionId: "selected-port", type: "error", error: "serial_worker_exited" });
    const freshReader = port.readable!.getReader();
    d.emit({ connectionId: "selected-port", type: "data", data: Uint8Array.of(0, 255) });
    expect((await freshReader.read()).value).toEqual(Uint8Array.of(0, 255));
    freshReader.releaseLock();
    await port.close();
    expect(d.bridge.close).toHaveBeenCalledTimes(2);
  });

  it("cleans failed opens, propagates unplug errors, and surfaces a failed native close", async () => {
    const d = nativeBridge();
    const port = await getLuminaBoxSerialApi()!.requestPort();
    d.bridge.open.mockResolvedValueOnce({ status: "error", error: "serial_open_failed" });
    await expect(port.open({ baudRate: 115200 })).rejects.toThrow("serial_open_failed");
    expect(d.listeners.size).toBe(0);
    expect(d.bridge.close).toHaveBeenCalledTimes(1);
    expect(port.readable).toBeNull();
    await port.open({ baudRate: 115200 });
    const reader = port.readable!.getReader();
    const writer = port.writable!.getWriter();
    const disconnected = expect(reader.read()).rejects.toThrow("serial_worker_exited");
    d.emit({ connectionId: "selected-port", type: "closed" });
    await disconnected;
    await expect(writer.write(Uint8Array.of(1))).rejects.toThrow("serial_worker_exited");
    reader.releaseLock(); writer.releaseLock();
    d.bridge.close.mockResolvedValueOnce({ status: "error", error: "serial_close_failed" });
    await expect(port.close()).rejects.toThrow("serial_close_failed");
    expect(d.listeners.size).toBe(0);
  });
});
