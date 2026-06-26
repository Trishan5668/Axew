import type { AIEditAction } from '@shared/ai'
import type { Timeline } from '@shared/timeline'

const AI_SERVICE_URL = 'http://localhost:7002'
const OLLAMA_URL = 'http://localhost:11434'

interface StreamCallbacks {
  onChunk: (chunk: string) => void
  onDone: () => void
  onError: (error: string) => void
}

function buildTimelineContext(timeline: Timeline): string {
  const trackSummary = timeline.tracks
    .map((t) => `${t.name} (${t.type}): ${t.clips.length} clips`)
    .join('\n')
  return `Duration: ${timeline.duration}s, FPS: ${timeline.frameRate}\nTracks:\n${trackSummary}`
}

export async function sendAIMessage(
  message: string,
  timeline: Timeline | null,
  callbacks: StreamCallbacks,
): Promise<void> {
  const context = timeline ? buildTimelineContext(timeline) : 'No timeline available'
  const systemPrompt = `You are AXEW, an AI assistant for a professional video editor.
You help editors with timeline operations, story suggestions, pacing, and creative decisions.
Be concise, practical, and action-oriented.

Current Timeline Context:
${context}`

  try {
    const response = await fetch(`${AI_SERVICE_URL}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, system: systemPrompt }),
      signal: AbortSignal.timeout(120000),
    })

    if (response.ok && response.body) {
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value)
        for (const line of chunk.split('\n').filter(Boolean)) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (data.content) callbacks.onChunk(data.content)
              if (data.error) callbacks.onError(data.error)
            } catch {
              /* skip */
            }
          }
        }
      }
      callbacks.onDone()
      return
    }
  } catch {
    /* fall through */
  }

  try {
    const response = await fetch(`${OLLAMA_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'llama3',
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: message },
        ],
        stream: true,
      }),
    })

    if (!response.ok || !response.body) {
      throw new Error(`Ollama error: ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      for (const line of decoder.decode(value).split('\n').filter(Boolean)) {
        try {
          const data = JSON.parse(line)
          if (data.message?.content) callbacks.onChunk(data.message.content)
        } catch {
          /* skip */
        }
      }
    }
    callbacks.onDone()
  } catch {
    callbacks.onError(
      'Could not connect to AI service. Ensure Ollama is running (ollama serve) or start the Python AI service.',
    )
  }
}

export async function checkOllamaStatus(): Promise<boolean> {
  try {
    const resp = await fetch(`${OLLAMA_URL}/api/tags`, { signal: AbortSignal.timeout(5000) })
    return resp.ok
  } catch {
    return false
  }
}

export async function checkAIServiceStatus(): Promise<boolean> {
  try {
    const resp = await fetch(`${AI_SERVICE_URL}/health`, { signal: AbortSignal.timeout(5000) })
    return resp.ok
  } catch {
    return false
  }
}

export interface AIReadinessResult {
  live: boolean
  ready: boolean
  phase: string | null
}

export async function checkAIReadiness(): Promise<AIReadinessResult> {
  const result: AIReadinessResult = { live: false, ready: false, phase: null }

  try {
    const liveResp = await fetch(`${AI_SERVICE_URL}/health/live`, {
      signal: AbortSignal.timeout(5000),
    })
    if (liveResp.ok) {
      result.live = true
      const data = (await liveResp.json()) as { phase?: string }
      result.phase = data.phase ?? null
    }
  } catch {
    return result
  }

  try {
    const readyResp = await fetch(`${AI_SERVICE_URL}/health/ready`, {
      signal: AbortSignal.timeout(5000),
    })
    if (readyResp.ok) {
      result.ready = true
      const data = (await readyResp.json()) as { phase?: string }
      result.phase = data.phase ?? null
    } else if (readyResp.status === 503) {
      const data = (await readyResp.json()) as { phase?: string }
      result.phase = data.phase ?? result.phase
    }
  } catch {
    // live but not ready yet
  }

  return result
}

export async function detectSilence(
  mediaPath: string,
  thresholdDb = -40,
): Promise<{ start: number; end: number; duration: number; averageDb: number }[]> {
  const response = await fetch(`${AI_SERVICE_URL}/api/analysis/silence`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ media_path: mediaPath, threshold_db: thresholdDb }),
  })
  if (!response.ok) throw new Error('Silence detection failed')
  const data = await response.json()
  return data.silences ?? []
}

export interface TranscriptionDiagnostics {
  ready: boolean
  ffmpeg: boolean
  whisper: boolean
  torch: boolean
  errors: string[]
  hints: string[]
}

export async function fetchTranscriptionDiagnostics(): Promise<TranscriptionDiagnostics> {
  const response = await fetch(`${AI_SERVICE_URL}/api/analysis/diagnostics`, {
    signal: AbortSignal.timeout(10000),
  })
  if (!response.ok) {
    return {
      ready: false,
      ffmpeg: false,
      whisper: false,
      torch: false,
      errors: [`Diagnostics unavailable (${response.status})`],
      hints: ['Start the AI service: cd apps/ai-service && python -m uvicorn main:app --port 7002'],
    }
  }
  const data = await response.json()
  return {
    ready: Boolean(data.ready),
    ffmpeg: Boolean(data.ffmpeg),
    whisper: Boolean(data.whisper),
    torch: Boolean(data.torch),
    errors: data.errors ?? [],
    hints: data.hints ?? [],
  }
}

export type OpusClipHealthStatus = 'online' | 'offline'

export interface OpusClipHealthResult {
  status: OpusClipHealthStatus
  service: string
  apiKeyPresent: boolean
  reason: string | null
}

/**
 * Query the OpusClip health endpoint.
 *
 * This NEVER throws — any network/timeout/parse failure resolves to an
 * `offline` result so the polling UI can render safely and never crash the
 * application. The check is fast (<1s) and never exposes the API key.
 */
export async function fetchOpusClipHealth(): Promise<OpusClipHealthResult> {
  try {
    const response = await fetch(`${AI_SERVICE_URL}/opusclip/health`, {
      signal: AbortSignal.timeout(2500),
    })
    const data = (await response.json().catch(() => ({}))) as Partial<{
      status: string
      service: string
      api_key_present: boolean
      reason: string
    }>
    const online = response.ok && data.status === 'online'
    return {
      status: online ? 'online' : 'offline',
      service: data.service ?? 'opusclip',
      apiKeyPresent: Boolean(data.api_key_present),
      reason: online ? null : data.reason ?? `http_${response.status}`,
    }
  } catch (err) {
    const reason =
      err instanceof DOMException && err.name === 'TimeoutError'
        ? 'timeout'
        : 'backend_unreachable'
    return {
      status: 'offline',
      service: 'opusclip',
      apiKeyPresent: false,
      reason,
    }
  }
}

async function parseApiError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    const detail = body.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') {
      const parts = [
        detail.code && `[${detail.code}]`,
        detail.message ?? detail.msg,
        detail.hint,
      ].filter(Boolean)
      if (parts.length) return parts.join(' ')
    }
    return body.message ?? fallback
  } catch {
    return `${fallback} (HTTP ${response.status})`
  }
}

export async function transcribeMedia(mediaPath: string, model = 'base') {
  let normalizedPath = mediaPath.trim()
  if (normalizedPath.toLowerCase().startsWith('file://')) {
    normalizedPath = normalizedPath.slice(7)
    if (/^[a-zA-Z]\//.test(normalizedPath)) {
      normalizedPath = `${normalizedPath[0]}:${normalizedPath.slice(1)}`
    }
  }
  const response = await fetch(`${AI_SERVICE_URL}/api/analysis/transcribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-axew-timeout': '900' },
    body: JSON.stringify({ media_path: normalizedPath, model }),
    signal: AbortSignal.timeout(600000),
  })
  if (!response.ok) {
    throw new Error(await parseApiError(response, 'Transcription failed'))
  }
  return response.json()
}

