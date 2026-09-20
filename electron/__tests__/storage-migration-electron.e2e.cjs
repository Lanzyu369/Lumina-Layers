"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { fileURLToPath, pathToFileURL } = require("node:url");

const { app, BrowserWindow } = require("electron");
const migration = require("../storage-migration.cjs");

const CONFIGURED_TARGET_URL = process.env.LUMINA_MIGRATION_E2E_TARGET_URL || null;
const MODULE_BASE_URL = process.env.LUMINA_MIGRATION_E2E_MODULE_BASE_URL || "http://127.0.0.1:8001";
const PROJECT_STORAGE_URL_1 = JSON.stringify(`${MODULE_BASE_URL}/src/workshop/projectStorage.ts?migration-e2e=1`);
const PROJECT_STORAGE_URL_2 = JSON.stringify(`${MODULE_BASE_URL}/src/workshop/projectStorage.ts?migration-e2e=2`);
const SOURCE_DB = "lumina-workshop";
const SOURCE_MODULE = "legacy-module";
const PRELOAD = path.join(__dirname, "..", "storage-migration-preload.cjs");
const TEST_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-storage-migration-electron-"));
fs.mkdirSync(path.join(TEST_ROOT, "user-data"), { recursive: true });

function migrationWindowOptions() {
  return {
    show: false,
    width: 1,
    height: 1,
    webPreferences: {
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: false,
      preload: PRELOAD,
    },
  };
}

async function loadWindow(url) {
  const window = new BrowserWindow(migrationWindowOptions());
  if (url.startsWith("file://")) await window.loadFile(fileURLToPath(url));
  else await window.loadURL(url);
  return window;
}

async function execute(window, script) {
  return window.webContents.executeJavaScript(`(${script})()`, true);
}

async function closeWindow(window) {
  if (!window || window.isDestroyed()) return;
  await new Promise(resolve => {
    window.once("closed", resolve);
    window.close();
    setTimeout(resolve, 250);
  });
}

function projectRecord(projectId, project) {
  return {
    moduleId: SOURCE_MODULE,
    projectId,
    schemaVersion: "2.0.0-beta",
    createdAt: "2026-09-21T00:00:00.000Z",
    updatedAt: projectId === "first"
      ? "2026-09-21T00:00:01.000Z"
      : "2026-09-21T00:00:02.000Z",
    project,
  };
}

async function seedLegacySource(indexPath, includeSecond, includeUnsupported) {
  const source = await loadWindow(pathToFileURL(indexPath).href);
  try {
    await execute(source, `async () => {
      localStorage.setItem("lumina-settings", JSON.stringify({ theme: "legacy" }));
      const request = indexedDB.open(${JSON.stringify(SOURCE_DB)}, 2);
      await new Promise((resolve, reject) => {
        request.onupgradeneeded = () => {
          const database = request.result;
          const transaction = request.transaction;
          const projects = database.objectStoreNames.contains("projects")
            ? transaction.objectStore("projects")
            : database.createObjectStore("projects", { keyPath: "key" });
          if (!projects.indexNames.contains("updatedAt")) projects.createIndex("updatedAt", "updatedAt");
          if (!projects.indexNames.contains("moduleId")) projects.createIndex("moduleId", "moduleId");
          const snapshots = database.objectStoreNames.contains("snapshots")
            ? transaction.objectStore("snapshots")
            : database.createObjectStore("snapshots", { keyPath: "key" });
          if (!snapshots.indexNames.contains("moduleId")) snapshots.createIndex("moduleId", "moduleId");
          if (!database.objectStoreNames.contains("metadata")) database.createObjectStore("metadata", { keyPath: "key" });
        };
        request.onerror = () => reject(request.error || new Error("legacy seed open failed"));
        request.onsuccess = () => resolve(request.result);
      }).then(async database => {
        const transaction = database.transaction("projects", "readwrite");
        const first = {
          key: "legacy-module:first",
          moduleId: "legacy-module",
          projectId: "first",
          schemaVersion: "2.0.0-beta",
          createdAt: "2026-09-21T00:00:00.000Z",
          updatedAt: "2026-09-21T00:00:01.000Z",
          project: {
            bytes: new Uint8Array([1, 2, 3]),
            buffer: new Uint8Array([4, 5]).buffer,
            blob: new Blob(["legacy"], { type: "text/plain" }),
            date: new Date("2026-09-21T00:00:03.000Z"),
            map: new Map([["origin", "legacy"]]),
            set: new Set(["source"]),
            big: 42n,
          },
        };
        transaction.objectStore("projects").put(first);
        if (${Boolean(includeSecond)}) {
          transaction.objectStore("projects").put({
            key: "legacy-module:second",
            moduleId: "legacy-module",
            projectId: "second",
            schemaVersion: "2.0.0-beta",
            createdAt: "2026-09-21T00:00:00.000Z",
            updatedAt: "2026-09-21T00:00:02.000Z",
            project: { sourceOnly: true },
          });
        }
        await new Promise((resolve, reject) => {
          transaction.oncomplete = resolve;
          transaction.onerror = () => reject(transaction.error || new Error("legacy seed write failed"));
          transaction.onabort = () => reject(transaction.error || new Error("legacy seed write aborted"));
        });
        database.close();
      });
      if (${Boolean(includeUnsupported)}) {
        const unsupported = indexedDB.open("legacy-unsupported", 1);
        await new Promise((resolve, reject) => {
          unsupported.onupgradeneeded = () => unsupported.result.createObjectStore("data");
          unsupported.onerror = () => reject(unsupported.error || new Error("unsupported seed open failed"));
          unsupported.onsuccess = () => {
            const database = unsupported.result;
            const transaction = database.transaction("data", "readwrite");
            transaction.objectStore("data").put({ unsupported: true }, "entry");
            transaction.oncomplete = () => { database.close(); resolve(); };
            transaction.onerror = () => reject(transaction.error || new Error("unsupported seed write failed"));
          };
        });
      } else {
        await new Promise((resolve, reject) => {
          const request = indexedDB.deleteDatabase("legacy-unsupported");
          request.onerror = () => reject(request.error || new Error("unsupported source cleanup failed"));
          request.onsuccess = resolve;
          request.onblocked = resolve;
        });
      }
    }`);
  } finally {
    await closeWindow(source);
  }
}

