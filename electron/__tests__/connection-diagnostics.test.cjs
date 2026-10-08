const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  createConnectionDiagnosticsSaver,
  MAX_CONNECTION_DIAGNOSTICS_BYTES,
} = require("../connection-diagnostics.cjs");

const diagnostics = {
  version: 1, status: "disconnected", mode: "unknown", captureId: "capture-1",
  receivedBytes: 500, appliedCount: 1, pendingCount: 1, lastHeartbeatAt: 1000,
  issue: "operation_timeout", lastError: "serial_operation_timeout",
  trace: [{ at: 3500, event: "command_failed", detail: "ping: serial_operation_timeout" }],
};

function fixture({ trusted = true, result, writeError } = {}) {
  const events = [];
  const window = {};
  const save = createConnectionDiagnosticsSaver({
    getWindow: () => window,
    isTrustedIpcSender: (event) => { events.push(["trust", event]); return trusted; },
    dialog: { showSaveDialog: async (owner, options) => {
      events.push(["dialog", owner, options]);
      return result ?? { canceled: false, filePath: "C:/selected/connection.json" };
    } },
    writeFile: async (...args) => {
      events.push(["write", ...args]);
      if (writeError) throw writeError;
    },
  });
  return { save, events, window };
}

describe("connection diagnostics desktop save", () => {
  it("rejects an untrusted sender before validation, dialog or filesystem access", async () => {
    const f = fixture({ trusted: false });
    const event = { senderFrame: "untrusted child frame" };
    assert.deepEqual(await f.save(event, null), { status: "error", error: "untrusted_sender" });
    assert.deepEqual(f.events, [["trust", event]]);
  });

  it("writes the original JSON as UTF-8 only to the path selected in the native dialog", async () => {
    const f = fixture();
    const event = {};
    const text = JSON.stringify({ ...diagnostics, filePath: "C:/renderer/cannot-select-this.json" }, null, 2);
    assert.deepEqual(await f.save(event, text), { status: "saved" });
    assert.deepEqual(f.events, [
      ["trust", event],
      ["dialog", f.window, { defaultPath: "lumina-box-connection.json", filters: [{ name: "JSON", extensions: ["json"] }] }],
      ["write", "C:/selected/connection.json", text, "utf8"],
    ]);
  });

  it("returns cancellation without writing a file", async () => {
    const f = fixture({ result: { canceled: true, filePath: "C:/selected/connection.json" } });
    assert.deepEqual(await f.save({}, JSON.stringify(diagnostics)), { status: "cancelled" });
    assert.deepEqual(f.events.map(([type]) => type), ["trust", "dialog"]);
  });

  it("rejects malformed, unsupported, oversized and invalid-shaped diagnostics before opening a dialog", async () => {
    const oversized = JSON.stringify({ ...diagnostics,
      trace: Array.from({ length: 40 }, () => ({ at: 1, event: "command_failed", detail: "\u4e2d".repeat(600) })),
    });
    assert.ok(oversized.length < MAX_CONNECTION_DIAGNOSTICS_BYTES);
    assert.ok(Buffer.byteLength(oversized, "utf8") > MAX_CONNECTION_DIAGNOSTICS_BYTES);
    for (const value of [null, diagnostics, "{", "null", "[]",
      JSON.stringify({ ...diagnostics, version: 2 }),
      JSON.stringify({ ...diagnostics, status: "invalid" }),
      JSON.stringify({ ...diagnostics, receivedBytes: -1 }),
      JSON.stringify({ ...diagnostics, trace: Array(41).fill(diagnostics.trace[0]) }),
      JSON.stringify({ ...diagnostics, trace: [{ at: 1, event: 123 }] }), oversized]) {
      const f = fixture();
      assert.deepEqual(await f.save({}, value), { status: "error", error: "invalid_diagnostics" });
      assert.deepEqual(f.events.map(([type]) => type), ["trust"]);
    }
  });

  it("returns a bounded error code when writing fails without exposing the exception", async () => {
    const f = fixture({ writeError: new Error("private filesystem path and stack") });
    const result = await f.save({}, JSON.stringify(diagnostics));
    assert.deepEqual(result, { status: "error", error: "save_failed" });
    assert.equal(JSON.stringify(result).includes("private"), false);
    assert.deepEqual(f.events.map(([type]) => type), ["trust", "dialog", "write"]);
  });
});
