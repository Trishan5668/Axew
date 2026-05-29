import type { AIEditAction, AIHighlightRange, StructuredAction } from '@shared/ai'
import type { MediaFile } from '@shared/media'
import { structuredToEditAction } from './actionSchema'
import { applyAIAction } from './editOrchestrator'
import { ensureTranscript, planActionsFromPrompt } from './semanticRetrieval'
import { useAIStore } from '../stores/aiStore'
import { useDebugStore } from '../stores/debugStore'
import { usePlaybackStore } from '../stores/playbackStore'
import { useProjectStore } from '../stores/projectStore'
import { useUIStore } from '../stores/uiStore'

function getPrimaryVideoMedia(): MediaFile | null {
  const project = useProjectStore.getState().currentProject
  if (!project) return null
  return Object.values(project.mediaFiles).find((m) => m.type === 'video') ?? null
}

function logPhase(phase: import('@shared/ai').AIExecutionPhase, message: string, data?: Record<string, unknown>) {
  useAIStore.getState().appendExecutionLog(phase, message, data)
}

/**
 * Autonomous pipeline: prompt → semantic parse → transcript search → actions → timeline mutation → preview
 */
export async function executePromptPipeline(prompt: string): Promise<void> {
  const store = useAIStore.getState()
  store.resetExecution()
  store.setExecutionPhase('parsing')
  logPhase('parsing', `Prompt: ${prompt.slice(0, 120)}`)

  const project = useProjectStore.getState().currentProject
  if (!project) {
    store.setExecutionPhase('error')
    logPhase('error', 'No project open')
    return
  }

  const media = getPrimaryVideoMedia()
  if (!media) {
    useUIStore.getState().addNotification({
      type: 'error',
      message: 'Add video media to the project before running AI edits',
    })
    store.setExecutionPhase('error')
    logPhase('error', 'No video media')
    return
  }

  const utilityOnly = /cut\s+silence|remove\s+silence|detect\s+scene|transcribe|subtitle|caption/i.test(
    prompt,
  )

  try {
    let segments: import('@shared/ai').TranscriptSegment[] = []

    if (!utilityOnly) {
      store.setExecutionPhase('transcribing')
      logPhase('transcribing', `Ensuring transcript for ${media.name}`)
      const transcript = await ensureTranscript(media)
      segments = transcript.segments
      store.setExecutionPhase('searching')
      logPhase('searching', `Indexed ${segments.length} segments`)
    } else {
      logPhase('parsing', 'Utility intent — skipping transcript index')
    }

    store.setExecutionPhase('planning')
    const sessionId = useAIStore.getState().retrievalSessionId
    const plan = await planActionsFromPrompt(prompt, segments, media.duration, sessionId)
    store.setSemanticMatches(plan.matches)
    store.setLastRetrievalQuery(prompt)
    if (plan.sessionId) store.setRetrievalSessionId(plan.sessionId)

    if (plan.debug) {
      useDebugStore.getState().setRetrievalDebug(plan.debug as any)
      const d = plan.debug as {
        parsed_intent?: Record<string, unknown>
        parsed_query?: Record<string, unknown>
        pipeline_trace?: string[]
        candidates?: Array<{
          chunk_id: string
          text: string
          start_sec: number
          end_sec: number
          score_bm25: number
          score_semantic: number
          score_reranked: number
          confidence: number
        }>
        final_window?: { start_sec: number; end_sec: number; confidence: number }
        media_duration?: number
      }
      store.setDebugRetrieval({
        query: prompt,
        parsedIntent: d.parsed_query ?? d.parsed_intent ?? {},
        pipelineTrace: d.pipeline_trace ?? plan.trace,
        candidates: (d.candidates ?? []).map((c) => ({
          chunkId: c.chunk_id,
          text: c.text,
          startSec: c.start_sec,
          endSec: c.end_sec,
          scoreBm25: c.score_bm25,
          scoreSemantic: c.score_semantic,
          scoreReranked: c.score_reranked,
          confidence: c.confidence,
        })),
        finalWindow: {
          startSec: d.final_window?.start_sec ?? 0,
          endSec: d.final_window?.end_sec ?? 0,
          confidence: d.final_window?.confidence ?? 0,
        },
        confidenceGrade: plan.confidenceGrade,
        mediaDuration: d.media_duration ?? media.duration,
      })
    }
    for (const line of plan.trace) {
      logPhase('planning', line)
    }
    logPhase('planning', `Intent: ${plan.intent}, ${plan.actions.length} action(s)`)

    const editActions: AIEditAction[] = []
    for (const raw of plan.actions as StructuredAction[]) {
      const action = structuredToEditAction(raw)
      if (action) {
        const start = action.params.start as number | undefined
        const end = action.params.end as number | undefined
        if (typeof start === 'number' || typeof end === 'number') {
          if (typeof start !== 'number' || typeof end !== 'number' || end <= start || (end - start) <= 0.5) {
            throw new Error(`Invalid propagated timestamps for ${action.type}: start=${String(start)} end=${String(end)}`)
          }
        }
        if (!action.params.mediaId) action.params.mediaId = media.id
        editActions.push(action)
      }
    }

    const suggestedAction = editActions.find((action) => action.type === 'highlight-segment') ?? null
    store.setSuggestedAction(suggestedAction)

    if (editActions.length === 0) {
      store.setExecutionPhase('error')
      logPhase('error', 'No executable actions generated')
      useUIStore.getState().addNotification({
        type: 'warning',
        message: 'No matching transcript segment found for this prompt',
      })
      return
    }

    const highlights: AIHighlightRange[] = []
    for (const a of editActions) {
      const start = a.params.start as number | undefined
      const end = a.params.end as number | undefined
      if (typeof start === 'number' && typeof end === 'number') {
        highlights.push({
          start,
          end,
          confidence: a.confidence,
          label: (a.params.matchText as string) ?? a.description,
        })
      }
    }
    store.setHighlightRanges(highlights)

    store.setExecutionPhase('executing')
    const applied = []
    for (const action of editActions) {
      store.addPendingAction(action)
      logPhase('executing', `Applying ${action.type}`, { params: action.params })
      try {
        await applyAIAction(action)
        applied.push({ action, appliedAt: Date.now(), success: true })
        store.recordAppliedOperation({ action, appliedAt: Date.now(), success: true })
        logPhase('executing', `Applied ${action.type}`, {
          start: action.params.start,
          end: action.params.end,
          confidence: action.confidence,
        })
      } catch (err) {
        applied.push({
          action,
          appliedAt: Date.now(),
          success: false,
          error: String(err),
        })
        store.recordAppliedOperation({
          action,
          appliedAt: Date.now(),
          success: false,
          error: String(err),
        })
        logPhase('error', `${action.type} failed: ${String(err)}`)
      }
    }

    const firstHighlight = highlights[0]
    if (firstHighlight) {
      store.setExecutionPhase('preview')
      usePlaybackStore.getState().setCurrentTime(firstHighlight.start, { syncVideo: true })
      usePlaybackStore.getState().setLoopPoints(firstHighlight.start, firstHighlight.end)
      usePlaybackStore.getState().setLoop(true)
      logPhase('preview', `Preview ${firstHighlight.start.toFixed(2)}s – ${firstHighlight.end.toFixed(2)}s`)
    }

    // Fetch retrieval debug payload after execution (success or partial)
    try {
      const resp = await fetch('http://localhost:7002/api/semantic/last_debug', {
        signal: AbortSignal.timeout(3000),
      })
      if (resp.ok) {
        const debugData = await resp.json()
        if (debugData.status === 'ok' && debugData.data) {
          useDebugStore.getState().setRetrievalDebug(debugData.data)
        }
      }
    } catch {
      // non-critical debug fetch
    }

    store.setExecutionPhase('done')
    logPhase('done', `Applied ${applied.filter((o) => o.success).length} operation(s)`)
    useUIStore.getState().addNotification({
      type: 'success',
      message: `AI applied ${applied.filter((o) => o.success).length} edit(s)`,
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    store.setExecutionPhase('error')
    logPhase('error', message)
    useUIStore.getState().addNotification({
      type: 'error',
      message: message.length > 200 ? `${message.slice(0, 200)}…` : message,
    })
  }
}
