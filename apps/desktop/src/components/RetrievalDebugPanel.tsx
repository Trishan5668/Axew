import { useCallback, useEffect, useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import { ThumbsDown, ThumbsUp, X, HelpCircle, RefreshCw, AlertTriangle, Check, XCircle } from 'lucide-react'
import { cn } from '../lib/cn'
import { submitRetrievalFeedback, explainRetrievalSelection } from '../lib/semanticRetrieval'
import { useAIStore } from '../stores/aiStore'
import { useDebugStore } from '../stores/debugStore'
import { applyPromptToTimeline } from '../lib/editOrchestrator'

export function RetrievalDebugPanel() {
  const { debugRetrieval, retrievalSessionId, lastRetrievalQuery, setDebugPanelOpen } = useAIStore()
  const { lastRetrievalDebug, lastExtractionResult } = useDebugStore()
  const [explanation, setExplanation] = useState<string | null>(null)
  const [explaining, setExplaining] = useState(false)
  const [activeSection, setActiveSection] = useState<string>('intent')

  const debugData = lastRetrievalDebug
  const duration = debugRetrieval?.mediaDuration ?? 900
  const finalWindow = debugRetrieval?.finalWindow
  const candidates = debugRetrieval?.candidates ?? []

  const handleExplain = useCallback(async () => {
    if (!lastRetrievalQuery) return
    setExplaining(true)
    try {
      const text = candidates[0]?.text ?? ''
      setExplanation(await explainRetrievalSelection(lastRetrievalQuery, text))
    } finally {
      setExplaining(false)
    }
  }, [lastRetrievalQuery, candidates])

  const handleFeedback = useCallback(
    async (feedback: 'perfect' | 'close' | 'wrong') => {
      if (!retrievalSessionId) return
      await submitRetrievalFeedback(retrievalSessionId, feedback, lastRetrievalQuery ?? '')
    },
    [retrievalSessionId, lastRetrievalQuery],
  )

  const handleReretrieve = useCallback(async () => {
    if (!lastRetrievalQuery) return
    setDebugPanelOpen(false)
    await applyPromptToTimeline(lastRetrievalQuery)
  }, [lastRetrievalQuery, setDebugPanelOpen])

  // Keyboard shortcut: Shift+D to toggle
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.shiftKey && e.key === 'D') {
        setDebugPanelOpen(!useAIStore.getState().debugPanelOpen)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setDebugPanelOpen])

  return (
    <div className="absolute bottom-0 left-0 right-0 z-50 max-h-[60%] overflow-y-auto border-t border-axew-ai/40 bg-axew-surface shadow-2xl">
      <div className="flex items-center justify-between border-b border-axew-border px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-axew-ai">Retrieval Debug (Shift+D)</span>
          {debugData?.total_pipeline_ms && (
            <span className="text-2xs text-axew-textDim">
              {debugData.total_pipeline_ms.toFixed(0)}ms
            </span>
          )}
        </div>
        <button type="button" onClick={() => setDebugPanelOpen(false)} className="text-axew-textDim hover:text-axew-text">
          <X size={14} />
        </button>
      </div>

      {!debugData && !debugRetrieval ? (
        <div className="p-3">
          <p className="text-xs text-axew-textMuted">Run an AI extract prompt to inspect retrieval.</p>
        </div>
      ) : (
        <div className="p-3 space-y-3">
          {/* Section tabs */}
          <div className="flex gap-1 flex-wrap">
            {(['intent', 'events', 'candidates', 'action', 'reranker', 'timerange', 'ffmpeg', 'confidence'] as const).map((section) => (
              <button
                key={section}
                type="button"
                onClick={() => setActiveSection(section)}
                className={cn(
                  'rounded px-2 py-0.5 text-2xs font-medium',
                  activeSection === section
                    ? 'bg-axew-ai/30 text-axew-ai border border-axew-ai/50'
                    : 'bg-axew-panel text-axew-textMuted hover:text-axew-text',
                )}
              >
                {section === 'intent' && 'Intent Graph'}
                {section === 'events' && 'Semantic Events'}
                {section === 'candidates' && 'Candidates'}
                {section === 'action' && 'Action Plan'}
                {section === 'reranker' && 'Reranker'}
                {section === 'timerange' && 'Time Range'}
                {section === 'ffmpeg' && 'FFmpeg'}
                {section === 'confidence' && 'Confidence'}
              </button>
            ))}
          </div>

          {/* Section A: Intent Graph */}
          {activeSection === 'intent' && debugData?.intent_graph && (
            <IntentGraphSection intent={debugData.intent_graph} />
          )}

          {activeSection === 'events' && (
            <SemanticEventsSection events={debugData?.semantic_events ?? []} />
          )}

          {/* Section B: Candidate Ranking */}
          {activeSection === 'candidates' && (
            <CandidateRankingSection
              candidates={debugData?.top_k_candidates ?? candidates.map(c => ({
                chunk_id: c.chunkId,
                text: c.text,
                start_time: c.startSec,
                end_time: c.endSec,
                bm25_score: c.scoreBm25,
                embedding_score: c.scoreSemantic,
                entity_match_score: 0,
                action_score: 0,
                monetary_score: 0,
                contextual_score: 0,
                event_completeness_score: 0,
                prefix_penalty: 0,
                rerank_score: c.scoreReranked,
                final_score: c.confidence,
                explanation: '',
              }))}
              threshold={debugData?.confidence_gated ? 0.45 : undefined}
            />
          )}

          {activeSection === 'action' && (
            <ActionPlanSection
              actionPlan={debugData?.action_plan}
              eventScores={debugData?.event_scores ?? []}
              rejectedActions={debugData?.rejected_actions ?? []}
              failureReason={debugData?.failure_reason ?? null}
              plannerRejectionReason={typeof debugData?.planner_rejection_reason === 'string' ? debugData.planner_rejection_reason : null}
              fallbackActivated={Boolean(debugData?.fallback_activated)}
              executionMode={typeof debugData?.execution_mode === 'string' ? debugData.execution_mode : null}
            />
          )}

          {/* Section C: Reranker Responses */}
          {activeSection === 'reranker' && (
            <RerankerSection responses={debugData?.reranker_responses ?? []} />
          )}

          {/* Section D: Time Range */}
          {activeSection === 'timerange' && (
            <TimeRangeSection
              timeRange={debugData?.time_range}
              duration={duration}
              finalWindow={finalWindow}
              timestampPropagation={debugData?.timestamp_propagation as Record<string, unknown> | undefined}
            />
          )}

          {/* Section E: FFmpeg Diagnostics */}
          {activeSection === 'ffmpeg' && (
            <FFmpegSection extraction={lastExtractionResult} />
          )}

          {/* Section F: Low Confidence Alert */}
          {activeSection === 'confidence' && (
            <ConfidenceSection
              gated={debugData?.confidence_gated ?? false}
              chosenChunk={debugData?.chosen_chunk}
              threshold={0.45}
              selectionReason={
                typeof debugData?.selection_reason === 'string'
                  ? debugData.selection_reason
                  : typeof debugData?.why_selected === 'string'
                    ? debugData.why_selected
                    : undefined
              }
              rankBefore={debugData?.rank_before_calibration}
              rankAfter={debugData?.rank_after_calibration}
              fallbackActivated={Boolean(debugData?.fallback_activated)}
            />
          )}

          {/* Actions row */}
          <div className="flex flex-wrap gap-1 pt-2 border-t border-axew-border">
            <ActionButton icon={HelpCircle} label="Why this?" onClick={handleExplain} disabled={explaining} />
            <ActionButton icon={RefreshCw} label="Re-retrieve" onClick={handleReretrieve} />
            <button
              type="button"
              className="rounded border border-emerald-500/40 px-2 py-1 text-2xs text-emerald-300"
              onClick={() => handleFeedback('perfect')}
            >
              <ThumbsUp size={12} className="inline" />
            </button>
            <button
              type="button"
              className="rounded border border-red-500/40 px-2 py-1 text-2xs text-red-300"
              onClick={() => handleFeedback('wrong')}
            >
              <ThumbsDown size={12} className="inline" />
            </button>
          </div>

          {explanation && (
            <p className="rounded bg-axew-panel p-2 text-2xs text-axew-textMuted">{explanation}</p>
          )}
        </div>
      )}
    </div>
  )
}

