import { contextBridge, ipcRenderer } from 'electron'

type IpcListener = (...args: unknown[]) => void

const api = {
  dialog: {
    openFile: (options: Electron.OpenDialogOptions) =>
      ipcRenderer.invoke('dialog:openFile', options),
    saveFile: (options: Electron.SaveDialogOptions) =>
      ipcRenderer.invoke('dialog:saveFile', options),
  },
  shell: {
    openExternal: (url: string) => ipcRenderer.invoke('shell:openExternal', url),
  },
  app: {
    getVersion: () => ipcRenderer.invoke('app:getVersion'),
    getPaths: () => ipcRenderer.invoke('app:getPaths'),
  },
  auth: {
    getOAuthRedirectUrl: () =>
      ipcRenderer.invoke('auth:getOAuthRedirectUrl') as Promise<string>,
  },
  fs: {
    readFile: (filePath: string) => ipcRenderer.invoke('fs:readFile', filePath),
    writeFile: (filePath: string, content: string) =>
      ipcRenderer.invoke('fs:writeFile', filePath, content),
    exists: (filePath: string) => ipcRenderer.invoke('fs:exists', filePath),
  },
  media: {
    resolvePlaybackUrl: (filePath: string) =>
      ipcRenderer.invoke('media:resolvePlaybackUrl', filePath) as Promise<{
        exists: boolean
        url: string | null
        error: string | null
      }>,
  },
  services: {
    getStatus: () => ipcRenderer.invoke('services:getStatus'),
    restartAI: () => ipcRenderer.invoke('services:restartAI'),
    restartRust: () => ipcRenderer.invoke('services:restartRust'),
  },
  models: {
    list: () => ipcRenderer.invoke('models:list'),
    hasAny: () => ipcRenderer.invoke('models:has-any') as Promise<boolean>,
    download: (modelId: string) =>
      ipcRenderer.invoke('models:download', modelId) as Promise<{ ok: boolean; path?: string; error?: string }>,
  },
  menu: {
    on: (event: string, listener: IpcListener) => {
      ipcRenderer.on(`menu:${event}`, listener)
    },
    off: (event: string, listener: IpcListener) => {
      ipcRenderer.removeListener(`menu:${event}`, listener)
    },
  },
  ipc: {
    send: (channel: string, ...args: unknown[]) => ipcRenderer.send(channel, ...args),
    invoke: (channel: string, ...args: unknown[]) => ipcRenderer.invoke(channel, ...args),
    on: (channel: string, listener: IpcListener) => {
      ipcRenderer.on(channel, listener)
      return () => ipcRenderer.removeListener(channel, listener)
    },
  },
}

contextBridge.exposeInMainWorld('axew', api)

export type AxewAPI = typeof api
