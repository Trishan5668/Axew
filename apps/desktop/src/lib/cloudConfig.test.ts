import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  getCloudEnvironment,
  hasElectronApi,
  isCloudEnabled,
} from './cloudConfig'

describe('cloudConfig', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    delete (window as unknown as { axew?: unknown }).axew
  })

  describe('isCloudEnabled', () => {
    it('is false when the flag is unset', () => {
      expect(isCloudEnabled()).toBe(false)
    })

    it.each(['true', '1', 'yes', 'on', 'TRUE'])('is true for %s', (value) => {
      vi.stubEnv('VITE_AXEW_CLOUD_ENABLED', value)
      expect(isCloudEnabled()).toBe(true)
    })

    it.each(['false', '0', 'no', '', 'off'])('is false for %s', (value) => {
      vi.stubEnv('VITE_AXEW_CLOUD_ENABLED', value)
      expect(isCloudEnabled()).toBe(false)
    })
  })

  describe('hasElectronApi', () => {
    it('is false without window.axew', () => {
      expect(hasElectronApi()).toBe(false)
    })

    it('is true when the preload bridge is present', () => {
      ;(window as unknown as { axew: unknown }).axew = { ipc: {} }
      expect(hasElectronApi()).toBe(true)
    })
  })

  it('getCloudEnvironment returns a complete snapshot', () => {
    const env = getCloudEnvironment()
    expect(env).toEqual(
      expect.objectContaining({
        cloudEnabled: expect.any(Boolean),
        production: expect.any(Boolean),
        development: expect.any(Boolean),
        electron: expect.any(Boolean),
        packaged: expect.any(Boolean),
      }),
    )
  })
})
