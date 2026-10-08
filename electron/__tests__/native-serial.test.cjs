const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const { createNativeSerialBridge } = require("../native-serial.cjs");
const { createSerialPortPicker } = require("../serial-port-picker.cjs");
const { MAX_SERIAL_BYTES, MAX_PENDING_SERIAL_OPERATIONS } = require("../serial-worker-client.cjs");
const flush = async () => { for (let index = 0; index < 20; index++) await Promise.resolve(); };
const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

class FakeChild extends EventEmitter {
  constructor() { super(); this.sent = []; this.kills = 0; this.hold = new Set(); this.holdExit = false; this.exited = false; }
  postMessage(message) {
    this.sent.push(message);
    if (!this.hold.has(message.command)) queueMicrotask(() => this.emit("message", {
      requestId: message.requestId, ok: true,
      value: message.command === "list" ? [{ path: "COM25", manufacturer: "Espressif" }] : undefined,
    }));
  }
  kill() { this.kills++; if (!this.holdExit) queueMicrotask(() => this.exit()); return true; }
  exit() { if (!this.exited) { this.exited = true; this.emit("exit", 0); } }
}

function fixture({ hold = [], holdExit = false, operationMs = 2000 } = {}) {
  const children = [];
  const owner = new EventEmitter();
  owner.mainFrame = { parent: null, url: "http://127.0.0.1:4174/" };
  owner.getURL = () => owner.mainFrame.url;
  owner.isDestroyed = () => false;
  const events = [];
  owner.send = (channel, event) => events.push({ channel, ...event });
  const window = { isDestroyed: () => false, webContents: owner };
  const picker = createSerialPortPicker({ getWindow: () => window, dialog: {},
    frontendUrl: "http://127.0.0.1:4174", packagedIndexUrl: "file:///app/dist/index.html" });
  const event = { sender: owner, senderFrame: owner.mainFrame };
  let picks = 0;
  const bridge = createNativeSerialBridge({
    isTrustedIpcSender: picker.isTrustedIpcSender,
    pickPort: async (_event, ports) => { picks++; return ports[0]?.path ?? null; },
    spawnWorker: () => {
      const child = new FakeChild();
      if (children.length) { child.hold = new Set(hold); child.holdExit = holdExit; }
      children.push(child);
      return child;
    }, operationMs,
  });
  const select = async () => {
    const selected = await bridge.requestPort(event);
    assert.equal(selected.status, "selected");
    return selected.connectionId;
  };
  return { bridge, children, owner, event, events, select, get picks() { return picks; } };
}

