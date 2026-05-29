import type { SemanticMatch, Transcript, TranscriptSegment } from '@shared/ai'
import type { MediaFile } from '@shared/media'
import { fetchTranscriptionDiagnostics, transcribeMedia } from './aiClient'
import { getAxew } from './axewBridge'
import { useProjectStore } from '../stores/projectStore'

const AI_SERVICE_URL = 'http://localhost:7002'

// ---------------------------------------------------------------------------
// Resilient fetch with retry, timeout, and offline-awareness
// ---------------------------------------------------------------------------

let _aiOnline = true
let _lastHealthCheck = 0

export function isAIOnline(): boolean {
  return _aiOnline
}

async function checkAIHealth(): Promise<boolean> {
  const now = Date.now()
  if (now - _lastHealthCheck < 5_000) return _aiOnline
  _lastHealthCheck = now
  try {
    const resp = await fetch(`${AI_SERVICE_URL}/health`, {
      signal: AbortSignal.timeout(5_000),
    })
    _aiOnline = resp.ok
    return _aiOnline
  } catch {
    _aiOnline = false
    return false
  }
}

async function resilientFetch(
  url: string,
  init: RequestInit,
  opts: { timeoutMs?: number; retries?: number; label?: string } = {},
): Promise<Response> {
  const { timeoutMs = 60_000, retries = 1, label = url } = opts

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const resp = await fetch(url, {
        ...init,
        headers: {
          ...(init.headers ?? {}),
          'x-axew-timeout': String(Math.ceil(timeoutMs / 1000)),
        },
        signal: controller.signal,
      })
      clearTimeout(timer)
      _aiOnline = true

      if (resp.status === 503) {
        const body = await resp.json().catch(() => ({}))
        const detail = (body as { detail?: string }).detail ?? 'Service unavailable'
        if (attempt < retries) {
          console.warn(`[AI] ${label} returned 503, retrying in 2s… (${detail})`)
          await new Promise((r) => setTimeout(r, 2_000))
          continue
        }
        throw new Error(`AI service overloaded: ${detail}`)
      }
      return resp
    } catch (err) {
      clearTimeout(timer)
      if (err instanceof DOMException && err.name === 'AbortError') {
        if (attempt < retries) {
          console.warn(`[AI] ${label} timed out, retrying…`)
          continue
        }
        _aiOnline = false
        throw new Error(`AI request timed out after ${timeoutMs / 1000}s — service may be overloaded`)
      }
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, 1_000))
        continue
      }
      _aiOnline = false
      throw err
    }
  }
  throw new Error('Unreachable')
}

export async function ensureTranscript(media: MediaFile): Promise<Transcript> {
  const project = useProjectStore.getState().currentProject
  if (!project) throw new Error('No project open')

  const existing = project.transcripts?.[media.id]
  if (existing?.segments?.length) return existing

  let mediaPath = media.path
  const fileExists = await getAxew().fs.exists(mediaPath)
  if (!fileExists) {
    throw new Error(`Media file not found on disk: ${mediaPath}`)
  }

  const diagnostics = await fetchTranscriptionDiagnostics()
  if (!diagnostics.ready) {
    const hint = diagnostics.hints.join(' · ') || 'pip install -r apps/ai-service/requirements.txt'
    throw new Error(
      `Transcription not ready: ${diagnostics.errors.join(', ') || 'missing dependencies'}. ${hint}`,
    )
  }

  const result = await transcribeMedia(mediaPath)
  const transcript: Transcript = {
    mediaId: media.id,
    language: result.language ?? 'unknown',
    segments: (result.segments ?? []).map(
      (seg: { id?: string; start: number; end: number; text: string; confidence?: number }) => ({
        id: seg.id ?? `${seg.start}`,
        start: seg.start,
        end: seg.end,
        text: seg.text,
        confidence: seg.confidence ?? 0,
      }),
    ),
    fullText: result.full_text ?? '',
    generatedAt: Date.now(),
  }

  useProjectStore.getState().setTranscript(media.id, transcript)

  return transcript
}

function fallbackSubstringSearch(
  query: string,
  segments: TranscriptSegment[],
): SemanticMatch[] {
  const terms = query.toLowerCase().split(/\s+/).filter((t) => t.length > 2)
  if (!terms.length) return []

  return segments
    .map((s) => {
      const text = s.text.toLowerCase()
      const hits = terms.filter((t) => text.includes(t)).length
      const score = hits / terms.length
      return { segmentId: s.id, text: s.text, start: s.start, end: s.end, score }
    })
    .filter((m) => m.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 8)
}

export async function semanticSearchTranscript(
  query: string,
  segments: TranscriptSegment[],
): Promise<SemanticMatch[]> {
  if (!(await checkAIHealth())) {
    console.warn('[AI] Offline — falling back to substring search')
    return fallbackSubstringSearch(query, segments)
  }

  try {
    const response = await resilientFetch(
      `${AI_SERVICE_URL}/api/execution/semantic-search`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          segments: segments.map((s) => ({
            id: s.id,
            start: s.start,
            end: s.end,
            text: s.text,
          })),
          top_k: 8,
          min_score: 0.22,
        }),
      },
      { timeoutMs: 180_000, retries: 1, label: 'semantic-search' },
    )

    if (!response.ok) {
      throw new Error(`Semantic search failed: ${response.status}`)
    }

    const data = await response.json()
    return (data.matches ?? []).map(
      (m: { segment_id: string; text: string; start: number; end: number; score: number }) => ({
        segmentId: m.segment_id,
        text: m.text,
        start: m.start,
        end: m.end,
        score: m.score,
      }),
    )
  } catch (err) {
    console.warn('[AI] Semantic search failed, using substring fallback:', err)
    return fallbackSubstringSearch(query, segments)
  }
}

