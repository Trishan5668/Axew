import { useEffect, useRef, useState } from 'react'
import { fetchOpusClipHealth } from '../lib/aiClient'

export type OpusClipHealthState = 'loading' | 'online' | 'offline'

export interface OpusClipHealth {
  /** Current connection status. Starts as `loading` until the first poll resolves. */
  state: OpusClipHealthState
  /** Whether the backend reports an API key is configured. */
  apiKeyPresent: boolean
  /** Machine-readable reason when offline (e.g. `missing_api_key`, `timeout`). */
  reason: string | null
  /** Epoch ms of the last successful check, or null before the first check. */
  lastChecked: number | null
}

export interface UseOpusclipHealthOptions {
  /**
   * When false the hook performs NO network polling and resolves to a stable
   * disabled state. The hook still runs every internal hook unconditionally so
   * React's hook order is identical whether or not cloud features are enabled.
   */
  enabled?: boolean
  /** Poll interval in ms. Defaults to 30s. */
  intervalMs?: number
}

const DEFAULT_INTERVAL = 30_000

const INITIAL: OpusClipHealth = {
  state: 'loading',
  apiKeyPresent: false,
  reason: null,
  lastChecked: null,
}

const DISABLED: OpusClipHealth = {
  state: 'offline',
  apiKeyPresent: false,
  reason: 'cloud_disabled',
  lastChecked: null,
}

/**
 * Poll the OpusClip health endpoint and expose a never-throwing status object.
 *
 * Hook-safety contract: this hook ALWAYS calls the same hooks in the same order
 * regardless of `enabled`. When disabled it simply skips scheduling network
 * work and reports a stable `cloud_disabled` state. This guarantees identical
 * behaviour between `pnpm dev` and the packaged production EXE.
 */
export function useOpusclipHealth(options: UseOpusclipHealthOptions = {}): OpusClipHealth {
  const { enabled = true, intervalMs = DEFAULT_INTERVAL } = options
  const [health, setHealth] = useState<OpusClipHealth>(INITIAL)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true

    if (!enabled) {
      setHealth(DISABLED)
      return () => {
        mountedRef.current = false
      }
    }

    let timer: ReturnType<typeof setInterval> | undefined

    const poll = async () => {
      try {
        const result = await fetchOpusClipHealth()
        if (!mountedRef.current) return
        setHealth({
          state: result.status,
          apiKeyPresent: result.apiKeyPresent,
          reason: result.reason,
          lastChecked: Date.now(),
        })
      } catch {
        // fetchOpusClipHealth never throws, but guard anyway so a failure can
        // never crash the host component.
        if (!mountedRef.current) return
        setHealth({
          state: 'offline',
          apiKeyPresent: false,
          reason: 'backend_unreachable',
          lastChecked: Date.now(),
        })
      }
    }

    void poll()
    timer = setInterval(() => void poll(), intervalMs)

    return () => {
      mountedRef.current = false
      if (timer) clearInterval(timer)
    }
  }, [enabled, intervalMs])

  return health
}
