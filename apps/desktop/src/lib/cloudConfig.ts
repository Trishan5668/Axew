function readBooleanFlag(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value === 1
  if (typeof value === 'string') {
    const v = value.trim().toLowerCase()
    return v === 'true' || v === '1' || v === 'yes' || v === 'on'
  }
  return false
}

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

export function isCloudEnabled(): boolean {
  return readBooleanFlag(viteEnv().VITE_AXEW_CLOUD_ENABLED)
}

export function isProductionBuild(): boolean {
  return readBooleanFlag(viteEnv().PROD)
}

export function isDevelopmentBuild(): boolean {
  const env = viteEnv()
  if (typeof env.DEV !== 'undefined') return readBooleanFlag(env.DEV)
  return !isProductionBuild()
}

export interface CloudEnvironment {
  cloudEnabled: boolean
  production: boolean
  development: boolean
}

export function getCloudEnvironment(): CloudEnvironment {
  return {
    cloudEnabled: isCloudEnabled(),
    production: isProductionBuild(),
    development: isDevelopmentBuild(),
  }
}
