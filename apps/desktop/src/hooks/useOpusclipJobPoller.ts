/**
 * Polls the AI service for the current OpusClip job and pulls results
 * once it completes.
 *
 * Behavior:
 *   - Activates whenever `jobId` is non-null in opusclipStore.
 *   - Polls GET /opusclip/status/:id every ~3s with mild jitter.
 *   - On `stage='completed'` it fetches GET /opusclip/result/:id and
 *     stores the normalized results in the slice, then stops polling.
 *   - On `stage='failed' | 'expired'` it stops polling and surfaces the
 *     server-provided error_message in the slice.
 *   - Cleans up the interval + aborts in-flight fetches on unmount or
 *     when the jobId changes.
 */

import { useEffect, useRef } from 'react'
import {
  getJobResult,
  getJobStatus,
  isJobTerminal,
} from '../lib/opusclipClient'
import { useOpusclipStore } from '../stores/opusclipSlice'

const POLL_INTERVAL_MS = 3000
const POLL_JITTER_MS = 750
const MAX_CONSECUTIVE_ERRORS = 4

export function useOpusclipJobPoller(): void {
  const jobId = useOpusclipStore((s) => s.jobId)
  const setJobStatus = useOpusclipStore((s) => s.setJobStatus)
  const setResults = useOpusclipStore((s) => s.setResults)
  const setStatus = useOpusclipStore((s) => s.setStatus)

  const errorCountRef = useRef(0)
  const stoppedRef = useRef(false)

  useEffect(() => {
    if (!jobId) return

    const controller = new AbortController()
    stoppedRef.current = false
    errorCountRef.current = 0
    let timer: ReturnType<typeof setTimeout> | null = null

    const tick = async () => {
      if (stoppedRef.current) return

      try {
        const status = await getJobStatus(jobId, controller.signal)
        errorCountRef.current = 0
        setJobStatus(status)

        if (status.stage === 'completed') {
          try {
            const result = await getJobResult(jobId, controller.signal)
            setResults(result.results)
          } catch (err) {
            const message =
              err instanceof Error ? err.message : 'Failed to fetch results.'
            setStatus('error', message)
          }
          stoppedRef.current = true
          return
        }

        if (isJobTerminal(status.stage)) {
          // 'failed' / 'expired' already wrote the error_message via setJobStatus
          stoppedRef.current = true
          return
        }
      } catch (err) {
        errorCountRef.current += 1
        if (errorCountRef.current >= MAX_CONSECUTIVE_ERRORS) {
          const message =
            err instanceof Error
              ? err.message
              : 'Lost connection to the AI service.'
          setStatus('error', message)
          stoppedRef.current = true
          return
        }
        // transient: fall through and retry on the next tick
      }

      const jitter = Math.random() * POLL_JITTER_MS
      timer = setTimeout(tick, POLL_INTERVAL_MS + jitter)
    }

    tick()

    return () => {
      stoppedRef.current = true
      controller.abort()
      if (timer !== null) clearTimeout(timer)
    }
  }, [jobId, setJobStatus, setResults, setStatus])
}
