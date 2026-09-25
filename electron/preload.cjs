const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  saveGeneratedFile: (payload) => ipcRenderer.invoke("save-generated-file", payload),
  setLanguage: (lang) => ipcRenderer.send("set-language", lang),
  getAppVersion: () => ipcRenderer.invoke("get-app-version"),
  getNativeBedModel: (deviceProfileId) =>
    ipcRenderer.invoke("get-native-bed-model", deviceProfileId),
  getWorkshopRuntimeMode: () =>
    ipcRenderer.invoke("get-workshop-runtime-mode"),
  openWiki: (url) => ipcRenderer.invoke("open-wiki", url),
  pickWorkshopImage: () =>
    ipcRenderer.invoke("pick-workshop-image"),
});
