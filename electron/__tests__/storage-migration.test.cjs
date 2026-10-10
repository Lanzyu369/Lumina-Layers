"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");

const migration = require("../storage-migration.cjs");

test("legacy storage snapshots detect localStorage and IndexedDB data", () => {
  assert.equal(migration.hasSnapshotData({ schemaVersion: 1, localStorage: { theme: "dark" }, indexedDB: [] }), true);
  assert.equal(migration.hasSnapshotData({ schemaVersion: 1, localStorage: {}, indexedDB: [{ name: "lumina-workshop" }] }), true);
  assert.equal(migration.hasSnapshotData({ schemaVersion: 1, localStorage: {}, indexedDB: [] }), false);
});

test("import script preserves ordinary localStorage and IndexedDB records", () => {
  const script = migration.buildImportScript();
  assert.match(script, /localStorage\.setItem/);
  assert.match(script, /localStorage\.getItem/);
  assert.match(script, /indexedDB\.open/);
  assert.match(script, /getKey/);
  assert.match(script, /applicationDatabaseVersion = 2/);
  assert.doesNotMatch(script, /Math\.max\([^\n]+\) \+ 1/);
  assert.match(script, /__luminaMigrationReceive/);
  assert.doesNotMatch(script, /module:project/);
});

test("merges legacy sources without choosing conflicting values by order", () => {
  const merged = migration.mergeSnapshots([
    {
      schemaVersion: 1,
      localStorage: { theme: "dark", keepA: "a" },
      indexedDB: [{
        name: "lumina-workshop",
        version: 2,
        stores: [{
          name: "projects",
          keyPath: "key",
          autoIncrement: false,
          indexes: [],
          records: [{ key: "module:old", value: { source: "file" } }],
        }],
      }],
    },
    {
      schemaVersion: 1,
      localStorage: { theme: "light", keepB: "b" },
      indexedDB: [{
        name: "lumina-workshop",
        version: 2,
        stores: [{
          name: "projects",
          keyPath: "key",
          autoIncrement: false,
          indexes: [],
          records: [{ key: "module:old", value: { source: "http" } }],
        }],
      }],
    },
  ]);
  assert.equal(merged.conflictCount, 2);
  assert.deepEqual(merged.snapshot.localStorage, { keepA: "a", keepB: "b" });
  const projectStore = merged.snapshot.indexedDB
    .find(database => database.name === "lumina-workshop")
    .stores.find(store => store.name === "projects");
  assert.deepEqual(projectStore.records, []);
  assert.deepEqual(
    merged.snapshot.indexedDB.find(database => database.name === "lumina-workshop")
      .stores.map(store => store.name).sort(),
    ["metadata", "projects", "snapshots"],
  );
});

test("snapshot transfer preserves structured-clone project values", () => {
  const blob = new Blob(["lumina"], { type: "text/plain" });
  const snapshot = {
    schemaVersion: 1,
    localStorage: {},
    indexedDB: [{
      name: "lumina-workshop",
      version: 2,
      stores: [{
        name: "projects",
        keyPath: "key",
        autoIncrement: false,
        indexes: [],
        records: [{
          key: "module:project",
          value: {
            bytes: new Uint8Array([1, 2, 3]),
            buffer: new ArrayBuffer(2),
            blob,
            date: new Date("2026-09-21T00:00:00.000Z"),
            map: new Map([["kind", "project"]]),
            set: new Set(["lumina"]),
            big: 42n,
          },
        }],
      }],
    }],
  };
  const transferred = migration.cloneSnapshotForTransfer(snapshot);
  const value = transferred.indexedDB[0].stores[0].records[0].value;
  assert.deepEqual([...value.bytes], [1, 2, 3]);
  assert.ok(value.buffer instanceof ArrayBuffer);
  assert.equal(value.blob.type, "text/plain");
  assert.equal(value.date.toISOString(), "2026-09-21T00:00:00.000Z");
  assert.deepEqual([...value.map.entries()], [["kind", "project"]]);
  assert.deepEqual([...value.set.values()], ["lumina"]);
  assert.equal(value.big, 42n);
});

