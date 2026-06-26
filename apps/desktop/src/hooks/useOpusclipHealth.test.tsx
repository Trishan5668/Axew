import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useOpusclipHealth } from './useOpusclipHealth'
import * as aiClient from '../lib/aiClient'

describe('useOpusclipHealth', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('starts in the loading state', () => {
    vi.spyOn(aiClient, 'fetchOpusClipHealth').mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useOpusclipHealth())
    expect(result.current.state).toBe('loading')
  })

  it('reports online when the endpoint reports online', async () => {
    vi.spyOn(aiClient, 'fetchOpusClipHealth').mockResolvedValue({
      status: 'online',
      service: 'opusclip',
      apiKeyPresent: true,
      reason: null,
    })
    const { result } = renderHook(() => useOpusclipHealth())
    await waitFor(() => expect(result.current.state).toBe('online'))
    expect(result.current.apiKeyPresent).toBe(true)
    expect(result.current.lastChecked).not.toBeNull()
  })

  it('reports offline with reason when the endpoint reports offline', async () => {
    vi.spyOn(aiClient, 'fetchOpusClipHealth').mockResolvedValue({
      status: 'offline',
      service: 'opusclip',
      apiKeyPresent: false,
      reason: 'missing_api_key',
    })
    const { result } = renderHook(() => useOpusclipHealth())
    await waitFor(() => expect(result.current.state).toBe('offline'))
    expect(result.current.reason).toBe('missing_api_key')
  })

  it('never crashes when the client rejects (network failure)', async () => {
    vi.spyOn(aiClient, 'fetchOpusClipHealth').mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useOpusclipHealth())
    await waitFor(() => expect(result.current.state).toBe('offline'))
    expect(result.current.reason).toBe('backend_unreachable')
  })

  it('polls again on the interval and updates automatically', async () => {
    const spy = vi
      .spyOn(aiClient, 'fetchOpusClipHealth')
      .mockResolvedValueOnce({
        status: 'offline',
        service: 'opusclip',
        apiKeyPresent: true,
        reason: 'service_unavailable',
      })
      .mockResolvedValue({
        status: 'online',
        service: 'opusclip',
        apiKeyPresent: true,
        reason: null,
      })

    const { result } = renderHook(() => useOpusclipHealth({ intervalMs: 200 }))

    await waitFor(() => expect(result.current.state).toBe('offline'))
    await waitFor(() => expect(result.current.state).toBe('online'), { timeout: 2000 })
    expect(spy.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('does not poll when disabled (cloud features off)', async () => {
    const spy = vi.spyOn(aiClient, 'fetchOpusClipHealth')
    const { result } = renderHook(() => useOpusclipHealth({ enabled: false }))
    await waitFor(() => expect(result.current.state).toBe('offline'))
    expect(spy).not.toHaveBeenCalled()
    expect(result.current.reason).toBe('cloud_disabled')
  })
})
