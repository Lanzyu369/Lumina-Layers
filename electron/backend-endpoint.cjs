"use strict";
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { randomBytes } = require("node:crypto");

const PORT_STATE_VERSION = 1;

function validatePort(value) {
  return Number.isInteger(value) && value >= 1024 && value <= 65535;
}

function readStablePort(portFile) {
  if (portFile === undefined) return null;
  if (typeof portFile !== "string" || !path.isAbsolute(portFile)) {
    throw new TypeError("Stable backend port file must be an absolute path.");
  }
  if (!fs.existsSync(portFile)) return null;
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(portFile, "utf8"));
  } catch (error) {
    throw new Error(`invalid_backend_port_state:${error.code || error.name}`);
  }
  if (parsed?.schemaVersion !== PORT_STATE_VERSION || !validatePort(parsed.port)) {
    throw new Error("invalid_backend_port_state:unsupported");
  }
  return parsed.port;
}

function writeStablePort(portFile, port) {
  if (portFile === undefined) return;
  const temporary = `${portFile}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`;
  fs.mkdirSync(path.dirname(portFile), { recursive: true });
  fs.writeFileSync(temporary, `${JSON.stringify({ schemaVersion: PORT_STATE_VERSION, port })}\n`, { mode: 0o600 });
  fs.renameSync(temporary, portFile);
}

async function canListen(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", error => {
      if (["EADDRINUSE", "EACCES"].includes(error.code)) resolve(false);
      else reject(error);
    });
    server.listen({ port, host: "127.0.0.1", exclusive: true }, () =>
      server.close(error => error ? reject(error) : resolve(true)));
  });
}

/** Check required local ports without terminating their owners. */
async function assertPortsAvailable(ports) {
  for (const port of ports) {
    await new Promise((resolve, reject) => {
      const server = net.createServer();
      server.once("error", error => reject(new Error(`port_in_use:${port}:${error.code}`)));
      server.listen(port, "127.0.0.1", () => server.close(resolve));
    });
  }
}

/** Pick a bounded loopback endpoint and persist it for a stable desktop origin. */
async function selectBackendEndpoint({ preferredPort = 8000, maxAttempts = 100, portFile } = {}) {
  if (!Number.isInteger(preferredPort) || preferredPort < 1024 || preferredPort > 65535 ||
      !Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 100) {
    throw new TypeError("Invalid backend port range.");
  }
  const stablePort = readStablePort(portFile);
  if (stablePort !== null) {
    if (!(await canListen(stablePort))) {
      throw new Error(`port_in_use:stable_backend_port:${stablePort}`);
    }
    return makeEndpoint(stablePort);
  }
  for (let port = preferredPort; port < Math.min(preferredPort + maxAttempts, 65536); port++) {
    if (await canListen(port)) {
      writeStablePort(portFile, port);
      return makeEndpoint(port);
    }
  }
  throw new Error("port_in_use:no_available_backend_port");
}

function makeEndpoint(port) {
  const origin = `http://127.0.0.1:${port}`;
  return { port, origin, healthUrl: `${origin}/api/health`, instanceId: randomBytes(32).toString("hex") };
}

/** Read only a small JSON health document and verify this launch, not just HTTP success. */
function validateHealthResponse(response, instanceId, done) {
  const limit = 16 * 1024;
  let finished = false;
  const finish = valid => {
    if (finished) return;
    finished = true;
    done(valid);
  };
  if (response.statusCode !== 200 ||
      !/^application\/json(?:\s*;|$)/i.test(response.headers?.["content-type"] || "") ||
      Number(response.headers?.["content-length"]) > limit || !instanceId) {
    finish(false);
    return;
  }
  const chunks = [];
  let bytes = 0;
  response.on("data", chunk => {
    if (finished) return;
    bytes += chunk.length;
    if (bytes > limit) { finish(false); return; }
    chunks.push(chunk);
  });
  response.once("aborted", () => finish(false));
  response.once("error", () => finish(false));
  response.once("end", () => {
    if (finished) return;
    try {
      const data = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      finish(data?.status === "ok" && data?.service === "lumina-studio" && data?.desktop_instance_id === instanceId);
    } catch { finish(false); }
  });
}

module.exports = { assertPortsAvailable, selectBackendEndpoint, validateHealthResponse };
