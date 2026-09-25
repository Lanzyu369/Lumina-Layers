"use strict";
const path = require("node:path");
const net = require("node:net");

/** Resolve shared user files and version-specific caches. 解析共享用户数据与逐版本缓存。 */
function managedRuntime(env, backendPort = 8000) {
  const root = env.LUMINA_MANAGED_USER_DATA;
  if (!root) return null;
  if (!path.isAbsolute(root)) throw new Error("Managed user data must be absolute.");
  const key = env.LUMINA_MANAGED_RUNTIME_KEY;
  if (!/^[a-f0-9]{32}$/.test(key || "")) throw new Error("Invalid managed runtime key.");
  const cache = path.join(root, "derived", key);
  const logs = path.join(root, "logs", key);
  return {
    userData: path.join(root, "electron"),
    chromiumCache: path.join(cache, "chromium-disk-cache"),
    frontendUrl: `http://127.0.0.1:${backendPort}/`,
    backendCwd: path.join(cache, "workspace"),
    backendEnv: {
      LUMINA_API_HOST: "127.0.0.1",
      LUMINA_API_PORT: String(backendPort),
      LUMINA_SETTINGS_PATH: path.join(root, "settings", "user_settings.json"),
      LUMINA_MATERIALS_DIR: path.join(root, "materials"),
      LUMINA_CUSTOM_LUT_DIR: path.join(root, "luts", "Custom"),
      LUMINA_CLOUD_LUT_DIR: path.join(root, "luts", "Cloud_sync"),
      LUMINA_WORKSHOP_DATA_DIR: path.join(root, "workshop"),
      LUMINA_FEEDBACK_DUMP_DIR: path.join(root, "feedback"),
      LUMINA_RUNTIME_CACHE_DIR: cache,
      LUMINA_LOG_DIR: logs,
      LUMINA_LOG_PATH: path.join(logs, `desktop-${Date.now()}.jsonl`),
    },
  };
}

/** Check ports without terminating their owners. 只检查端口，不终止占用它们的进程。 */
async function assertPortsAvailable(ports) {
  for (const port of ports) {
    await new Promise((resolve, reject) => {
      const server = net.createServer();
      server.once("error", error => reject(new Error(`port_in_use:${port}:${error.code}`)));
      server.listen(port, "127.0.0.1", () => server.close(resolve));
    });
  }
}

module.exports = { managedRuntime, assertPortsAvailable };
