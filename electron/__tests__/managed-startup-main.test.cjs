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

for (const platform of ["win32", "darwin"]) {
  test(`packaged ${platform} starts with the public cloud material library`, async t => {
    const state = await fixture(t, "healthy", platform);
    const env = state.children[0].spawnOptions.env;
    assert.equal(env.LUMINA_MATERIAL_REGISTRY_URL, "https://materials.luminastudio.com.cn/api/material-registry/v1");
    assert.equal(env.LUMINA_MATERIAL_REGISTRY_FALLBACK_URL, "https://dan5.shmx.top/api/material-registry/v1");
    assert.equal(env.LUMINA_MATERIAL_REGISTRY_CHANNELS, "official,community");
    assert.equal(env.LUMINA_MATERIAL_SYNC_STARTUP_REFRESH, "0");
    assert.equal(env.LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S, "0");
    assert.equal(env.LUMINA_MATERIAL_REGISTRY_TOKEN, undefined);
    assert.equal(env.LUMINA_LUT_REGISTRY_TOKEN, undefined);
    assert.equal(env.LUMINA_FEEDBACK_RELAY_TOKEN, undefined);
  });
}

test("packaged cloud defaults preserve explicit endpoint and channel overrides", async t => {
  const custom = {
    LUMINA_MATERIAL_REGISTRY_URL: "https://custom.example/registry",
    LUMINA_MATERIAL_REGISTRY_CHANNELS: "private",
    LUMINA_LUT_REGISTRY_URL: "https://luts.example/registry",
  };
  const state = await fixture(t, "healthy", "win32", custom);
  for (const [key, value] of Object.entries(custom)) assert.equal(state.children[0].spawnOptions.env[key], value);
  assert.equal(state.children[0].spawnOptions.env.LUMINA_MATERIAL_REGISTRY_FALLBACK_URL, undefined);
});

for (const value of ["", "https://backup.example/registry"]) {
  test(`cloud fallback preserves explicit override ${JSON.stringify(value)}`, async t => {
    const state = await fixture(t, "healthy", "darwin", { LUMINA_MATERIAL_REGISTRY_FALLBACK_URL: value });
    assert.equal(state.children[0].spawnOptions.env.LUMINA_MATERIAL_REGISTRY_FALLBACK_URL, value);
  });
}

test("an explicit empty cloud endpoint remains disabled", async t => {
  const state = await fixture(t, "healthy", "win32", { LUMINA_MATERIAL_REGISTRY_URL: "" });
  assert.equal(state.children[0].spawnOptions.env.LUMINA_MATERIAL_REGISTRY_URL, "");
  assert.equal(state.children[0].spawnOptions.env.LUMINA_MATERIAL_REGISTRY_FALLBACK_URL, undefined);
});

for (const value of ["", "https://custom.example/feedback"]) {
  test(`feedback default preserves explicit endpoint ${JSON.stringify(value)}`, async t => {
    const state = await fixture(t, "healthy", "win32", { LUMINA_FEEDBACK_RELAY_URL: value });
    assert.equal(state.children[0].spawnOptions.env.LUMINA_FEEDBACK_RELAY_URL, value);
  });
}

test("official cloud defaults preserve explicit sync and channel preferences", async t => {
  const custom = {
    LUMINA_MATERIAL_REGISTRY_CHANNELS: "official",
    LUMINA_MATERIAL_SYNC_STARTUP_REFRESH: "1",
    LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S: "3600",
  };
  const state = await fixture(t, "healthy", "darwin", custom);
  for (const [key, value] of Object.entries(custom)) assert.equal(state.children[0].spawnOptions.env[key], value);
});

test("source development mode does not enable a remote material service", () => {
  const source = fs.readFileSync(mainPath, "utf8");
  const start = source.indexOf("function backendRuntimeEnv()");
  const end = source.indexOf("\n// ═", start);
  assert.ok(start >= 0 && end > start);
  const env = vm.runInNewContext(`(${source.slice(start, end)})()`, {
    path, app: { getPath: () => "/development/data" },
    workshopSessionToken: "test-session", managed: null, isDev: true,
    process: { env: {} }, fs: { existsSync: () => false },
    MATERIALS_SEED_RESOURCE: "/missing/materials.zip", WORKSHOP_SEED_RESOURCE_DIR: "/missing/workshop",
    backendEndpoint: { port: 8001, instanceId: "test-instance" },
  });
  assert.equal(env.LUMINA_MATERIAL_REGISTRY_URL, undefined);
  assert.equal(env.LUMINA_MATERIAL_REGISTRY_FALLBACK_URL, undefined);
  assert.equal(env.LUMINA_MATERIAL_REGISTRY_CHANNELS, undefined);
  assert.equal(env.LUMINA_MATERIAL_SYNC_STARTUP_REFRESH, undefined);
  assert.equal(env.LUMINA_FEEDBACK_RELAY_URL, undefined);
});

async function until(check) {
  const deadline = Date.now() + 2000;
  while (!check()) {
    assert.ok(Date.now() < deadline, "main startup must reach the expected boundary");
    await new Promise(resolve => setImmediate(resolve));
  }
}