function IntentGraphSection({ intent }: { intent: Record<string, unknown> }) {
  return (
    <div className="space-y-2">
      <table className="w-full text-2xs">
        <tbody>
          <tr className="border-b border-axew-border/50">
            <td className="py-1 pr-3 text-axew-textDim font-medium">Action</td>
            <td className="py-1 text-axew-text">{String(intent.action_type ?? '—')}</td>
            <td className="py-1 pr-3 text-axew-textDim font-medium pl-4">Subject</td>
            <td className="py-1 text-axew-text">{String(intent.subject ?? '—')}</td>
          </tr>
          <tr className="border-b border-axew-border/50">
            <td className="py-1 pr-3 text-axew-textDim font-medium">Verb</td>
            <td className="py-1 text-axew-text">{String(intent.verb ?? '—')}</td>
            <td className="py-1 pr-3 text-axew-textDim font-medium pl-4">Object</td>
            <td className="py-1 text-axew-text">{String(intent.object ?? '—')}</td>
          </tr>
          <tr className="border-b border-axew-border/50">
            <td className="py-1 pr-3 text-axew-textDim font-medium">Recipient</td>
            <td className="py-1 text-axew-text">{String(intent.recipient ?? '—')}</td>
            <td className="py-1 pr-3 text-axew-textDim font-medium pl-4">Monetary</td>
            <td className="py-1 text-axew-text">{String(intent.monetary_amount ?? '—')}</td>
          </tr>
        </tbody>
      </table>

      <div className="flex flex-wrap gap-1">
        {(intent.named_entities as string[] ?? []).map((e) => (
          <span key={e} className="rounded bg-blue-500/20 border border-blue-500/40 px-1.5 py-0.5 text-2xs text-blue-300">
            {e}
          </span>
        ))}
        {(intent.keywords as string[] ?? []).map((k) => (
          <span key={k} className="rounded bg-purple-500/20 border border-purple-500/40 px-1.5 py-0.5 text-2xs text-purple-300">
            {k}
          </span>
        ))}
      </div>

      {typeof intent.event_description === 'string' && intent.event_description.length > 0 && (
        <div className="rounded bg-axew-panel p-2 text-xs text-axew-text border-l-2 border-axew-ai">
          {String(intent.event_description)}
        </div>
      )}
    </div>
  )
}