test("migration reads legacy sources, imports into the target, and becomes idempotent", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-storage-migration-"));
  const indexPath = path.join(root, "index.html");
  const markerPath = path.join(root, "legacy-storage-migration.json");
  fs.writeFileSync(indexPath, "<!doctype html>");
  const windows = [];
  class FakeWindow {
    constructor() {
      this.url = null;
      this.destroyed = false;
      this.sent = [];
      this.webContents = {
        executeJavaScript: async code => {
          if (code.includes("__luminaMigrationReceive")) return { ok: true };
          return { schemaVersion: 1, localStorage: { migrated: "yes" }, indexedDB: [] };
        },
        send: (_channel, payload) => { this.sent.push(payload); },
      };
      windows.push(this);
    }
    loadURL(url) { this.url = url; return Promise.resolve(); }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  }

  assert.equal(await migration.migrateLegacyStorage({
    BrowserWindow: FakeWindow,
    indexPath,
    targetUrl: "http://127.0.0.1:8001/api/health",
    markerPath,
  }), "migrated");
  assert.equal(JSON.parse(fs.readFileSync(markerPath, "utf8")).status, "migrated");
  assert.equal(windows.at(-1).url, "http://127.0.0.1:8001/api/health");
  assert.equal(windows.at(-1).sent.length, 1);
  assert.equal(await migration.migrateLegacyStorage({
    BrowserWindow: FakeWindow,
    indexPath,
    targetUrl: "http://127.0.0.1:8001/api/health",
    markerPath,
  }), "already-migrated");
});

test("migration defers completion when the legacy HTTP origin is occupied", async t => {
  const blocker = net.createServer();
  await new Promise((resolve, reject) => {
    blocker.once("error", reject);
    blocker.listen({ port: migration.LEGACY_HTTP_PORT, host: "127.0.0.1", exclusive: true }, resolve);
  }).catch(error => {
    if (error.code === "EADDRINUSE") {
      t.skip("legacy migration port is already occupied by the test environment");
      return;
    }
    throw error;
  });
  if (!blocker.listening) return;
  t.after(() => blocker.close());

  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-storage-migration-deferred-"));
  const indexPath = path.join(root, "index.html");
  const markerPath = path.join(root, "legacy-storage-migration.json");
  fs.writeFileSync(indexPath, "<!doctype html>");
  fs.writeFileSync(markerPath, JSON.stringify({ schemaVersion: 1, status: "no-data" }));
  class FakeWindow {
    constructor() {
      this.destroyed = false;
      this.webContents = {
        executeJavaScript: async () => ({ schemaVersion: 1, localStorage: {}, indexedDB: [] }),
        send: () => {},
      };
    }
    loadURL() { return Promise.resolve(); }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  }

  assert.equal(await migration.migrateLegacyStorage({
    BrowserWindow: FakeWindow,
    indexPath,
    targetUrl: "http://127.0.0.1:8001/api/health",
    markerPath,
  }), "deferred");
  assert.equal(JSON.parse(fs.readFileSync(markerPath, "utf8")).schemaVersion, 1);
});

test("the current legacy origin does not require a second listener", async t => {
  const blocker = net.createServer();
  await new Promise((resolve, reject) => {
    blocker.once("error", reject);
    blocker.listen({ port: migration.LEGACY_HTTP_PORT, host: "127.0.0.1", exclusive: true }, resolve);
  }).catch(error => {
    if (error.code === "EADDRINUSE") {
      t.skip("legacy migration port is already occupied by the test environment");
      return;
    }
    throw error;
  });
  if (!blocker.listening) return;
  t.after(() => blocker.close());

  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-storage-migration-current-origin-"));
  const indexPath = path.join(root, "index.html");
  const markerPath = path.join(root, "legacy-storage-migration.json");
  fs.writeFileSync(indexPath, "<!doctype html>");
  class FakeWindow {
    constructor() {
      this.destroyed = false;
      this.webContents = {
        executeJavaScript: async () => ({ schemaVersion: 1, localStorage: {}, indexedDB: [] }),
        send: () => {},
      };
    }
    loadURL() { return Promise.resolve(); }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  }

  assert.equal(await migration.migrateLegacyStorage({
    BrowserWindow: FakeWindow,
    indexPath,
    targetUrl: "http://127.0.0.1:8000/api/health",
    markerPath,
  }), "no-data");
  assert.equal(JSON.parse(fs.readFileSync(markerPath, "utf8")).status, "no-data");
});

test("source read failure does not create a completion marker", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-storage-migration-read-failure-"));
  const indexPath = path.join(root, "index.html");
  const markerPath = path.join(root, "legacy-storage-migration.json");
  fs.writeFileSync(indexPath, "<!doctype html>");
  class FakeWindow {
    constructor() {
      this.destroyed = false;
      this.webContents = {
        executeJavaScript: async () => ({ schemaVersion: 1, ok: false, error: "legacy_indexeddb_read_failed" }),
        send: () => {},
      };
    }
    loadURL() { return Promise.resolve(); }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  }

  assert.equal(await migration.migrateLegacyStorage({
    BrowserWindow: FakeWindow,
    indexPath,
    targetUrl: "http://127.0.0.1:8000/api/health",
    markerPath,
  }), "deferred");
  assert.equal(fs.existsSync(markerPath), false);
});

