import { useEffect, useRef, useState } from 'react'
import { Activity, Loader2, RotateCcw, Scissors, Sparkles, Wand2, Zap } from 'lucide-react'
import { fetchTranscriptionDiagnostics } from '../../lib/aiClient'
import { applyPromptToTimeline, confirmSuggestedAction } from '../../lib/editOrchestrator'
import { useAIStore } from '../../stores/aiStore'
import { useProjectStore } from '../../stores/projectStore'
import { useTimelineStore } from '../../stores/timelineStore'
import { cn } from '../../lib/cn'

const QUICK_PROMPTS = [
  { label: 'Cut silence', icon: Scissors, prompt: 'Remove silence from the timeline' },
  { label: 'Detect scenes', icon: Wand2, prompt: 'Detect scene changes and add markers' },
  { label: 'Transcribe', icon: Sparkles, prompt: 'Transcribe and add subtitles' },
]

const PHASE_LABELS: Record<string, string> = {
  idle: 'Ready',
  parsing: 'Parsing intent',
  transcribing: 'Building transcript index',
  searching: 'Semantic search',
  planning: 'Generating actions',
  executing: 'Applying timeline edits',
  preview: 'Previewing extract',
  done: 'Complete',
  error: 'Error',
}

export function AIPanel() {
  const [input, setInput] = useState('')
  const [transcriptionReady, setTranscriptionReady] = useState<boolean | null>(null)
  const [setupHints, setSetupHints] = useState<string[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const { currentProject } = useProjectStore()
  const { undo } = useTimelineStore()
  const {
    isThinking,
    executionPhase,
    executionLogs,
    semanticMatches,
    highlightRanges,
    appliedOperations,
    pendingActions,
    aiServiceStatus,
    resetExecution,
    suggestedAction,
    setSuggestedAction,
  } = useAIStore()

  useEffect(() => {
    if (aiServiceStatus !== 'connected') {
      setTranscriptionReady(null)
      return
    }
    fetchTranscriptionDiagnostics().then((d) => {
      setTranscriptionReady(d.ready)
      setSetupHints(d.ready ? [] : [...d.errors, ...d.hints])
    })
  }, [aiServiceStatus])

  const handleExecute = async () => {
    if (!input.trim() || isThinking) return
    const prompt = input.trim()
    setInput('')
    await applyPromptToTimeline(prompt)
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }

  const handleQuickPrompt = async (prompt: string) => {
    if (isThinking) return
    await applyPromptToTimeline(prompt)
  }

  return (
    <div className="flex h-full flex-col bg-axew-surface">
      <div className="flex flex-shrink-0 items-center justify-between border-b border-axew-border px-3 py-2">
        <div className="flex items-center gap-1.5">
          <Zap size={12} className="text-axew-ai" />
          <span className="text-xs font-medium text-axew-text">AI Engine</span>
        </div>
        <div className="flex items-center gap-2 text-2xs text-axew-textDim">
          <span className={
            aiServiceStatus === 'connected'
              ? 'text-axew-success'
              : aiServiceStatus === 'starting'
                ? 'text-yellow-400'
                : ''
          }>
            {aiServiceStatus === 'connected'
              ? 'Online'
              : aiServiceStatus === 'starting'
                ? 'Starting…'
                : 'Offline'}
          </span>
          {transcriptionReady === true && (
            <span className="text-axew-success">Whisper</span>
          )}
          {transcriptionReady === false && (
            <span className="text-amber-400" title={setupHints.join('\n')}>
              Setup needed
            </span>
          )}
          <Activity size={10} className={executionPhase !== 'idle' ? 'text-axew-ai animate-pulse' : ''} />
        </div>
      </div>

      <div className="flex flex-shrink-0 gap-1 border-b border-axew-border p-2">
        {QUICK_PROMPTS.map(({ label, icon: Icon, prompt }) => (
          <button
            key={label}
            type="button"
            disabled={isThinking || !currentProject}
            className="flex flex-1 flex-col items-center gap-0.5 rounded border border-axew-border bg-axew-panel px-1 py-1.5 text-2xs text-axew-textMuted hover:border-axew-ai/40 hover:text-axew-text disabled:opacity-40"
            onClick={() => handleQuickPrompt(prompt)}
          >
            <Icon size={11} />
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className="flex flex-shrink-0 items-center gap-2 border-b border-axew-border px-3 py-1.5">
        <span className="text-2xs text-axew-textDim">Status</span>
        <span
          className={cn(
            'text-2xs font-medium',
            executionPhase === 'done' && 'text-axew-success',
            executionPhase === 'error' && 'text-red-400',
            executionPhase !== 'idle' && executionPhase !== 'done' && executionPhase !== 'error' && 'text-axew-ai',
          )}
        >
          {isThinking ? (
            <span className="flex items-center gap-1">
              <Loader2 size={10} className="animate-spin" />
              {PHASE_LABELS[executionPhase] ?? executionPhase}
            </span>
          ) : (
            PHASE_LABELS[executionPhase] ?? 'Ready'
          )}
        </span>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-2 overflow-y-auto p-3">
        {!currentProject && (
          <p className="text-center text-2xs text-axew-textDim">Open a project to run AI timeline edits.</p>
        )}

        {transcriptionReady === false && setupHints.length > 0 && (
          <section className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-2xs text-amber-200">
            <p className="mb-1 font-medium">Transcription setup required</p>
            <ul className="list-inside list-disc space-y-0.5 text-amber-200/90">
              {setupHints.slice(0, 4).map((hint, i) => (
                <li key={i}>{hint}</li>
              ))}
            </ul>
            <p className="mt-1 text-axew-textDim">
              Run: apps/ai-service/scripts/setup_transcription.ps1
            </p>
          </section>
        )}

        {highlightRanges.length > 0 && (
          <section className="rounded border border-axew-ai/30 bg-axew-ai/5 p-2">
            <p className="mb-1 text-2xs font-medium text-axew-ai">Extracted region</p>
            {highlightRanges.map((r, i) => (
              <div key={i} className="text-2xs text-axew-textMuted">
                <span className="text-axew-text">
                  {r.start.toFixed(2)}s – {r.end.toFixed(2)}s
                </span>
                <span className="ml-2 text-axew-textDim">({Math.round(r.confidence * 100)}%)</span>
                {r.label && <p className="mt-0.5 truncate text-axew-textDim">{r.label}</p>}
              </div>
            ))}
          </section>
        )}

        {suggestedAction && (
          <section className="rounded border border-amber-500/40 bg-amber-500/10 p-2">
            <p className="mb-1 text-2xs font-medium text-amber-200">Candidate extraction</p>
            <p className="text-2xs text-amber-100/90">
              AXEW found a plausible segment and highlighted it for preview instead of mutating the timeline automatically.
            </p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                className="rounded bg-amber-400 px-2 py-1 text-2xs font-medium text-black hover:bg-amber-300"
                onClick={() => confirmSuggestedAction()}
              >
                Apply suggested extract
              </button>
              <button
                type="button"
                className="rounded border border-amber-300/40 px-2 py-1 text-2xs text-amber-100"
                onClick={() => setSuggestedAction(null)}
              >
                Dismiss
              </button>
            </div>
          </section>
        )}

        {semanticMatches.length > 0 && (
          <section>
            <p className="mb-1 text-2xs font-medium text-axew-textDim">Transcript matches</p>
            {semanticMatches.slice(0, 5).map((m) => (
              <div
                key={m.segmentId}
                className="mb-1 rounded border border-axew-border bg-axew-panel px-2 py-1"
              >
                <div className="flex justify-between text-2xs">
                  <span className="text-axew-text">
                    {m.start.toFixed(1)}s – {m.end.toFixed(1)}s
                  </span>
                  <span className="text-axew-ai">{Math.round(m.score * 100)}%</span>
                </div>
                <p className="truncate text-2xs text-axew-textMuted">{m.text}</p>
              </div>
            ))}
          </section>
        )}

        {appliedOperations.length > 0 && (
          <section>
            <p className="mb-1 text-2xs font-medium text-axew-textDim">Applied operations</p>
            {appliedOperations.map((op, i) => (
              <div
                key={i}
                className={cn(
                  'mb-1 rounded px-2 py-1 text-2xs',
                  op.success ? 'bg-axew-panel text-axew-text' : 'bg-red-900/20 text-red-300',
                )}
              >
                {op.action.type}
                {op.action.confidence > 0 && (
                  <span className="ml-1 text-axew-textDim">
                    ({Math.round(op.action.confidence * 100)}%)
                  </span>
                )}
              </div>
            ))}
          </section>
        )}

        {pendingActions.length > 0 && (
          <section>
            <p className="mb-1 text-2xs text-axew-textDim">Queued ({pendingActions.length})</p>
            {pendingActions.map((action, i) => (
              <div key={`${action.type}-${i}`} className="mb-1 rounded border border-axew-border px-2 py-1 text-2xs">
                {action.type}: {action.description}
              </div>
            ))}
          </section>
        )}

        {executionLogs.length > 0 && (
          <section>
            <p className="mb-1 text-2xs font-medium text-axew-textDim">Execution trace</p>
            <div className="max-h-32 space-y-0.5 overflow-y-auto font-mono text-2xs text-axew-textDim">
              {executionLogs.map((log) => (
                <div key={log.id}>
                  <span className="text-axew-textDim/60">[{log.phase}]</span> {log.message}
                </div>
              ))}
            </div>
          </section>
        )}

        {executionLogs.length === 0 && currentProject && !isThinking && (
          <p className="text-center text-2xs text-axew-textDim">
            Describe what to keep or extract. AXEW will search the transcript and edit the timeline
            automatically.
          </p>
        )}
      </div>

      <div className="flex flex-shrink-0 items-center gap-1 border-t border-axew-border px-2 py-1">
        <button
          type="button"
          title="Undo last edit"
          className="rounded p-1.5 text-axew-textDim hover:bg-axew-panel hover:text-axew-text"
          onClick={() => undo()}
        >
          <RotateCcw size={12} />
        </button>
        <button
          type="button"
          className="text-2xs text-axew-textDim hover:text-axew-text"
          onClick={() => resetExecution()}
        >
          Clear log
        </button>
      </div>

      <div className="flex flex-shrink-0 gap-1 border-t border-axew-border p-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleExecute()}
          placeholder='e.g. "Keep only where interviewer gives 101 rupees to Vijay Mallya"'
          className="flex-1 rounded border border-axew-border bg-axew-panel px-2 py-1.5 text-xs text-axew-text outline-none placeholder:text-axew-textDim focus:border-axew-accent"
        />
        <button
          type="button"
          className="rounded bg-axew-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-axew-accentHover disabled:opacity-40"
          onClick={handleExecute}
          disabled={isThinking || !input.trim() || !currentProject}
        >
          Run
        </button>
      </div>
    </div>
  )
}
