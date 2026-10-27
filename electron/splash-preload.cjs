const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('studioSplash', {
  read: () => ipcRenderer.invoke('studio-splash-state'),
  finished: () => ipcRenderer.send('studio-splash-finished'),
});
