import { useEffect, useRef } from 'react'
import {
  checkAIReadiness,
  checkOllamaStatus,
  fetchTranscriptionDiagnostics,
} from '../lib/aiClient'
import { useAIStore } from '../stores/aiStore'

const STARTING_PHASES = new Set([
  'spawning',
  'initializing',
  'model_loading',
  'starting',
  'waiting_for_liveness',
  'waiting_for_ready',
  'SPAWNING',
  'INITIALIZING',
  'MODEL_LOADING',
])

export function useAIServiceCheck() {
  const {
    setOllamaStatus,
    setAIServiceStatus,
    setAIServicePhase,
    appendExecutionLog,
  } = useAIStore()
  const diagChecked = useRef(false)
  const lastIpcTime = useRef(0)

  useEffect(() => {
    const axew = (window as unknown as { axew?: { ipc?: { on?: (ch: string, fn: (...a: unknown[]) => void) => () => void } } }).axew
    let unsubStatus: (() => void) | undefined

    if (axew?.ipc?.on) {
      unsubStatus = axew.ipc.on('ai:status', (_event: unknown, payload: unknown) => {
        const data = payload as {
          online?: boolean
          phase?: string
          reason?: string
        }
        lastIpcTime.current = Date.now()

        if (data.phase) {
          setAIServicePhase(data.phase)
        }

        if (data.online) {
          setAIServiceStatus('connected')
        } else if (data.phase && STARTING_PHASES.has(data.phase)) {
          setAIServiceStatus('starting')
        } else if (data.phase === 'crashed' || data.phase === 'offline') {
          setAIServiceStatus('disconnected')
        } else {
          // For unknown phases during non-online state, preserve starting
          // status briefly to prevent flicker
          const current = useAIStore.getState().aiServiceStatus
          if (current !== 'starting') {
            setAIServiceStatus('disconnected')
          }
        }
      })
    }

    const check = async () => {
      // Skip polling if we received a fresh IPC event within last 10s
      if (Date.now() - lastIpcTime.current < 10_000) return

      setOllamaStatus('checking')

      const [ollama, aiReady] = await Promise.all([
        checkOllamaStatus(),
        checkAIReadiness(),
      ])

      setOllamaStatus(ollama ? 'connected' : 'disconnected')

      if (aiReady.ready) {
        setAIServiceStatus('connected')
        setAIServicePhase(aiReady.phase ?? 'READY')

        if (!diagChecked.current) {
          diagChecked.current = true
          const diag = await fetchTranscriptionDiagnostics()
          if (!diag.ready) {
            appendExecutionLog(
              'error',
              `Transcription deps: ${diag.errors.join(', ') || 'not ready'}`,
              { hints: diag.hints },
            )
          }
        }
      } else if (aiReady.live) {
        setAIServiceStatus('starting')
        setAIServicePhase(aiReady.phase ?? 'INITIALIZING')
      } else {
        const current = useAIStore.getState().aiServiceStatus
        if (current !== 'starting') {
          setAIServiceStatus('disconnected')
        }
      }
    }

    check()
    const interval = setInterval(check, 30_000)

    return () => {
      clearInterval(interval)
      unsubStatus?.()
    }
  }, [setOllamaStatus, setAIServiceStatus, setAIServicePhase, appendExecutionLog])
}