export interface PlanResult {
  intent: string
  actions: import('@shared/ai').StructuredAction[]
  matches: SemanticMatch[]
  trace: string[]
  confidenceGrade?: string | null
  sessionId?: string | null
  debug?: Record<string, unknown> | null
}

export async function planActionsFromPrompt(
  prompt: string,
  segments: TranscriptSegment[],
  mediaDuration: number,
  sessionId?: string | null,
): Promise<PlanResult> {
  const offline = !(await checkAIHealth())

  if (offline) {
    console.warn('[AI] Offline — producing local fallback plan')
    const matches = fallbackSubstringSearch(prompt, segments)
    return {
      intent: 'keep_segment',
      actions: [],
      matches,
      trace: ['ai_offline', 'fallback_substring_search', 'planner_error_no_silent_first_clip_fallback'],
      confidenceGrade: null,
      sessionId: null,
      debug: null,
    }
  }

  try {
    const response = await resilientFetch(
      `${AI_SERVICE_URL}/api/execution/plan`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt,
          segments: segments.map((s) => ({
            id: s.id,
            start: s.start,
            end: s.end,
            text: s.text,
          })),
          media_duration: mediaDuration,
          padding_seconds: 0.4,
          use_intelligence: true,
          session_id: sessionId ?? undefined,
        }),
      },
      { timeoutMs: 300_000, retries: 1, label: 'plan-actions' },
    )

    if (!response.ok) {
      throw new Error(`Action planning failed: ${response.status}`)
    }

    const data = await response.json()
    return {
      intent: data.intent ?? 'unknown',
      actions: data.actions ?? [],
      matches: (data.matches ?? []).map(
        (m: { segment_id: string; text: string; start: number; end: number; score: number }) => ({
          segmentId: m.segment_id,
          text: m.text,
          start: m.start,
          end: m.end,
          score: m.score,
        }),
      ),
      trace: data.trace ?? [],
      confidenceGrade: data.confidence_grade ?? null,
      sessionId: data.session_id ?? null,
      debug: data.debug ?? null,
    }
  } catch (err) {
    console.warn('[AI] Plan actions failed, producing offline fallback:', err)
    const matches = fallbackSubstringSearch(prompt, segments)
    return {
      intent: 'keep_segment',
      actions: [],
      matches,
      trace: ['ai_error', String(err), 'planner_error_no_silent_first_clip_fallback'],
      confidenceGrade: null,
      sessionId: null,
      debug: null,
    }
  }
}

export interface SemanticExtractResult {
  status: 'success' | 'low_confidence' | 'parse_error' | 'error'
  timeRange?: { start: number; end: number }
  confidence?: number
  message?: string
  bestScore?: number
  threshold?: number
  debug?: Record<string, unknown>
}

export async function semanticExtract(
  prompt: string,
  mediaId: string,
  segments: { id: string; start: number; end: number; text: string; words?: unknown[] }[],
): Promise<SemanticExtractResult> {
  const { useDebugStore } = await import('../stores/debugStore')

  try {
    const response = await resilientFetch(
      `${AI_SERVICE_URL}/api/semantic/extract`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt,
          media_id: mediaId,
          segments: segments.map((s) => ({
            id: s.id,
            start: s.start,
            end: s.end,
            text: s.text,
            words: s.words ?? [],
          })),
        }),
      },
      { timeoutMs: 300_000, retries: 1, label: 'semantic-extract' },
    )

    const data = await response.json()

    if (data.debug) {
      useDebugStore.getState().setRetrievalDebug(data.debug)
    }

    // Also fetch the full debug payload
    fetchLastDebug().catch(() => {})

    return {
      status: data.status,
      timeRange: data.time_range ? { start: data.time_range.start, end: data.time_range.end } : undefined,
      confidence: data.confidence,
      message: data.message,
      bestScore: data.best_score,
      threshold: data.threshold,
      debug: data.debug,
    }
  } catch (err) {
    console.error('[AI] Semantic extract failed:', err)
    return {
      status: 'error',
      message: String(err),
    }
  }
}

async function fetchLastDebug(): Promise<void> {
  try {
    const { useDebugStore } = await import('../stores/debugStore')
    const resp = await fetch(`${AI_SERVICE_URL}/api/semantic/last_debug`, {
      signal: AbortSignal.timeout(5_000),
    })
    if (resp.ok) {
      const data = await resp.json()
      if (data.status === 'ok' && data.data) {
        useDebugStore.getState().setRetrievalDebug(data.data)
      }
    }
  } catch {
    // non-critical
  }
}

export async function submitRetrievalFeedback(
  sessionId: string,
  feedback: string,
  query: string,
): Promise<void> {
  await fetch(`${AI_SERVICE_URL}/debug/retrieval/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, feedback, query }),
  })
}

export async function explainRetrievalSelection(query: string, segmentText: string): Promise<string> {
  try {
    const response = await fetch('http://localhost:11434/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'llama3.2:3b',
        prompt: `Explain in 2 sentences why this transcript segment was selected for the query "${query}": ${segmentText.slice(0, 400)}`,
        stream: false,
      }),
      signal: AbortSignal.timeout(30000),
    })
    if (!response.ok) {
      return 'Explanation unavailable (Ollama offline).'
    }
    const data = await response.json()
    return String(data.response ?? 'No explanation returned.')
  } catch {
    return 'Explanation unavailable — segment matched highest retrieval confidence for your query.'
  }
}
