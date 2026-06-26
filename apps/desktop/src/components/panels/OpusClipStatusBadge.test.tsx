import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OpusClipStatusBadge } from './OpusClipStatusBadge'
import * as cloudConfig from '../../lib/cloudConfig'
import * as aiClient from '../../lib/aiClient'

describe('OpusClipStatusBadge', () => {
  beforeEach(() => {
    vi.spyOn(cloudConfig, 'isCloudEnabled').mockReturnValue(true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the loading state before the first poll resolves', () => {
    vi.spyOn(aiClient, 'fetchOpusClipHealth').mockReturnValue(new Promise(() => {}))
    render(<OpusClipStatusBadge />)
    const badge = screen.getByTestId('opusclip-status-badge')
    expect(badge).toHaveAttribute('data-state', 'loading')
    expect(badge).toHaveTextContent(/Checking/i)
  })

  it('renders the online state', async () => {
    vi.spyOn(aiClient, 'fetchOpusClipHealth').mockResolvedValue({
      status: 'online',
      service: 'opusclip',
      apiKeyPresent: true,
      reason: null,
    })
    render(<OpusClipStatusBadge />)
    await waitFor(() =>
      expect(screen.getByTestId('opusclip-status-badge')).toHaveAttribute(
        'data-state',
        'online',
      ),
    )
    expect(screen.getByTestId('opusclip-status-badge')).toHaveTextContent(/Online/i)
  })

  it('renders the offline state with a reason tooltip', async () => {
    vi.spyOn(aiClient, 'fetchOpusClipHealth').mockResolvedValue({
      status: 'offline',
      service: 'opusclip',
      apiKeyPresent: false,
      reason: 'missing_api_key',
    })
    render(<OpusClipStatusBadge />)
    await waitFor(() =>
      expect(screen.getByTestId('opusclip-status-badge')).toHaveAttribute(
        'data-state',
        'offline',
      ),
    )
    const badge = screen.getByTestId('opusclip-status-badge')
    expect(badge).toHaveTextContent(/Offline/i)
    expect(badge).toHaveAttribute('title', 'No API key configured')
  })

  it('renders offline when cloud features are disabled without polling', async () => {
    vi.spyOn(cloudConfig, 'isCloudEnabled').mockReturnValue(false)
    const spy = vi.spyOn(aiClient, 'fetchOpusClipHealth')
    render(<OpusClipStatusBadge />)
    await waitFor(() =>
      expect(screen.getByTestId('opusclip-status-badge')).toHaveAttribute(
        'data-state',
        'offline',
      ),
    )
    expect(spy).not.toHaveBeenCalled()
  })
})