function SemanticEventsSection({ events }: { events: Record<string, unknown>[] }) {
  if (!events.length) {
    return <p className="text-2xs text-axew-textMuted">No grounded semantic events were captured for this request.</p>
  }

  return (
    <div className="space-y-2 max-h-52 overflow-y-auto">
      {events.map((event, index) => (
        <div key={String(event.id ?? index)} className="rounded border border-axew-border p-2 text-2xs space-y-1">
          <div className="flex items-center justify-between">
            <span className="font-mono text-axew-textDim">
              {Number(event.start_time ?? 0).toFixed(1)}sâ€“{Number(event.end_time ?? 0).toFixed(1)}s
            </span>
            <span className="text-axew-ai">{Math.round(Number(event.confidence ?? 0) * 100)}%</span>
          </div>
          <div className="flex flex-wrap gap-1">
            <SemanticChip label="actor" value={event.actor} />
            <SemanticChip label="action" value={event.action} />
            <SemanticChip label="object" value={event.object} />
            <SemanticChip label="recipient" value={event.recipient} />
            <SemanticChip label="money" value={event.monetary_amount} />
          </div>
          <p className="text-axew-textMuted">{String(event.transcript_text ?? '').slice(0, 160)}</p>
        </div>
      ))}
    </div>
  )
}

