"use strict";

const { randomUUID } = require("node:crypto");
const { SerialWorkerClient, MAX_SERIAL_BYTES } = require("./serial-worker-client.cjs");

const EVENT_CHANNEL = "native-serial-event";
const resultError = (error) => ({ status: "error", error });
const knownErrors = new Set([
  "serial_operation_timeout", "serial_worker_exited", "serial_worker_failed", "serial_queue_full",
  "serial_open_failed", "serial_write_failed", "serial_close_failed", "serial_list_failed", "serial_data_overflow",
  "serial_device_not_functioning",
]);
const errorCode = (error, fallback) => knownErrors.has(error?.message) ? error.message : fallback;

/** Keep native port grants and process ownership confined to the trusted main frame.
 * 将原生串口授权与进程所有权限定在可信主页面内。 */
function createNativeSerialBridge({ isTrustedIpcSender, pickPort, spawnWorker, operationMs = 2000 }) {
  let grant = null;
  let selecting = null;
  let detachOwner = () => {};
  const clients = new Set();

  function validContext(event) {
    return isTrustedIpcSender(event) && grant?.owner === event.sender && grant.frame === event.senderFrame
      && grant.url === event.senderFrame.url;
  }
  function getGrant(event, connectionId) {
    if (!isTrustedIpcSender(event)) return { error: "untrusted_sender" };
    if (!validContext(event) || typeof connectionId !== "string" || grant.id !== connectionId) {
      return { error: "invalid_connection" };
    }
    return { entry: grant };
  }
  function emit(entry, event) {
    if (grant !== entry || !validContext({ sender: entry.owner, senderFrame: entry.frame })) return;
    try { entry.owner.send(EVENT_CHANNEL, { connectionId: entry.id, ...event }); } catch { /* Renderer is closing. */ }
  }
  function spawn(entry = null) {
    const client = new SerialWorkerClient({
      child: spawnWorker(), operationMs,
      onData: (data) => { if (entry) emit(entry, { type: "data", data }); },
      onExit: (error) => {
        clients.delete(client);
        if (entry?.worker === client) {
          entry.worker = null;
          if (error) emit(entry, { type: "error", error });
          emit(entry, { type: "closed" });
        }
      },
    });
    clients.add(client);
    return client;
  }
  async function dispose() {
    grant = null;
    selecting?.abort();
    detachOwner();
    detachOwner = () => {};
    await Promise.all([...clients].map((client) => client.terminate()));
  }
  function watchOwner(owner) {
    detachOwner();
    const revoke = () => { void dispose(); };
    const navigation = (_event, _url, _inPlace, isMainFrame) => { if (isMainFrame !== false) revoke(); };
    owner.on("did-start-navigation", navigation);
    owner.on("destroyed", revoke);
    owner.on("render-process-gone", revoke);
    detachOwner = () => {
      owner.removeListener("did-start-navigation", navigation);
      owner.removeListener("destroyed", revoke);
      owner.removeListener("render-process-gone", revoke);
    };
  }
  async function requestPort(event) {
    if (!isTrustedIpcSender(event)) return resultError("untrusted_sender");
    if (selecting || clients.size) return resultError("connection_busy");
    const controller = new AbortController();
    selecting = controller;
    const frame = event.senderFrame;
    const url = frame.url;
    watchOwner(event.sender);
    let listing;
    try {
      listing = spawn();
      const ports = await listing.request("list");
      await listing.terminate();
      if (controller.signal.aborted || !isTrustedIpcSender(event) || event.senderFrame !== frame || frame.url !== url) {
        return { status: "cancelled" };
      }
      const selectedPath = await pickPort(event, ports, controller.signal);
      if (!selectedPath || controller.signal.aborted || !isTrustedIpcSender(event)
        || event.senderFrame !== frame || frame.url !== url) return { status: "cancelled" };
      if (!ports.some((port) => port.path === selectedPath)) return resultError("invalid_connection");
      const id = randomUUID();
      grant = { id, path: selectedPath, owner: event.sender, frame, url, worker: null };
      return { status: "selected", connectionId: id };
    } catch (error) {
      await listing?.terminate(errorCode(error, "serial_list_failed"));
      return resultError(errorCode(error, "serial_list_failed"));
    } finally {
      if (selecting === controller) selecting = null;
    }
  }
  async function open(event, connectionId) {
    const { entry, error } = getGrant(event, connectionId);
    if (error) return resultError(error);
    if (entry.worker || selecting || clients.size) return resultError("connection_busy");
    let client;
    try {
      client = spawn(entry);
      entry.worker = client;
      await client.request("open", { path: entry.path });
      return { status: "ok" };
    } catch (failure) {
      await client?.terminate(errorCode(failure, "serial_open_failed"));
      return resultError(errorCode(failure, "serial_open_failed"));
    }
  }
  async function write(event, connectionId, bytes) {
    const { entry, error } = getGrant(event, connectionId);
    if (error) return resultError(error);
    if (!(bytes instanceof Uint8Array) || !bytes.byteLength || bytes.byteLength > MAX_SERIAL_BYTES) return resultError("invalid_bytes");
    const client = entry.worker;
    if (!client) return resultError("invalid_connection");
    try {
      await client.request("write", { bytes: new Uint8Array(bytes) });
      return { status: "ok" };
    } catch (failure) {
      const code = errorCode(failure, "serial_write_failed");
      if (code !== "serial_queue_full") await client.terminate(code);
      return resultError(code);
    }
  }
  async function close(event, connectionId) {
    const { entry, error } = getGrant(event, connectionId);
    if (error) return resultError(error);
    const client = entry.worker;
    if (!client) return { status: "ok" };
    if (client.stopping) { await client.terminate(); return { status: "ok" }; }
    try {
      await client.request("close");
      await client.terminate();
      return { status: "ok" };
    } catch (failure) {
      const code = errorCode(failure, "serial_close_failed");
      await client.terminate(code);
      // Exit confirms closure even when graceful close timed out.
      return { status: "ok" };
    }
  }
  function install(ipcMain) {
    ipcMain.handle("native-serial-request-port", requestPort);
    ipcMain.handle("native-serial-open", open);
    ipcMain.handle("native-serial-write", write);
    ipcMain.handle("native-serial-close", close);
  }
  return { install, dispose, requestPort, open, write, close };
}

module.exports = { createNativeSerialBridge, EVENT_CHANNEL };
