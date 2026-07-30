const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  setLanguage: (lang) => ipcRenderer.send("set-language", lang),
  getAppVersion: () => ipcRenderer.invoke("get-app-version"),
  getWorkshopRuntimeMode: () =>
    ipcRenderer.invoke("get-workshop-runtime-mode"),
  pickWorkshopImage: () =>
    ipcRenderer.invoke("pick-workshop-image"),
});
