"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");
const { createRequire } = require("node:module");
const mainPath = path.join(__dirname, "../main.cjs");
const nativeRequire = createRequire(mainPath);
const KEY = "c".repeat(32);
const ID = "4c6637cf-9b83-4e8c-81b2-9dbf9053da80";

async function until(check) {
  const deadline = Date.now() + 2000;
  while (!check()) {
    assert.ok(Date.now() < deadline, "main startup must reach the expected boundary");
    await new Promise(resolve => setImmediate(resolve));
  }
}

async function fixture(t, mode = "healthy", platform = "win32") {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-main-startup-"));
  const windows = [], children = [], commands = [], streams = [], requests = [], timers = [], dialogs = [];
  const signals = [], errorBoxes = [];
  const event = () => ({ defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } });
  const app = new EventEmitter();
  Object.assign(app, {
    isPackaged: true, commandLine: { appendSwitch() {} },
    getPath: () => root, setPath() {}, requestSingleInstanceLock: () => mode !== "second-instance",
    whenReady: () => Promise.resolve(), getVersion: () => "2.0.0", setName() {}, setAboutPanelOptions() {},
    quit() {
      const before = event();
      this.emit("before-quit", before);
      if (before.defaultPrevented) return;
      this.closingForQuit = true;
      for (const window of windows.filter(window => !window.isDestroyed())) window.close();
      this.closingForQuit = false;
      if (windows.some(window => !window.isDestroyed())) return;
      this.emit("will-quit", event());
      this.quitted = true;
    },
  });
  class Window extends EventEmitter {
    constructor(options) {
      super(); this.options = options; this.visible = false;
      this.webContents = new EventEmitter();
      this.webContents.setWindowOpenHandler = () => {};
      windows.push(this);
    }
    loadURL() { return Promise.resolve(); }
    loadFile() { return Promise.resolve(); }
    show() { this.visible = true; this.emit("show"); }
    isVisible() { return this.visible; }
    isDestroyed() { return Boolean(this.destroyed); }
    close() {
      const closing = event();
      this.emit("close", closing);
      if (!closing.defaultPrevented) this.destroy();
    }
    destroy() {
      this.destroyed = true;
      this.emit("closed");
      if (!app.closingForQuit && windows.every(window => window.isDestroyed())) app.emit("window-all-closed");
    }
  }
  const session = new EventEmitter();
  Object.assign(session, { webRequest: { onBeforeRequest() {} }, setPermissionRequestHandler() {}, setPermissionCheckHandler() {} });
  let healthCallback;
  const electron = {
    app, BrowserWindow: Window, Menu: { setApplicationMenu() {} },
    dialog: { showErrorBox(...args) { errorBoxes.push(args); }, showMessageBox: (_window, options) => new Promise((resolve, reject) => dialogs.push({ options, resolve, reject })) },
    ipcMain: { on() {}, handle() {} }, protocol: { registerSchemesAsPrivileged() {}, handle() {} },
    session: { defaultSession: session }, net: {}, webFrameMain: {},
  };
  const modules = {
    electron,
    child_process: {
      spawn() {
        const child = new EventEmitter();
        Object.assign(child, { stdout: new EventEmitter(), stderr: new EventEmitter(), pid: 24680, exitCode: null, signalCode: null, killed: false });
        children.push(child);
        queueMicrotask(() => {
          if (mode === "spawn-error") { child.pid = undefined; child.emit("error", new Error("fixture spawn error")); }
          else child.emit("spawn");
        });
        return child;
      },
      execSync(command) { commands.push(command); },
    },
    http: { get(_url, callback) {
      healthCallback = callback;
      const request = new EventEmitter();
      request.respond = callback;
      request.setTimeout = (_delay, handler) => { request.timeout = handler; };
      request.destroy = () => { request.destroyed = true; };
      requests.push(request);
      return request;
    } },
    "./managed-runtime.cjs": { ...nativeRequire("./managed-runtime.cjs"), assertPortsAvailable: async () => { if (mode === "port-busy") throw new Error("port_in_use:8000:EADDRINUSE"); } },
    fs: { ...fs, createWriteStream(...args) { const stream = fs.createWriteStream(...args); streams.push(stream); return stream; } },
  };
  const statusPath = path.join(root, "logs", KEY, `launch-${ID}`, "status.json");
  const read = () => fs.existsSync(statusPath) ? JSON.parse(fs.readFileSync(statusPath, "utf8")) : null;
  t.after(async () => {
    for (const child of children) { child.exitCode = 0; child.emit("exit", 0, null); }
    app.emit("will-quit", event());
    await new Promise(resolve => setImmediate(resolve));
    await Promise.all(streams.map(stream => new Promise(resolve => stream.end(resolve))));
    fs.rmSync(root, { recursive: true, force: true });
  });
  vm.runInNewContext(fs.readFileSync(mainPath, "utf8"), {
    require: name => modules[name] || nativeRequire(name),
    __dirname: path.dirname(mainPath), console,
    setTimeout(callback, delay) { const handle = setTimeout(callback, delay); timers.push({ callback, delay, handle }); return handle; },
    clearTimeout, URL, Response, Headers,
    process: { platform, resourcesPath: path.join(root, "resources"), pid: process.pid,
      kill(pid, signal) { signals.push({ pid, signal }); },
      env: { LUMINA_MANAGED_USER_DATA: root, LUMINA_MANAGED_RUNTIME_KEY: KEY, LUMINA_MANAGED_LAUNCH_ID: ID } },
  }, { filename: mainPath });
  await until(() => healthCallback || app.quitted);
  return {
    root, windows, children, commands, requests, app, read, dialogs, signals, errorBoxes,
    healthy() { healthCallback({ statusCode: 200, resume() {} }); },
    expireHealth() { timers.find(timer => timer.delay >= 30000).callback(); },
    passOldDeadline() { for (const timer of timers.filter(timer => timer.delay >= 30000 && timer.delay <= 45000)) timer.callback(); },
    healthBudget: () => timers.find(timer => timer.delay >= 30000).delay,
    mainWindow: () => windows.find(window => window.options.title === "Lumina Studio 2"),
  };
}

