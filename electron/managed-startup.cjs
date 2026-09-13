"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

const ERROR_CODES = new Set([
  "app_already_running", "startup_port_in_use", "startup_backend_spawn_failed",
  "startup_backend_timeout", "startup_backend_exited", "startup_frontend_failed", "startup_failed",
]);

function directory(name) {
  try { fs.mkdirSync(name); } catch (error) { if (error.code !== "EEXIST") throw error; }
  const stat = fs.lstatSync(name);
  if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error("startup_status_unavailable");
}

/** Report one launcher-owned startup without exposing credentials. 仅报告本次托管启动，不含凭证。 */
function createManagedStartup(env, onWriteError = () => {}) {
  if (!env.LUMINA_MANAGED_USER_DATA || !env.LUMINA_MANAGED_LAUNCH_ID) return null;
  const root = env.LUMINA_MANAGED_USER_DATA;
  const key = env.LUMINA_MANAGED_RUNTIME_KEY;
  const id = env.LUMINA_MANAGED_LAUNCH_ID;
  if (!path.isAbsolute(root) || !/^[a-f0-9]{32}$/.test(key || "") ||
      !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(id)) {
    throw new Error("startup_context_invalid");
  }
  const directories = [root, path.join(root, "logs"), path.join(root, "logs", key), path.join(root, "logs", key, `launch-${id}`)];
  const statusPath = path.join(directories.at(-1), "status.json");
  let state = "starting";
  let backend = null;
  let healthy = false;
  let loaded = false;
  let shown = false;
  let window = null;

  function write(errorCode) {
    let temporary;
    try {
      for (const item of directories) directory(item);
      temporary = path.join(directories.at(-1), `${randomUUID()}.tmp`);
      fs.writeFileSync(temporary, JSON.stringify({ protocol: 1, launchId: id, runtimeKey: key, pid: process.pid, state,
        ...(errorCode ? { errorCode } : {}) }), { flag: "wx", mode: 0o600 });
      fs.renameSync(temporary, statusPath);
    } finally {
      if (temporary && fs.existsSync(temporary)) fs.unlinkSync(temporary);
    }
  }
  // Failure to create the initial handshake is a startup boundary error.
  try { write(); } catch { throw new Error("startup_status_unavailable"); }

  function publish(next, errorCode) {
    if (state !== "starting") return;
    state = next;
    try { write(errorCode); } catch (error) {
      state = "failed";
      onWriteError(error);
    }
  }
  function fail(code) { publish("failed", ERROR_CODES.has(code) ? code : "startup_failed"); }
  function alive() { return backend && Number.isInteger(backend.pid) && backend.pid > 0 && backend.exitCode === null && backend.signalCode === null && !backend.killed; }
  function maybeReady() {
    if (backend && !alive()) { fail("startup_backend_exited"); return; }
    if (healthy && loaded && shown && alive() && window && !window.isDestroyed() && window.isVisible()) publish("ready");
  }
  return {
    fail,
    watchBackend(proc) {
      backend = proc;
      proc.once("exit", () => fail("startup_backend_exited"));
      proc.on("error", () => fail("startup_backend_exited"));
      maybeReady();
    },
    backendHealthy() { healthy = true; maybeReady(); },
    watchWindow(value) {
      window = value;
      value.once("show", () => { shown = true; maybeReady(); });
      value.once("closed", () => fail("startup_frontend_failed"));
      value.webContents.once("did-finish-load", () => { loaded = true; maybeReady(); });
      value.webContents.on("did-fail-load", (_event, _code, _description, _url, isMainFrame) => {
        if (isMainFrame) fail("startup_frontend_failed");
      });
      value.webContents.on("did-frame-navigate", (_event, _url, status, _text, isMainFrame) => {
        if (isMainFrame && status >= 400) fail("startup_frontend_failed");
      });
      value.webContents.once("render-process-gone", () => fail("startup_frontend_failed"));
    },
  };
}

module.exports = { createManagedStartup };
