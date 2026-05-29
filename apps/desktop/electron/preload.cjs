const { contextBridge, ipcRenderer } = require('electron')

const api = {
  dialog: {
    openFile: (options) => ipcRenderer.invoke('dialog:openFile', options),
    saveFile: (options) => ipcRenderer.invoke('dialog:saveFile', options),
  },
  shell: {
    openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url),
  },
  app: {
    getVersion: () => ipcRenderer.invoke('app:getVersion'),
    getPaths: () => ipcRenderer.invoke('app:getPaths'),
  },
  fs: {
    readFile: (filePath) => ipcRenderer.invoke('fs:readFile', filePath),
    writeFile: (filePath, content) => ipcRenderer.invoke('fs:writeFile', filePath, content),
    exists: (filePath) => ipcRenderer.invoke('fs:exists', filePath),
  },
  media: {
    resolvePlaybackUrl: (filePath) => ipcRenderer.invoke('media:resolvePlaybackUrl', filePath),
  },
  services: {
    getStatus: () => ipcRenderer.invoke('services:getStatus'),
  },
  menu: {
    on: (event, listener) => {
      ipcRenderer.on(`menu:${event}`, listener)
    },
    off: (event, listener) => {
      ipcRenderer.removeListener(`menu:${event}`, listener)
    },
  },
  ipc: {
    send: (channel, ...args) => ipcRenderer.send(channel, ...args),
    invoke: (channel, ...args) => ipcRenderer.invoke(channel, ...args),
    on: (channel, listener) => {
      ipcRenderer.on(channel, listener)
      return () => ipcRenderer.removeListener(channel, listener)
    },
  },
}

contextBridge.exposeInMainWorld('axew', api)