test("import failure does not create a completion marker", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-storage-migration-write-failure-"));
  const indexPath = path.join(root, "index.html");
  const markerPath = path.join(root, "legacy-storage-migration.json");
  fs.writeFileSync(indexPath, "<!doctype html>");
  class FakeWindow {
    constructor() {
      this.destroyed = false;
      this.webContents = {
        executeJavaScript: async code => code.includes("__luminaMigrationReceive")
          ? { ok: false, error: "legacy_indexeddb_write_failed" }
          : { schemaVersion: 1, localStorage: { migrated: "yes" }, indexedDB: [] },
        send: () => {},
      };
    }
    loadURL() { return Promise.resolve(); }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  }

  assert.equal(await migration.migrateLegacyStorage({
    BrowserWindow: FakeWindow,
    indexPath,
    targetUrl: "http://127.0.0.1:8000/api/health",
    markerPath,
  }), "failed");
  assert.equal(fs.existsSync(markerPath), false);
});

test("dedicated handover replaces settings, including source deletions and an empty source", async () => {
  for (const source of [{ theme: "latest" }, {}]) {
    const values = new Map([["theme", "stale"], ["removed", "obsolete"]]);
    const result = await vm.runInNewContext(migration.buildImportScript({ replace: true }), {
      globalThis: { __luminaMigrationReceive: () => Promise.resolve({ localStorage: source, indexedDB: [] }) },
      localStorage: {
        getItem: key => values.has(key) ? values.get(key) : null,
        setItem: (key, value) => values.set(key, value),
        clear: () => values.clear(),
      },
      Blob, RegExp, ArrayBuffer, Map, Set, Date,
    });
    assert.equal(result.ok, true);
    assert.deepEqual(Object.fromEntries(values), source, "the committed source is authoritative, not a fill-missing import");
  }
});

test("default legacy settings import still fills gaps without overwriting user edits", async () => {
  const values = new Map([["theme", "edited"]]);
  const result = await vm.runInNewContext(migration.buildImportScript(), {
    globalThis: { __luminaMigrationReceive: () => Promise.resolve({ localStorage: { theme: "old", extra: "new" }, indexedDB: [] }) },
    localStorage: { getItem: key => values.has(key) ? values.get(key) : null, setItem: (key, value) => values.set(key, value) },
    Blob, RegExp, ArrayBuffer, Map, Set, Date,
  });
  assert.equal(result.ok, true);
  assert.deepEqual(Object.fromEntries(values), { theme: "edited", extra: "new" });
});

test("handover source failure closes its window and removes all temporary HTTP interception", async () => {
  assert.equal(typeof migration.handoverBackendStorage, "function", "dedicated handover must fail closed instead of opening an empty UI");
  const windows = [];
  let handler;
  let unhandled = 0;
  const storageSession = { protocol: {
    handle: async (scheme, callback) => { assert.equal(scheme, "http"); handler = callback; },
    unhandle: async scheme => { assert.equal(scheme, "http"); handler = null; unhandled++; },
  } };
  class FailedSourceWindow {
    constructor(options) {
      this.options = options;
      this.webContents = { executeJavaScript: async () => ({ ok: false, error: "legacy_indexeddb_read_failed" }) };
      windows.push(this);
    }
    async loadURL(url) {
      assert.ok(handler, "interception must be registered before any old-origin navigation");
      const inert = await handler({ url, method: "GET" });
      assert.equal(inert.status, 200);
      assert.doesNotMatch(await inert.text(), /<script|src=/);
      assert.equal((await handler({ url: "http://127.0.0.1:8100/foreign", method: "GET" })).status, 403);
    }
    isDestroyed() { return Boolean(this.destroyed); }
    destroy() { this.destroyed = true; }
  }
  await assert.rejects(migration.handoverBackendStorage({
    BrowserWindow: FailedSourceWindow, storageSession,
    sourceOrigin: "http://127.0.0.1:8100", targetOrigin: "http://127.0.0.1:8101",
  }), error => error.code === "storage_handover_failed" && error.stage === "storage_source_read");
  assert.equal(unhandled, 1);
  assert.equal(handler, null);
  assert.equal(windows.length, 1);
  assert.equal(windows[0].destroyed, true);
  assert.equal(windows[0].options.webPreferences.session, storageSession);
  assert.equal(windows[0].options.webPreferences.webSecurity, true);
});
