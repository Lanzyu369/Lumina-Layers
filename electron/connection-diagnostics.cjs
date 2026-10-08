"use strict";

const fs = require("node:fs/promises");

const MAX_CONNECTION_DIAGNOSTICS_BYTES = 64 * 1024;
const STATUSES = new Set([
  "disconnected", "connecting", "handshaking", "connected", "recovering", "disconnecting",
]);
const MODES = new Set(["unknown", "handshaking", "legacy", "reliable"]);
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const isCounter = (value) => Number.isSafeInteger(value) && value >= 0;
const isText = (value, maximum) => typeof value === "string" && value.length <= maximum;
const isNullableText = (value, maximum) => value === null || isText(value, maximum);

function validDiagnostics(text) {
  if (typeof text !== "string" || Buffer.byteLength(text, "utf8") > MAX_CONNECTION_DIAGNOSTICS_BYTES) return false;
  let value;
  try { value = JSON.parse(text); } catch { return false; }
  return isObject(value) && value.version === 1 && STATUSES.has(value.status) && MODES.has(value.mode)
    && typeof value.captureId === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value.captureId)
    && isCounter(value.receivedBytes) && isCounter(value.appliedCount) && isCounter(value.pendingCount)
    && (value.lastHeartbeatAt === null || isCounter(value.lastHeartbeatAt))
    && isNullableText(value.issue, 128) && isNullableText(value.lastError, 4096)
    && Array.isArray(value.trace) && value.trace.length <= 40
    && value.trace.every((entry) => isObject(entry) && isCounter(entry.at)
      && typeof entry.event === "string" && /^[a-z][a-z0-9_]{0,79}$/.test(entry.event)
      && (entry.measurementId === undefined || isText(entry.measurementId, 128))
      && (entry.detail === undefined || isText(entry.detail, 8192)));
}

/** Save bounded connection diagnostics for trusted main-frame IPC only.
 * 仅允许可信主页面通过 IPC 保存大小受限的连接诊断。 */
function createConnectionDiagnosticsSaver({ getWindow, dialog, isTrustedIpcSender, writeFile = fs.writeFile }) {
  return async function saveConnectionDiagnostics(event, text) {
    if (!isTrustedIpcSender(event)) return { status: "error", error: "untrusted_sender" };
    if (!validDiagnostics(text)) return { status: "error", error: "invalid_diagnostics" };
    try {
      const result = await dialog.showSaveDialog(getWindow(), {
        defaultPath: "lumina-box-connection.json",
        filters: [{ name: "JSON", extensions: ["json"] }],
      });
      if (result.canceled || !result.filePath) return { status: "cancelled" };
      await writeFile(result.filePath, text, "utf8");
      return { status: "saved" };
    } catch {
      return { status: "error", error: "save_failed" };
    }
  };
}

module.exports = { createConnectionDiagnosticsSaver, MAX_CONNECTION_DIAGNOSTICS_BYTES };
