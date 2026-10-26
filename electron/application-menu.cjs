const COMMANDS = ['about', 'settings', 'import', 'export', 'report'];
        { label: labels.about, click: () => {
          const window = getWindow();
          if (enabled.about && window && !window.isDestroyed()) window.webContents.send('application-menu-command', 'about');
          else app.showAboutPanel();
        } }, command('settings', 'Command+,'), separator,
