const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  setLanguage: (lang, serialLabels) => ipcRenderer.send("set-language", lang, serialLabels),
  getAppVersion: () => ipcRenderer.invoke("get-app-version"),
  saveConnectionDiagnostics: (text) => ipcRenderer.invoke("save-connection-diagnostics", text),
  nativeSerial: {
    requestPort: () => ipcRenderer.invoke("native-serial-request-port"),
    open: (connectionId) => ipcRenderer.invoke("native-serial-open", connectionId),
    write: (connectionId, bytes) => ipcRenderer.invoke("native-serial-write", connectionId, bytes),
    close: (connectionId) => ipcRenderer.invoke("native-serial-close", connectionId),
    subscribe: (listener) => {
      const receive = (_event, message) => listener(message);
      ipcRenderer.on("native-serial-event", receive);
      return () => ipcRenderer.removeListener("native-serial-event", receive);
    },
  },
  saveGeneratedFile: (payload) => ipcRenderer.invoke("save-generated-file", payload),
  setGeneratedFileDirectory: (directory) =>
    ipcRenderer.invoke("set-generated-file-directory", directory),
  pickGeneratedFileDirectory: () =>
    ipcRenderer.invoke("pick-generated-file-directory"),
  getNativeBedModel: (deviceProfileId) =>
    ipcRenderer.invoke("get-native-bed-model", deviceProfileId),
  getWorkshopRuntimeMode: () =>
    ipcRenderer.invoke("get-workshop-runtime-mode"),
  openWiki: (url) => ipcRenderer.invoke("open-wiki", url),
  pickWorkshopImage: () =>
    ipcRenderer.invoke("pick-workshop-image"),
});
