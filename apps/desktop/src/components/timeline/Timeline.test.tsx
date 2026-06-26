import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Timeline } from './Timeline'
import * as cloudConfig from '../../lib/cloudConfig'
import * as aiClient from '../../lib/aiClient'
import { useProjectStore } from '../../stores/projectStore'

const HOOK_ORDER_ERROR = /rendered (more|fewer) hooks|order of hooks/i

interface ModeConfig {
  name: string
  cloudEnabled: boolean
  electron: boolean
}

/**
 * The packaged EXE differs from `pnpm dev` along two axes: it is a production
 * build and it exposes `window.axew`. The historical crash came from gating a
 * hook on these signals. These matrix cases prove the hook order is identical
 * in every configuration.
 */
const MODES: ModeConfig[] = [
  { name: 'dev / cloud disabled', cloudEnabled: false, electron: false },
  { name: 'dev / cloud enabled', cloudEnabled: true, electron: false },
  { name: 'production browser / cloud disabled', cloudEnabled: false, electron: false },
  { name: 'production browser / cloud enabled', cloudEnabled: true, electron: false },
  { name: 'packaged EXE / cloud disabled', cloudEnabled: false, electron: true },
  { name: 'packaged EXE / cloud enabled', cloudEnabled: true, electron: true },
]

function applyMode(mode: ModeConfig) {
  vi.spyOn(cloudConfig, 'isCloudEnabled').mockReturnValue(mode.cloudEnabled)
  if (mode.electron) {
    ;(window as unknown as { axew: unknown }).axew = { ipc: { on: () => () => {} } }
  } else {
    delete (window as unknown as { axew?: unknown }).axew
  }
}

describe('Timeline startup (hook-order safety matrix)', () => {
  let errorSpy: { mock: { calls: unknown[][] } }

  beforeEach(() => {
    // Non-resolving promise: these tests assert hook-order safety only, so we
    // avoid async state updates (and the accompanying act() warnings).
    vi.spyOn(aiClient, 'fetchOpusClipHealth').mockReturnValue(new Promise(() => {}))
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    useProjectStore.getState().closeProject()
    delete (window as unknown as { axew?: unknown }).axew
    vi.restoreAllMocks()
  })

  function expectNoHookOrderErrors() {
    const hookErrors = errorSpy.mock.calls.filter((call) =>
      call.some((arg) => typeof arg === 'string' && HOOK_ORDER_ERROR.test(arg)),
    )
    expect(hookErrors).toHaveLength(0)
  }

  it.each(MODES)('renders without a project in %s', (mode) => {
    applyMode(mode as ModeConfig)
    const { container } = render(<Timeline />)
    expect(container).toBeTruthy()
    expectNoHookOrderErrors()
  })

  it.each(MODES)('renders with a project in %s', (mode) => {
    applyMode(mode as ModeConfig)
    useProjectStore.getState().createProject('Test Project')
    const { container } = render(<Timeline />)
    expect(container.querySelector('.bg-axew-timeline')).toBeTruthy()
    expectNoHookOrderErrors()
  })

  it('does not throw "more hooks" when toggling dev → packaged/cloud-enabled on the same instance', () => {
    // Start in dev / cloud disabled.
    const cloudSpy = vi.spyOn(cloudConfig, 'isCloudEnabled').mockReturnValue(false)
    useProjectStore.getState().createProject('Test Project')

    const { rerender } = render(<Timeline />)

    // Simulate switching to the packaged EXE production config and re-render
    // the SAME component instance.
    cloudSpy.mockReturnValue(true)
    ;(window as unknown as { axew: unknown }).axew = { ipc: { on: () => () => {} } }
    expect(() => rerender(<Timeline />)).not.toThrow()

    // And toggle the project away (exercises the early-return branch on a
    // mounted instance — hooks still run first).
    useProjectStore.getState().closeProject()
    expect(() => rerender(<Timeline />)).not.toThrow()

    expectNoHookOrderErrors()
  })
})
