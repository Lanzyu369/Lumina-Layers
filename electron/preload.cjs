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
  platform: process.platform,
  alignTrafficLights: (centerY, controlsHeight) => ipcRenderer.invoke("align-traffic-lights", centerY, controlsHeight),
  setTitlebarTheme: (theme) => ipcRenderer.send("set-titlebar-theme", theme),
  setApplicationMenuState: (state) => ipcRenderer.send("application-menu-state", state),
  onApplicationMenuCommand: (listener) => {
    const forward = (_event, command) => listener(command);
    ipcRenderer.on("application-menu-command", forward);
    return () => ipcRenderer.removeListener("application-menu-command", forward);
  },
  saveGeneratedFile: (payload) => ipcRenderer.invoke("save-generated-file", payload),
  setGeneratedFileDirectory: (directory) =>
    ipcRenderer.invoke("set-generated-file-directory", directory),
  pickGeneratedFileDirectory: () =>
    ipcRenderer.invoke("pick-generated-file-directory"),
  getInterfaceScale: () => ipcRenderer.invoke("get-interface-scale"),
  setInterfaceScale: (preference) =>
    ipcRenderer.invoke("set-interface-scale", preference),
  onInterfaceScaleChanged: (listener) => {
    const forward = (_event, payload) => listener(payload);
    ipcRenderer.on("interface-scale-changed", forward);
    return () => ipcRenderer.removeListener("interface-scale-changed", forward);
  },
  getNativeBedModel: (deviceProfileId) =>
    ipcRenderer.invoke("get-native-bed-model", deviceProfileId),
  getWorkshopRuntimeMode: () =>
    ipcRenderer.invoke("get-workshop-runtime-mode"),
  openWiki: (url) => ipcRenderer.invoke("open-wiki", url),
  openGradientModel: (url) => ipcRenderer.invoke("open-gradient-model", url),
  pickWorkshopImage: () =>
    ipcRenderer.invoke("pick-workshop-image"),
});