test("actual Electron main confirms the owned backend and loaded visible main window", async t => {
  const f = await fixture(t);
  assert.equal(f.read()?.state, "starting", "main must consume the startup reporter");
  f.healthy(); await until(() => f.mainWindow());
  const win = f.mainWindow();
  win.emit("ready-to-show");
  assert.equal(f.read().state, "starting", "showing before load is not success");
  win.webContents.emit("did-finish-load");
  assert.equal(f.read().state, "ready");
  assert.ok(fs.existsSync(path.join(f.root, "logs", KEY, "lumina-electron.log")), "managed main log shares the version log tree");
  assert.equal(f.commands.some(command => command.includes("netstat")), false, "managed startup never kills port owners");
});

for (const [mode, errorCode] of [["port-busy", "startup_port_in_use"], ["spawn-error", "startup_backend_spawn_failed"], ["second-instance", "app_already_running"]]) {
  test(`actual main reports ${mode} before quitting`, async t => {
    const f = await fixture(t, mode);
    await until(() => f.app.quitted);
    assert.equal(f.read()?.state, "failed");
    assert.equal(f.read().errorCode, errorCode);
    assert.equal(f.mainWindow(), undefined);
    assert.equal(f.commands.some(command => command.includes("netstat")), false);
  });
}

test("actual main never reports ready for an HTTP error document", async t => {
  const f = await fixture(t);
  f.healthy(); await until(() => f.mainWindow());
  const win = f.mainWindow();
  win.webContents.emit("did-frame-navigate", {}, "http://127.0.0.1:8000/", 500, "Server Error", true);
  win.webContents.emit("did-finish-load"); win.emit("ready-to-show");
  assert.equal(f.read()?.state, "failed");
  assert.equal(f.read().errorCode, "startup_frontend_failed");
});

test("actual main preserves backend-exit failure even if health later answers", async t => {
  const f = await fixture(t);
  const child = f.children[0]; child.exitCode = 1; child.emit("exit", 1, null);
  f.healthy(); await until(() => f.mainWindow() || f.app.quitted);
  assert.equal(f.mainWindow(), undefined, "a dead owned backend must not open a main window");
  assert.equal(f.app.quitted, true, "failed owned startup must quit instead of blocking retries");
  assert.equal(f.read()?.state, "failed");
  assert.equal(f.read().errorCode, "startup_backend_exited");
});

