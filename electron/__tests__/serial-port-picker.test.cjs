const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const { createSerialPortPicker, normalizeLabels } = require("../serial-port-picker.cjs");

const HOST = "http://127.0.0.1:4174/";
const INDEX = "file:///app/resources/app/dist/index.html";
const LABELS = { title: "title", message: "message", empty: "empty", cancel: "cancel", next: "next", previous: "previous" };
const flush = () => new Promise((resolve) => setImmediate(resolve));
const port = (id) => ({ portId: id, portName: `COM${id}`, displayName: `Device ${id}` });

function fixture(url = HOST, rejectAbort = false) {
  const session = new EventEmitter();
  const contents = new EventEmitter();
  contents.mainFrame = { url, parent: null };
  contents.isDestroyed = () => false;
  contents.getURL = () => contents.mainFrame.url;
  const window = new EventEmitter();
  window.webContents = contents;
  window.isDestroyed = () => false;
  const dialogs = [];
  const dialog = {
    showMessageBox(parent, options) {
      assert.equal(parent, window);
      let resolve;
      let reject;
      const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
      options.signal.addEventListener("abort", () => rejectAbort ? reject(new Error("aborted")) : resolve({ response: 0 }), { once: true });
      dialogs.push({ options, answer: (response) => resolve({ response }) });
      return promise;
    },
  };
  const picker = createSerialPortPicker({ getWindow: () => window, dialog, frontendUrl: HOST, packagedIndexUrl: INDEX });
  picker.install(session);
  picker.setLabels({ sender: contents, senderFrame: contents.mainFrame }, LABELS);
  function request(ports = [port("1"), port("2")], owner = contents) {
    const responses = [];
    let prevented = false;
    session.emit("select-serial-port", { preventDefault() { prevented = true; } }, ports, owner,
      (id) => responses.push(id));
    assert.equal(prevented, true);
    return responses;
  }
  return { session, contents, window, dialogs, picker, request };
}

describe("Desktop serial permission boundary", () => {
  it("allows only the trusted main window's main frame", () => {
    const f = fixture();
    const details = { isMainFrame: true, requestingUrl: HOST };
    assert.equal(f.picker.allowPermission(f.contents, HOST, details), true);
    assert.equal(f.picker.allowPermission(f.contents, HOST, { ...details, isMainFrame: false }), false);
    assert.equal(f.picker.allowPermission(f.contents, "null", details), false);
    assert.equal(f.picker.allowPermission(f.contents, "lumina-workshop://module/ui", details), false);
    assert.equal(f.picker.allowPermission(f.contents, HOST, {}), false);
    assert.equal(f.picker.allowPermission({ ...f.contents }, HOST, details), false);
    assert.equal(f.picker.allowPermission(f.contents, HOST, { ...details, requestingUrl: "http://127.0.0.1:8000/" }), false);
    f.picker.dispose();
  });

  it("permits the packaged index but rejects other local files", () => {
    const f = fixture(INDEX);
    assert.equal(f.picker.allowPermission(f.contents, "file://", { isMainFrame: true, requestingUrl: INDEX }), true);
    f.contents.mainFrame.url = "file:///tmp/other.html";
    assert.equal(f.picker.allowPermission(f.contents, "file://", { isMainFrame: true, requestingUrl: f.contents.mainFrame.url }), false);
    assert.deepEqual(f.request(), [""]);
    assert.equal(f.dialogs.length, 0);
    f.picker.dispose();
  });

  it("accepts translated labels only from the trusted top frame", () => {
    const f = fixture();
    assert.equal(f.picker.setLabels({ sender: f.contents, senderFrame: { url: HOST } }, LABELS), false);
    assert.equal(f.picker.setLabels({ sender: f.contents, senderFrame: f.contents.mainFrame }, { title: "only" }), false);
    assert.equal(normalizeLabels({ ...LABELS, title: "\0" }), null);
    assert.equal(normalizeLabels({ ...LABELS, title: "x".repeat(501) }), null);
    f.picker.dispose();
  });
});

describe("Native SerialPort selection", () => {
  it("requires an explicit choice and paginates the enumerated paths", async () => {
    const f = fixture();
    const event = { sender: f.contents, senderFrame: f.contents.mainFrame };
    const controller = new AbortController();
    const ports = Array.from({ length: 7 }, (_, index) => ({ path: `COM${index + 1}` }));
    let settled = false;
    const picking = f.picker.pickNativePort(event, ports, controller.signal).then((value) => { settled = true; return value; });
    assert.equal(settled, false);
    assert.deepEqual(f.dialogs[0].options.buttons, ["cancel", "COM1", "COM2", "COM3", "COM4", "COM5", "next"]);
    f.dialogs[0].answer(6);
    await flush();
    assert.deepEqual(f.dialogs[1].options.buttons, ["cancel", "COM6", "COM7", "previous"]);
    f.dialogs[1].answer(2);
    assert.equal(await picking, "COM7");
    f.picker.dispose();
  });

  it("rejects a child frame and cancels an aborted or invalidated main-frame dialog", async () => {
    const f = fixture(HOST, true);
    const ports = [{ path: "COM25" }];
    const controller = new AbortController();
    assert.equal(await f.picker.pickNativePort({ sender: f.contents, senderFrame: { parent: f.contents.mainFrame } }, ports, controller.signal), null);
    assert.equal(f.dialogs.length, 0);
    const event = { sender: f.contents, senderFrame: f.contents.mainFrame };
    const aborted = f.picker.pickNativePort(event, ports, controller.signal);
    controller.abort();
    assert.equal(await aborted, null);
    const stale = f.picker.pickNativePort(event, ports, new AbortController().signal);
    f.contents.mainFrame.url = "lumina-workshop://untrusted/ui";
    f.dialogs[1].answer(1);
    assert.equal(await stale, null);
    f.picker.dispose();
  });
});

