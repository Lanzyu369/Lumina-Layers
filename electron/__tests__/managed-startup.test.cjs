"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { EventEmitter } = require("node:events");
const helper = path.join(__dirname, "../managed-startup.cjs");
const { createManagedStartup } = fs.existsSync(helper) ? require(helper) : {};
const KEY = "a".repeat(32);
const ID = "0c33c110-23dd-46b0-bcfe-98964b13c870";

function fixture(t) {
  assert.equal(typeof createManagedStartup, "function", "managed startup reporter is implemented");
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-startup-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const env = { LUMINA_MANAGED_USER_DATA: root, LUMINA_MANAGED_RUNTIME_KEY: KEY, LUMINA_MANAGED_LAUNCH_ID: ID };
  const reporter = createManagedStartup(env);
  const status = path.join(root, "logs", KEY, `launch-${ID}`, "status.json");
  const read = () => JSON.parse(fs.readFileSync(status, "utf8"));
  const backend = new EventEmitter();
  Object.assign(backend, { pid: 321, exitCode: null, signalCode: null, killed: false });
  const window = new EventEmitter();
  window.webContents = new EventEmitter();
  window.isDestroyed = () => false;
  window.isVisible = () => true;
  reporter.watchBackend(backend);
  reporter.watchWindow(window);
  return { root, env, reporter, backend, window, status, read };
}

test("managed startup writes an attempt-bound starting record and no temporary leftovers", t => {
  const f = fixture(t);
  assert.deepEqual(f.read(), { protocol: 1, launchId: ID, runtimeKey: KEY, pid: process.pid, state: "starting" });
  assert.deepEqual(fs.readdirSync(path.dirname(f.status)), ["status.json"]);
  for (const env of [{}, { ...f.env, LUMINA_MANAGED_LAUNCH_ID: undefined }]) {
    assert.equal(createManagedStartup(env), null, "ordinary desktop and legacy launcher are untouched");
  }
  for (const env of [
    { ...f.env, LUMINA_MANAGED_USER_DATA: "relative" },
    { ...f.env, LUMINA_MANAGED_RUNTIME_KEY: "../escape" },
    { ...f.env, LUMINA_MANAGED_LAUNCH_ID: "../../escape" },
  ]) assert.throws(() => createManagedStartup(env), /startup_context_invalid/);
});

for (const order of ["shown-first", "loaded-first"]) {
  test(`ready requires a healthy owned backend, main-frame load and visible window (${order})`, t => {
    const f = fixture(t);
    const loaded = () => f.window.webContents.emit("did-finish-load");
    const shown = () => f.window.emit("show");
    const first = order === "shown-first" ? shown : loaded;
    const second = order === "shown-first" ? loaded : shown;
    first();
    f.reporter.backendHealthy();
    assert.equal(f.read().state, "starting", "both load and show are required");
    second();
    assert.equal(f.read().state, "ready");
  });
}

for (const failure of ["http", "main-load", "renderer", "backend-exit", "backend-error"]) {
  test(`${failure} before readiness cannot be overwritten by later load/show events`, t => {
    const f = fixture(t);
    if (failure === "http") f.window.webContents.emit("did-frame-navigate", {}, "http://127.0.0.1:8000/", 500, "Server error", true);
    if (failure === "main-load") f.window.webContents.emit("did-fail-load", {}, -2, "failed", "http://127.0.0.1:8000/", true);
    if (failure === "renderer") f.window.webContents.emit("render-process-gone", {}, { reason: "crashed" });
    if (failure === "backend-exit") { f.backend.exitCode = 1; f.backend.emit("exit", 1, null); }
    if (failure === "backend-error") f.backend.emit("error", new Error("owned child failed"));
    f.reporter.backendHealthy();
    f.window.webContents.emit("did-finish-load"); f.window.emit("show");
    assert.equal(f.read().state, "failed");
    assert.equal(f.read().errorCode, failure.startsWith("backend") ? "startup_backend_exited" : "startup_frontend_failed");
  });
}

test("subframe failures do not misreport the healthy main window", t => {
  const f = fixture(t);
  f.window.webContents.emit("did-fail-load", {}, -2, "failed", "lumina-workshop://runtime/", false);
  f.window.webContents.emit("did-frame-navigate", {}, "lumina-workshop://runtime/", 500, "failed", false);
  f.reporter.backendHealthy(); f.window.emit("show");
  assert.equal(f.read().state, "starting");
  f.window.webContents.emit("did-finish-load");
  assert.equal(f.read().state, "ready");
});

test("a backend already exited at observation cannot become ready", t => {
  const f = fixture(t);
  f.backend.exitCode = 0;
  f.reporter.backendHealthy(); f.window.emit("show"); f.window.webContents.emit("did-finish-load");
  assert.equal(f.read().errorCode, "startup_backend_exited");
});

test("failure codes cannot leak raw errors or credentials into the protocol", t => {
  const f = fixture(t);
  f.reporter.fail("https://example.invalid/?token=private");
  assert.equal(f.read().errorCode, "startup_failed");
  assert.equal(fs.readFileSync(f.status, "utf8").includes("private"), false);
});

test("refuses a symlinked shared log directory without writing outside it", { skip: process.platform === "win32" }, t => {
  const f = fixture(t);
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-outside-"));
  t.after(() => fs.rmSync(outside, { recursive: true, force: true }));
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-linked-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.symlinkSync(outside, path.join(root, "logs"), "dir");
  assert.throws(() => createManagedStartup({ ...f.env, LUMINA_MANAGED_USER_DATA: root }), /startup_status_unavailable/);
  assert.deepEqual(fs.readdirSync(outside), []);
});
