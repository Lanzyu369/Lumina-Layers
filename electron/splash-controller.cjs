const path = require('node:path');
const fs = require('node:fs');
const texts = require('./splash-text.json');

// The Studio process owns the complete splash lifecycle, including the final hold.
function createSplashController({ BrowserWindow, ipcMain, app, language = 'zh', onProgress = () => {}, fallbackMs = 8500 }) {
  const started = Date.now();
  const timings = [0];
  const historyPath = path.join(app.getPath('userData'), 'splash-timings.json');
  let history = null;
  try { history = JSON.parse(fs.readFileSync(historyPath, 'utf8')); } catch {}
  let checkpoint = 0, ready = false, finished = false, resolveFinish, fallback;
  const completion = new Promise(resolve => { resolveFinish = resolve; });
  const window = new BrowserWindow({ width: 480, height: 620, frame: false, resizable: false,
    center: true, show: false, backgroundColor: '#e2e8f0',
    webPreferences: { preload: path.join(__dirname, 'splash-preload.cjs'), contextIsolation: true,
      nodeIntegration: false, sandbox: true, backgroundThrottling: false } });
  const snapshot = () => ({ checkpoint, ready, elapsedMs: Date.now() - started, history,
    version: app.getVersion(), text: Object.fromEntries(Object.entries(texts).map(([key, value]) => [key, value[language] || value.en])) });
  const trusted = event => event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame;
  const finish = () => {
    if (finished) return;
    finished = true;
    clearTimeout(fallback);
    resolveFinish();
  };
  ipcMain.handle('studio-splash-state', event => trusted(event) ? snapshot() : null);
  const completed = event => { if (trusted(event) && ready) finish(); };
  ipcMain.on('studio-splash-finished', completed);
  window.once('ready-to-show', () => { if (!window.isDestroyed()) window.show(); });
  window.once('closed', () => {
    finish();
    ipcMain.removeHandler('studio-splash-state');
    ipcMain.removeListener('studio-splash-finished', completed);
  });
  window.webContents.once('render-process-gone', finish);
  void window.loadFile(path.join(__dirname, 'splash.html')).catch(finish);
  return {
    window,
    checkpoint(value) {
      if (ready || !Number.isInteger(value) || value < checkpoint || value > 7) return;
      checkpoint = value;
      for (let i = 1; i <= value; i++) timings[i] ??= Date.now() - started;
      onProgress(value);
    },
    async complete() {
      if (!ready) {
        ready = true; checkpoint = 8;
        for (let i = 1; i <= 8; i++) timings[i] ??= Date.now() - started;
        try { fs.writeFileSync(historyPath, JSON.stringify(timings)); } catch {}
        // Allow the active wave + up to three 1600 ms waves + the 1 s final hold.
        // This timeout only releases a failed/stalled renderer; normal completion comes from IPC.
        if (!finished) fallback = setTimeout(finish, fallbackMs);
      }
      await completion;
    },
    close() { finish(); if (!window.isDestroyed()) window.close(); },
  };
}
module.exports = { createSplashController };