describe("Explicit desktop serial selection", () => {
  it("never auto-selects and connects only the clicked port", async () => {
    const f = fixture();
    const responses = f.request();
    assert.deepEqual(responses, []);
    assert.deepEqual(f.dialogs[0].options.buttons, ["cancel", "COM1", "COM2"]);
    assert.equal(f.dialogs[0].options.defaultId, 0);
    f.dialogs[0].answer(2);
    await flush();
    assert.deepEqual(responses, ["2"]);
    assert.equal(f.session.listenerCount("serial-port-removed"), 0);
    assert.equal(f.contents.listenerCount("did-start-navigation"), 0);
    f.picker.dispose();
  });

  it("supports cancel and devices arriving after an empty list", async () => {
    const f = fixture();
    const first = f.request([]);
    assert.equal(f.dialogs[0].options.message, "empty");
    f.session.emit("serial-port-added", {}, port("3"), f.contents);
    await flush();
    assert.equal(f.dialogs[0].options.signal.aborted, true);
    assert.deepEqual(f.dialogs[1].options.buttons, ["cancel", "COM3"]);
    f.dialogs[1].answer(0);
    await flush();
    assert.deepEqual(first, [""]);
    f.picker.dispose();
  });

  it("cannot grant a removed port or use a stale dialog response", async () => {
    const f = fixture();
    const responses = f.request();
    f.dialogs[0].answer(1);
    f.session.emit("serial-port-removed", {}, port("1"), f.contents);
    await flush();
    assert.deepEqual(responses, []);
    assert.deepEqual(f.dialogs[1].options.buttons, ["cancel", "COM2"]);
    f.dialogs[1].answer(1);
    await flush();
    assert.deepEqual(responses, ["2"]);
    f.picker.dispose();
  });

  it("refreshes safely when native abort rejects and opaque IDs match paging words", async () => {
    const f = fixture(HOST, true);
    const responses = f.request([]);
    f.session.emit("serial-port-added", {}, port("next"), f.contents);
    await flush();
    assert.deepEqual(responses, []);
    f.dialogs[1].answer(1);
    await flush();
    assert.deepEqual(responses, ["next"]);
    f.picker.dispose();
  });

  it("paginates every available device without guessing", async () => {
    const f = fixture();
    const responses = f.request(Array.from({ length: 7 }, (_, i) => port(String(i + 1))));
    assert.equal(f.dialogs[0].options.buttons.at(-1), "next");
    f.dialogs[0].answer(6);
    await flush();
    assert.deepEqual(f.dialogs[1].options.buttons, ["cancel", "COM6", "COM7", "previous"]);
    f.dialogs[1].answer(2);
    await flush();
    assert.deepEqual(responses, ["7"]);
    f.picker.dispose();
  });

  for (const reason of ["navigation", "close", "destroyed", "crash"]) {
    it(`cancels once and removes listeners on ${reason}`, async () => {
      const f = fixture();
      const responses = f.request();
      if (reason === "navigation") f.contents.emit("did-start-navigation", {}, HOST, false, true);
      if (reason === "close") f.window.emit("close", {});
      if (reason === "destroyed") f.contents.emit("destroyed");
      if (reason === "crash") f.contents.emit("render-process-gone", {}, {});
      await flush();
      f.dialogs[0].answer(2);
      await flush();
      assert.deepEqual(responses, [""]);
      assert.equal(f.dialogs[0].options.signal.aborted, true);
      assert.equal(f.session.listenerCount("serial-port-added"), 0);
      assert.equal(f.window.listenerCount("close"), 0);
      f.picker.dispose();
    });
  }

  it("cancels the old request when a second one starts", async () => {
    const f = fixture();
    const first = f.request();
    const second = f.request([port("3")]);
    await flush();
    assert.deepEqual(first, [""]);
    f.dialogs[1].answer(1);
    await flush();
    assert.deepEqual(second, ["3"]);
    f.picker.dispose();
  });

  it("binds the serial-only permission handler", () => {
    const root = path.join(__dirname, "..");
    const main = fs.readFileSync(path.join(root, "main.cjs"), "utf8");
    assert.match(main, /serialPortPicker\.install\(session\.defaultSession\)/);
    assert.match(main, /permission === "serial"/);
    assert.doesNotMatch(main, /setDevicePermissionHandler\(/);
  });
});
