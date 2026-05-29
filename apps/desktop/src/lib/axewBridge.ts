import type { AxewAPI } from '../types/axew'

const noop = () => {}

const devFallbackAxew: AxewAPI = {
  dialog: {
    openFile: async () => ({ canceled: true, filePaths: [] }),
    saveFile: async () => ({ canceled: true, filePath: undefined }),
  },
  shell: {
    openExternal: async () => {},
  },
  app: {
    getVersion: async () => '0.1.0-dev',
    getPaths: async () => ({
      userData: '',
      documents: '',
      downloads: '',
      home: '',
      temp: '',
    }),
  },
  fs: {
    readFile: async () => ({ success: false, error: 'AXEW bridge unavailable' }),
    writeFile: async () => ({ success: false, error: 'AXEW bridge unavailable' }),
    exists: async () => false,
  },
  media: {
    resolvePlaybackUrl: async (filePath: string) => ({
      exists: false,
      url: null,
      error: `AXEW bridge unavailable (cannot play ${filePath})`,
    }),
  },
  services: {
    getStatus: async () => ({
      rust: { running: false, port: '7001' },
      ai: {
        running: false,
        healthy: false,
        ready: false,
        phase: 'offline',
        port: '7002',
        restarts: 0,
        memory: null,
      },
    }),
    restartAI: async () => ({ ok: true }),
    restartRust: async () => ({ ok: true }),
  },
  menu: {
    on: noop,
    off: noop,
  },
  ipc: {
    send: noop,
    invoke: async () => undefined,
    on: () => noop,
  },
}

export function isAxewAvailable(): boolean {
  return typeof window !== 'undefined' && Boolean(window.axew)
}

export function getAxew(): AxewAPI {
  if (isAxewAvailable()) {
    return window.axew
  }
  if (import.meta.env.DEV) {
    console.warn('[AXEW] window.axew unavailable — using dev fallback bridge')
  }
  return devFallbackAxew
}
