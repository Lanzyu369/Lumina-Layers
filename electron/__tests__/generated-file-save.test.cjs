const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { saveGeneratedFile, MAX_GENERATED_FILE_BYTES } = require('../generated-file-save.cjs');

function setup(overrides = {}) {
  const mainFrame = { url: 'file:///app/index.html' };
  const webContents = { mainFrame };
  return { event: { sender: webContents, senderFrame: mainFrame }, window: { webContents }, trustedUrl: mainFrame.url,
    payload: { purpose: 'project', filename: 'art.lumina.json', bytes: new TextEncoder().encode('{}') },
    showSaveDialog: async () => ({ canceled: true }), ...overrides };
}
test('cancel does not write', async () => {
  assert.deepEqual(await saveGeneratedFile(setup()), { status: 'canceled' });
});
test('requires actual JSON or a PNG signature for the selected purpose', async () => {
  for (const payload of [
    { purpose: 'project', filename: 'x.lumina.json', bytes: new TextEncoder().encode('not json') },
    { purpose: 'screenshot', filename: 'x.png', bytes: new TextEncoder().encode('not png') },
  ]) assert.equal((await saveGeneratedFile(setup({ payload }))).status, 'error');
  for (const purpose of ['screenshot', 'share-card']) {
    const payload = { purpose, filename: 'x.png', bytes: new Uint8Array([137,80,78,71,13,10,26,10]) };
    assert.equal((await saveGeneratedFile(setup({ payload }))).status, 'canceled');
  }
});
test('only the trusted main window main frame can save', async () => {
  for (const mutate of [s => s.event.sender = {}, s => s.event.senderFrame = { url: s.trustedUrl }, s => s.trustedUrl = 'https://evil.test']) {
    const s = setup({ showSaveDialog: () => assert.fail('must not open') }); mutate(s);
    assert.equal((await saveGeneratedFile(s)).status, 'error');
  }
});
test('invalid names, types, and oversized payloads are rejected before dialog', async () => {
  for (const update of [{ filename: '../evil.lumina.json' }, { filename: 'x.exe' }, { filename: 'CON.lumina.json' }, { purpose: 'other' }, { purpose: { toString: null } }, { purpose: ['screenshot'], filename: 'x.png', bytes: new Uint8Array([137,80,78,71,13,10,26,10]) }, { bytes: new Uint8Array(MAX_GENERATED_FILE_BYTES + 1) }]) {
    assert.equal((await saveGeneratedFile(setup({ payload: { ...setup().payload, ...update }, showSaveDialog: () => assert.fail('must not open') }))).status, 'error');
  }
});
test('project dialog uses the native JSON extension', async () => {
  let actualExtensions;
  await saveGeneratedFile(setup({ showSaveDialog: async (_owner, options) => {
    actualExtensions = options.filters[0].extensions;
    return { canceled: true };
  } }));
  assert.deepEqual(actualExtensions, ['json']);
});
test('failed exclusive create never deletes a file it does not own', async () => {
  let deletes = 0;
  const result = await saveGeneratedFile(setup({
    showSaveDialog: async () => ({ canceled: false, filePath: '/tmp/art.lumina.json' }),
    fileSystem: { open: async () => { throw new Error('EEXIST'); }, unlink: async () => { deletes++; } },
  }));
  assert.equal(result.status, 'error');
  assert.equal(deletes, 0);
});
test('writes exact bytes atomically and keeps old target when rename fails', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'lumina-save-test-'));
  const target = path.join(dir, 'renamed.json');
  try {
    await fs.writeFile(target, 'old');
    const s = setup({ showSaveDialog: async () => ({ filePath: target, canceled: false }) });
    assert.equal((await saveGeneratedFile({ ...s, fileSystem: { ...fs, rename: async () => { throw new Error('write failed'); } } })).status, 'error');
    assert.equal(await fs.readFile(target, 'utf8'), 'old');
    assert.deepEqual(await fs.readdir(dir), ['renamed.json']);
    assert.equal((await saveGeneratedFile(s)).status, 'saved');
    assert.equal(await fs.readFile(target, 'utf8'), '{}');
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});
