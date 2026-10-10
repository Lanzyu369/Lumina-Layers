"use strict";

// Run each phase in a separate Electron 35 process with the same isolated root.
// See port-recovery-electron.e2e.md for the exact build and invocation contract.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { app, BrowserWindow, session } = require("electron");
const { selectBackendEndpoint, commitBackendEndpoint, validateHealthResponse } = require("../backend-endpoint.cjs");
const { handoverBackendStorage } = require("../storage-migration.cjs");

const ROOT = process.env.LUMINA_PORT_E2E_ROOT;
const MODULE_FILE = process.env.LUMINA_PORT_E2E_MODULE;
const PHASE = process.env.LUMINA_PORT_E2E_PHASE;
assert.ok(ROOT && path.isAbsolute(ROOT), "LUMINA_PORT_E2E_ROOT must be an isolated absolute directory");
assert.ok(MODULE_FILE && path.isAbsolute(MODULE_FILE), "LUMINA_PORT_E2E_MODULE must be the prebundled actual frontend storage module");
assert.ok(["seed", "recover", "restart", "return", "empty"].includes(PHASE), "unknown E2E phase");
fs.mkdirSync(path.join(ROOT, "user-data"), { recursive: true });
app.setPath("userData", path.join(ROOT, "user-data"));
const STATE = path.join(ROOT, "backend-port.json");
const FIXTURE = path.join(ROOT, "fixture.json");
const servers = [];

async function listen(port, handler) {
  const server = http.createServer(handler);
  await new Promise((resolve, reject) => server.once("error", reject).listen({ port, host: "127.0.0.1", exclusive: true }, resolve));
  servers.push(server);
  return server;
}

async function ownedHost(port, instanceId) {
  const moduleBytes = fs.readFileSync(MODULE_FILE);
  return listen(port, (request, response) => {
    if (request.url === "/project-storage.js") {
      response.writeHead(200, { "content-type": "text/javascript", "cache-control": "no-store" });
      response.end(moduleBytes);
    } else if (request.url === "/api/health") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ status: "ok", service: "lumina-studio", desktop_instance_id: instanceId }));
    } else {
      response.writeHead(200, { "content-type": "text/html", "cache-control": "no-store" });
      response.end("<!doctype html><title>Owned port recovery test</title>");
    }
  });
}

async function health(endpoint) {
  const valid = await new Promise((resolve, reject) => {
    const request = http.get(endpoint.healthUrl, response => validateHealthResponse(response, endpoint.instanceId, ok => {
      request.destroy(); resolve(ok);
    }));
    request.once("error", reject);
  });
  assert.equal(valid, true, "handover must follow a health response from this owned backend");
}

async function atOrigin(origin, operation, ...args) {
  const window = new BrowserWindow({ show: false, webPreferences: {
    contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true,
  } });
  try {
    await window.loadURL(`${origin}/`);
    return await window.webContents.executeJavaScript(`(async () => {
      const api = await import("/project-storage.js");
      const result = api.createWorkshopProjectStorage();
      if (!result.persistent || !(result.storage instanceof api.IndexedDbWorkshopProjectStorage)) {
        throw new Error("the real persistent frontend storage implementation is required");
      }
      return (${operation.toString()})(result.storage, ${args.map(value => JSON.stringify(value)).join(",")});
    })()`, true);
  } finally {
    await new Promise(resolve => { window.once("closed", resolve); window.close(); });
  }
}

async function seed(storage, kind) {
  const rich = {
    bytes: new Uint8Array([1, 2, 3]), buffer: new Uint8Array([4, 5]).buffer,
    blob: new Blob(["port-origin"], { type: "text/plain" }),
    date: new Date("2026-10-10T01:02:03.000Z"), regex: /lumina-(old|new)/gi,
    map: new Map([["origin", "committed"]]), set: new Set(["source"]), big: 42n,
    edit: kind,
  };
  const record = projectId => ({ moduleId: "port-e2e", projectId, schemaVersion: "2.0.0-beta",
    createdAt: "2026-10-10T00:00:00.000Z", updatedAt: "2026-10-10T00:00:01.000Z", project: rich });
  localStorage.setItem("lumina-settings", JSON.stringify({ theme: kind }));
  localStorage.setItem("removed-setting", kind);
  await storage.save(record("first"));
  await storage.save(record("removed"));
  if (kind === "stale") await storage.save(record("stale-only"));
  return storage.snapshotModule("port-e2e", "seed");
}

