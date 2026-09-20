"use strict";
const net = require("node:net");
const { randomBytes } = require("node:crypto");

/** Pick a bounded loopback endpoint without signalling any existing listener. */
async function selectBackendEndpoint({ preferredPort = 8000, maxAttempts = 100 } = {}) {
  if (!Number.isInteger(preferredPort) || preferredPort < 1024 || preferredPort > 65535 ||
      !Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 100) {
    throw new TypeError("Invalid backend port range.");
  }
  for (let port = preferredPort; port < Math.min(preferredPort + maxAttempts, 65536); port++) {
    const available = await new Promise((resolve, reject) => {
      const server = net.createServer();
      server.once("error", error => {
        if (["EADDRINUSE", "EACCES"].includes(error.code)) resolve(false);
        else reject(error);
      });
      server.listen({ port, host: "127.0.0.1", exclusive: true }, () => server.close(error => error ? reject(error) : resolve(true)));
    });
    if (available) {
      const origin = `http://127.0.0.1:${port}`;
      return { port, origin, healthUrl: `${origin}/api/health`, instanceId: randomBytes(32).toString("hex") };
    }
  }
  throw new Error("port_in_use:no_available_backend_port");
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

module.exports = { selectBackendEndpoint, validateHealthResponse };
