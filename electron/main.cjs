const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  net: electronNet,
  protocol,
  session,
  webFrameMain,
} = require("electron");
const { spawn, execSync } = require("child_process");
const http = require("http");
const nodeNet = require("net");
const fs = require("fs");
const path = require("path");
const {
  createWorkshopSessionToken,
  isAllowedWorkshopDownload,
  isAllowedWorkshopIpcSender,
  isAllowedWorkshopPermission,
  isAllowedWorkshopPopup,
  isAllowedWorkshopRequest,
  isWorkshopFrameProcessIsolated,
  resolveWorkshopRuntimeRequest,
  shouldBlockWorkshopNavigation,
  shouldBlockWorkshopRedirect,
  shouldRetryFrontendLoad,
} = require("./workshop-security.cjs");
const {
  loadWorkshopImageFile,
} = require("./workshop-file-picker.cjs");

// ═══════════════════════════════════════════════════════════
//  Constants
// ═══════════════════════════════════════════════════════════

const BACKEND_PORT = 8000;
const FRONTEND_PORT = 4174;
const BACKEND_HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/api/health`;
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;
const HEALTH_TIMEOUT_MS = 30000;
const PORT_TIMEOUT_MS = 30000;
const POLL_INTERVAL_MS = 500;
const WORKSHOP_SCHEME = "lumina-workshop";
const WORKSHOP_RUNTIME_HEADER_NAMES = [
  "cache-control",
  "content-security-policy",
  "content-type",
  "permissions-policy",
  "referrer-policy",
  "x-content-type-options",
];

const isDev = !app.isPackaged;
const ROOT_DIR = path.join(__dirname, "..");
const IS_WIN = process.platform === "win32";
const IS_MAC = process.platform === "darwin";
const MATERIALS_SEED_RESOURCE = path.join(
  process.resourcesPath || ROOT_DIR,
  "materials",
  "lumina-materials-seed.zip",
);
const WORKSHOP_SEED_RESOURCE_DIR = isDev
  ? path.join(__dirname, "resources", "workshop-seed")
  : path.join(process.resourcesPath, "workshop-seed");
const workshopSessionToken = createWorkshopSessionToken();
let workshopSafeMode = false;

protocol.registerSchemesAsPrivileged([
  {
    scheme: WORKSHOP_SCHEME,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: false,
      corsEnabled: false,
      allowServiceWorkers: false,
      codeCache: false,
    },
  },
]);

// Platform-aware icon paths.
//   - Windows: 仍用仓库根目录的 icon.ico（任务栏 / 安装包用）
//   - macOS:   用 electron/build 下生成的 icns（包内）+ png（运行时窗口 + Dock）
//   - Linux:   复用 mac 的 png
const ICON_PATH = (() => {
  if (IS_WIN) return path.join(ROOT_DIR, "icon.ico");
  return path.join(__dirname, "build", "icon.png");
})();
const ICON_ICNS_PATH = path.join(__dirname, "build", "icon.icns");

// ═══════════════════════════════════════════════════════════
//  Quit dialog i18n
// ═══════════════════════════════════════════════════════════

const QUIT_DIALOG = {
  zh: {
    title: "\u9000\u51FA\u786E\u8BA4",
    message: "\u786E\u5B9A\u8981\u9000\u51FA Lumina Studio \u5417\uFF1F",
    detail: "\u9000\u51FA\u540E\u6240\u6709\u672A\u4FDD\u5B58\u7684\u64CD\u4F5C\u5C06\u4E22\u5931\u3002",
    quit: "\u9000\u51FA",
    cancel: "\u53D6\u6D88",
  },
  en: {
    title: "Quit Confirmation",
    message: "Are you sure you want to quit Lumina Studio?",
    detail: "All unsaved changes will be lost.",
    quit: "Quit",
    cancel: "Cancel",
  },
};

let currentLang = "zh";

// ═══════════════════════════════════════════════════════════
//  Logging
// ═══════════════════════════════════════════════════════════

let logStream = null;

function initLog() {
  const logDir = app.getPath("logs");
  try {
    fs.mkdirSync(logDir, { recursive: true });
  } catch (_) {}
  const logFile = path.join(logDir, "lumina-electron.log");
  logStream = fs.createWriteStream(logFile, { flags: "a" });
}

function log(tag, msg) {
  const ts = new Date().toISOString().slice(11, 19);
  const line = `${ts} [${tag}] ${msg}`;
  if (logStream) {
    logStream.write(line + "\n");
  }
  if (isDev) {
    console.log(line);
  }
}

function logSys(m) { log("SYS", m); }
function logOk(m) { log(" OK", m); }
function logErr(m) { log("ERR", m); }
function logBe(m) { log("  B", m); }
function logFe(m) { log("  F", m); }

// ═══════════════════════════════════════════════════════════
//  Child process management
// ═══════════════════════════════════════════════════════════

const children = [];

function spawnChild(name, cmd, args, cwd, envExtra = {}) {
  return new Promise((resolve, reject) => {
    const logFn = name.includes("Backend") ? logBe : logFe;
    try {
      const proc = spawn(cmd, args, {
        cwd,
        env: { ...process.env, ...envExtra },
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        // mac/linux: detach 让子进程拥有独立进程组，退出时一并 kill 整个组，
        // 避免 vite/uvicorn 的 fork worker 残留占住端口。
        detached: !IS_WIN,
      });

      proc.stdout.on("data", (data) => {
        const lines = data.toString("utf-8").split("\n").filter(Boolean);
        for (const line of lines) {
          logFn(line);
        }
      });

      proc.stderr.on("data", (data) => {
        const lines = data.toString("utf-8").split("\n").filter(Boolean);
        for (const line of lines) {
          logFn(line);
        }
      });

      proc.on("error", (err) => {
        logErr(`${name} spawn error: ${err.message}`);
        reject(err);
      });

      proc.on("exit", (code) => {
        logFn(`${name} exited with code ${code}`);
        const idx = children.indexOf(proc);
        if (idx !== -1) children.splice(idx, 1);
      });

      children.push(proc);
      logOk(`${name} started (pid=${proc.pid})`);
      resolve(proc);
    } catch (err) {
      logErr(`${name} failed to start: ${err.message}`);
      reject(err);
    }
  });
}

function killChild(proc) {
  if (!proc || proc.exitCode !== null) return;
  try {
    if (IS_WIN) {
      execSync(`taskkill /T /F /PID ${proc.pid}`, {
        windowsHide: true,
        stdio: "ignore",
      });
    } else {
      // detached spawn 后 pid === pgid，传负号给 process.kill 杀整个进程组，
      // 这样 vite worker / uvicorn reload 子进程也会跟着退出。
      try {
        process.kill(-proc.pid, "SIGTERM");
      } catch (_) {
        proc.kill("SIGTERM");
      }
    }
  } catch (_) {}
}

function killAllChildren() {
  for (const proc of children) {
    killChild(proc);
  }
  children.length = 0;
}

// ═══════════════════════════════════════════════════════════
//  Port cleanup (port of start_dev.py _kill_listening)
// ═══════════════════════════════════════════════════════════

function killListening(ports) {
  if (IS_WIN) {
    try {
      const out = execSync("netstat -ano", {
        windowsHide: true,
        encoding: "utf-8",
      });
      const portPattern = ports.join("|");
      const re = new RegExp(
        `\\s+TCP\\s+[\\d.]+:(${portPattern})\\s+\\S+\\s+LISTENING\\s+(\\d+)`,
      );
      const killed = new Set();
      for (const line of out.split("\n")) {
        const m = line.match(re);
        if (m) {
          const pid = parseInt(m[2], 10);
          const port = m[1];
          if (killed.has(pid)) continue;
          try {
            execSync(`taskkill /T /F /PID ${pid}`, {
              windowsHide: true,
              stdio: "ignore",
            });
            logSys(`Killed PID ${pid} (port ${port})`);
            killed.add(pid);
          } catch (_) {
            logErr(`Failed to kill PID ${pid} (port ${port})`);
          }
        }
      }
    } catch (err) {
      logErr(`Port cleanup error: ${err.message}`);
    }
    return;
  }

  // macOS / Linux: 用 lsof 拿到 LISTEN 状态的 PID 再 kill。
  // lsof 在没有匹配进程时退出码为 1,这是正常情况而不是错误,要吞掉。
  for (const port of ports) {
    try {
      const out = execSync(
        `lsof -nP -iTCP:${port} -sTCP:LISTEN -t`,
        { encoding: "utf-8" },
      ).trim();
      if (!out) continue;
      const pids = out.split(/\s+/).map((s) => parseInt(s, 10)).filter(Boolean);
      for (const pid of pids) {
        try {
          process.kill(pid, "SIGTERM");
          logSys(`Killed PID ${pid} (port ${port})`);
        } catch (err) {
          // ESRCH = 进程已经不在,忽略;其它错误记一条。
          if (err.code !== "ESRCH") {
            logErr(`Failed to kill PID ${pid} (port ${port}): ${err.message}`);
          }
        }
      }
    } catch (err) {
      // lsof 没匹配进程时 status=1, stdout/stderr 都为空,直接跳过。
      if (err.status === 1 && !err.stderr) continue;
      logErr(`Port ${port} cleanup error: ${err.message}`);
    }
  }
}

// ═══════════════════════════════════════════════════════════
//  Health / port probes
// ═══════════════════════════════════════════════════════════

function waitForHealth(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    function probe() {
      if (Date.now() - start > timeoutMs) {
        reject(new Error(`Health check timeout after ${timeoutMs}ms`));
        return;
      }
      const req = http.get(url, (res) => {
        if (res.statusCode >= 200 && res.statusCode < 400) {
          res.resume();
          resolve();
        } else {
          res.resume();
          setTimeout(probe, POLL_INTERVAL_MS);
        }
      });
      req.on("error", () => {
        setTimeout(probe, POLL_INTERVAL_MS);
      });
      req.setTimeout(3000, () => {
        req.destroy();
        setTimeout(probe, POLL_INTERVAL_MS);
      });
    }
    probe();
  });
}

function waitForPort(port, timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    function probe() {
      if (Date.now() - start > timeoutMs) {
        reject(new Error(`Port ${port} timeout after ${timeoutMs}ms`));
        return;
      }
      const sock = nodeNet.connect(port, "127.0.0.1", () => {
        sock.destroy();
        resolve();
      });
      sock.on("error", () => {
        sock.destroy();
        setTimeout(probe, POLL_INTERVAL_MS);
      });
      sock.setTimeout(2000, () => {
        sock.destroy();
        setTimeout(probe, POLL_INTERVAL_MS);
      });
    }
    probe();
  });
}

// ═══════════════════════════════════════════════════════════
//  Find executables
// ═══════════════════════════════════════════════════════════

function findPython() {
  // Windows: venv 下的可执行文件叫 python.exe;mac/linux 在 bin/python。
  const candidates = IS_WIN
    ? [
        path.join(ROOT_DIR, "venv", "Scripts", "python.exe"),
        path.join(ROOT_DIR, ".venv", "Scripts", "python.exe"),
      ]
    : [
        path.join(ROOT_DIR, ".venv", "bin", "python"),
        path.join(ROOT_DIR, "venv", "bin", "python"),
        path.join(ROOT_DIR, ".venv", "bin", "python3"),
        path.join(ROOT_DIR, "venv", "bin", "python3"),
      ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  // PATH 回退:mac 上系统通常只有 python3,Windows 一般是 python。
  return IS_WIN ? "python" : "python3";
}

function findNode() {
  const lookupCmd = IS_WIN ? "where node" : "which node";
  try {
    const out = execSync(lookupCmd, {
      windowsHide: true,
      encoding: "utf-8",
    });
    const lines = out.trim().split("\n");
    if (lines.length > 0 && lines[0].trim()) return lines[0].trim();
  } catch (_) {}
  return "node";
}

function backendRuntimeEnv() {
  const env = {
    LUMINA_MATERIALS_DIR: path.join(app.getPath("userData"), "materials"),
    LUMINA_WORKSHOP_DATA_DIR: path.join(
      app.getPath("userData"),
      "workshop",
    ),
    LUMINA_WORKSHOP_DESKTOP_TOKEN: workshopSessionToken,
  };
  if (fs.existsSync(MATERIALS_SEED_RESOURCE)) {
    env.LUMINA_MATERIALS_SEED_PATH = MATERIALS_SEED_RESOURCE;
  }
  if (
    !isDev ||
    fs.existsSync(path.join(WORKSHOP_SEED_RESOURCE_DIR, "seed-lock.json"))
  ) {
    env.LUMINA_WORKSHOP_SEED_DIR = WORKSHOP_SEED_RESOURCE_DIR;
  }
  return env;
}

// ═══════════════════════════════════════════════════════════
//  Single instance lock
// ═══════════════════════════════════════════════════════════

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
}

// ═══════════════════════════════════════════════════════════
//  Window management
// ═══════════════════════════════════════════════════════════

let win = null;
let splashWin = null;
let isQuitting = false;

function fixedWorkshopResponse(status, message) {
  return new Response(message, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'none'",
      "Content-Type": "text/plain; charset=utf-8",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function handleWorkshopProtocol(request) {
  if (workshopSafeMode) {
    return fixedWorkshopResponse(
      503,
      "Workshop runtime isolation unavailable.",
    );
  }
  if (request.method !== "GET") {
    return fixedWorkshopResponse(405, "Method not allowed.");
  }
  const runtime = resolveWorkshopRuntimeRequest(request.url);
  if (runtime === null) {
    return fixedWorkshopResponse(404, "Workshop runtime not found.");
  }
  try {
    const upstream = await electronNet.fetch(runtime.backendUrl, {
      headers: {
        "X-Lumina-Workshop-Desktop-Token": workshopSessionToken,
      },
      redirect: "error",
    });
    if (!upstream.ok) {
      const status =
        upstream.status >= 400 && upstream.status <= 599
          ? upstream.status
          : 502;
      return fixedWorkshopResponse(
        status,
        "Workshop runtime unavailable.",
      );
    }
    const headers = new Headers();
    for (const name of WORKSHOP_RUNTIME_HEADER_NAMES) {
      const value = upstream.headers.get(name);
      if (value !== null) {
        headers.set(name, value);
      }
    }
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers,
    });
  } catch (err) {
    logErr(`Workshop protocol proxy failed: ${err.name}`);
    return fixedWorkshopResponse(502, "Workshop runtime unavailable.");
  }
}

function installWorkshopSessionSecurity() {
  protocol.handle("lumina-workshop", handleWorkshopProtocol);

  session.defaultSession.webRequest.onBeforeRequest(
    { urls: ["<all_urls>"] },
    (details, callback) => {
      const trustedInternal =
        details.webContentsId === undefined &&
        details.webContents === undefined &&
        details.frame == null;
      const allowed = isAllowedWorkshopRequest({
        frameUrl: details.frame?.url ?? null,
        initiator: details.referrer || null,
        parentFrameUrl: details.frame?.parent?.url ?? null,
        resourceType: details.resourceType,
        trustedInternal,
        url: details.url,
      });
      callback({ cancel: !allowed });
    },
  );

  session.defaultSession.setPermissionRequestHandler(
    (webContents, _permission, callback, details) => {
      callback(
        isAllowedWorkshopPermission({
          frameUrl:
            details?.requestingUrl ??
            webContents?.getURL() ??
            null,
          requestingOrigin:
            details?.securityOrigin ??
            details?.requestingUrl ??
            null,
        }),
      );
    },
  );
  session.defaultSession.setPermissionCheckHandler(
    (webContents, _permission, requestingOrigin, details) =>
      isAllowedWorkshopPermission({
        frameUrl:
          details?.requestingUrl ??
          webContents?.getURL() ??
          null,
        requestingOrigin,
      }),
  );
}

function createSplash() {
  splashWin = new BrowserWindow({
    width: 480,
    height: 320,
    frame: false,
    transparent: true,
    resizable: false,
    center: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    icon: fs.existsSync(ICON_PATH) ? ICON_PATH : undefined,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  splashWin.loadFile(path.join(__dirname, "splash.html"));
}

function closeSplash() {
  if (splashWin && !splashWin.isDestroyed()) {
    splashWin.close();
    splashWin = null;
  }
}

function createWindow() {
  const windowOptions = {
    width: 1440,
    height: 900,
    title: "Lumina Studio 2",
    icon: fs.existsSync(ICON_PATH) ? ICON_PATH : undefined,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
      sandbox: false,
    },
    show: false,
  };

  win = new BrowserWindow(windowOptions);

  Menu.setApplicationMenu(null);

  win.webContents.setWindowOpenHandler(({ url, referrer }) => {
    const openerUrl = referrer?.url || null;
    if (!isAllowedWorkshopPopup({ openerUrl, targetUrl: url })) {
      return { action: "deny" };
    }
    if (url.includes("/api/") || url.includes("/files/")) {
      win.webContents.downloadURL(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });

  session.defaultSession.on("will-download", (event, item, webContents) => {
    if (
      !isAllowedWorkshopDownload({
        frameUrl: webContents?.getURL() ?? null,
        url: item.getURL(),
      })
    ) {
      event.preventDefault();
      return;
    }
    const filename = item.getFilename();
    const savePath = dialog.showSaveDialogSync(win, {
      defaultPath: filename,
      filters: [{ name: "All Files", extensions: ["*"] }],
    });
    if (savePath) {
      item.setSavePath(savePath);
    } else {
      event.preventDefault();
    }
  });

  win.webContents.on("will-frame-navigate", (details) => {
    if (
      shouldBlockWorkshopNavigation({
        frameUrl: details.frame?.url ?? null,
        initiatorUrl: details.initiator?.url ?? null,
        isMainFrame: details.isMainFrame,
        targetUrl: details.url,
      })
    ) {
      details.preventDefault();
    }
  });

  win.webContents.on("will-redirect", (details) => {
    if (
      shouldBlockWorkshopRedirect({
        frameUrl: details.frame?.url ?? null,
        initiatorUrl: details.initiator?.url ?? null,
        targetUrl: details.url,
      })
    ) {
      details.preventDefault();
    }
  });

  win.webContents.on(
    "did-frame-navigate",
    (
      _event,
      url,
      _httpResponseCode,
      _httpStatusText,
      isMainFrame,
      frameProcessId,
      frameRoutingId,
    ) => {
      if (isMainFrame || resolveWorkshopRuntimeRequest(url) === null) {
        return;
      }
      if (
        isWorkshopFrameProcessIsolated(
          win.webContents.getProcessId(),
          frameProcessId,
        )
      ) {
        return;
      }
      workshopSafeMode = true;
      logErr(
        "runtime-isolation-unavailable: Workshop safe mode enabled",
      );
      const frame = webFrameMain.fromId(
        frameProcessId,
        frameRoutingId,
      );
      void frame
        ?.executeJavaScript(
          "window.stop();document.documentElement.replaceChildren();",
        )
        .catch(() => {});
    },
  );

  win.on("close", (e) => {
    if (isQuitting) return;
    e.preventDefault();
    const dlg = QUIT_DIALOG[currentLang] || QUIT_DIALOG.zh;
    dialog
      .showMessageBox(win, {
        type: "question",
        title: dlg.title,
        message: dlg.message,
        detail: dlg.detail,
        buttons: [dlg.cancel, dlg.quit],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      })
      .then(({ response }) => {
        if (response === 1) {
          isQuitting = true;
          win.destroy();
        }
      });
  });

  if (isDev) {
    win.loadURL(FRONTEND_URL);
  } else {
    const indexPath = path.join(
      process.resourcesPath,
      "app",
      "dist",
      "index.html",
    );
    win.loadFile(indexPath);
  }

  win.once("ready-to-show", () => {
    closeSplash();
    win.show();
  });

  if (isDev) {
    win.webContents.on(
      "did-fail-load",
      (
        _event,
        _errorCode,
        _errorDescription,
        validatedUrl,
        isMainFrame,
      ) => {
        if (
          !shouldRetryFrontendLoad({
            isMainFrame,
            validatedUrl,
          })
        ) {
          return;
        }
        logErr("Frontend failed to load, retrying in 2s...");
        setTimeout(() => {
          if (win && !win.isDestroyed()) {
            win.loadURL(FRONTEND_URL);
          }
        }, 2000);
      },
    );
  }
}

// ═══════════════════════════════════════════════════════════
//  IPC handlers
// ═══════════════════════════════════════════════════════════

ipcMain.on("set-language", (_event, lang) => {
  if (lang === "zh" || lang === "en") {
    currentLang = lang;
    logSys(`Language set to ${lang}`);
  }
});

ipcMain.handle("get-app-version", () => {
  return app.getVersion();
});

ipcMain.handle("get-workshop-runtime-mode", () => ({
  mode: "desktop-secure",
  safeMode: workshopSafeMode,
}));

ipcMain.handle("pick-workshop-image", async (event) => {
  const senderUrl = event.senderFrame?.url ?? null;
  if (!isAllowedWorkshopIpcSender(senderUrl)) {
    throw new Error("Workshop image picker denied for this frame.");
  }
  const options = {
    title: "Select a Workshop image",
    properties: ["openFile"],
    filters: [
      {
        name: "Images",
        extensions: ["png", "jpg", "jpeg", "webp"],
      },
    ],
  };
  const result =
    win && !win.isDestroyed()
      ? await dialog.showOpenDialog(win, options)
      : await dialog.showOpenDialog(options);
  if (result.canceled || result.filePaths.length !== 1) {
    return null;
  }
  return loadWorkshopImageFile(result.filePaths[0]);
});

// ═══════════════════════════════════════════════════════════
//  App lifecycle
// ═══════════════════════════════════════════════════════════

app.on("before-quit", () => {
  killAllChildren();
});

app.on("window-all-closed", () => {
  // macOS 习惯:关掉所有窗口应用仍驻留 Dock,Cmd+Q 才真正退出。
  // 但本应用是单窗口工具,而且 close 时已经走了"是否退出"的确认对话框,
  // 用户选了关闭就是想退出,所以这里和 Windows 一样直接 quit。
  app.quit();
});

app.whenReady().then(async () => {
  initLog();
  logSys("Lumina Studio Electron starting...");
  logSys(`Mode: ${isDev ? "development" : "production"}`);
  installWorkshopSessionSecurity();

  // 让 about 面板 / app.getName() / 部分 macOS 系统提示显示正确的名字。
  // 注意:dev 模式下 macOS 顶部菜单栏左上角的加粗应用名由 Electron.app 的
  // Info.plist::CFBundleName 决定,无法在运行期改写;打包后(productName 写进
  // Info.plist)就会自动变成 "Lumina Studio"。
  app.setName("Lumina Studio 2");
  if (IS_MAC) {
    app.setAboutPanelOptions({
      applicationName: "Lumina Studio 2",
      applicationVersion: app.getVersion(),
      copyright: "© Lumina Studio",
      iconPath: ICON_PATH,
    });
  }

  // macOS: 让 Dock 显示 Lumina 自己的图标而不是默认 Electron 图标。
  // 仅在 dev/未签名运行时需要;打包后由 .app 包内的 Contents/Resources/icon.icns 接管。
  if (IS_MAC && app.dock && fs.existsSync(ICON_PATH)) {
    try {
      app.dock.setIcon(ICON_PATH);
    } catch (err) {
      logErr(`Dock icon set failed: ${err.message}`);
    }
  }

  createSplash();

  logSys("Cleaning up residual processes...");
  killListening([BACKEND_PORT, FRONTEND_PORT]);

  // ── Start backend ──
  let backendProc;
  if (isDev) {
    const python = findPython();
    const apiServer = path.join(ROOT_DIR, "api_server.py");
    logSys(`Starting backend: ${python} ${apiServer}`);
    try {
      backendProc = await spawnChild(
        "Backend",
        python,
        [apiServer],
        ROOT_DIR,
        backendRuntimeEnv(),
      );
    } catch (err) {
      dialog.showErrorBox(
        "Backend Start Failed",
        `Failed to start backend: ${err.message}`,
      );
      app.quit();
      return;
    }
  } else {
    // 生产模式下后端可执行文件按平台命名:
    //   - Windows: lumina-backend.exe (PyInstaller --onefile)
    //   - macOS:   lumina-backend (无后缀)
    //   - Linux:   lumina-backend
    // mac/linux 的打包脚本目前还没就绪,这里先做好分流,后续接打包不用再动 main.cjs。
    const backendExe = path.join(
      process.resourcesPath,
      "backend",
      IS_WIN ? "lumina-backend.exe" : "lumina-backend",
    );
    logSys(`Starting backend: ${backendExe}`);
    try {
      backendProc = await spawnChild("Backend", backendExe, [], ROOT_DIR, backendRuntimeEnv());
    } catch (err) {
      dialog.showErrorBox(
        "Backend Start Failed",
        `Failed to start backend: ${err.message}`,
      );
      app.quit();
      return;
    }
  }

  // ── Wait for backend health ──
  logSys("Waiting for backend health...");
  try {
    await waitForHealth(BACKEND_HEALTH_URL, HEALTH_TIMEOUT_MS);
    logOk("Backend is healthy");
  } catch (err) {
    logErr(`Backend health check failed: ${err.message}`);
    dialog.showErrorBox(
      "Backend Unavailable",
      `Backend did not respond within ${HEALTH_TIMEOUT_MS / 1000}s. Please check logs.`,
    );
    app.quit();
    return;
  }

  // ── Start Vite dev server (dev mode only) ──
  if (isDev) {
    const node = findNode();
    const viteJs = path.join(
      ROOT_DIR,
      "frontend",
      "node_modules",
      "vite",
      "bin",
      "vite.js",
    );
    const frontendDir = path.join(ROOT_DIR, "frontend");
    logSys(`Starting Vite: ${node} ${viteJs}`);
    try {
      await spawnChild("Frontend", node, [viteJs], frontendDir);
    } catch (err) {
      logErr(`Vite start failed: ${err.message}`);
    }

    logSys("Waiting for Vite dev server...");
    try {
      await waitForPort(FRONTEND_PORT, PORT_TIMEOUT_MS);
      logOk("Vite dev server is ready");
    } catch (err) {
      logErr(`Vite port check failed: ${err.message}`);
    }
  }

  // ── Create main window ──
  createWindow();
});
