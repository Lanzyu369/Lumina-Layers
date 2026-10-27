const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createSplashController } = require('../splash-controller.cjs');

function fixture(t, fallbackMs = 1000) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'studio-splash-'));
  const ipcMain = new EventEmitter(), handlers = new Map();
  ipcMain.handle = (key, fn) => handlers.set(key, fn);
  ipcMain.removeHandler = key => handlers.delete(key);
  class Window extends EventEmitter {
    constructor() { super(); this.webContents = new EventEmitter(); this.webContents.mainFrame = {}; }
    loadFile() { return Promise.resolve(); }
    show() { this.visible = true; }
    close() { this.destroyed = true; this.emit('closed'); }
    isDestroyed() { return !!this.destroyed; }
  }
  const controller = createSplashController({ BrowserWindow: Window, ipcMain,
    app: { getPath: () => root, getVersion: () => '2.0.0' }, fallbackMs });
  const event = { sender: controller.window.webContents, senderFrame: controller.window.webContents.mainFrame };
  t.after(() => { controller.close(); fs.rmSync(root, { recursive: true, force: true }); });
  return { controller, ipcMain, handlers, event };
}
test('only the splash main frame can finish after the workspace is ready', async t => {
  const f = fixture(t);
  f.ipcMain.emit('studio-splash-finished', f.event);
  let completed = false;
  const pending = f.controller.complete().then(() => { completed = true; });
  f.ipcMain.emit('studio-splash-finished', { ...f.event, senderFrame: {} });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(completed, false);
  assert.equal(f.handlers.get('studio-splash-state')(f.event).ready, true);
  f.ipcMain.emit('studio-splash-finished', f.event);
  await pending;
  assert.equal(completed, true);
  assert.equal(f.controller.window.isDestroyed(), false, 'caller shows main before closing splash');
});
test('a stalled or crashed splash cannot strand the ready workspace', async t => {
  const f = fixture(t, 10);
  await f.controller.complete();
  const g = fixture(t);
  g.controller.window.webContents.emit('render-process-gone');
  await g.controller.complete();
});
