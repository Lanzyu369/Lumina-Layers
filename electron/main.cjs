const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  session,
} = require("electron");
const { spawn, execSync } = require("child_process");
const http = require("http");
const net = require("net");
const fs = require("fs");
const path = require("path");

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

const isDev = !app.isPackaged;
const ROOT_DIR = path.join(__dirname, "..");
const ICON_PATH = path.join(ROOT_DIR, "icon.ico");

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

function spawnChild(name, cmd, args, cwd) {
  return new Promise((resolve, reject) => {
    const logFn = name.includes("Backend") ? logBe : logFe;
    try {
      const proc = spawn(cmd, args, {
        cwd,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        detached: false,
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
    if (process.platform === "win32") {
      execSync(`taskkill /T /F /PID ${proc.pid}`, {
        windowsHide: true,
        stdio: "ignore",
      });
    } else {
      proc.kill("SIGTERM");
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
  if (process.platform !== "win32") return;
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
      const sock = net.connect(port, "127.0.0.1", () => {
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
  const venvPaths = [
    path.join(ROOT_DIR, "venv", "Scripts", "python.exe"),
    path.join(ROOT_DIR, ".venv", "Scripts", "python.exe"),
  ];
  for (const p of venvPaths) {
    if (fs.existsSync(p)) return p;
  }
  return "python";
}

function findNode() {
  try {
    const out = execSync("where node", {
      windowsHide: true,
      encoding: "utf-8",
    });
    const lines = out.trim().split("\n");
    if (lines.length > 0) return lines[0].trim();
  } catch (_) {}
  return "node";
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

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.includes("/api/") || url.includes("/files/")) {
      win.webContents.downloadURL(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });

  session.defaultSession.on("will-download", (event, item) => {
    event.preventDefault();
    const filename = item.getFilename();
    const savePath = dialog.showSaveDialogSync(win, {
      defaultPath: filename,
      filters: [{ name: "All Files", extensions: ["*"] }],
    });
    if (savePath) {
      item.setSavePath(savePath);
    }
  });

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
    win.webContents.on("did-fail-load", () => {
      logErr("Frontend failed to load, retrying in 2s...");
      setTimeout(() => {
        if (win && !win.isDestroyed()) {
          win.loadURL(FRONTEND_URL);
        }
      }, 2000);
    });
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

// ═══════════════════════════════════════════════════════════
//  App lifecycle
// ═══════════════════════════════════════════════════════════

app.on("before-quit", () => {
  killAllChildren();
});

app.on("window-all-closed", () => {
  app.quit();
});

app.whenReady().then(async () => {
  initLog();
  logSys("Lumina Studio Electron starting...");
  logSys(`Mode: ${isDev ? "development" : "production"}`);

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
      backendProc = await spawnChild("Backend", python, [apiServer], ROOT_DIR);
    } catch (err) {
      dialog.showErrorBox(
        "Backend Start Failed",
        `Failed to start backend: ${err.message}`,
      );
      app.quit();
      return;
    }
  } else {
    const backendExe = path.join(
      process.resourcesPath,
      "backend",
      "lumina-backend.exe",
    );
    logSys(`Starting backend: ${backendExe}`);
    try {
      backendProc = await spawnChild("Backend", backendExe, [], ROOT_DIR);
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
