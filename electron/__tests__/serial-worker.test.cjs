const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { installSerialWorker } = require("../serial-worker.cjs");
const { MAX_SERIAL_BYTES } = require("../serial-worker-client.cjs");
const flush = async () => { for (let index = 0; index < 30; index++) await Promise.resolve(); };

describe("isolated SerialPort worker", () => {
  it("opens only the main-selected path with fixed settings, drains writes, chunks reads and closes in order", async () => {
    const messages = [];
    const parent = new EventEmitter();
    parent.postMessage = (message) => messages.push(message);
    const operations = [];
    let instance;
    class Port extends EventEmitter {
      static async list() { return [{ path: "COM25", manufacturer: "Espressif" }]; }
      constructor(options) { super(); this.options = options; this.isOpen = false; instance = this; }
      open(callback) { operations.push("open"); this.isOpen = true; callback(); }
      write(bytes, callback) { operations.push(`write:${bytes[0]}`); callback(); }
      drain(callback) { operations.push("drain"); callback(); }
      close(callback) { operations.push("close"); this.isOpen = false; this.emit("close"); callback(); }
    }
    installSerialWorker(parent, Port);
    parent.emit("message", { data: { requestId: 1, command: "list" } });
    await flush();
    assert.equal(messages[0].value[0].path, "COM25");
    parent.emit("message", { data: { requestId: 2, command: "open", path: "COM25" } });
    await flush();
    assert.deepEqual(instance.options, { path: "COM25", baudRate: 115200, dataBits: 8, stopBits: 1,
      parity: "none", rtscts: false, xon: false, xoff: false, xany: false, autoOpen: false, highWaterMark: MAX_SERIAL_BYTES });
    instance.emit("data", Buffer.alloc(MAX_SERIAL_BYTES + 1, 1));
    assert.deepEqual(messages.filter((message) => message.type === "data").map((message) => message.data.length), [MAX_SERIAL_BYTES, 1]);
    parent.emit("message", { data: { requestId: 3, command: "write", bytes: new Uint8Array([1]) } });
    parent.emit("message", { data: { requestId: 4, command: "write", bytes: new Uint8Array([2]) } });
    parent.emit("message", { data: { requestId: 5, command: "close" } });
    await flush();
    assert.deepEqual(operations, ["open", "write:1", "drain", "write:2", "drain", "close"]);
    assert.equal(messages.some((message) => message.type === "closed"), false);
    assert.equal(messages.find((message) => message.requestId === 5).ok, true);
  });

  it("keeps native open failures bounded to an error code without paths or stacks", async () => {
    const messages = [];
    const parent = new EventEmitter();
    parent.postMessage = (message) => messages.push(message);
    class Port extends EventEmitter {
      open(callback) { callback(new Error("private device path and stack")); }
    }
    installSerialWorker(parent, Port);
    parent.emit("message", { data: { requestId: 1, command: "open", path: "COM25" } });
    await flush();
    assert.deepEqual(messages, [{ requestId: 1, ok: false, error: "serial_open_failed" }]);
  });
});
