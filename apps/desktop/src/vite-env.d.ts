/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Enables AXEW cloud features (OpusClip integration). Set to "true" to enable. */
  readonly VITE_AXEW_CLOUD_ENABLED?: string
  /** Enables verbose playback debugging. */
  readonly VITE_DEBUG_PLAYBACK?: string
  /** Injected by vite-plugin-electron in dev. */
  readonly VITE_DEV_SERVER_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
