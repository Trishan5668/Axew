import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useTimelineOpusClipMenu } from './useTimelineOpusClipMenu'
import * as cloudConfig from '../lib/cloudConfig'
import * as aiClient from '../lib/aiClient'

const HOOK_ORDER_ERROR = /rendered (more|fewer) hooks|order of hooks/i

describe('useTimelineOpusClipMenu', () => {
  beforeEach(() => {
    vi.spyOn(aiClient, 'fetchOpusClipHealth').mockResolvedValue({
      status: 'online',
      service: 'opusclip',
      apiKeyPresent: true,
      reason: null,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns disabled state and an empty menu when cloud is disabled', () => {
    vi.spyOn(cloudConfig, 'isCloudEnabled').mockReturnValue(false)
    const { result } = renderHook(() => useTimelineOpusClipMenu())
    expect(result.current.enabled).toBe(false)
    expect(result.current.items).toHaveLength(0)
  })

  it('openMenu is a no-op when cloud is disabled', () => {
    vi.spyOn(cloudConfig, 'isCloudEnabled').mockReturnValue(false)
    const { result } = renderHook(() => useTimelineOpusClipMenu())
    act(() => {
      result.current.openMenu({ clientX: 10, clientY: 20 }, 'clip-1')
    })
    expect(result.current.state.open).toBe(false)
  })

  it('opens a menu with items when cloud is enabled', () => {
    vi.spyOn(cloudConfig, 'isCloudEnabled').mockReturnValue(true)
    const { result } = renderHook(() => useTimelineOpusClipMenu())
    act(() => {
      result.current.openMenu({ clientX: 10, clientY: 20 }, 'clip-1')
    })
    expect(result.current.enabled).toBe(true)
    expect(result.current.state.open).toBe(true)
    expect(result.current.state.clipId).toBe('clip-1')
    expect(result.current.items.length).toBeGreaterThan(0)
  })

  // This is the core regression guard for the EXE-only crash: the SAME hook
  // instance must keep an identical hook order even when the cloud flag flips
  // (which is what differed between dev and the packaged production build).
  it('keeps a stable hook order when the cloud flag changes between renders', () => {
    const cloudSpy = vi.spyOn(cloudConfig, 'isCloudEnabled').mockReturnValue(false)
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const { rerender, result } = renderHook(() => useTimelineOpusClipMenu())
    expect(result.current.enabled).toBe(false)

    // Flip to enabled (simulating prod/EXE divergence) and re-render the
    // SAME instance — this would throw "Rendered more hooks" with the buggy
    // conditional-hook pattern.
    cloudSpy.mockReturnValue(true)
    expect(() => rerender()).not.toThrow()
    expect(result.current.enabled).toBe(true)

    cloudSpy.mockReturnValue(false)
    expect(() => rerender()).not.toThrow()

    const hookOrderErrors = errorSpy.mock.calls.filter((call) =>
      call.some((arg) => typeof arg === 'string' && HOOK_ORDER_ERROR.test(arg)),
    )
    expect(hookOrderErrors).toHaveLength(0)
  })
})