async function inspectAndSave(storage, expectedEdit, nextEdit, expectRemoved, expectedTheme = expectedEdit) {
  const record = await storage.load("port-e2e", "first");
  if (record?.project?.edit !== expectedEdit) throw new Error("wrong authoritative project revision");
  const project = record.project;
  if (!(project.bytes instanceof Uint8Array) || project.bytes.join(",") !== "1,2,3") throw new Error("typed array lost");
  if (!(project.buffer instanceof ArrayBuffer) || new Uint8Array(project.buffer).join(",") !== "4,5") throw new Error("ArrayBuffer lost");
  if (!(project.blob instanceof Blob) || project.blob.type !== "text/plain" || await project.blob.text() !== "port-origin") throw new Error("Blob lost");
  if (!(project.date instanceof Date) || project.date.toISOString() !== "2026-10-10T01:02:03.000Z") throw new Error("Date lost");
  if (!(project.regex instanceof RegExp) || project.regex.source !== "lumina-(old|new)" || project.regex.flags !== "gi") throw new Error("RegExp lost");
  if (!(project.map instanceof Map) || project.map.get("origin") !== "committed") throw new Error("Map lost");
  if (!(project.set instanceof Set) || !project.set.has("source") || project.big !== 42n) throw new Error("Set or BigInt lost");
  if (Boolean(await storage.load("port-e2e", "removed")) !== expectRemoved) throw new Error("removed project was resurrected or lost");
  if (await storage.load("port-e2e", "stale-only")) throw new Error("stale destination project survived");
  if (localStorage.getItem("lumina-settings") !== JSON.stringify({ theme: expectedTheme })) throw new Error("stale settings survived");
  const databases = await indexedDB.databases();
  if (databases.length !== 1 || databases[0].name !== "lumina-workshop" || databases[0].version !== 2) throw new Error("application db2 contract changed");
  await storage.save({ ...record, updatedAt: new Date().toISOString(), project: { ...project, edit: nextEdit } });
  localStorage.setItem("lumina-settings", JSON.stringify({ theme: nextEdit }));
  if ((await storage.load("port-e2e", "first"))?.project?.edit !== nextEdit) throw new Error("frontend save failed");
  return { typesPreserved: true, databaseVersion: databases[0].version, edit: nextEdit };
}

async function storeCounts(storage) {
  // Open through the actual interface first; raw reads inspect all three stores.
  await storage.load("port-e2e", "first");
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("lumina-workshop", 2);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const database = request.result;
      const transaction = database.transaction(["projects", "snapshots", "metadata"], "readonly");
      const counts = {};
      for (const name of ["projects", "snapshots", "metadata"]) {
        const count = transaction.objectStore(name).count();
        count.onsuccess = () => { counts[name] = count.result; };
      }
      transaction.oncomplete = () => { database.close(); resolve(counts); };
      transaction.onerror = () => { database.close(); reject(transaction.error); };
    };
  });
}