function SemanticChip({ label, value }: { label: string; value: unknown }) {
  if (!value) return null
  return (
    <span className="rounded border border-axew-ai/30 bg-axew-ai/10 px-1.5 py-0.5 text-2xs text-axew-text">
      <span className="text-axew-textDim">{label}:</span> {String(value)}
    </span>
  )
}

interface CandidateData {
  chunk_id: string
  text: string
  start_time: number
  end_time: number
  bm25_score: number
  embedding_score: number
  entity_match_score: number
  action_score?: number
  monetary_score?: number
  contextual_score?: number
  event_completeness_score?: number
  prefix_penalty?: number
  rerank_score: number
  final_score: number
  explanation: string
}

function CandidateRankingSection({ candidates, threshold }: { candidates: CandidateData[]; threshold?: number }) {
  return (
    <div className="max-h-52 overflow-y-auto space-y-1">
      <div className="grid grid-cols-[2rem_5rem_3rem_3rem_3rem_3rem_3rem_3rem_3rem_1fr] gap-1 text-2xs font-medium text-axew-textDim border-b border-axew-border pb-1 sticky top-0 bg-axew-surface">
        <span>#</span>
        <span>Time</span>
        <span>Embed</span>
        <span>Entity</span>
        <span>Action</span>
        <span>Money</span>
        <span>Ctx</span>
        <span>Full</span>
        <span>Prefix</span>
        <span>Final</span>
        <span>Text</span>
      </div>
      {candidates.map((c, i) => {
        const isChosen = i === 0
        const isClose = i > 0 && i < 3 && c.final_score > (candidates[0]?.final_score ?? 0) - 0.1
        const isBelowThreshold = threshold !== undefined && c.final_score < threshold
        return (
          <div
            key={c.chunk_id}
            className={cn(
              'grid grid-cols-[2rem_5rem_3rem_3rem_3rem_3rem_3rem_3rem_3rem_1fr] gap-1 text-2xs rounded px-1 py-0.5',
              isChosen && 'bg-emerald-500/10 border border-emerald-500/30',
              isClose && !isChosen && 'bg-amber-500/10 border border-amber-500/30',
              isBelowThreshold && !isChosen && !isClose && 'bg-red-500/10 border border-red-500/30 opacity-60',
              !isChosen && !isClose && !isBelowThreshold && 'border border-transparent',
            )}
          >
            <span className="text-axew-textDim">{i + 1}</span>
            <span className="font-mono text-axew-text">{c.start_time.toFixed(1)}–{c.end_time.toFixed(1)}s</span>
            <span className="font-mono">{c.embedding_score.toFixed(2)}</span>
            <span className="font-mono">{c.entity_match_score.toFixed(2)}</span>
            <span className="font-mono">{Number(c.action_score ?? 0).toFixed(2)}</span>
            <span className="font-mono">{Number(c.monetary_score ?? 0).toFixed(2)}</span>
            <span className="font-mono">{Number(c.contextual_score ?? 0).toFixed(2)}</span>
            <span className="font-mono">{Number(c.event_completeness_score ?? 0).toFixed(2)}</span>
            <span className="font-mono text-red-300">-{Number(c.prefix_penalty ?? 0).toFixed(2)}</span>
            <span className="font-mono font-medium">{c.final_score.toFixed(3)}</span>
            <span className="truncate text-axew-textMuted" title={c.text}>{c.text.slice(0, 80)}</span>
          </div>
        )
      })}
    </div>
  )
}