export async function detectScenes(mediaPath: string, threshold = 0.4) {
  const response = await fetch(`${AI_SERVICE_URL}/api/analysis/scenes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ media_path: mediaPath, threshold }),
  })
  if (!response.ok) throw new Error('Scene detection failed')
  return response.json()
}

export async function embedText(text: string): Promise<number[]> {
  const response = await fetch(`${AI_SERVICE_URL}/api/analysis/embed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!response.ok) throw new Error('Embedding failed')
  const data = await response.json()
  return data.embedding ?? []
}

/** @deprecated Use actionExecutionEngine + /api/execution/plan instead */
export function parseAIActionsFromText(text: string): AIEditAction[] {
  const actions: AIEditAction[] = []
  const patterns: { type: AIEditAction['type']; regex: RegExp }[] = [
    { type: 'cut-silence', regex: /cut\s+silence|remove\s+silence/i },
    { type: 'detect-scenes', regex: /detect\s+scenes|find\s+scenes/i },
    { type: 'add-subtitle', regex: /transcribe|subtitle|caption/i },
    { type: 'split-clip', regex: /split\s+clip/i },
    { type: 'delete-clip', regex: /delete\s+clip|remove\s+clip/i },
  ]

  for (const { type, regex } of patterns) {
    if (regex.test(text)) {
      actions.push({
        type,
        params: {},
        description: `Suggested: ${type}`,
        confidence: 0.7,
      })
    }
  }

  return actions
}

export async function planStructuredActions(
  prompt: string,
  segments: { id: string; start: number; end: number; text: string }[],
  mediaDuration: number,
) {
  const response = await fetch(`${AI_SERVICE_URL}/api/execution/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-axew-timeout': '300' },
    body: JSON.stringify({
      prompt,
      segments,
      media_duration: mediaDuration,
      padding_seconds: 0.4,
    }),
    signal: AbortSignal.timeout(120000),
  })
  if (!response.ok) throw new Error(`Plan failed: ${response.status}`)
  return response.json()
}
