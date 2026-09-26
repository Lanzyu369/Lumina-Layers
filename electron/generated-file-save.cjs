const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { resolveDefaultSavePath } = require('./generated-file-directory.cjs');
const MAX_GENERATED_FILE_BYTES = 128 * 1024 * 1024;
const extensions = { project: '.lumina.json', 'share-card': '.png', screenshot: '.png' };

async function saveGeneratedFile({ event, window, trustedUrl, payload, showSaveDialog, defaultDirectory = '', fileSystem = fs }) {
  const frame = event?.senderFrame;
  if (!window?.webContents || event.sender !== window.webContents || !frame ||
      frame !== window.webContents.mainFrame || typeof trustedUrl !== 'string' || frame.url !== trustedUrl) {
    return { status: 'error', code: 'denied' };
  }
  const { purpose, filename, bytes } = payload ?? {};
  const extension = typeof purpose === 'string' && Object.hasOwn(extensions, purpose) ? extensions[purpose] : null;
  if (!extension || typeof filename !== 'string' || filename.length > 180 ||
      /[\\/<>:"|?*\x00-\x1f]/.test(filename) || filename.startsWith('.') ||
      /^(con|prn|aux|nul|com[1-9]|lpt[1-9])\./i.test(filename) ||
      !filename.endsWith(extension) || !(bytes instanceof Uint8Array) || !bytes.byteLength) {
    return { status: 'error', code: 'invalid' };
  }
  if (bytes.byteLength > MAX_GENERATED_FILE_BYTES) return { status: 'error', code: 'too-large' };
  try {
    if (purpose === 'project') {
      JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    } else if (![137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => bytes[index] === value)) {
      return { status: 'error', code: 'invalid' };
    }
  } catch (_) { return { status: 'error', code: 'invalid' }; }
  let temporaryPath;
  try {
    const choice = await showSaveDialog(window, { defaultPath: resolveDefaultSavePath(defaultDirectory, filename),
      filters: [{ name: purpose === 'project' ? 'Lumina JSON' : 'PNG', extensions: [purpose === 'project' ? 'json' : 'png'] }] });
    if (choice.canceled || !choice.filePath) return { status: 'canceled' };
    if (!choice.filePath.toLowerCase().endsWith(purpose === 'project' ? '.json' : extension)) return { status: 'error', code: 'invalid' };
    const candidatePath = path.join(path.dirname(choice.filePath), `.lumina-save-${randomUUID()}.tmp`);
    const handle = await fileSystem.open(candidatePath, 'wx', 0o600);
    temporaryPath = candidatePath;
    try {
      await handle.writeFile(bytes);
      await handle.sync();
    } finally { await handle.close(); }
    await fileSystem.rename(temporaryPath, choice.filePath);
    temporaryPath = undefined;
    return { status: 'saved' };
  } catch (_) {
    return { status: 'error', code: 'write-failed' };
  } finally {
    if (temporaryPath) await fileSystem.unlink(temporaryPath).catch(() => {});
  }
}
module.exports = { MAX_GENERATED_FILE_BYTES, saveGeneratedFile };
