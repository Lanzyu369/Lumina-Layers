"use strict";

// Opt-in, isolated diagnostic runner. Never changes the installed application.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");

function resourceName(value) {
  try {
    const url = new URL(value);
    if (url.protocol === "file:") return `file:///<local>/${path.basename(url.pathname)}`;
    if (["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) {
      return url.origin + url.pathname;
    }
    return "<external-url>";
  } catch { return "<unavailable>"; }
}

function redact(value) {
  return String(value).slice(0, 8192)
    .replace(/https?:\/\/[^\s"'<>]+/gi, resourceName)
    .replace(/file:\/\/[^\s"'<>]+/gi, resourceName)
    .replace(/[A-Z]:[\\/][^\r\n"'<>]*/gi, "<local-path>")
    .replace(/(?:Bearer\s+)[\w.\-]+/gi, "Bearer <redacted>")
    .replace(/((?:token|password|activationCode|signature)\s*[:=]\s*)[^\s,;}]+/gi, "$1<redacted>");
}

function isEntryResource(url, type) {
  try {
    const parsed = new URL(url);
    return ["127.0.0.1", "localhost", "[::1]"].includes(parsed.hostname)
      && (type === "document" || /\.(?:js|mjs|css)$/i.test(parsed.pathname));
  } catch { return false; }
}

function sha256(bytes) { return crypto.createHash("sha256").update(bytes).digest("hex"); }

/** Inspect the shipped Electron app with fresh managed data. / 使用全新托管资料检查发行本体。 */
async function diagnose({ executable, output, seconds = 30, playwright, onCollected }) {
  if (!path.isAbsolute(executable) || !path.isAbsolute(output)) throw new Error("Absolute paths required");
  if (!Number.isInteger(seconds) || seconds < 5 || seconds > 180) throw new Error("Seconds must be 5..180");
  const dist = path.join(path.dirname(executable), "resources", "app", "dist");
  const index = fs.readFileSync(path.join(dist, "index.html"), "utf8");
  fs.mkdirSync(output); // Refuse to overwrite an earlier run or reuse its profile.
  const reportPath = path.join(output, "startup-report.json");
  const report = {
    schemaVersion: 1, scope: "isolated packaged startup; not customer root-cause proof",
    startedAt: new Date().toISOString(), exeSha256: sha256(fs.readFileSync(executable)),
    indexSha256: sha256(Buffer.from(index)), events: [], resources: [], pages: [],
  };
  const write = () => fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
  const add = event => { if (report.events.length < 120) report.events.push(event); };
  const pending = new Set();
  const watched = new Set();
  let application;
  let proc;
  let exited = false;
  const env = { ...process.env };
  // Do not inherit real managed data, credentials, runtime switches or Node mode.
  for (const key of Object.keys(env)) {
    if (/^LUMINA_|^ELECTRON_RUN_AS_NODE$|^NODE_OPTIONS$|^NODE_PATH$/i.test(key)) delete env[key];
  }
  const runtimeKey = crypto.createHash("md5").update(executable).digest("hex");
  Object.assign(env, {
    LUMINA_MANAGED_USER_DATA: path.join(output, "data"),
    LUMINA_MANAGED_RUNTIME_KEY: runtimeKey,
    LUMINA_MANAGED_LAUNCH_ID: crypto.randomUUID(),
  });
  function watch(page) {
    if (watched.has(page)) return;
    watched.add(page);
    page.on("pageerror", error => add({ kind: "exception", page: resourceName(page.url()), message: redact(error.message), stack: redact(error.stack) }));
    page.on("console", message => {
      if (message.type() === "error") add({ kind: "console", page: resourceName(page.url()), message: redact(message.text()), source: resourceName(message.location().url), line: message.location().lineNumber });
    });
    page.on("crash", () => add({ kind: "renderer-crash", page: resourceName(page.url()) }));
    page.on("requestfailed", request => {
      if (isEntryResource(request.url(), request.resourceType())) add({ kind: "request-failed", url: resourceName(request.url()), error: redact(request.failure()?.errorText) });
    });
    page.on("response", response => {
      if (!isEntryResource(response.url(), response.request().resourceType()) || report.resources.length >= 40) return;
      const row = { url: resourceName(response.url()), status: response.status(), contentType: response.headers()["content-type"] || null };
      report.resources.push(row);
      const task = (async () => {
        try {
          const bytes = await response.body();
          row.bytes = bytes.length;
          row.sha256 = sha256(bytes);
          row.looksLikeHtml = /^\s*(?:<!doctype html|<html)/i.test(bytes.subarray(0, 100).toString());
          const relative = decodeURIComponent(new URL(response.url()).pathname).replace(/^\/+/, "") || "index.html";
          const file = path.resolve(dist, relative);
          if (file.startsWith(path.resolve(dist) + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) {
            row.matchesPackagedFile = sha256(fs.readFileSync(file)) === row.sha256;
          }
        } catch (error) { row.bodyError = redact(error.message); }
      })();
      pending.add(task);
      task.finally(() => pending.delete(task));
    });
  }
  try {
    application = await playwright._electron.launch({ executablePath: executable, args: [], env, timeout: 60000 });
    proc = application.process();
    proc.once("exit", (code, signal) => { exited = true; report.exit = { code, signal }; });
    application.on("window", watch);
    application.windows().forEach(watch);
    report.runtime = await application.evaluate(({ app }) => ({ packaged: app.isPackaged, electron: process.versions.electron, chrome: process.versions.chrome, platform: process.platform, arch: process.arch }));
    await application.evaluate(({ app }) => {
      globalThis.luminaStartupProbe = [];
      const record = value => { if (globalThis.luminaStartupProbe.length < 20) globalThis.luminaStartupProbe.push(value); };
      app.on("web-contents-created", (_event, contents) => {
        contents.on("preload-error", (_errorEvent, _file, error) => record({ kind: "preload-error", message: error.message }));
        contents.on("render-process-gone", (_errorEvent, details) => record({ kind: "render-process-gone", reason: details.reason, exitCode: details.exitCode }));
      });
      app.on("child-process-gone", (_event, details) => record({ kind: "child-process-gone", type: details.type, reason: details.reason, exitCode: details.exitCode }));
    });
    await new Promise(resolve => setTimeout(resolve, seconds * 1000));
    for (const page of application.windows()) {
      if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+\/$/.test(page.url())) continue;
      const state = await page.evaluate(() => {
        const root = document.getElementById("root");
        const rect = root?.getBoundingClientRect();
        const labels = [...document.querySelectorAll("button")].map(b => b.textContent?.trim());
        return { url: location.origin + location.pathname, rootChildren: root?.childElementCount ?? 0,
          rootBounds: rect ? { width: rect.width, height: rect.height } : null,
          rootDisplay: root ? getComputedStyle(root).display : null,
          hasSettings: labels.some(t => t === "设置" || t === "Settings"),
          hasConverter: labels.some(t => t === "图像转换" || t === "Image Conversion"),
          hasFileInput: !!document.querySelector('input[type="file"]'),
          visibility: document.visibilityState };
      }).catch(error => ({ url: resourceName(page.url()), inspectionError: redact(error.message) }));
      report.pages.push(state);
      // A separate bounded probe, explicitly not the initial navigation response.
      try {
        const response = await page.request.get(page.url(), { timeout: 5000 });
        const bytes = await response.body();
        report.documentProbe = { url: resourceName(page.url()), status: response.status(),
          contentType: response.headers()["content-type"] || null, bytes: bytes.length,
          sha256: sha256(bytes), matchesPackagedIndex: sha256(bytes) === report.indexSha256 };
      } catch (error) { report.documentProbe = { error: redact(error.message) }; }
    }
    await Promise.allSettled([...pending]);
    const statusPath = path.join(output, "data", "logs", runtimeKey, `launch-${env.LUMINA_MANAGED_LAUNCH_ID}`, "status.json");
    if (fs.existsSync(statusPath)) {
      const status = JSON.parse(fs.readFileSync(statusPath, "utf8"));
      report.handshake = { state: status.state, errorCode: status.errorCode || null };
    }
    report.gpu = await application.evaluate(({ app }) => app.getGPUFeatureStatus()).catch(error => ({ error: redact(error.message) }));
    for (const event of await application.evaluate(() => globalThis.luminaStartupProbe || [])) {
      add({ ...event, ...(event.message ? { message: redact(event.message) } : {}) });
    }
    report.collectedAt = new Date().toISOString();
    write();
    console.log("Evidence saved. Close the test Studio window normally within 120 seconds.");
    if (onCollected) await onCollected(application, report);
    const deadline = Date.now() + 120000;
    while (!exited && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 500));
  } catch (error) {
    report.error = redact(error.message);
    throw error;
  } finally {
    if (proc && !exited) {
      // Only the process tree owned by this run, never name-based user-process cleanup.
      report.forcedCleanup = true;
      const result = spawnSync("taskkill.exe", ["/PID", String(proc.pid), "/T", "/F"], { windowsHide: true });
      report.cleanupExitCode = result.status;
      await new Promise(resolve => setTimeout(resolve, 500));
    } else report.forcedCleanup = false;
    report.finishedAt = new Date().toISOString();
    write();
  }
  return report;
}

if (require.main === module) {
  const [executable, output, moduleRoot] = process.argv.slice(2);
  const playwright = require(moduleRoot ? path.join(moduleRoot, "playwright") : "playwright");
  diagnose({ executable, output, playwright }).catch(error => { console.error(redact(error.message)); process.exitCode = 1; });
}
module.exports = { diagnose, redact, resourceName, isEntryResource };