function ActionPlanSection({
  actionPlan,
  eventScores,
  rejectedActions,
  failureReason,
  plannerRejectionReason,
  fallbackActivated,
  executionMode,
}: {
  actionPlan?: Record<string, unknown>
  eventScores: Record<string, unknown>[]
  rejectedActions: Record<string, unknown>[]
  failureReason?: string | null
  plannerRejectionReason?: string | null
  fallbackActivated?: boolean
  executionMode?: string | null
}) {
  const planAction = actionPlan?.action as Record<string, unknown> | undefined

  return (
    <div className="space-y-3">
      {planAction ? (
        <div className="rounded border border-emerald-500/40 bg-emerald-500/10 p-3 text-2xs">
          <div className="flex items-center justify-between">
            <span className="font-medium text-emerald-300">{String(planAction.action_type ?? 'planned_action')}</span>
            <span className="text-emerald-200">{Math.round(Number(planAction.confidence ?? 0) * 100)}%</span>
          </div>
          <p className="mt-1 text-axew-textMuted">
            {Number(planAction.start_time ?? 0).toFixed(2)}s â€“ {Number(planAction.end_time ?? 0).toFixed(2)}s
          </p>
          {typeof planAction.reasoning === 'string' && planAction.reasoning.length > 0 && (
            <p className="mt-1 text-axew-text">{String(planAction.reasoning)}</p>
          )}
        </div>
      ) : (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-2xs text-red-200">
          {plannerRejectionReason ?? failureReason ?? 'Planner did not produce an executable action.'}
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 text-2xs">
        <div className="rounded border border-axew-border p-2">
          <p className="text-axew-textDim">Execution mode</p>
          <p className="font-mono text-axew-text">{executionMode ?? 'unknown'}</p>
        </div>
        <div className="rounded border border-axew-border p-2">
          <p className="text-axew-textDim">Fallback activated</p>
          <p className={fallbackActivated ? 'text-amber-300' : 'text-emerald-300'}>
            {fallbackActivated ? 'yes' : 'no'}
          </p>
        </div>
        <div className="rounded border border-axew-border p-2">
          <p className="text-axew-textDim">Planner rejection</p>
          <p className="text-axew-text truncate" title={plannerRejectionReason ?? undefined}>
            {plannerRejectionReason ?? 'none'}
          </p>
        </div>
      </div>

      {!!eventScores.length && (
        <div className="space-y-1">
          <p className="text-2xs font-medium text-axew-textDim">Event Alignment Scores</p>
          {eventScores.map((score, index) => (
            <div key={String(score.event_id ?? index)} className="rounded border border-axew-border p-2 text-2xs">
              <div className="flex items-center justify-between">
                <span className="font-mono text-axew-textDim">{String(score.source_chunk_id ?? score.event_id ?? `event_${index}`)}</span>
                <span className="font-mono text-axew-text">{Number(score.final_score ?? 0).toFixed(3)}</span>
              </div>
              <div className="mt-1 grid grid-cols-4 gap-2 text-axew-textMuted">
                <span>actor {Number(score.actor_score ?? 0).toFixed(2)}</span>
                <span>action {Number(score.action_score ?? 0).toFixed(2)}</span>
                <span>recipient {Number(score.recipient_score ?? 0).toFixed(2)}</span>
                <span>money {Number(score.monetary_score ?? 0).toFixed(2)}</span>
              </div>
              {!!(score.reasoning as unknown[] | undefined)?.length && (
                <p className="mt-1 text-axew-textMuted">{(score.reasoning as string[]).join(' | ')}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {!!rejectedActions.length && (
        <div className="space-y-1">
          <p className="text-2xs font-medium text-axew-textDim">Rejected Actions</p>
          {rejectedActions.map((item, index) => (
            <div key={String(item.event_id ?? index)} className="rounded border border-axew-border p-2 text-2xs opacity-80">
              <div className="flex items-center justify-between">
                <span className="font-mono text-axew-textDim">
                  {Number(item.start_time ?? 0).toFixed(1)}sâ€“{Number(item.end_time ?? 0).toFixed(1)}s
                </span>
                <span className="font-mono text-red-300">{Number(item.final_score ?? 0).toFixed(3)}</span>
              </div>
              <p className="mt-1 text-axew-textMuted">{String(item.transcript_text ?? '').slice(0, 140)}</p>
              {!!(item.reasoning as unknown[] | undefined)?.length && (
                <p className="mt-1 text-red-200">{(item.reasoning as string[]).join(' | ')}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function RerankerSection({ responses }: { responses: Record<string, unknown>[] }) {
  if (!responses.length) {
    return <p className="text-2xs text-axew-textMuted">No reranker data available.</p>
  }
  return (
    <div className="space-y-2 max-h-48 overflow-y-auto">
      {responses.map((r, i) => (
        <div key={i} className="rounded border border-axew-border p-2 text-2xs space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-axew-textDim">
              {Number(r.start_time ?? 0).toFixed(1)}–{Number(r.end_time ?? 0).toFixed(1)}s
            </span>
            {r.contains_event ? (
              <span className="flex items-center gap-0.5 text-emerald-300">
                <Check size={10} /> contains_event
              </span>
            ) : (
              <span className="flex items-center gap-0.5 text-red-300">
                <XCircle size={10} /> no_event
              </span>
            )}
            <span className="text-axew-textMuted">conf: {Number(r.confidence ?? 0).toFixed(2)}</span>
          </div>
          {typeof r.reasoning === 'string' && r.reasoning.length > 0 && (
            <p className="text-axew-textMuted italic">{String(r.reasoning)}</p>
          )}
          {typeof r.error === 'string' && r.error.length > 0 && (
            <p className="text-red-300">Error: {String(r.error)}</p>
          )}
        </div>
      ))}
    </div>
  )
}

function TimeRangeSection({
  timeRange,
  duration,
  finalWindow,
  timestampPropagation,
}: {
  timeRange?: Record<string, unknown>
  duration: number
  finalWindow?: { startSec: number; endSec: number; confidence: number }
  timestampPropagation?: Record<string, unknown>
}) {
  const start = Number(timeRange?.start ?? finalWindow?.startSec ?? 0)
  const end = Number(timeRange?.end ?? finalWindow?.endSec ?? 0)
  const conf = Number(timeRange?.confidence ?? finalWindow?.confidence ?? 0)
  const method = String(timeRange?.method ?? 'unknown')

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-3 text-2xs">
        <div>
          <span className="text-axew-textDim">Start</span>
          <p className="font-mono text-axew-text">{start.toFixed(3)}s</p>
        </div>
        <div>
          <span className="text-axew-textDim">End</span>
          <p className="font-mono text-axew-text">{end.toFixed(3)}s</p>
        </div>
        <div>
          <span className="text-axew-textDim">Duration</span>
          <p className="font-mono text-axew-text">{(end - start).toFixed(3)}s</p>
        </div>
        <div>
          <span className="text-axew-textDim">Method</span>
          <p className="font-mono text-axew-text">{method}</p>
        </div>
      </div>

      {/* Mini-timeline visualization */}
      <div className="relative h-6 rounded bg-axew-panel overflow-hidden">
        <div
          className="absolute top-0 bottom-0 bg-axew-ai/60 rounded"
          style={{
            left: `${Math.max(0, (start / duration) * 100)}%`,
            width: `${Math.max(1, ((end - start) / duration) * 100)}%`,
          }}
        />
        <div className="absolute inset-0 flex items-center justify-center text-2xs text-white/70">
          {start.toFixed(1)}s – {end.toFixed(1)}s ({(conf * 100).toFixed(0)}%)
        </div>
      </div>
      {timestampPropagation && (
        <div className="rounded border border-axew-border p-2 text-2xs space-y-1">
          <p className="text-axew-textDim">Timestamp propagation</p>
          <p className="font-mono text-axew-text">
            candidate: {Number(timestampPropagation.candidate_start_sec ?? 0).toFixed(3)}s - {Number(timestampPropagation.candidate_end_sec ?? 0).toFixed(3)}s
          </p>
          <p className="font-mono text-axew-text">
            action: {Number(timestampPropagation.action_start_sec ?? start).toFixed(3)}s - {Number(timestampPropagation.action_end_sec ?? end).toFixed(3)}s
          </p>
          <p className={timestampPropagation.changed_during_pipeline ? 'text-amber-300' : 'text-emerald-300'}>
            changed during pipeline: {String(Boolean(timestampPropagation.changed_during_pipeline))}
          </p>
        </div>
      )}
    </div>
  )
}

interface ExtractionDiagnostics {
  ffmpegCommand?: string
  ffmpegStderr?: string
  validation?: {
    has_video_stream: boolean
    has_audio_stream: boolean
    video_codec: string
    audio_codec: string
    duration_seconds: number
    is_playable: boolean
    warnings: string[]
  }
}

function FFmpegSection({ extraction }: { extraction: ExtractionDiagnostics | null }) {
  const [stderrExpanded, setStderrExpanded] = useState(false)

  if (!extraction) {
    return <p className="text-2xs text-axew-textMuted">No extraction diagnostics available. Run an extraction to see FFmpeg output.</p>
  }

  return (
    <div className="space-y-3">
      {extraction.ffmpegCommand && (
        <div>
          <p className="text-2xs text-axew-textDim mb-1">Command (click to copy)</p>
          <pre
            className="rounded bg-axew-panel p-2 text-2xs font-mono text-axew-text overflow-x-auto cursor-pointer hover:bg-axew-panel/80 whitespace-pre-wrap break-all"
            onClick={() => navigator.clipboard.writeText(extraction.ffmpegCommand ?? '')}
          >
            {extraction.ffmpegCommand}
          </pre>
        </div>
      )}

      {extraction.ffmpegStderr && (
        <div>
          <button
            type="button"
            className="text-2xs text-axew-textDim hover:text-axew-text"
            onClick={() => setStderrExpanded(!stderrExpanded)}
          >
            FFmpeg stderr {stderrExpanded ? '▼' : '▶'}
          </button>
          {stderrExpanded && (
            <pre className="mt-1 rounded bg-axew-panel p-2 text-2xs font-mono text-axew-textMuted max-h-40 overflow-y-auto whitespace-pre-wrap">
              {extraction.ffmpegStderr}
            </pre>
          )}
        </div>
      )}

      {extraction.validation && (
        <div className="flex flex-wrap gap-2 text-2xs">
          <ValidationBadge
            label="Video"
            ok={extraction.validation.has_video_stream}
            detail={extraction.validation.video_codec}
          />
          <ValidationBadge
            label="Audio"
            ok={extraction.validation.has_audio_stream}
            detail={extraction.validation.audio_codec}
          />
          <ValidationBadge
            label="Playable"
            ok={extraction.validation.is_playable}
          />
          <span className="text-axew-textMuted">
            dur: {extraction.validation.duration_seconds.toFixed(2)}s
          </span>
          {extraction.validation.warnings.map((w, i) => (
            <span key={i} className="text-amber-300 flex items-center gap-0.5">
              <AlertTriangle size={10} /> {w}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function ValidationBadge({ label, ok, detail }: { label: string; ok: boolean; detail?: string }) {
  return (
    <span className={cn(
      'rounded px-1.5 py-0.5 border',
      ok ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300' : 'bg-red-500/20 border-red-500/40 text-red-300',
    )}>
      {ok ? <Check size={10} className="inline mr-0.5" /> : <XCircle size={10} className="inline mr-0.5" />}
      {label}{detail ? `: ${detail}` : ''}
    </span>
  )
}

function ConfidenceSection({
  gated,
  chosenChunk,
  threshold,
  selectionReason,
  rankBefore,
  rankAfter,
  fallbackActivated,
}: {
  gated: boolean
  chosenChunk?: Record<string, unknown>
  threshold: number
  selectionReason?: string
  rankBefore?: Array<Record<string, unknown>>
  rankAfter?: Array<Record<string, unknown>>
  fallbackActivated?: boolean
}) {
  if (gated) {
    return (
      <div className="space-y-2">
        <div className="rounded border border-red-500/60 bg-red-500/10 p-3">
          <div className="flex items-center gap-2 text-red-300">
            <AlertTriangle size={16} />
            <span className="text-xs font-medium">No confident match found</span>
          </div>
          <p className="mt-1 text-2xs text-red-200">
            Score: {Number(chosenChunk?.final_score ?? 0).toFixed(3)} | Threshold: {threshold}
          </p>
          <p className="mt-1 text-2xs text-axew-textMuted">
            Extraction was blocked. The best candidate scored below the confidence threshold.
            This prevents wrong clips from being produced.
          </p>
        </div>
        {chosenChunk && (
          <div className="rounded bg-axew-panel p-2 opacity-60">
            <p className="text-2xs text-axew-textDim">Best candidate (rejected):</p>
            <p className="text-2xs text-axew-textMuted mt-1">
              {Number(chosenChunk.start_time ?? 0).toFixed(1)}s–{Number(chosenChunk.end_time ?? 0).toFixed(1)}s:
              {' '}{String(chosenChunk.text ?? '').slice(0, 120)}
            </p>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="rounded border border-emerald-500/40 bg-emerald-500/10 p-3">
        <div className="flex items-center gap-2 text-emerald-300">
          <Check size={16} />
          <span className="text-xs font-medium">Confidence gate passed</span>
        </div>
        <p className="mt-1 text-2xs text-axew-textMuted">
          Score: {Number(chosenChunk?.final_score ?? 0).toFixed(3)}
          {chosenChunk?.raw_score != null && (
            <> (raw: {Number(chosenChunk.raw_score).toFixed(3)})</>
          )}
          {' '}| Threshold: {threshold}
        </p>
        <p className="mt-1 text-2xs text-axew-textMuted">
          Fallback: {fallbackActivated ? 'yes (legacy monetary)' : 'no'}
          {chosenChunk?.opener_cap_applied ? ' | opener cap applied' : ''}
        </p>
      </div>
      {selectionReason && (
        <div className="rounded border border-axew-border p-2 text-2xs">
          <p className="text-axew-textDim font-medium">Why this candidate won</p>
          <p className="mt-1 font-mono text-axew-text break-words">{selectionReason}</p>
        </div>
      )}
      {!!rankAfter?.length && (
        <div className="rounded border border-axew-border p-2 text-2xs space-y-1">
          <p className="text-axew-textDim font-medium">Rank after calibration (top 5)</p>
          {rankAfter.slice(0, 5).map((row, i) => (
            <p key={i} className="font-mono text-axew-textMuted">
              #{i + 1} {Number(row.start_sec ?? 0).toFixed(1)}s conf={Number(row.confidence ?? 0).toFixed(3)}{' '}
              {String(row.origin ?? '')}
            </p>
          ))}
        </div>
      )}
      {!!rankBefore?.length && rankBefore !== rankAfter && (
        <div className="rounded border border-axew-border p-2 text-2xs opacity-80">
          <p className="text-axew-textDim font-medium">Rank before calibration</p>
          {rankBefore.slice(0, 3).map((row, i) => (
            <p key={i} className="font-mono text-axew-textMuted">
              #{i + 1} {Number(row.start_sec ?? 0).toFixed(1)}s conf={Number(row.confidence ?? 0).toFixed(3)}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  disabled,
}: {
  icon: LucideIcon
  label: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      className="flex items-center gap-1 rounded border border-axew-border px-2 py-1 text-2xs hover:border-axew-ai/50 disabled:opacity-40"
      onClick={onClick}
    >
      <Icon size={12} />
      {label}
    </button>
  )
}
