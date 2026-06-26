/**
 * Cloud / runtime environment detection helpers.
 *
 * These are PLAIN FUNCTIONS — never hooks. They may be called safely from
 * anywhere (render bodies, hooks, event handlers, module scope) without
 * affecting React's hook ordering.
 *
 * Why this matters: the packaged Electron EXE runs the renderer in a
 * production build (`import.meta.env.PROD === true`) and exposes
 * `window.axew`, whereas `pnpm dev` / `pnpm electron:dev` run a development
 * build. Code that branches on these signals MUST do so *inside* a hook or
 * after all hooks have run — never to decide *whether* a hook is called.
 * Centralising the detection here keeps that contract easy to honour.
 */

function readBooleanFlag(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value === 1
  if (typeof value === 'string') {
    const v = value.trim().toLowerCase()
    return v === 'true' || v === '1' || v === 'yes' || v === 'on'
  }
  return false
}

/**
 * Safe accessor for build-time env that never throws.
 *
 * Merges `process.env` (available under Node/test runners) with Vite's
 * `import.meta.env` (the canonical source in the browser/packaged build).
 * `import.meta.env` wins so production inlined values always take precedence.
 */
function viteEnv(): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  try {
    if (typeof process !== 'undefined' && process.env) {
      Object.assign(out, process.env)
    }
  } catch {
    /* process not available in browser */
  }
  try {
    const env = (import.meta as unknown as { env?: Record<string, unknown> }).env
    if (env) {
      for (const [key, value] of Object.entries(env)) {
        if (value !== undefined) out[key] = value
      }
    }
  } catch {
    /* import.meta.env unavailable */
  }
  return out
}

/** Whether the AXEW cloud / OpusClip integration is enabled via env flag. */
export function isCloudEnabled(): boolean {
  return readBooleanFlag(viteEnv().VITE_AXEW_CLOUD_ENABLED)
}

/** Whether this is a production (minified) build. True inside the packaged EXE. */
export function isProductionBuild(): boolean {
  return readBooleanFlag(viteEnv().PROD)
}

/** Whether this is a development build (`pnpm dev`). */
export function isDevelopmentBuild(): boolean {
  // `import.meta.env.DEV` is the canonical Vite flag; fall back to !PROD.
  const env = viteEnv()
  if (typeof env.DEV !== 'undefined') return readBooleanFlag(env.DEV)
  return !isProductionBuild()
}

/** Whether the Electron preload bridge (`window.axew`) is available. */
export function hasElectronApi(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof (window as unknown as { axew?: unknown }).axew !== 'undefined' &&
    (window as unknown as { axew?: unknown }).axew !== null
  )
}

/**
 * Whether we are running inside the packaged desktop EXE: a production build
 * served by Electron (preload bridge present). This is the configuration that
 * historically diverged from `pnpm dev`.
 */
export function isPackagedApp(): boolean {
  return isProductionBuild() && hasElectronApi()
}

export interface CloudEnvironment {
  cloudEnabled: boolean
  production: boolean
  development: boolean
  electron: boolean
  packaged: boolean
}

/** Snapshot of all runtime flags. Pure — safe to call inside render. */
export function getCloudEnvironment(): CloudEnvironment {
  return {
    cloudEnabled: isCloudEnabled(),
    production: isProductionBuild(),
    development: isDevelopmentBuild(),
    electron: hasElectronApi(),
    packaged: isPackagedApp(),
  }
}
