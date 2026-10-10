import { afterEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { createLuminaBoxSerialStore } from "../stores/luminaBoxSerialStore";
import type { LuminaBoxSerialPort } from "../api/luminaBoxSerial";

const message = {
  protocol: "lumina-box", version: 1, type: "measurement", measurement_id: "boot-1-1",
  thickness_mm: 0.16, mode: "auto", reflectance_xyz: [0, 21.2, 100], transmittance_xyz: [31.2, 42, 37],
};

function createPort() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const cancelled = vi.fn();
  const port = {
    readable: new ReadableStream<Uint8Array>({ start(value) { controller = value; }, cancel: cancelled }),
    open: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
  };
  return { port, controller, cancelled, send: (value: unknown) => controller.enqueue(new TextEncoder().encode(`${JSON.stringify(value)}\n`)) };
}

const stores: ReturnType<typeof createLuminaBoxSerialStore>[] = [];
const makeStore = (getApi: Parameters<typeof createLuminaBoxSerialStore>[0]) => {
  const store = createLuminaBoxSerialStore(getApi);
  stores.push(store);
  return store;
};

afterEach(async () => {
  await Promise.all(stores.splice(0).map((store) => store.getState().disconnect()));
});

describe("Lumina Box serial connection", () => {
  it("reports native device initialization failure without treating it as a protocol fault", async () => {
    const device = createPort();
    device.port.open.mockRejectedValue(new Error("serial_device_not_functioning"));
    const store = makeStore(() => ({ requestPort: async () => device.port }));
    const receive = vi.fn();
    store.getState().connect(receive);
    await waitFor(() => expect(store.getState().status).toBe("disconnected"));
    expect(store.getState().issue).toBe("device_not_functioning");
    expect(store.getState().lastError).toBe("serial_device_not_functioning");
    expect(store.getState().receivedBytes).toBe(0);
    expect(receive).not.toHaveBeenCalled();
    expect(store.getState().trace).toEqual(expect.arrayContaining([
      expect.objectContaining({ event: "connection_failed", detail: "serial_device_not_functioning" }),
    ]));
  });

  it("opens 115200 baud and delivers each measurement only once", async () => {
    const device = createPort();
    const store = makeStore(() => ({ requestPort: async () => device.port }));
    const receive = vi.fn().mockReturnValue("applied");
    store.getState().connect(receive);
    await waitFor(() => expect(store.getState().status).toBe("connected"));
    expect(device.port.open).toHaveBeenCalledWith({ baudRate: 115200 });
    device.send(message);
    device.send(message);
    device.send({ ...message, measurement_id: "boot-1-2" });
    await waitFor(() => expect(store.getState().receivedCount).toBe(2));
    expect(receive).toHaveBeenCalledTimes(2);
    await store.getState().disconnect();
    expect(device.cancelled).toHaveBeenCalledTimes(1);
    expect(device.port.readable.locked).toBe(false);
    expect(device.port.close).toHaveBeenCalledTimes(1);
  });

  it("rejects invalid packets, reports placement errors, then resumes after valid data", async () => {
    const device = createPort();
    const store = makeStore(() => ({ requestPort: async () => device.port }));
    const receive = vi.fn().mockReturnValueOnce("thickness_missing").mockReturnValue("applied");
    store.getState().connect(receive);
    await waitFor(() => expect(store.getState().status).toBe("connected"));
    device.send({ ...message, reflectance_xyz: [999, 2, 3] });
    await waitFor(() => expect(store.getState().issue).toBe("invalid_measurement"));
    expect(receive).not.toHaveBeenCalled();
    device.send(message);
    await waitFor(() => expect(store.getState().issue).toBe("thickness_missing"));
    expect(store.getState().receivedCount).toBe(0);
    device.send({ ...message, measurement_id: "boot-1-2" });
    await waitFor(() => expect(store.getState().receivedCount).toBe(1));
    expect(store.getState().issue).toBeNull();
  });

  it("cancels queued reads synchronously when material changes", async () => {
    const device = createPort();
    const store = makeStore(() => ({ requestPort: async () => device.port }));
    const receive = vi.fn().mockReturnValue("applied");
    store.getState().connect(receive);
    await waitFor(() => expect(store.getState().status).toBe("connected"));
    device.send(message);
    await store.getState().disconnect("material_changed");
    expect(receive).not.toHaveBeenCalled();
    expect(store.getState().issue).toBe("material_changed");
    expect(store.getState().status).toBe("disconnected");
  });

  it("does not open a port selected after the consumer has left", async () => {
    const device = createPort();
    let select!: (port: LuminaBoxSerialPort) => void;
    const pending = new Promise<LuminaBoxSerialPort>((resolve) => { select = resolve; });
    const store = makeStore(() => ({ requestPort: () => pending }));
    store.getState().connect(vi.fn());
    const stopped = store.getState().disconnect();
    select(device.port);
    await stopped;
    expect(device.port.open).not.toHaveBeenCalled();
    expect(store.getState().status).toBe("disconnected");
  });

  it("closes a port that finishes opening after disconnect", async () => {
    const device = createPort();
    let opened!: () => void;
    device.port.open.mockReturnValue(new Promise<void>((resolve) => { opened = resolve; }));
    const store = makeStore(() => ({ requestPort: async () => device.port }));
    store.getState().connect(vi.fn());
    await waitFor(() => expect(device.port.open).toHaveBeenCalled());
    const stopped = store.getState().disconnect();
    opened();
    await stopped;
    expect(device.port.close).toHaveBeenCalledTimes(1);
    expect(device.port.readable.locked).toBe(false);
  });

  it.each(["end", "error"] as const)("releases resources on device %s", async (kind) => {
    const device = createPort();
    const store = makeStore(() => ({ requestPort: async () => device.port }));
    store.getState().connect(vi.fn());
    await waitFor(() => expect(store.getState().status).toBe("connected"));
    if (kind === "end") device.controller.close();
    else device.controller.error(new Error("device removed"));
    await waitFor(() => expect(store.getState().status).toBe("disconnected"));
    expect(store.getState().issue).toBe("connection_lost");
    expect(device.port.readable.locked).toBe(false);
    expect(device.port.close).toHaveBeenCalledTimes(1);
  });

  it("handles unsupported browsers, cancelled selection and denied/busy ports", async () => {
    const unsupported = makeStore(() => null);
    unsupported.getState().connect(vi.fn());
    expect(unsupported.getState().issue).toBe("unsupported");
    for (const [name, issue] of [["NotFoundError", null], ["SecurityError", "unsupported"], ["NotSupportedError", "unsupported"], ["NetworkError", "connection_failed"]] as const) {
      const error = new Error("unavailable");
      error.name = name;
      const store = makeStore(() => ({ requestPort: vi.fn().mockRejectedValue(error) }));
      store.getState().connect(vi.fn());
      await waitFor(() => expect(store.getState().status).toBe("disconnected"));
      expect(store.getState().issue).toBe(issue);
    }
  });

  it("prevents competing connects and creates fresh reader state when reconnecting", async () => {
    const devices = [createPort(), createPort()];
    const requestPort = vi.fn().mockResolvedValueOnce(devices[0].port).mockResolvedValueOnce(devices[1].port);
    const store = makeStore(() => ({ requestPort }));
    const receive = vi.fn().mockReturnValue("applied");
    store.getState().connect(receive);
    store.getState().connect(receive);
    await waitFor(() => expect(store.getState().status).toBe("connected"));
    devices[0].controller.enqueue(new TextEncoder().encode('{"protocol":'));
    await store.getState().disconnect();
    store.getState().connect(receive);
    await waitFor(() => expect(store.getState().status).toBe("connected"));
    devices[1].send(message);
    await waitFor(() => expect(receive).toHaveBeenCalledTimes(1));
    expect(requestPort).toHaveBeenCalledTimes(2);
  });
});
