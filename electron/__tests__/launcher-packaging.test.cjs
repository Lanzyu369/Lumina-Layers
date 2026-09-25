"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ELECTRON_DIR = path.join(__dirname, "..");

test("the full desktop includes the startup reporter and an explicit resource protocol marker", () => {
  const config = readJson("package.json").build;
  assert.ok(config.files.includes("managed-startup.cjs"));
  assert.ok(config.extraResources.some(item => item.from === "launcher-startup.json" && item.to === "launcher-startup.json"));
  assert.deepEqual(readJson("launcher-startup.json"), { protocol: 1 });
});

function readJson(name) {
  return JSON.parse(fs.readFileSync(path.join(ELECTRON_DIR, name), "utf8"));
}
