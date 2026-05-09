const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("omnipilotDesktop", {
  onHotkey: (callback) => ipcRenderer.on("omnipilot-hotkey", callback),
  onRefresh: (callback) => ipcRenderer.on("omnipilot-refresh", callback),
  onMiniCollapsed: (callback) => ipcRenderer.on("omnipilot-mini-collapsed", (_event, collapsed) => callback(collapsed)),
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
  showMain: () => ipcRenderer.invoke("show-main"),
  showMini: () => ipcRenderer.invoke("show-mini"),
  hideMini: () => ipcRenderer.invoke("hide-mini"),
  collapseMini: () => ipcRenderer.invoke("collapse-mini"),
  expandMini: () => ipcRenderer.invoke("expand-mini"),
  quit: () => ipcRenderer.invoke("quit-app"),
});
