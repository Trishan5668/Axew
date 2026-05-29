import { Activity, Cpu, Loader2, Zap } from 'lucide-react'
import { formatTimecode } from '../../lib/timecode'
import { useAIStore } from '../../stores/aiStore'
import { usePlaybackStore } from '../../stores/playbackStore'
import { useUIStore } from '../../stores/uiStore'

function aiStatusColor(status: string, phase: string | null): string {
  if (status === 'connected') {
    if (phase === 'degraded' || phase === 'DEGRADED') return 'text-yellow-400'
    return 'text-axew-success'
  }
  if (status === 'starting') return 'text-yellow-400'
  return 'text-axew-textDim'
}

function aiStatusLabel(status: string, phase: string | null): string {
  if (status === 'connected') {
    if (phase === 'degraded' || phase === 'DEGRADED') return 'AI (degraded)'
    return 'AI'
  }
  if (status === 'starting') {
    const p = phase?.toLowerCase()
    if (p === 'model_loading') return 'AI (loading models)'
    if (p === 'initializing') return 'AI (initializing)'
    if (p === 'spawning') return 'AI (spawning)'
    return 'AI (starting)'
  }
  if (phase === 'crashed') return 'AI (crashed)'
  return 'AI (offline)'
}

export function StatusBar() {
  const { currentTime, duration, frameRate } = usePlaybackStore()
  const { statusMessage } = useUIStore()
  const { ollamaStatus, aiServiceStatus, aiServicePhase } = useAIStore()

  const isAIStarting = aiServiceStatus === 'starting'

  return (
    <div className="flex h-6 flex-shrink-0 select-none items-center gap-4 border-t border-axew-border bg-axew-bg px-3 text-2xs text-axew-textMuted">
      <div className="flex items-center gap-1.5 font-mono">
        <span>{formatTimecode(currentTime, frameRate)}</span>
        <span className="text-axew-textDim">/</span>
        <span className="text-axew-textDim">{formatTimecode(duration, frameRate)}</span>
      </div>

      <div className="h-3 w-px bg-axew-border" />
      <span>{frameRate} fps</span>

      {statusMessage && (
        <>
          <div className="h-3 w-px bg-axew-border" />
          <span className="text-axew-accent">{statusMessage}</span>
        </>
      )}

      <div className="flex-1" />

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1">
          <Zap
            size={9}
            className={ollamaStatus === 'connected' ? 'text-axew-success' : 'text-axew-textDim'}
          />
          <span>Ollama</span>
        </div>
        <div className="flex items-center gap-1">
          {isAIStarting ? (
            <Loader2 size={9} className="animate-spin text-yellow-400" />
          ) : (
            <Activity size={9} className={aiStatusColor(aiServiceStatus, aiServicePhase)} />
          )}
          <span className={aiStatusColor(aiServiceStatus, aiServicePhase)}>
            {aiStatusLabel(aiServiceStatus, aiServicePhase)}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Cpu size={9} className="text-axew-textDim" />
          <span>Rust</span>
        </div>
      </div>
    </div>
  )
}
