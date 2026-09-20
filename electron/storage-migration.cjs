"use strict";

const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const MIGRATION_VERSION = 1;
const LEGACY_HTTP_PORT = 8000;
const MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024;

const EXPORT_SCRIPT = `
(async () => {
  const result = { schemaVersion: 1, localStorage: {}, indexedDB: [] };
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key !== null) result.localStorage[key] = localStorage.getItem(key);
    }
  } catch (_) {}
  if (!globalThis.indexedDB || typeof indexedDB.databases !== "function") return result;
  let databases = [];
  try { databases = await indexedDB.databases(); } catch (_) { return result; }
  for (const info of databases) {
    if (!info || typeof info.name !== "string" || !info.name) continue;
    try {
      const database = await new Promise((resolve, reject) => {
        const request = indexedDB.open(info.name);
        request.onerror = () => reject(request.error || new Error("IndexedDB open failed"));
        request.onsuccess = () => resolve(request.result);
      });
      const stores = [];
      for (const storeName of Array.from(database.objectStoreNames)) {
        const transaction = database.transaction(storeName, "readonly");
        const store = transaction.objectStore(storeName);
        const schema = {
          name: store.name,
          keyPath: store.keyPath,
          autoIncrement: store.autoIncrement,
          indexes: Array.from(store.indexNames).map(indexName => {
            const index = store.index(indexName);
            return {
              name: index.name,
              keyPath: index.keyPath,
              unique: index.unique,
              multiEntry: index.multiEntry,
            };
          }),
          records: [],
        };
        await new Promise((resolve, reject) => {
          const request = store.openCursor();
          request.onerror = () => reject(request.error || new Error("IndexedDB cursor failed"));
          request.onsuccess = event => {
            const cursor = event.target.result;
            if (!cursor) { resolve(); return; }
            schema.records.push({ key: cursor.key, value: cursor.value });
            cursor.continue();
          };
        });
        stores.push(schema);
      }
      database.close();
      result.indexedDB.push({ name: info.name, version: database.version, stores });
    } catch (_) {}
  }
  return result;
})()
`;

function hasSnapshotData(snapshot) {
  return Boolean(
    snapshot &&
    ((snapshot.localStorage && Object.keys(snapshot.localStorage).length > 0) ||
      (Array.isArray(snapshot.indexedDB) && snapshot.indexedDB.length > 0)),
  );
}

function buildImportScript(snapshot) {
  const serialized = JSON.stringify(snapshot);
  if (typeof serialized !== "string" || Buffer.byteLength(serialized, "utf8") > MAX_SNAPSHOT_BYTES) {
    throw new Error("legacy_storage_snapshot_too_large");
  }
  return `
(async () => {
  const snapshot = ${serialized};
  for (const [key, value] of Object.entries(snapshot.localStorage || {})) {
    try { localStorage.setItem(key, value == null ? "" : String(value)); } catch (_) {}
  }
  for (const database of snapshot.indexedDB || []) {
    if (!database || typeof database.name !== "string" || !database.name) continue;
    try {
      const existing = await new Promise((resolve, reject) => {
        const request = indexedDB.open(database.name);
        request.onerror = () => reject(request.error || new Error("IndexedDB version probe failed"));
        request.onsuccess = () => { const db = request.result; const version = db.version; db.close(); resolve(version); };
      });
      const version = Math.max(Number(existing) || 1, Number(database.version) || 1) + 1;
      const opened = await new Promise((resolve, reject) => {
        const request = indexedDB.open(database.name, version);
        request.onerror = () => reject(request.error || new Error("IndexedDB import open failed"));
        request.onblocked = () => reject(new Error("IndexedDB import blocked"));
        request.onupgradeneeded = () => {
          const db = request.result;
          for (const schema of database.stores || []) {
            let store;
            if (db.objectStoreNames.contains(schema.name)) {
              store = request.transaction.objectStore(schema.name);
            } else {
              store = db.createObjectStore(schema.name, {
                keyPath: schema.keyPath == null ? undefined : schema.keyPath,
                autoIncrement: Boolean(schema.autoIncrement),
              });
            }
            for (const index of schema.indexes || []) {
              if (!store.indexNames.contains(index.name)) {
                store.createIndex(index.name, index.keyPath, {
                  unique: Boolean(index.unique),
                  multiEntry: Boolean(index.multiEntry),
                });
              }
            }
          }
        };
        request.onsuccess = () => resolve(request.result);
      });
      opened.close();
      const writable = await new Promise((resolve, reject) => {
        const request = indexedDB.open(database.name);
        request.onerror = () => reject(request.error || new Error("IndexedDB import reopen failed"));
        request.onsuccess = () => resolve(request.result);
      });
      const transaction = writable.transaction(
        (database.stores || []).map(schema => schema.name).filter(name => writable.objectStoreNames.contains(name)),
        "readwrite",
      );
      for (const schema of database.stores || []) {
        if (!writable.objectStoreNames.contains(schema.name)) continue;
        const store = transaction.objectStore(schema.name);
        for (const record of schema.records || []) {
          if (store.keyPath == null) store.put(record.value, record.key);
          else store.put(record.value);
        }
      }
      await new Promise((resolve, reject) => {
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error || new Error("IndexedDB import transaction failed"));
        transaction.onabort = () => reject(transaction.error || new Error("IndexedDB import transaction aborted"));
      });
      writable.close();
    } catch (_) {}
  }
  return true;
})()
`;
}

