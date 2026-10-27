const fs = require('node:fs');
const path = require('node:path');

function createLauncherStartup(env = process.env) {
  const shared = env.LUMINA_MANAGED_USER_DATA;
  const key = env.LUMINA_MANAGED_RUNTIME_KEY;
  const launchId = env.LUMINA_MANAGED_LAUNCH_ID;
  const enabled = !!shared && /^[a-zA-Z0-9_-]+$/.test(key || '') && /^[a-zA-Z0-9-]+$/.test(launchId || '');
  const directory = enabled ? path.join(shared, 'logs', key, `launch-${launchId}`) : null;
  let ready = false;
  function report(state, checkpoint, errorCode) {
    if (!enabled) return;
    fs.mkdirSync(directory, { recursive: true });
    const file = path.join(directory, 'status.json');
    fs.writeFileSync(`${file}.tmp`, JSON.stringify({ protocol: 2, launchId, runtimeKey: key,
      pid: process.pid, state, checkpoint, ...(errorCode ? { errorCode } : {}) }));
    fs.renameSync(`${file}.tmp`, file);
  }
  return {
    enabled,
    checkpoint(value) { report('starting', value); },
    failed() { if (!ready) report('failed', 0, 'startup_failed'); },
    async present(window) {
      if (!window.isDestroyed()) {
        await new Promise((resolve, reject) => {
          const done = () => { clearTimeout(timer); window.removeListener('show', done); window.removeListener('closed', done); resolve(); };
          const timer = setTimeout(() => {
            window.removeListener('show', done); window.removeListener('closed', done);
            reject(new Error('startup_frontend_failed'));
          }, 1500);
          window.once('show', done);
          window.once('closed', done);
          window.show();
          if (window.isVisible()) done();
        });
        if (window.isDestroyed()) return;
        window.focus();
        ready = true;
        report('ready', 8);
      }
    },
  };
}

module.exports = { createLauncherStartup };
