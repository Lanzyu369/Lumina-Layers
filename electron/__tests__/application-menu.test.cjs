const test = require('node:test');
const assert = require('node:assert/strict');
const { createApplicationMenu } = require('../application-menu.cjs');

test('About uses the application page when ready and the native fallback before readiness', () => {
  let template;
  let fallback = 0;
  const sent = [];
  const menu = createApplicationMenu({
    Menu: { buildFromTemplate: value => value, setApplicationMenu: value => { template = value; } },
    app: { showAboutPanel() { fallback++; } },
    getWindow: () => ({ isDestroyed: () => false, webContents: { send: (...args) => sent.push(args) } }),
    getScale: () => null,
    openDocs() {},
  });
  menu.rebuild();
  template[0].submenu[0].click();
  assert.equal(fallback, 1);
  menu.update({ commands: { about: true } });
  template[0].submenu[0].click();
  assert.deepEqual(sent, [['application-menu-command', 'about']]);
  assert.equal(fallback, 1);
  menu.reset();
  template[0].submenu[0].click();
  assert.equal(fallback, 2);
});

test('native menu dispatches available commands, translates, resets on navigation and reuses persisted scale', () => {
  let template;
  const sent = [];
  const scripts = [];
  let preference = '100';
  let docs = 0;
  const menu = createApplicationMenu({
    Menu: { buildFromTemplate: value => value, setApplicationMenu: value => { template = value; } },
    app: { showAboutPanel() {} },
    getWindow: () => ({ isDestroyed: () => false, webContents: {
      send: (...args) => sent.push(args),
      executeJavaScript: (...args) => { scripts.push(args); return Promise.resolve(); },
    } }),
    getScale: () => ({ preference: () => preference, choose: value => { preference = value; } }),
    openDocs: () => { docs++; },
  });
  const item = id => template.flatMap(entry => entry.submenu).find(entry => entry.id === id);
  menu.rebuild();
  assert.equal(item('export').enabled, false);
  item('export').click();
  assert.equal(sent.length, 0);
  menu.update({ labels: { file: '文件' }, commands: { import: true, settings: true } });
  assert.equal(template[1].label, '文件');
  item('import').click();
  assert.deepEqual(scripts, [["window.dispatchEvent(new Event('lumina-menu-import'))", true]]);
  item('settings').click();
  assert.deepEqual(sent, [['application-menu-command', 'settings']]);
  template[3].submenu[0].click();
  assert.equal(preference, '110');
  template[3].submenu[2].click();
  assert.equal(preference, '100');
  template[5].submenu[0].click();
  assert.equal(docs, 1);
  const oldItem = item('import');
  menu.reset();
  oldItem.click();
  assert.equal(sent.length, 1);
  assert.equal(scripts.length, 1);
  assert.equal(item('import').enabled, false);
  assert.equal(template[0].submenu.at(-1).role, 'quit');
  assert.ok(!JSON.stringify(template).includes('reload'));
});
