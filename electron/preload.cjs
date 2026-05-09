const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  setLanguage: (lang) => ipcRenderer.send("set-language", lang),
  getAppVersion: () => ipcRenderer.invoke("get-app-version"),
});