test("health retries close rejected responses and stale timeouts cannot destroy the next request", async t => {
  const f = await fixture(t);
  const first = f.requests[0];
  first.respond({ statusCode: 503, resume() {} });
  assert.equal(first.destroyed, true, "rejecting health must close a potentially endless body");
  await until(() => f.requests.length === 2);
  const second = f.requests[1];
  first.timeout();
  assert.notEqual(second.destroyed, true, "the old request callback cannot destroy the new request");
  second.respond({ statusCode: 200, resume() {} });
  await until(() => f.mainWindow());
  assert.equal(second.destroyed, true, "the successful probe also releases its socket");
});

test("actual main reports the bounded health deadline and closes the pending request", async t => {
  const f = await fixture(t);
  f.expireHealth();
  await until(() => f.app.quitted);
  assert.equal(f.read().errorCode, "startup_backend_timeout");
  assert.equal(f.mainWindow(), undefined);
  assert.equal(f.requests[0].destroyed, true);
  assert.equal(f.errorBoxes.length, 0, "managed failure must not block cleanup on a second native dialog");
});

test("cold initialization can pass the old deadline without claiming readiness early", async t => {
  const f = await fixture(t);
  f.passOldDeadline();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.read().state, 'starting');
  assert.ok(f.healthBudget() <= 180000, 'initialization must remain bounded');
  assert.equal(f.children.length, 1);
  f.healthy(); await until(() => f.mainWindow());
  f.mainWindow().webContents.emit('did-finish-load');
  assert.equal(f.read().state, 'starting');
  f.mainWindow().emit('ready-to-show');
  assert.equal(f.read().state, 'ready');
});

for (const platform of ["win32", "darwin"]) {
for (const trigger of ["app-quit", "window-close"]) {
  test(`actual main keeps its backend when ${platform} ${trigger} is cancelled, then cleans up on confirmation`, async t => {
    const f = await fixture(t, "healthy", platform);
    f.healthy(); await until(() => f.mainWindow());
    const win = f.mainWindow();
    win.emit("ready-to-show");
    const requestQuit = () => trigger === "app-quit" ? f.app.quit() : win.close();
    requestQuit();
    assert.equal(f.dialogs.length, 1);
    assert.equal(f.commands.length, 0, "confirmation must precede backend cleanup");
    assert.equal(f.signals.length, 0, "confirmation must precede process-group cleanup");
    f.dialogs[0].resolve({ response: 0 });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(win.isDestroyed(), false);
    assert.notEqual(f.app.quitted, true);
    assert.equal(f.commands.length, 0, "cancellation must keep the owned backend alive");
    assert.equal(f.signals.length, 0);
    requestQuit();
    assert.equal(f.dialogs.length, 2, "cancelling must allow another exit attempt");
    f.dialogs[1].resolve({ response: 1 });
    await until(() => f.app.quitted);
    assert.equal(win.isDestroyed(), true);
    if (platform === "win32") {
      assert.deepEqual(f.commands, ["taskkill /T /F /PID 24680"], "clean the owned process tree exactly once");
    } else {
      assert.deepEqual(f.signals, [{ pid: -24680, signal: "SIGTERM" }], "clean the owned process group exactly once");
    }
    assert.equal(f.dialogs.length, 2, "confirmed app.quit must not open another dialog");
  });
}
}

test("actual main shares one pending confirmation across app and window exit requests", async t => {
  const f = await fixture(t);
  f.healthy(); await until(() => f.mainWindow());
  f.mainWindow().close();
  f.app.quit();
  f.mainWindow().close();
  assert.equal(f.dialogs.length, 1, "repeated exit gestures must not stack dialogs");
  assert.equal(f.commands.length, 0);
  f.dialogs[0].resolve({ response: 0 });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.mainWindow().isDestroyed(), false);
});

test("actual main treats a failed exit dialog as cancellation and allows retry", async t => {
  const f = await fixture(t);
  f.healthy(); await until(() => f.mainWindow());
  f.app.quit();
  f.dialogs[0].reject(new Error("fixture dialog failed"));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.commands.length, 0);
  assert.equal(f.mainWindow().isDestroyed(), false);
  f.mainWindow().close();
  assert.equal(f.dialogs.length, 2);
  f.dialogs[1].resolve({ response: 0 });
});
