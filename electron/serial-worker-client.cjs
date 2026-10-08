"use strict";

const MAX_SERIAL_BYTES = 64 * 1024;
const MAX_PENDING_SERIAL_OPERATIONS = 8;

/** Own one utility process until its exit confirms the OS handle is released.
 * 持有独立串口进程，直到退出确认操作系统句柄已释放。 */
class SerialWorkerClient {
  constructor({ child, onData = () => {}, onExit = () => {}, operationMs = 2000 }) {
    this.child = child;
    this.operationMs = operationMs;
    this.pending = new Map();
    this.nextRequestId = 0;
    this.stopping = false;
    this.exited = false;
    this.exitError = null;
    this.exitPromise = new Promise((resolve) => { this.resolveExit = resolve; });
    this.onSpawn = () => { if (this.stopping) this.child.kill(); };
    this.onMessage = (message) => {
      if (!message || this.stopping || this.exited) return;
      if (message.type === "data") {
        if (!(message.data instanceof Uint8Array) || message.data.byteLength > MAX_SERIAL_BYTES) {
          void this.terminate("serial_data_overflow");
          return;
        }
        if (message.data.byteLength) onData(new Uint8Array(message.data));
      } else if (message.type === "error" || message.type === "closed") {
        void this.terminate(message.type === "error" ? message.error : "serial_worker_exited");
      } else {
        const request = this.pending.get(message.requestId);
        if (!request) return;
        clearTimeout(request.timer);
        this.pending.delete(message.requestId);
        if (message.ok === true) request.resolve(message.value);
        else request.reject(new Error(message.error || "serial_worker_failed"));
      }
    };
    this.onError = () => { void this.terminate("serial_worker_failed"); };
    this.onChildExit = () => {
      this.exited = true;
      this.child.removeListener("spawn", this.onSpawn);
      this.child.removeListener("message", this.onMessage);
      this.child.removeListener("error", this.onError);
      this.child.removeListener("exit", this.onChildExit);
      for (const request of this.pending.values()) {
        clearTimeout(request.timer);
        request.reject(new Error(this.exitError || "serial_worker_exited"));
      }
      this.pending.clear();
      onExit(this.exitError);
      this.resolveExit();
    };
    child.on("spawn", this.onSpawn);
    child.on("message", this.onMessage);
    child.on("error", this.onError);
    child.once("exit", this.onChildExit);
  }

  request(command, payload = {}) {
    if (this.stopping || this.exited) return Promise.reject(new Error(this.exitError || "serial_worker_exited"));
    if (this.pending.size >= MAX_PENDING_SERIAL_OPERATIONS) return Promise.reject(new Error("serial_queue_full"));
    return new Promise((resolve, reject) => {
      const requestId = ++this.nextRequestId;
      const timer = setTimeout(() => { void this.terminate("serial_operation_timeout"); }, this.operationMs);
      this.pending.set(requestId, { resolve, reject, timer });
      try { this.child.postMessage({ requestId, command, ...payload }); }
      catch { void this.terminate("serial_worker_failed"); }
    });
  }

  async terminate(error = null) {
    if (!this.stopping && !this.exited) {
      this.stopping = true;
      this.exitError = error;
      this.child.kill();
    }
    await this.exitPromise;
  }
}

module.exports = { SerialWorkerClient, MAX_SERIAL_BYTES, MAX_PENDING_SERIAL_OPERATIONS };