async function fixture(t, mode = "healthy", platform = "win32", environment = {}) {
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
    loadURL(url) { this.loadedUrl = url; return Promise.resolve(); }
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
    "./backend-endpoint.cjs": {
      ...(fs.existsSync(path.join(__dirname, "../backend-endpoint.cjs")) ? nativeRequire("./backend-endpoint.cjs") : {}),
      selectBackendEndpoint: async () => {
        if (mode === "port-busy") throw new Error("port_in_use");
        return { port: 8001, origin: "http://127.0.0.1:8001", healthUrl: "http://127.0.0.1:8001/api/health", instanceId: "fixture-instance" };
      },
    },
    electron,
    child_process: {
      spawn(command, args, options) {
        const child = new EventEmitter();
        child.spawnOptions = options;
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
      env: { LUMINA_MANAGED_USER_DATA: root, LUMINA_MANAGED_RUNTIME_KEY: KEY, LUMINA_MANAGED_LAUNCH_ID: ID, ...environment } },
  }, { filename: mainPath });
  await until(() => healthCallback || app.quitted);
  return {
    root, windows, children, commands, requests, app, read, dialogs, signals, errorBoxes,
    healthy() { respondHealthy(healthCallback); },
    expireHealth() { timers.find(timer => timer.delay >= 30000).callback(); },
    passOldDeadline() { for (const timer of timers.filter(timer => timer.delay >= 30000 && timer.delay <= 45000)) timer.callback(); },
    healthBudget: () => timers.find(timer => timer.delay >= 30000).delay,
    mainWindow: () => windows.find(window => window.options.title === "Lumina Studio 2"),
  };
}

function respondHealthy(callback, instanceId = "fixture-instance") {
  const response = new EventEmitter();
  Object.assign(response, { statusCode: 200, headers: { "content-type": "application/json" }, resume() {} });
  callback(response);
  response.emit("data", Buffer.from(JSON.stringify({ status: "ok", service: "lumina-studio", desktop_instance_id: instanceId })));
  response.emit("end");
}

test("main passes selected endpoint and private identity to backend and frontend", async t => {
  const f = await fixture(t);
  assert.equal(f.children[0].spawnOptions.env.LUMINA_API_PORT, "8001");
  assert.equal(f.children[0].spawnOptions.env.LUMINA_DESKTOP_INSTANCE_ID, "fixture-instance");
  assert.equal(f.children[0].spawnOptions.env.LUMINA_SERVE_FRONTEND_DIST, "1");
  assert.ok(f.children[0].spawnOptions.env.LUMINA_CLEAR_CACHE_ALLOWED_LOCAL_PORTS?.split(",").includes("8001"));
  f.healthy(); await until(() => f.mainWindow());
  assert.equal(f.mainWindow().loadedUrl, "http://127.0.0.1:8001/");
});

test("main rejects another launch identity even with HTTP 200", async t => {
  const f = await fixture(t);
  respondHealthy(f.requests[0].respond, "old-instance");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.mainWindow(), undefined);
});

test("selected port enables local material mutations while preserving configured local ports", async t => {
  const f = await fixture(t, "healthy", "win32", {
    LUMINA_MATERIAL_LIBRARY_ALLOWED_LOCAL_PORTS: "9100,9101",
    LUMINA_CLEAR_CACHE_ALLOWED_LOCAL_PORTS: "9200",
  });
  const env = f.children[0].spawnOptions.env;
  assert.equal(env.LUMINA_MATERIAL_LIBRARY_ALLOWED_LOCAL_PORTS, "9100,9101,8001");
  assert.equal(env.LUMINA_CLEAR_CACHE_ALLOWED_LOCAL_PORTS, "9200,8001");
});

test("unmanaged package serves the same selected origin without killing port owners", async t => {
  const f = await fixture(t, "healthy", "win32", { LUMINA_MANAGED_USER_DATA: "" });
  assert.equal(f.commands.some(command => command.includes("netstat") || command.includes("lsof")), false);
  assert.equal(f.children[0].spawnOptions.env.LUMINA_SERVE_FRONTEND_DIST, "1");
  f.healthy(); await until(() => f.mainWindow());
  assert.equal(f.mainWindow().loadedUrl, "http://127.0.0.1:8001/");
});

test("actual Electron main confirms the owned backend and loaded visible main window", async t => {
  const f = await fixture(t);
  assert.equal(f.read()?.state, "starting", "main must consume the startup reporter");
  f.healthy(); await until(() => f.mainWindow());
  const win = f.mainWindow();
  win.emit("ready-to-show");
  assert.equal(f.read().state, "starting", "showing before load is not success");
  win.webContents.emit("did-finish-load");
  assert.equal(f.read().state, "ready");
  const mainLogPath = path.join(f.root, "logs", KEY, "lumina-electron.log");
  // Readiness events do not await createWriteStream's asynchronous open/write.
  await until(() => fs.existsSync(mainLogPath) && fs.statSync(mainLogPath).size > 0);
  assert.ok(fs.existsSync(mainLogPath), "managed main log shares the version log tree");
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
  respondHealthy(second.respond);
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