async function inspectAndEditTarget(targetUrl) {
  const target = await loadWindow(targetUrl);
  try {
    return await execute(target, `async () => {
      const { createWorkshopProjectStorage } = await import(${PROJECT_STORAGE_URL_1});
      const result = createWorkshopProjectStorage();
      const loaded = await result.storage.load("legacy-module", "first");
      if (!loaded) throw new Error("migrated project was not readable");
      const project = loaded.project;
      if (!(project.bytes instanceof Uint8Array)) throw new Error("Uint8Array was not preserved");
      if (!(project.buffer instanceof ArrayBuffer)) throw new Error("ArrayBuffer was not preserved");
      if (!project.blob || Object.prototype.toString.call(project.blob) !== "[object Blob]" || typeof project.blob.text !== "function" || await project.blob.text() !== "legacy") {
        throw new Error("Blob was not preserved: " + Object.prototype.toString.call(project.blob) + ":" + typeof project.blob?.text);
      }
      if (!(project.date instanceof Date) || project.date.toISOString() !== "2026-09-21T00:00:03.000Z") throw new Error("Date was not preserved");
      if (!(project.map instanceof Map) || project.map.get("origin") !== "legacy") throw new Error("Map was not preserved");
      if (!(project.set instanceof Set) || !project.set.has("source")) throw new Error("Set was not preserved");
      if (project.big !== 42n) throw new Error("BigInt was not preserved");
      localStorage.setItem("lumina-settings", JSON.stringify({ theme: "user-edited" }));
      await result.storage.save({
        ...loaded,
        updatedAt: "2026-09-21T00:01:00.000Z",
        project: { ...project, userEdited: true },
      });
      const saved = await result.storage.load("legacy-module", "first");
      const rawRecord = await new Promise((resolve, reject) => {
        const request = indexedDB.open("lumina-workshop");
        request.onerror = () => reject(request.error || new Error("raw open failed"));
        request.onsuccess = () => {
          const database = request.result;
          const transaction = database.transaction("projects", "readonly");
          const keyRequest = transaction.objectStore("projects").getKey("legacy-module:first");
          keyRequest.onerror = () => reject(keyRequest.error || new Error("raw getKey failed"));
          keyRequest.onsuccess = () => {
            const valueRequest = transaction.objectStore("projects").get("legacy-module:first");
            valueRequest.onerror = () => reject(valueRequest.error || new Error("raw get failed"));
            valueRequest.onsuccess = () => { database.close(); resolve({ key: keyRequest.result, userEdited: Boolean(valueRequest.result?.project?.userEdited) }); };
          };
        };
      });
      const databases = await indexedDB.databases();
      return {
        edited: true,
        databaseVersion: databases.find(database => database.name === "lumina-workshop")?.version ?? null,
        setting: localStorage.getItem("lumina-settings"),
        savedUserEdited: Boolean(saved?.project?.userEdited),
        rawRecord,
      };
    }`);
  } finally {
    await closeWindow(target);
  }
}

