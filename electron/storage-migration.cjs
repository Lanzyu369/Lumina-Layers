"use strict";

const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { isDeepStrictEqual } = require("node:util");
const { fileURLToPath, pathToFileURL } = require("node:url");

const MIGRATION_VERSION = 2;
const APPLICATION_DATABASE_NAME = "lumina-workshop";
const APPLICATION_DATABASE_VERSION = 2;
const APPLICATION_DATABASE_STORES = [
  {
    name: "projects",
    keyPath: "key",
    autoIncrement: false,
    indexes: [
      { name: "updatedAt", keyPath: "updatedAt", unique: false, multiEntry: false },
      { name: "moduleId", keyPath: "moduleId", unique: false, multiEntry: false },
    ],
  },
  {
    name: "snapshots",
    keyPath: "key",
    autoIncrement: false,
    indexes: [{ name: "moduleId", keyPath: "moduleId", unique: false, multiEntry: false }],
  },
  { name: "metadata", keyPath: "key", autoIncrement: false, indexes: [] },
];
const LEGACY_HTTP_PORT = 8000;
const MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024;
const MIGRATION_CHANNEL = "lumina-migration-payload";
const MIGRATION_PRELOAD_PATH = path.join(__dirname, "storage-migration-preload.cjs");

const EXPORT_SCRIPT = `
(async () => {
  const result = { schemaVersion: 1, ok: true, localStorage: {}, indexedDB: [] };
  const encodeTransferValue = async (value, seen = new WeakMap()) => {
    if (value === null || typeof value !== "object") return value;
    if (value instanceof Blob) {
      return {
        __luminaMigrationType: "Blob",
        type: value.type,
        bytes: await value.arrayBuffer(),
      };
    }
    if (value instanceof Date || value instanceof ArrayBuffer || ArrayBuffer.isView(value)) return value;
    if (typeof SharedArrayBuffer !== "undefined" && value instanceof SharedArrayBuffer) return value;
    if (seen.has(value)) return seen.get(value);
    if (value instanceof Map) {
      const output = new Map();
      seen.set(value, output);
      for (const [key, item] of value) output.set(await encodeTransferValue(key, seen), await encodeTransferValue(item, seen));
      return output;
    }
    if (value instanceof Set) {
      const output = new Set();
      seen.set(value, output);
      for (const item of value) output.add(await encodeTransferValue(item, seen));
      return output;
    }
    if (Array.isArray(value)) {
      const output = [];
      seen.set(value, output);
      for (const item of value) output.push(await encodeTransferValue(item, seen));
      return output;
    }
    const output = {};
    seen.set(value, output);
    for (const [key, item] of Object.entries(value)) output[key] = await encodeTransferValue(item, seen);
    return output;
  };
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key !== null) result.localStorage[key] = localStorage.getItem(key);
    }
  } catch (_) {
    return { schemaVersion: 1, ok: false, error: "legacy_local_storage_read_failed" };
  }
  if (!globalThis.indexedDB) return result;
  if (typeof indexedDB.databases !== "function") {
    return { schemaVersion: 1, ok: false, error: "legacy_indexeddb_enumeration_unavailable" };
  }
  let databases = [];
  try {
    databases = await indexedDB.databases();
  } catch (_) {
    return { schemaVersion: 1, ok: false, error: "legacy_indexeddb_enumeration_failed" };
  }
  for (const info of databases) {
    if (!info || typeof info.name !== "string" || !info.name) continue;
    let database = null;
    try {
      database = await new Promise((resolve, reject) => {
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
        for (const record of schema.records) record.value = await encodeTransferValue(record.value);
        stores.push(schema);
      }
      result.indexedDB.push({ name: info.name, version: database.version, stores });
    } catch (_) {
      return { schemaVersion: 1, ok: false, error: "legacy_indexeddb_read_failed" };
    } finally {
      try { database?.close(); } catch (_) {}
    }
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

function isBlobValue(value) {
  return Boolean(
    value &&
    typeof value === "object" &&
    typeof value.size === "number" &&
    typeof value.type === "string" &&
    typeof value.arrayBuffer === "function",
  );
}

function estimateSnapshotBytes(value, seen = new WeakSet()) {
  if (value == null) return 1;
  switch (typeof value) {
    case "string": return Buffer.byteLength(value, "utf8");
    case "number":
    case "boolean": return 8;
    case "bigint": return 16;
    case "undefined": return 1;
    case "symbol":
    case "function": throw new Error("legacy_storage_unsupported_value");
    default: break;
  }
  if (seen.has(value)) return 0;
  seen.add(value);
  if (value instanceof ArrayBuffer) return value.byteLength;
  if (typeof SharedArrayBuffer !== "undefined" && value instanceof SharedArrayBuffer) return value.byteLength;
  if (ArrayBuffer.isView(value)) return value.byteLength;
  if (isBlobValue(value)) return value.size;
  if (value instanceof Date) return 16;
  if (value instanceof RegExp) return Buffer.byteLength(value.source, "utf8") + Buffer.byteLength(value.flags, "utf8");
  if (value instanceof Map) {
    let bytes = 16;
    for (const [key, item] of value) bytes += estimateSnapshotBytes(key, seen) + estimateSnapshotBytes(item, seen);
    return bytes;
  }
  if (value instanceof Set) {
    let bytes = 16;
    for (const item of value) bytes += estimateSnapshotBytes(item, seen);
    return bytes;
  }
  if (Array.isArray(value)) return value.reduce((total, item) => total + estimateSnapshotBytes(item, seen), 16);
  let bytes = 16;
  for (const [key, item] of Object.entries(value)) {
    bytes += Buffer.byteLength(key, "utf8") + estimateSnapshotBytes(item, seen);
  }
  return bytes;
}

function cloneSnapshotForTransfer(snapshot) {
  if (typeof structuredClone !== "function") throw new Error("legacy_storage_structured_clone_unavailable");
  const cloned = structuredClone(snapshot);
  if (estimateSnapshotBytes(cloned) > MAX_SNAPSHOT_BYTES) throw new Error("legacy_storage_snapshot_too_large");
  return cloned;
}

function databaseTemplate() {
  return {
    name: APPLICATION_DATABASE_NAME,
    version: APPLICATION_DATABASE_VERSION,
    stores: APPLICATION_DATABASE_STORES.map(schema => ({
      ...schema,
      indexes: schema.indexes.map(index => ({ ...index })),
      records: [],
    })),
  };
}

function findRecord(records, key) {
  return records.findIndex(record => isDeepStrictEqual(record.key, key));
}

/**
 * Merge all readable legacy origins before crossing the Electron boundary.
 * Conflicting values are deliberately omitted instead of choosing by source order.
 */
function mergeSnapshots(snapshots) {
  const merged = {
    schemaVersion: 1,
    ok: true,
    localStorage: {},
    indexedDB: [],
  };
  const conflictingLocalStorage = new Set();
  const conflictingRecords = new Map();
  let database = null;
  let conflictCount = 0;

  for (const snapshot of snapshots) {
    for (const [key, value] of Object.entries(snapshot?.localStorage || {})) {
      if (conflictingLocalStorage.has(key)) continue;
      if (!Object.prototype.hasOwnProperty.call(merged.localStorage, key)) {
        merged.localStorage[key] = value;
        continue;
      }
      if (isDeepStrictEqual(merged.localStorage[key], value)) continue;
      delete merged.localStorage[key];
      conflictingLocalStorage.add(key);
      conflictCount += 1;
    }

    for (const sourceDatabase of snapshot?.indexedDB || []) {
      if (!sourceDatabase || sourceDatabase.name !== APPLICATION_DATABASE_NAME) {
        conflictCount += 1;
        continue;
      }
      if (Number(sourceDatabase.version) > APPLICATION_DATABASE_VERSION) {
        conflictCount += 1;
        continue;
      }
      if (!database) database = databaseTemplate();
      for (const sourceStore of sourceDatabase.stores || []) {
        const targetStore = database.stores.find(store => store.name === sourceStore.name);
        if (!targetStore) {
          conflictCount += 1;
          continue;
        }
        const conflictKeys = conflictingRecords.get(targetStore.name) || [];
        conflictingRecords.set(targetStore.name, conflictKeys);
        for (const record of sourceStore.records || []) {
          if (conflictKeys.some(key => isDeepStrictEqual(key, record.key))) continue;
          const index = findRecord(targetStore.records, record.key);
          if (index < 0) {
            targetStore.records.push({ key: record.key, value: record.value });
            continue;
          }
          if (isDeepStrictEqual(targetStore.records[index].value, record.value)) continue;
          targetStore.records.splice(index, 1);
          conflictKeys.push(record.key);
          conflictCount += 1;
        }
      }
    }
  }

  if (database) merged.indexedDB.push(database);
  return { snapshot: merged, conflictCount };
}

function buildImportScript() {
  return `
