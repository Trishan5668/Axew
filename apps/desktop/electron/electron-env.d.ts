import type { AxewAPI } from './preload'

declare global {
  interface Window {
    axew: AxewAPI
  }
}

export {}