describe("native serial desktop bridge", () => {
  it("rejects untrusted child frames before selection, process creation or byte handling", async () => {
    const f = fixture();
    const childEvent = { sender: f.owner, senderFrame: { parent: f.owner.mainFrame, url: f.owner.mainFrame.url } };
    for (const result of [await f.bridge.requestPort(childEvent), await f.bridge.open(childEvent, "COM25"),
      await f.bridge.write(childEvent, "COM25", null), await f.bridge.close(childEvent, "COM25")]) {
      assert.deepEqual(result, { status: "error", error: "untrusted_sender" });
    }
    assert.equal(f.children.length, 0);
    assert.equal(f.picks, 0);
  });

  it("keeps paths in main and reopens the same grant only after the previous worker exits", async () => {
    const f = fixture();
    const id = await f.select();
    assert.match(id, /^[a-f0-9-]{36}$/);
    assert.equal(id.includes("COM25"), false);
    assert.deepEqual(await f.bridge.open(f.event, "COM25"), { status: "error", error: "invalid_connection" });
    assert.deepEqual(await f.bridge.open(f.event, id), { status: "ok" });
    const first = f.children[1];
    assert.equal(first.sent[0].path, "COM25");
    first.emit("message", { type: "data", data: new Uint8Array([1, 2, 3]) });
    assert.deepEqual([...f.events[0].data], [1, 2, 3]);
    assert.deepEqual(await f.bridge.write(f.event, id, new Uint8Array([4])), { status: "ok" });
    assert.deepEqual(await f.bridge.close(f.event, id), { status: "ok" });
    assert.equal(first.exited, true);
    assert.deepEqual(await f.bridge.close(f.event, id), { status: "ok" });
    assert.deepEqual(await f.bridge.open(f.event, id), { status: "ok" });
    assert.equal(f.children[2].sent[0].path, "COM25");
    const count = f.events.length;
    first.emit("message", { type: "data", data: new Uint8Array([99]) });
    assert.equal(f.events.length, count);
    assert.equal(f.picks, 1);
    await f.bridge.dispose();
  });

  it("kills a stalled write and waits for exit before rejecting it or permitting a reopen", async () => {
    const f = fixture({ hold: ["write"], holdExit: true, operationMs: 20 });
    const id = await f.select();
    await f.bridge.open(f.event, id);
    const child = f.children[1];
    let settled = false;
    const writing = f.bridge.write(f.event, id, new Uint8Array([1])).then((value) => { settled = true; return value; });
    await delay(40);
    assert.equal(child.kills, 1);
    assert.equal(settled, false);
    assert.deepEqual(await f.bridge.open(f.event, id), { status: "error", error: "connection_busy" });
    const closing = f.bridge.close(f.event, id);
    child.exit();
    assert.deepEqual(await writing, { status: "error", error: "serial_operation_timeout" });
    assert.deepEqual(await closing, { status: "ok" });
    assert.deepEqual(f.events.map((entry) => entry.type), ["error", "closed"]);
    assert.equal(f.events[0].error, "serial_operation_timeout");
    assert.deepEqual(await f.bridge.open(f.event, id), { status: "ok" });
    f.children[2].holdExit = false;
    await f.bridge.dispose();
  });

  it("bounds a stuck close by killing the worker but retains ownership until exit", async () => {
    const f = fixture({ hold: ["close"], holdExit: true, operationMs: 20 });
    const id = await f.select();
    await f.bridge.open(f.event, id);
    const closing = f.bridge.close(f.event, id);
    await delay(40);
    assert.equal(f.children[1].kills, 1);
    assert.deepEqual(await f.bridge.open(f.event, id), { status: "error", error: "connection_busy" });
    f.children[1].exit();
    assert.deepEqual(await closing, { status: "ok" });
    assert.equal(f.events.find((event) => event.type === "error").error, "serial_operation_timeout");
    assert.deepEqual(await f.bridge.close(f.event, id), { status: "ok" });
    await f.bridge.dispose();
  });

  it("rejects invalid bytes and bounds pending writes without exposing an arbitrary path", async () => {
    const f = fixture({ hold: ["write"] });
    const id = await f.select();
    await f.bridge.open(f.event, id);
    for (const bytes of [[1, 2], new Uint8Array(), new Uint8Array(MAX_SERIAL_BYTES + 1)]) {
      assert.deepEqual(await f.bridge.write(f.event, id, bytes), { status: "error", error: "invalid_bytes" });
    }
    const pending = Array.from({ length: MAX_PENDING_SERIAL_OPERATIONS }, () => f.bridge.write(f.event, id, new Uint8Array([1])));
    assert.deepEqual(await f.bridge.write(f.event, id, new Uint8Array([2])), { status: "error", error: "serial_queue_full" });
    assert.equal(f.children[1].sent.filter((message) => message.command === "write").length, MAX_PENDING_SERIAL_OPERATIONS);
    await f.bridge.dispose();
    await Promise.all(pending);
  });

  it("revokes grants and kills owned workers on main-frame navigation or renderer loss", async () => {
    for (const signal of ["did-start-navigation", "destroyed", "render-process-gone"]) {
      const f = fixture({ holdExit: true });
      const id = await f.select();
      await f.bridge.open(f.event, id);
      f.owner.emit(signal, {}, "http://127.0.0.1:4174/next", false, true);
      assert.equal(f.children[1].kills, 1);
      assert.deepEqual(await f.bridge.open(f.event, id), { status: "error", error: "invalid_connection" });
      assert.deepEqual(await f.bridge.requestPort(f.event), { status: "error", error: "connection_busy" });
      f.children[1].exit();
      await flush();
      assert.equal(f.owner.listenerCount("did-start-navigation"), 0);
    }
  });

  it("rejects oversized worker data and reports failure only after termination", async () => {
    const f = fixture();
    const id = await f.select();
    await f.bridge.open(f.event, id);
    f.children[1].emit("message", { type: "data", data: new Uint8Array(MAX_SERIAL_BYTES + 1) });
    await flush();
    assert.equal(f.children[1].exited, true);
    assert.deepEqual(f.events.map((entry) => entry.type), ["error", "closed"]);
    assert.equal(f.events[0].error, "serial_data_overflow");
    await f.bridge.dispose();
  });

  it("preload forwards fixed channels and hides Electron event objects from subscribers", async () => {
    const renderer = new EventEmitter();
    const calls = [];
    renderer.invoke = async (...args) => { calls.push(args); return { status: "ok" }; };
    renderer.send = () => {};
    let api;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../preload.cjs"), "utf8"), {
      require: () => ({ ipcRenderer: renderer, contextBridge: { exposeInMainWorld: (_name, value) => { api = value; } } }),
    });
    await api.nativeSerial.requestPort();
    await api.nativeSerial.open("id");
    const bytes = new Uint8Array([1]);
    await api.nativeSerial.write("id", bytes);
    await api.nativeSerial.close("id");
    assert.deepEqual(calls, [["native-serial-request-port"], ["native-serial-open", "id"],
      ["native-serial-write", "id", bytes], ["native-serial-close", "id"]]);
    const events = [];
    const unsubscribe = api.nativeSerial.subscribe((...args) => events.push(args));
    const message = { connectionId: "id", type: "closed" };
    renderer.emit("native-serial-event", { sender: "must stay private" }, message);
    assert.deepEqual(events, [[message]]);
    unsubscribe();
    assert.equal(renderer.listenerCount("native-serial-event"), 0);
  });
});