(async () => {
  const snapshot = await globalThis.__luminaMigrationReceive();
  if (!snapshot || typeof snapshot !== "object") return { ok: false, error: "legacy_snapshot_missing" };
  const applicationDatabaseVersion = 2;
  const applicationDatabaseName = "lumina-workshop";
  const applicationDatabaseSchema = ${JSON.stringify(APPLICATION_DATABASE_STORES)};
  const sameKeyPath = (left, right) => JSON.stringify(left) === JSON.stringify(right);
  const reviveTransferValue = value => {
    if (value === null || typeof value !== "object") return value;
    if (value.__luminaMigrationType === "Blob" && value.bytes instanceof ArrayBuffer) {
      return new Blob([value.bytes], { type: typeof value.type === "string" ? value.type : "" });
    }
    if (Array.isArray(value)) return value.map(reviveTransferValue);
    if (value instanceof Map) return new Map([...value.entries()].map(([key, item]) => [reviveTransferValue(key), reviveTransferValue(item)]));
    if (value instanceof Set) return new Set([...value.values()].map(reviveTransferValue));
    if (value instanceof Date || value instanceof ArrayBuffer || ArrayBuffer.isView(value)) return value;
    const output = {};
    for (const [key, item] of Object.entries(value)) output[key] = reviveTransferValue(item);
    return output;
  };
  const schemaIsCurrent = database => applicationDatabaseSchema.every(expected => {
    if (!database.objectStoreNames.contains(expected.name)) return false;
    const store = database.transaction([expected.name], "readonly").objectStore(expected.name);
    if (!sameKeyPath(store.keyPath, expected.keyPath) || store.autoIncrement !== expected.autoIncrement) return false;
    return expected.indexes.every(index => {
      if (!store.indexNames.contains(index.name)) return false;
      const actual = store.index(index.name);
      return sameKeyPath(actual.keyPath, index.keyPath) &&
        actual.unique === index.unique && actual.multiEntry === index.multiEntry;
    });
  });
  for (const [key, value] of Object.entries(snapshot.localStorage || {})) {
    try {
      if (localStorage.getItem(key) !== null) continue;
      localStorage.setItem(key, value == null ? "" : String(value));
    } catch (_) {
      return { ok: false, error: "legacy_local_storage_write_failed" };
    }
  }
  for (const database of snapshot.indexedDB || []) {
    if (!database || database.name !== applicationDatabaseName) return { ok: false, error: "legacy_database_not_supported" };
    if (Number(database.version) > applicationDatabaseVersion) return { ok: false, error: "legacy_database_version_newer" };
    try {
      const existing = await new Promise((resolve, reject) => {
        const request = indexedDB.open(database.name);
        request.onerror = () => reject(request.error || new Error("IndexedDB version probe failed"));
        request.onsuccess = () => { const db = request.result; const version = db.version; db.close(); resolve(version); };
      });
      if (Number(existing) > applicationDatabaseVersion) return { ok: false, error: "legacy_target_database_version_newer" };
      const opened = await new Promise((resolve, reject) => {
        const request = indexedDB.open(database.name, applicationDatabaseVersion);
        request.onerror = () => reject(request.error || new Error("IndexedDB import open failed"));
        request.onblocked = () => reject(new Error("IndexedDB import blocked"));
        request.onupgradeneeded = () => {
          const db = request.result;
          for (const schema of applicationDatabaseSchema) {
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
      if (!schemaIsCurrent(writable)) {
        writable.close();
        return { ok: false, error: "legacy_database_schema_missing" };
      }
      const recordsByStore = new Map((database.stores || []).map(schema => [schema.name, schema.records || []]));
      await new Promise((resolve, reject) => {
        const transaction = writable.transaction(applicationDatabaseSchema.map(schema => schema.name), "readwrite");
        const queue = applicationDatabaseSchema.flatMap(schema =>
          (recordsByStore.get(schema.name) || []).map(record => ({ schema, record })),
        );
        let position = 0;
        const fail = error => { try { transaction.abort(); } catch (_) {} reject(error); };
        const next = () => {
          if (position >= queue.length) return;
          const { schema, record } = queue[position++];
          const store = transaction.objectStore(schema.name);
          let keyRequest;
          try { keyRequest = store.getKey(record.key); } catch (error) { fail(error); return; }
          keyRequest.onerror = () => fail(keyRequest.error || new Error("IndexedDB key lookup failed"));
          keyRequest.onsuccess = () => {
            if (keyRequest.result !== undefined) { next(); return; }
            let putRequest;
            try {
              const value = reviveTransferValue(record.value);
              putRequest = store.keyPath == null ? store.put(value, record.key) : store.put(value);
            } catch (error) { fail(error); return; }
            putRequest.onerror = () => fail(putRequest.error || new Error("IndexedDB import record failed"));
            putRequest.onsuccess = next;
          };
        };
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error || new Error("IndexedDB import transaction failed"));
        transaction.onabort = () => reject(transaction.error || new Error("IndexedDB import transaction aborted"));
        next();
      });
      writable.close();
    } catch (_) {
      return { ok: false, error: "legacy_indexeddb_write_failed" };
    }
  }
  return { ok: true };
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

async function destroyWindow(window) {
  if (!window || window.isDestroyed?.()) return;
  if (typeof window.close !== "function") {
    window.destroy?.();
    return;
  }
  await new Promise(resolve => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    window.once?.("closed", finish);
    window.close();
    setTimeout(() => {
      if (!window.isDestroyed?.()) window.destroy?.();
      finish();
    }, 1000);
  });
}

async function readSnapshot(BrowserWindow, url, load) {
  const window = new BrowserWindow({
    show: false,
    width: 1,
    height: 1,
    webPreferences: {
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false,
      preload: MIGRATION_PRELOAD_PATH,
    },
  });
  try {
    await load(window, url);
    const snapshot = await window.webContents.executeJavaScript(EXPORT_SCRIPT, true);
    if (!snapshot || snapshot.ok === false) throw new Error(snapshot?.error || "legacy_storage_read_failed");
    return snapshot;
  } finally {
    await destroyWindow(window);
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

async function migrateLegacyStorage({
  BrowserWindow,
  indexPath,
  targetUrl,
  markerPath,
  logger = () => {},
  legacyHttpPort = LEGACY_HTTP_PORT,
}) {
  if (markerExists(markerPath)) return "already-migrated";
  if (!fs.existsSync(indexPath)) return "no-index";
  const snapshots = [];
  const sources = [{
    url: pathToFileURL(indexPath).href,
    load: (window, url) => window.loadFile ? window.loadFile(indexPath) : window.loadURL(url),
  }];
  let allSourcesReadable = true;
  let targetOrigin;
  try {
    targetOrigin = new URL(targetUrl).origin;
  } catch (_) {
    return "failed";
  }
  let legacyServer = null;
  if (legacyHttpPort !== null) {
    const legacyHttpOrigin = `http://127.0.0.1:${legacyHttpPort}`;
    if (targetOrigin !== legacyHttpOrigin) {
      try {
        legacyServer = await startLegacyHttpHost(legacyHttpPort);
        sources.push({ url: `${legacyHttpOrigin}/`, load: (window, url) => window.loadURL(url) });
      } catch (error) {
        allSourcesReadable = false;
        logger(`legacy HTTP storage source unavailable: ${error.code || error.name}`);
      }
    }
  }
  try {
    for (const source of sources) {
      try {
        const snapshot = await readSnapshot(BrowserWindow, source.url, source.load);
        if (hasSnapshotData(snapshot)) snapshots.push(snapshot);
      } catch (error) {
        allSourcesReadable = false;
        logger(`legacy storage read failed: ${error.code || error.name}: ${error.message || "unknown"}`);
      }
    }
  } finally {
    if (legacyServer) await new Promise(resolve => legacyServer.close(resolve));
  }
  if (snapshots.length === 0) {
    if (!allSourcesReadable) return "deferred";
    writeMarker(markerPath, "no-data");
    return "no-data";
  }
  const target = new BrowserWindow({
    show: false,
    width: 1,
    height: 1,
    webPreferences: {
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false,
      preload: MIGRATION_PRELOAD_PATH,
    },
  });
  try {
    if (targetUrl.startsWith("file://") && target.loadFile) {
      await target.loadFile(fileURLToPath(targetUrl));
    } else {
      await target.loadURL(targetUrl);
    }
    const merged = mergeSnapshots(snapshots);
    if (merged.conflictCount > 0) logger(`legacy storage conflicts omitted: ${merged.conflictCount}`);
    if (!hasSnapshotData(merged.snapshot)) return allSourcesReadable ? "partial" : "deferred";
    target.webContents.send(MIGRATION_CHANNEL, cloneSnapshotForTransfer(merged.snapshot));
    const result = await target.webContents.executeJavaScript(buildImportScript(), true);
    if (!result || result.ok !== true) throw new Error(result?.error || "legacy_storage_import_failed");
    if (allSourcesReadable && merged.conflictCount === 0) {
      writeMarker(markerPath, "migrated");
      return "migrated";
    }
    return "partial";
  } catch (error) {
    logger(`legacy storage import failed: ${error.code || error.name}: ${error.message || "unknown"}`);
    return "failed";
  } finally {
    await destroyWindow(target);
  }
}

module.exports = {
  MIGRATION_CHANNEL,
  LEGACY_HTTP_PORT,
  buildImportScript,
  cloneSnapshotForTransfer,
  hasSnapshotData,
  mergeSnapshots,
  migrateLegacyStorage,
};
