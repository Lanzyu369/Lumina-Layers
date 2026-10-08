"use strict";

const { MAX_SERIAL_BYTES } = require("./serial-worker-client.cjs");

/** Run Node SerialPort operations inside a disposable utility process.
 * 在可终止的独立进程中执行 Node SerialPort 操作。 */
function installSerialWorker(parentPort, SerialPort) {
  let port = null;
  let closing = false;
  let writes = Promise.resolve();
  const send = (message) => parentPort.postMessage(message);
  const callbackOperation = (start) => new Promise((resolve, reject) => {
    start((error) => error ? reject(error) : resolve());
  });
  const failure = (command) => `serial_${command}_failed`;
  const run = async (message) => {
    const { requestId, command } = message;
    try {
      let value;
      if (command === "list") {
        value = (await SerialPort.list()).slice(0, 128).filter((item) =>
          typeof item.path === "string" && item.path.length > 0 && item.path.length <= 512 && !item.path.includes("\0"))
          .map((item) => ({ path: item.path, manufacturer: item.manufacturer, serialNumber: item.serialNumber }));
      } else if (command === "open") {
        if (port || typeof message.path !== "string") throw new Error("invalid_open");
        port = new SerialPort({ path: message.path, baudRate: 115200, dataBits: 8, stopBits: 1,
          parity: "none", rtscts: false, xon: false, xoff: false, xany: false,
          autoOpen: false, highWaterMark: MAX_SERIAL_BYTES });
        port.on("data", (bytes) => {
          for (let offset = 0; offset < bytes.length; offset += MAX_SERIAL_BYTES) {
            send({ type: "data", data: new Uint8Array(bytes.subarray(offset, offset + MAX_SERIAL_BYTES)) });
          }
        });
        port.on("error", () => send({ type: "error", error: "serial_write_failed" }));
        port.on("close", () => { if (!closing) send({ type: "closed" }); });
        await callbackOperation((callback) => port.open(callback));
      } else if (command === "write") {
        if (!port?.isOpen || !(message.bytes instanceof Uint8Array) || !message.bytes.byteLength
          || message.bytes.byteLength > MAX_SERIAL_BYTES) throw new Error("invalid_write");
        await callbackOperation((callback) => port.write(Buffer.from(message.bytes), callback));
        await callbackOperation((callback) => port.drain(callback));
      } else if (command === "close") {
        closing = true;
        if (port?.isOpen) await callbackOperation((callback) => port.close(callback));
      } else throw new Error("invalid_command");
      send({ requestId, ok: true, value });
    } catch {
      send({ requestId, ok: false, error: failure(command) });
    }
  };
  parentPort.on("message", ({ data }) => {
    if (!data || !Number.isSafeInteger(data.requestId) || typeof data.command !== "string") return;
    // Serial writes and close share one queue; reading continues through stream events.
    if (data.command === "write" || data.command === "close") writes = writes.then(() => run(data));
    else void run(data);
  });
}

if (process.parentPort) {
  try {
    const { SerialPort } = require("serialport");
    installSerialWorker(process.parentPort, SerialPort);
    process.parentPort.postMessage({ type: "ready", node: process.version, napi: process.versions.napi,
      platform: process.platform, arch: process.arch });
  } catch {
    process.parentPort.postMessage({ type: "error", error: "serial_worker_failed" });
  }
}

module.exports = { installSerialWorker };