async function verifyTargetAfterRetry(targetUrl) {
  const target = await loadWindow(targetUrl);
  try {
    return await execute(target, `async () => {
      const { createWorkshopProjectStorage } = await import(${PROJECT_STORAGE_URL_2});
      const result = createWorkshopProjectStorage();
      const first = await result.storage.load("legacy-module", "first");
      const second = await result.storage.load("legacy-module", "second");
      const databases = await indexedDB.databases();
      if (!first?.project?.userEdited) throw new Error("retry overwrote user-edited project");
      if (!second?.project?.sourceOnly) throw new Error("retry did not fill missing project");
      if (localStorage.getItem("lumina-settings") !== JSON.stringify({ theme: "user-edited" })) {
        throw new Error("retry overwrote user-edited settings");
      }
      await result.storage.save({
        ...second,
        updatedAt: "2026-09-21T00:02:00.000Z",
        project: { ...second.project, restartedAndSaved: true },
      });
      return {
        firstPreserved: Boolean(first.project.userEdited),
        secondFilled: Boolean(second.project.sourceOnly),
        restartSave: true,
        databaseVersion: databases.find(database => database.name === "lumina-workshop")?.version ?? null,
        setting: localStorage.getItem("lumina-settings"),
      };
    }`);
  } finally {
    await closeWindow(target);
  }
}

async function run() {
  const root = TEST_ROOT;
  app.setPath("userData", path.join(root, "user-data"));
  const sourceDirectory = path.join(root, "legacy");
  fs.mkdirSync(sourceDirectory, { recursive: true });
  const indexPath = path.join(sourceDirectory, "index.html");
  const markerPath = path.join(root, "legacy-storage-migration.json");
  fs.writeFileSync(indexPath, "<!doctype html><title>Legacy storage</title>");
  const targetServer = http.createServer((_request, response) => {
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end("<!doctype html><title>Migration target</title>");
  });
  if (!CONFIGURED_TARGET_URL) {
    await new Promise((resolve, reject) => {
      targetServer.once("error", reject);
      targetServer.listen({ port: 8003, host: "127.0.0.1", exclusive: true }, resolve);
    });
  }
  const targetUrl = CONFIGURED_TARGET_URL || "http://127.0.0.1:8003/";
  await seedLegacySource(indexPath, false, true);
  const sourceProbe = await loadWindow(pathToFileURL(indexPath).href);
  await closeWindow(sourceProbe);

  const partialStatus = await migration.migrateLegacyStorage({
    BrowserWindow,
    indexPath,
    targetUrl,
    markerPath,
    legacyHttpPort: null,
    logger: message => process.stderr.write(`migration: ${message}\n`),
  });
  assert.equal(partialStatus, "partial");
  assert.equal(fs.existsSync(markerPath), false);

  const firstEdit = await inspectAndEditTarget(targetUrl);
  assert.equal(firstEdit.edited, true);
  assert.equal(firstEdit.databaseVersion, 2);

  await seedLegacySource(indexPath, true, false);
  const retryStatus = await migration.migrateLegacyStorage({
    BrowserWindow,
    indexPath,
    targetUrl,
    markerPath,
    legacyHttpPort: null,
    logger: message => process.stderr.write(`migration: ${message}\n`),
  });
  assert.equal(retryStatus, "migrated");
  const finalState = await verifyTargetAfterRetry(targetUrl);
  assert.deepEqual(finalState, {
    firstPreserved: true,
    secondFilled: true,
    restartSave: true,
    databaseVersion: 2,
    setting: JSON.stringify({ theme: "user-edited" }),
  });
  if (!CONFIGURED_TARGET_URL) await new Promise(resolve => targetServer.close(resolve));
  return { partialStatus, retryStatus, firstEdit, finalState };
}

app.commandLine.appendSwitch("no-sandbox");
app.commandLine.appendSwitch("disable-gpu");
app.whenReady()
  .then(run)
  .then(result => {
    process.stdout.write(`${JSON.stringify({ ok: true, ...result })}\n`);
    app.exit(0);
  })
  .catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    app.exit(1);
  });
