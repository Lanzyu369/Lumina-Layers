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

