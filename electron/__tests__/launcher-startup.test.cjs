const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { createLauncherStartup } = require('../launcher-startup.cjs');
function windowFixture(onShow) {
  return Object.assign(new EventEmitter(), { isDestroyed: () => false, isVisible: () => true,
    show() { onShow(); this.emit('show'); }, focus() {} });
}

test('managed window reports ready only after Studio presents it, without waiting for a launcher animation', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lumina-handoff-'));
  try {
    const status = path.join(root, 'logs', 'runtime', 'launch-test', 'status.json');
    const managed = createLauncherStartup({ LUMINA_MANAGED_USER_DATA: root,
      LUMINA_MANAGED_RUNTIME_KEY: 'runtime', LUMINA_MANAGED_LAUNCH_ID: 'test',
      LUMINA_MANAGED_REVEAL: '1' });
    let shown = 0;
    managed.checkpoint(7);
    assert.equal(JSON.parse(fs.readFileSync(status)).state, 'starting');
    await managed.present(windowFixture(() => shown++));
    assert.equal(shown, 1);
    assert.equal(JSON.parse(fs.readFileSync(status)).state, 'ready');
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('unmanaged startup displays the window immediately', async () => {
  let shown = false;
  const managed = createLauncherStartup({});
  await managed.present(windowFixture(() => { shown = true; }));
  assert.equal(managed.enabled, false);
  assert.equal(shown, true);
});

test('presentation waits for the native window to become visible', async () => {
  const startup = createLauncherStartup({});
  const window = windowFixture(() => {});
  window.isVisible = () => false;
  window.show = () => {};
  let finished = false;
  const presentation = startup.present(window).then(() => { finished = true; });
  await Promise.resolve();
  assert.equal(finished, false);
  window.emit('show');
  await presentation;
  assert.equal(finished, true);
});
