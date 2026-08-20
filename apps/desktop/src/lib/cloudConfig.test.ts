import { afterEach, describe, expect, it, vi } from 'vitest'
import { getCloudEnvironment, isCloudEnabled } from './cloudConfig'

describe('cloudConfig', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
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

  it('getCloudEnvironment returns a browser runtime snapshot', () => {
    const env = getCloudEnvironment()
    expect(env).toEqual(
      expect.objectContaining({
        cloudEnabled: expect.any(Boolean),
        production: expect.any(Boolean),
        development: expect.any(Boolean),
      }),
    )
  })
})
