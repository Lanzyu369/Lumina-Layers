"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const migration = require("../storage-migration.cjs");

test("legacy storage snapshots detect localStorage and IndexedDB data", () => {
  assert.equal(migration.hasSnapshotData({ schemaVersion: 1, localStorage: { theme: "dark" }, indexedDB: [] }), true);
  assert.equal(migration.hasSnapshotData({ schemaVersion: 1, localStorage: {}, indexedDB: [{ name: "lumina-workshop" }] }), true);
  assert.equal(migration.hasSnapshotData({ schemaVersion: 1, localStorage: {}, indexedDB: [] }), false);
});

test("import script preserves ordinary localStorage and IndexedDB records", () => {
  const script = migration.buildImportScript();
  assert.match(script, /localStorage\.setItem/);
  assert.match(script, /indexedDB\.open/);
  assert.match(script, /__luminaMigrationReceive/);
  assert.doesNotMatch(script, /module:project/);
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
  assert.equal(windows.at(-1).sent.length, 2);
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