async function incompatibleTargetFixture(origin, remove) {
  const window = new BrowserWindow({ show: false, webPreferences: {
    contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true,
  } });
  try {
    await window.loadURL(`${origin}/`);
    await window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
      const request = ${remove ? 'indexedDB.deleteDatabase("lumina-workshop")' : 'indexedDB.open("lumina-workshop", 3)'};
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("test database fixture blocked"));
      request.onsuccess = () => { request.result?.close(); resolve(); };
    })`, true);
  } finally {
    await new Promise(resolve => { window.once("closed", resolve); window.close(); });
  }
}

async function run() {
  assert.equal(typeof handoverBackendStorage, "function", "desktop needs an authoritative, safe port-origin handover");
  if (PHASE === "seed") {
    assert.equal(fs.existsSync(FIXTURE), false, "seed requires a fresh isolated root");
    const host = await ownedHost(0, "seed");
    const port = host.address().port;
    const origin = `http://127.0.0.1:${port}`;
    const snapshotId = await atOrigin(origin, seed, "seed");
    fs.writeFileSync(STATE, JSON.stringify({ schemaVersion: 1, port }));
    fs.writeFileSync(FIXTURE, JSON.stringify({ sourcePort: port, snapshotId }));
    return { phase: PHASE, port, seededWithActualFrontendStorage: true };
  }
  const fixture = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
  if (PHASE === "restart") {
    const endpoint = await selectBackendEndpoint({ portFile: STATE });
    assert.equal(endpoint.port, fixture.targetPort);
    assert.equal(endpoint.previousOrigin, null);
    await ownedHost(endpoint.port, endpoint.instanceId);
    await health(endpoint);
    commitBackendEndpoint({ portFile: STATE, endpoint });
    const edited = await atOrigin(endpoint.origin, inspectAndSave, "recover", "restart", false);
    assert.deepEqual(await atOrigin(endpoint.origin, storeCounts), { projects: 1, snapshots: 0, metadata: 1 });
    return { phase: PHASE, ...edited, fullProcessRestart: true };
  }
  const oldPort = PHASE === "return" ? fixture.targetPort : fixture.sourcePort;
  let foreignRequests = 0;
  const foreign = await listen(oldPort, (_request, response) => {
    foreignRequests++;
    response.writeHead(200, { "content-type": "text/html" });
    response.end('<script>localStorage.clear();fetch("/foreign-executed")</script>');
  });
  const preferredPort = PHASE === "recover" ? oldPort : PHASE === "return" ? fixture.sourcePort : fixture.targetPort;
  const endpoint = await selectBackendEndpoint({ portFile: STATE, preferredPort, maxAttempts: PHASE === "recover" ? 2 : 1, allowEphemeralFallback: true });
  assert.notEqual(endpoint.port, oldPort);
  assert.equal(endpoint.previousOrigin, `http://127.0.0.1:${oldPort}`);
  assert.equal(JSON.parse(fs.readFileSync(STATE, "utf8")).port, oldPort);
  await ownedHost(endpoint.port, endpoint.instanceId);
  await health(endpoint);
  if (PHASE === "recover") {
    await atOrigin(endpoint.origin, seed, "stale");
    await incompatibleTargetFixture(endpoint.origin, false);
    // A real IndexedDB VersionError cannot advance the committed source or
    // leave HTTP interception installed. Retry after removing ONLY this test
    // fixture's intentionally incompatible destination database.
    await assert.rejects(handoverBackendStorage({ BrowserWindow, storageSession: session.defaultSession,
      sourceOrigin: endpoint.previousOrigin, targetOrigin: endpoint.origin }), error =>
      error.code === "storage_handover_failed" && error.stage === "storage_target_import");
    assert.equal(JSON.parse(fs.readFileSync(STATE, "utf8")).port, oldPort);
    assert.equal(await session.defaultSession.protocol.isProtocolHandled("http"), false);
    assert.equal(foreignRequests, 0);
    await incompatibleTargetFixture(endpoint.origin, true);
    await atOrigin(endpoint.origin, seed, "stale");
  }
  if (PHASE === "return") {
    assert.equal(endpoint.port, fixture.sourcePort);
    assert.equal(await atOrigin(endpoint.origin, async storage => Boolean(await storage.load("port-e2e", "removed"))), true,
      "the preserved old source supplies a genuinely stale destination");
  }
  await handoverBackendStorage({ BrowserWindow, storageSession: session.defaultSession,
    sourceOrigin: endpoint.previousOrigin, targetOrigin: endpoint.origin });
  assert.equal(JSON.parse(fs.readFileSync(STATE, "utf8")).port, oldPort, "successful import alone does not advance the origin");
  commitBackendEndpoint({ portFile: STATE, endpoint });
  assert.equal(JSON.parse(fs.readFileSync(STATE, "utf8")).port, endpoint.port);
  assert.equal(foreignRequests, 0, "never fetch or execute a foreign HTTP owner's page");
  assert.equal(foreign.listening, true, "do not terminate the port owner");
  assert.equal(await session.defaultSession.protocol.isProtocolHandled("http"), false, "temporary interception must be removed");
  if (PHASE === "empty") {
    assert.deepEqual(await atOrigin(endpoint.origin, storeCounts), { projects: 0, snapshots: 0, metadata: 0 });
    assert.equal(await atOrigin(endpoint.origin, () => localStorage.length), 0);
    return { phase: PHASE, authoritativeEmptySource: true, foreignRequests, ownerAlive: foreign.listening };
  }
  const edited = await atOrigin(endpoint.origin, inspectAndSave, PHASE === "recover" ? "seed" : "restart", PHASE, PHASE === "recover");
  if (PHASE === "recover") {
    assert.deepEqual(await atOrigin(endpoint.origin, storeCounts), { projects: 2, snapshots: 1, metadata: 2 });
    await atOrigin(endpoint.origin, async (storage, snapshotId) => storage.restoreSnapshot("port-e2e", snapshotId), fixture.snapshotId);
    await atOrigin(endpoint.origin, inspectAndSave, "seed", "recover", true, "recover");
    await atOrigin(endpoint.origin, async (storage, snapshotId) => {
      await storage.remove("port-e2e", "removed");
      await storage.deleteSnapshot("port-e2e", snapshotId);
      localStorage.removeItem("removed-setting");
    }, fixture.snapshotId);
    fixture.targetPort = endpoint.port;
    fs.writeFileSync(FIXTURE, JSON.stringify(fixture));
  } else {
    assert.equal(await atOrigin(endpoint.origin, () => localStorage.getItem("removed-setting")), null);
    assert.deepEqual(await atOrigin(endpoint.origin, storeCounts), { projects: 1, snapshots: 0, metadata: 1 });
    // Next process moves this empty authoritative source back over stale B.
    await atOrigin(endpoint.origin, async storage => { await storage.deleteModuleProjects("port-e2e"); localStorage.clear(); });
  }
  return { phase: PHASE, ...edited, foreignRequests, ownerAlive: foreign.listening,
    ...(PHASE === "recover" ? { realImportFailureRetried: true } : {}) };
}

async function cleanup() {
  for (const window of BrowserWindow.getAllWindows()) window.destroy();
  await Promise.all(servers.map(server => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); })));
}

app.commandLine.appendSwitch("disable-gpu");
app.whenReady().then(run).then(async result => {
  await cleanup();
  await session.defaultSession.flushStorageData();
  process.stdout.write(`${JSON.stringify({ ok: true, ...result })}\n`);
  app.exit(0);
}).catch(async error => {
  await cleanup();
  process.stderr.write(`${error.stack || error}\n`);
  app.exit(1);
});
