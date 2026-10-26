const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  createGeneratedFileDirectoryState,
  normalizeGeneratedFileDirectory,
  pickGeneratedFileDirectory,
  resolveDefaultSavePath,
  setGeneratedFileDirectory,
} = require('../generated-file-directory.cjs');
const { saveGeneratedFile } = require('../generated-file-save.cjs');

function trustedContext() {
  const mainFrame = { url: 'file:///app/index.html' };
  const webContents = { mainFrame };
  return {
    event: { sender: webContents, senderFrame: mainFrame },
    window: { webContents },
    trustedUrl: mainFrame.url,
  };
}

test('normalize keeps only absolute paths', () => {
  assert.equal(normalizeGeneratedFileDirectory('relative/dir'), '');
  assert.equal(normalizeGeneratedFileDirectory(42), '');
  assert.equal(normalizeGeneratedFileDirectory('/tmp/a\0b'), '');
  assert.equal(normalizeGeneratedFileDirectory(''), '');
  assert.equal(normalizeGeneratedFileDirectory(os.tmpdir()), path.normalize(os.tmpdir()));
});

test('default save path joins an existing directory with the filename', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lumina-dir-'));
  try {
    assert.equal(resolveDefaultSavePath(dir, 'model.3mf'), path.join(dir, 'model.3mf'));
    // Path segments in the suggested filename never escape the directory.
    assert.equal(resolveDefaultSavePath(dir, '../evil.3mf'), path.join(dir, 'evil.3mf'));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('default save path falls back to the bare filename', () => {
  assert.equal(resolveDefaultSavePath('', 'model.3mf'), 'model.3mf');
  const missing = path.join(os.tmpdir(), `lumina-missing-${Date.now()}`);
  assert.equal(resolveDefaultSavePath(missing, 'model.3mf'), 'model.3mf');
});

test('set and pick reject untrusted senders', async () => {
  const state = createGeneratedFileDirectoryState();
  const ctx = trustedContext();
  const untrusted = { ...ctx, event: { sender: {}, senderFrame: {} } };
  assert.equal(setGeneratedFileDirectory({ ...untrusted, state, directory: os.tmpdir() }).status, 'error');
  assert.equal(state.get(), '');
  const result = await pickGeneratedFileDirectory({
    ...untrusted, state, showOpenDialog: () => assert.fail('must not open'),
  });
  assert.equal(result.status, 'error');
});

test('set stores a normalized directory and pick opens there', async () => {
  const state = createGeneratedFileDirectoryState();
  const ctx = trustedContext();
  assert.deepEqual(
    setGeneratedFileDirectory({ ...ctx, state, directory: os.tmpdir() }),
    { status: 'ok', directory: path.normalize(os.tmpdir()) },
  );
  let seenOptions = null;
  const picked = await pickGeneratedFileDirectory({
    ...ctx,
    state,
    showOpenDialog: async (_owner, options) => {
      seenOptions = options;
      return { canceled: false, filePaths: [os.tmpdir()] };
    },
  });
  assert.equal(seenOptions.defaultPath, path.normalize(os.tmpdir()));
  assert.ok(seenOptions.properties.includes('openDirectory'));
  assert.deepEqual(picked, { status: 'selected', directory: path.normalize(os.tmpdir()) });
  const canceled = await pickGeneratedFileDirectory({
    ...ctx, state, showOpenDialog: async () => ({ canceled: true, filePaths: [] }),
  });
  assert.equal(canceled.status, 'canceled');
});

test('generated-file save dialog starts in the configured directory', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lumina-save-dir-'));
  try {
    let defaultPath = null;
    await saveGeneratedFile({
      ...trustedContext(),
      payload: { purpose: 'project', filename: 'art.lumina.json', bytes: new TextEncoder().encode('{}') },
      defaultDirectory: dir,
      showSaveDialog: async (_owner, options) => {
        defaultPath = options.defaultPath;
        return { canceled: true };
      },
    });
    assert.equal(defaultPath, path.join(dir, 'art.lumina.json'));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