function markerExists(markerPath) {
  try {
    const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"));
    return marker?.schemaVersion === MIGRATION_VERSION;
  } catch (_) {
    return false;
  }
}

function writeMarker(markerPath, status) {
  fs.mkdirSync(path.dirname(markerPath), { recursive: true });
  const temporary = `${markerPath}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify({
    schemaVersion: MIGRATION_VERSION,
    status,
    migratedAt: new Date().toISOString(),
  })}\n`, { mode: 0o600 });
  fs.renameSync(temporary, markerPath);
}

function destroyWindow(window) {
  if (window && !window.isDestroyed?.()) window.destroy();
}

async function readSnapshot(BrowserWindow, url, load) {
  const window = new BrowserWindow({
    show: false,
    width: 1,
    height: 1,
    webPreferences: { contextIsolation: false, nodeIntegration: false },
  });
  try {
    await load(window, url);
    return await window.webContents.executeJavaScript(EXPORT_SCRIPT, true);
  } finally {
    destroyWindow(window);
  }
}

async function startLegacyHttpHost(port) {
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end("<!doctype html><title>Lumina storage migration</title>");
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen({ port, host: "127.0.0.1", exclusive: true }, resolve);
  });
  return server;
}

async function migrateLegacyStorage({ BrowserWindow, indexPath, targetUrl, markerPath, logger = () => {} }) {
  if (markerExists(markerPath)) return "already-migrated";
  if (!fs.existsSync(indexPath)) return "no-index";
  const snapshots = [];
  const sources = [{ url: pathToFileURL(indexPath).href, load: (window, url) => window.loadURL(url) }];
  let legacyServer = null;
  try {
    legacyServer = await startLegacyHttpHost(LEGACY_HTTP_PORT);
    sources.push({ url: `http://127.0.0.1:${LEGACY_HTTP_PORT}/`, load: (window, url) => window.loadURL(url) });
  } catch (error) {
    if (error?.code !== "EADDRINUSE") logger(`legacy HTTP storage source unavailable: ${error.code || error.name}`);
  }
  try {
    for (const source of sources) {
      try {
        const snapshot = await readSnapshot(BrowserWindow, source.url, source.load);
        if (hasSnapshotData(snapshot)) snapshots.push(snapshot);
      } catch (error) {
        logger(`legacy storage read failed: ${error.code || error.name}`);
      }
    }
  } finally {
    if (legacyServer) await new Promise(resolve => legacyServer.close(resolve));
  }
  if (snapshots.length === 0) {
    writeMarker(markerPath, "no-data");
    return "no-data";
  }
  const target = new BrowserWindow({
    show: false,
    width: 1,
    height: 1,
    webPreferences: { contextIsolation: false, nodeIntegration: false },
  });
  try {
    await target.loadURL(targetUrl);
    for (const snapshot of snapshots) {
      await target.webContents.executeJavaScript(buildImportScript(snapshot), true);
    }
    writeMarker(markerPath, "migrated");
    return "migrated";
  } catch (error) {
    logger(`legacy storage import failed: ${error.code || error.name}`);
    return "failed";
  } finally {
    destroyWindow(target);
  }
}

module.exports = {
  LEGACY_HTTP_PORT,
  buildImportScript,
  hasSnapshotData,
  migrateLegacyStorage,
};
