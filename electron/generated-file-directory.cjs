const fsSync = require('node:fs');
const path = require('node:path');

const MAX_DIRECTORY_LENGTH = 1024;

/**
 * Normalize a user-chosen default directory for generated-file save dialogs.
 * Returns '' (system default) for anything that is not an absolute path.
 */
function normalizeGeneratedFileDirectory(value) {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > MAX_DIRECTORY_LENGTH || trimmed.includes('\0')) return '';
  return path.isAbsolute(trimmed) ? path.normalize(trimmed) : '';
}

/**
 * Build the save dialog defaultPath: the configured directory joined with the
 * suggested filename when that directory still exists, else the bare filename
 * so the OS falls back to its own default location.
 */
function resolveDefaultSavePath(directory, filename, fileSystem = fsSync) {
  const baseName = path.basename(String(filename || ''));
  const normalized = normalizeGeneratedFileDirectory(directory);
  if (!normalized) return baseName;
  try {
    if (!fileSystem.statSync(normalized).isDirectory()) return baseName;
  } catch (_) {
    return baseName;
  }
  return baseName ? path.join(normalized, baseName) : normalized;
}

/** Only the trusted main frame of the app window may change the directory. */
function isTrustedMainFrameSender(event, window, trustedUrl) {
  const frame = event?.senderFrame;
  return Boolean(
    window?.webContents && event?.sender === window.webContents && frame &&
    frame === window.webContents.mainFrame && typeof trustedUrl === 'string' &&
    frame.url === trustedUrl,
  );
}

/** In-memory holder for the directory the renderer last synchronized. */
function createGeneratedFileDirectoryState() {
  let directory = '';
  return {
    get: () => directory,
    set: (value) => {
      directory = normalizeGeneratedFileDirectory(value);
      return directory;
    },
  };
}

async function pickGeneratedFileDirectory({ event, window, trustedUrl, state, showOpenDialog }) {
  if (!isTrustedMainFrameSender(event, window, trustedUrl)) {
    return { status: 'error', code: 'denied' };
  }
  const current = state.get();
  const options = { properties: ['openDirectory', 'createDirectory'] };
  if (current) options.defaultPath = current;
  try {
    const choice = await showOpenDialog(window, options);
    const selected = choice?.filePaths?.[0];
    if (choice?.canceled || !selected) return { status: 'canceled' };
    const directory = normalizeGeneratedFileDirectory(selected);
    return directory ? { status: 'selected', directory } : { status: 'error', code: 'invalid' };
  } catch (_) {
    return { status: 'error', code: 'dialog-failed' };
  }
}

function setGeneratedFileDirectory({ event, window, trustedUrl, state, directory }) {
  if (!isTrustedMainFrameSender(event, window, trustedUrl)) {
    return { status: 'error', code: 'denied' };
  }
  return { status: 'ok', directory: state.set(directory) };
}

module.exports = {
  createGeneratedFileDirectoryState,
  isTrustedMainFrameSender,
  normalizeGeneratedFileDirectory,
  pickGeneratedFileDirectory,
  resolveDefaultSavePath,
  setGeneratedFileDirectory,
};
