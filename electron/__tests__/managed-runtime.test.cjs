const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const net = require('node:net');
const { managedRuntime, assertPortsAvailable } = require('../managed-runtime.cjs');

test('managed versions share user files but not derived caches', () => {
  const root = path.resolve('shared-fixture');
  const first = managedRuntime({ LUMINA_MANAGED_USER_DATA: root, LUMINA_MANAGED_RUNTIME_KEY: 'a'.repeat(32) });
  const second = managedRuntime({ LUMINA_MANAGED_USER_DATA: root, LUMINA_MANAGED_RUNTIME_KEY: 'b'.repeat(32) });
  assert.equal(first.userData, second.userData);
  assert.notEqual(first.chromiumCache, second.chromiumCache);
  assert.equal(first.frontendUrl, 'http://127.0.0.1:8000/');
  assert.notEqual(first.backendCwd, second.backendCwd);
  assert.equal(first.backendCwd, path.join(root, 'derived', 'a'.repeat(32), 'workspace'));
  assert.equal(first.backendEnv.LUMINA_SETTINGS_PATH, second.backendEnv.LUMINA_SETTINGS_PATH);
  assert.equal(first.backendEnv.LUMINA_CUSTOM_LUT_DIR, second.backendEnv.LUMINA_CUSTOM_LUT_DIR);
  assert.equal(first.backendEnv.LUMINA_MATERIALS_DIR, second.backendEnv.LUMINA_MATERIALS_DIR);
  assert.notEqual(first.backendEnv.LUMINA_RUNTIME_CACHE_DIR, second.backendEnv.LUMINA_RUNTIME_CACHE_DIR);
});

test('normal desktop startup is unchanged and malformed overrides fail explicitly', () => {
  assert.equal(managedRuntime({}), null);
  assert.throws(() => managedRuntime({ LUMINA_MANAGED_USER_DATA: '../escape' }), /absolute/);
  assert.throws(() => managedRuntime({ LUMINA_MANAGED_USER_DATA: path.resolve('shared'), LUMINA_MANAGED_RUNTIME_KEY: '../escape' }), /key/);
});

test('occupied port produces an error and never stops its owner', async () => {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const port = server.address().port;
    await assert.rejects(assertPortsAvailable([port]), /port_in_use/);
    assert.equal(server.listening, true);
  } finally { await new Promise(resolve => server.close(resolve)); }
});

test('free port can be probed without leaving a listener behind', async () => {
  await assertPortsAvailable([0]);
});
