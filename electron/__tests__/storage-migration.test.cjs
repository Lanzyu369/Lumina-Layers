"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const migration = require("../storage-migration.cjs");

test("legacy storage snapshots detect localStorage and IndexedDB data", () => {
  assert.equal(migration.hasSnapshotData({ schemaVersion: 1, localStorage: { theme: "dark" }, indexedDB: [] }), true);
  assert.equal(migration.hasSnapshotData({ schemaVersion: 1, localStorage: {}, indexedDB: [{ name: "lumina-workshop" }] }), true);
  assert.equal(migration.hasSnapshotData({ schemaVersion: 1, localStorage: {}, indexedDB: [] }), false);
});

test("import script preserves ordinary localStorage and IndexedDB records", () => {
  const script = migration.buildImportScript({
    schemaVersion: 1,
    localStorage: { "lumina-settings": JSON.stringify({ language: "zh" }) },
    indexedDB: [{
      name: "lumina-workshop",
      version: 2,
      stores: [{
        name: "projects",
        keyPath: "key",
        autoIncrement: false,
        indexes: [{ name: "updatedAt", keyPath: "updatedAt", unique: false, multiEntry: false }],
        records: [{ key: "module:project", value: { key: "module:project", updatedAt: "2026-09-21" } }],
      }],
    }],
  });
  assert.match(script, /localStorage\.setItem/);
  assert.match(script, /indexedDB\.open/);
  assert.match(script, /module:project/);
  assert.throws(() => migration.buildImportScript({ localStorage: { huge: "x".repeat(257 * 1024 * 1024) }, indexedDB: [] }), /too_large/);
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
      this.webContents = {
        executeJavaScript: async code => {
          if (code.includes("localStorage.setItem")) return true;
          return { schemaVersion: 1, localStorage: { migrated: "yes" }, indexedDB: [] };
        },
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
    targetUrl: "http://127.0.0.1:8001/",
    markerPath,
  }), "migrated");
  assert.equal(JSON.parse(fs.readFileSync(markerPath, "utf8")).status, "migrated");
  assert.equal(windows.at(-1).url, "http://127.0.0.1:8001/");
  assert.equal(await migration.migrateLegacyStorage({
    BrowserWindow: FakeWindow,
    indexPath,
    targetUrl: "http://127.0.0.1:8001/",
    markerPath,
  }), "already-migrated");
});
