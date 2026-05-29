export type OpenDialogResult = {
  canceled: boolean
  filePaths: string[]
}

export type SaveDialogResult = {
  canceled: boolean
  filePath?: string
}

export type AxewAPI = {
  dialog: {
    openFile: (options: Record<string, unknown>) => Promise<OpenDialogResult>
    saveFile: (options: Record<string, unknown>) => Promise<SaveDialogResult>
  }
  shell: {
    openExternal: (url: string) => Promise<void>
  }
  app: {
    getVersion: () => Promise<string>
    getPaths: () => Promise<{
      userData: string
      documents: string
      downloads: string
      home: string
      temp: string
    }>
  }
  fs: {
    readFile: (filePath: string) => Promise<{ success: boolean; data?: string; error?: string }>
    writeFile: (
      filePath: string,
      content: string,
    ) => Promise<{ success: boolean; error?: string }>
    exists: (filePath: string) => Promise<boolean>
  }
  media: {
    resolvePlaybackUrl: (filePath: string) => Promise<{
      exists: boolean
      url: string | null
      error: string | null
    }>
  }
  services: {
    getStatus: () => Promise<{
      rust: { running: boolean; port: string }
      ai: {
        running: boolean
        healthy: boolean
        ready: boolean
        phase: string
        port: string
        restarts: number
        memory: Record<string, unknown> | null
      }
    }>
    restartAI: () => Promise<{ ok: boolean }>
    restartRust: () => Promise<{ ok: boolean }>
  }
  menu: {
    on: (event: string, listener: (...args: unknown[]) => void) => void
    off: (event: string, listener: (...args: unknown[]) => void) => void
  }
  ipc: {
    send: (channel: string, ...args: unknown[]) => void
    invoke: (channel: string, ...args: unknown[]) => Promise<unknown>
    on: (channel: string, listener: (...args: unknown[]) => void) => () => void
  }
}
