import { useEffect, useRef } from 'react'
import {
  checkAIReadiness,
  checkOllamaStatus,
  fetchTranscriptionDiagnostics,
} from '../lib/aiClient'
import { useAIStore } from '../stores/aiStore'

export function useAIServiceCheck() {
  const {
    setOllamaStatus,
    setAIServiceStatus,
    setAIServicePhase,
    appendExecutionLog,
  } = useAIStore()
  const diagChecked = useRef(false)

  useEffect(() => {
    const check = async () => {
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
    }
  }, [setOllamaStatus, setAIServiceStatus, setAIServicePhase, appendExecutionLog])
}
