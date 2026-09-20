"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const helperPath = path.join(__dirname, "../backend-endpoint.cjs");
function helper() {
  assert.ok(fs.existsSync(helperPath), "desktop must provide an owned backend endpoint helper");
  return require(helperPath);
}
async function server(t, handler, port = 0) {
  const instance = http.createServer(handler);
  await new Promise((resolve, reject) => instance.once("error", reject).listen(port, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => { instance.closeAllConnections(); instance.close(resolve); }));
  return instance;
}
const health = id => JSON.stringify({ status: "ok", service: "lumina-studio", desktop_instance_id: id });

test("busy C-Lodop port is skipped without stopping its owner; new backend identity validates", async t => {
  const foreign = await server(t, (_req, res) => res.end("<html>C-Lodop</html>"));
  const endpoint = await helper().selectBackendEndpoint({ preferredPort: foreign.address().port });
  assert.notEqual(endpoint.port, foreign.address().port);
  assert.match(endpoint.instanceId, /^[a-f0-9]{64}$/);
  assert.equal(foreign.listening, true);
  await server(t, (_req, res) => { res.setHeader("content-type", "application/json"); res.end(health(endpoint.instanceId)); }, endpoint.port);
  assert.equal(await probe(endpoint.healthUrl, endpoint.instanceId), true);
  assert.equal(await (await fetch(`http://127.0.0.1:${foreign.address().port}`)).text(), "<html>C-Lodop</html>");
});

test("selection prefers a free port, generates fresh identities, and fails at bounded exhaustion", async t => {
  const occupied = await server(t, (_req, res) => res.end());
  const port = occupied.address().port;
  await assert.rejects(helper().selectBackendEndpoint({ preferredPort: port, maxAttempts: 1 }), /port_in_use/);
  const first = await helper().selectBackendEndpoint();
  const second = await helper().selectBackendEndpoint({ preferredPort: first.port });
  assert.equal(first.port, second.port);
  assert.notEqual(first.instanceId, second.instanceId);
});

test("persisted port keeps the packaged frontend origin stable across launches", async t => {
  const portFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "lumina-port-state-")), "backend-port.json");
  const first = await helper().selectBackendEndpoint({ portFile, preferredPort: 8100 });
  assert.equal(JSON.parse(fs.readFileSync(portFile, "utf8")).port, first.port);
  const second = await helper().selectBackendEndpoint({ portFile, preferredPort: 8100 });
  assert.equal(second.port, first.port);
  assert.notEqual(second.instanceId, first.instanceId);
});

test("a persisted port collision fails instead of silently changing the storage origin", async t => {
  const portFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "lumina-port-state-")), "backend-port.json");
  const first = await helper().selectBackendEndpoint({ portFile, preferredPort: 8101 });
  const owner = await server(t, (_req, res) => res.end("foreign"), first.port);
  await assert.rejects(
    helper().selectBackendEndpoint({ portFile, preferredPort: 8101 }),
    new RegExp(`stable_backend_port:${first.port}`),
  );
  assert.equal(owner.listening, true);
});

async function probe(url, id) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, res => helper().validateHealthResponse(res, id, valid => { req.destroy(); resolve(valid); }));
    req.on("error", reject);
  });
}

for (const [label, status, type, body] of [
  ["HTML200", 200, "text/html", "<html>C-Lodop</html>"],
  ["redirect", 302, "application/json", health("owned")],
  ["wrong service", 200, "application/json", health("owned").replace("lumina-studio", "another-service")],
  ["old instance", 200, "application/json", health("old")],
  ["missing instance", 200, "application/json", '{"status":"ok","service":"lumina-studio"}'],
  ["malformed", 200, "application/json", "{"],
  ["oversized", 200, "application/json", " ".repeat(17000) + health("owned")],
  ["unhealthy", 200, "application/json", health("owned").replace('"ok"', '"error"')],
]) {
  test(`health rejects ${label}`, async t => {
    const instance = await server(t, (_req, res) => { res.writeHead(status, { "content-type": type }); res.end(body); });
    assert.equal(await probe(`http://127.0.0.1:${instance.address().port}/api/health`, "owned"), false);
  });
}

test("valid JSON with charset and split chunks is accepted", async t => {
  const instance = await server(t, (_req, res) => {
    res.setHeader("content-type", "application/json; charset=utf-8");
    res.write(health("owned").slice(0, 12)); res.end(health("owned").slice(12));
  });
  assert.equal(await probe(`http://127.0.0.1:${instance.address().port}/api/health`, "owned"), true);
});
