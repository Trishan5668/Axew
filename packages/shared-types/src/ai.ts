export interface AIModel {
  id: string
  name: string
  type: AIModelType
  provider: AIProvider
  size: number
  quantization: string
  capabilities: AICapability[]
  status: AIModelStatus
  localPath: string | null
}

export type AIModelType = 'llm' | 'whisper' | 'embeddings' | 'vision' | 'audio'
export type AIProvider = 'ollama' | 'llama-cpp' | 'onnx' | 'pytorch' | 'openai-compatible'
export type AIModelStatus = 'available' | 'downloading' | 'loaded' | 'error' | 'not-installed'
export type AICapability = 'text' | 'vision' | 'audio' | 'code' | 'editing'

export interface AIMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  timestamp: number
  model?: string
  toolCalls?: AIToolCall[]
  toolResults?: AIToolResult[]
}

export interface AIToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export interface AIToolResult {
  toolCallId: string
  result: unknown
  error?: string
}

export interface AIEditAction {
  type: AIEditActionType
  params: Record<string, unknown>
  description: string
  confidence: number
  clipIds?: string[]
}

export type AIEditActionType =
  | 'cut-silence'
  | 'split-clip'
  | 'delete-clip'
  | 'trim-clip'
  | 'add-transition'
  | 'adjust-speed'
  | 'reorder-clips'
  | 'add-subtitle'
  | 'add-marker'
  | 'set-volume'
  | 'detect-scenes'
  | 'generate-highlights'
  | 'extract-clip'
  | 'keep-segment'
  | 'isolate-segment'
  | 'highlight-segment'

/** JSON action envelope returned by the execution planner */
export interface StructuredAction {
  action: string
  start?: number
  end?: number
  clipId?: string
  time?: number
  mediaId?: string
  name?: string
  confidence?: number
  matchText?: string
  reasoning?: string
  requiresConfirmation?: boolean
}

export interface SemanticMatch {
  segmentId: string
  text: string
  start: number
  end: number
  score: number
}

/**
 * Channels exposed by the Phase 16 entity-grounded retriever.
 * Each value is in [0, 1] or null when the channel is not applicable
 * to the parsed query (see python/retrieval/multimodal_fusion_scorer.py).
 */
export interface RetrievalEvidence {
  lexical?: number | null
  semantic?: number | null
  entityMatch?: number | null
  actionMatch?: number | null
  tenseMatch?: number | null
  speakerRoleMatch?: number | null
  vocativeMatch?: number | null
  monetaryMatch?: number | null
  eventGraph?: number | null
  visual?: number | null
  audio?: number | null
}

/**
 * Structured intent extracted from a natural-language editing query.
 * Mirrors python.retrieval.entity_grounded_retriever.GroundedQuery.
 */
export interface GroundedQuery {
  rawQuery: string
  actionType: string | null
  actionVerbs: string[]
  subjectRole: string | null
  objectEntity: string | null
  monetaryAmount: number | null
  monetaryText: string | null
  monetaryCurrency: string | null
  targetTense: 'present' | 'past' | 'future' | 'unknown' | null
  namedEntities: string[]
  keywords: string[]
  requiresStrictGrounding: boolean
}

export interface FramePreciseWindow {
  startSec: number
  endSec: number
  anchorSec: number
  anchorText: string
  anchorKind: 'action_verb' | 'vocative' | 'monetary' | 'moment_mid'
  momentId: string | null
  extendedMoments: string[]
  confidence: number
  method: string
}

export interface FusionScoreBreakdown {
  score: number
  composite: number
  passesGate: boolean
  strongSignalCount: number
  contributingChannels: string[]
  missingRequired: string[]
  weightsUsed: Record<string, number>
  explanation: string
}

export interface GroundedRetrievalCandidate {
  momentId: string
  segmentId: string
  speaker: string | null
  speakerRole: string | null
  tense: string
  startSec: number
  endSec: number
  text: string
  evidence: RetrievalEvidence
  fusion: FusionScoreBreakdown
  window: FramePreciseWindow | null
}

export interface GroundedRetrievalResult {
  query: GroundedQuery
  winner: GroundedRetrievalCandidate | null
  candidates: GroundedRetrievalCandidate[]
  debug: Record<string, unknown>
}

export type AIExecutionPhase =
  | 'idle'
  | 'parsing'
  | 'transcribing'
  | 'searching'
  | 'planning'
  | 'executing'
  | 'preview'
  | 'done'
  | 'error'

export interface AIExecutionLogEntry {
  id: string
  timestamp: number
  phase: AIExecutionPhase
  message: string
  data?: Record<string, unknown>
}

export interface AIAppliedOperation {
  action: AIEditAction
  appliedAt: number
  success: boolean
  error?: string
}

export interface AIHighlightRange {
  start: number
  end: number
  confidence: number
  label: string
}

export interface Transcript {
  mediaId: string
  language: string
  segments: TranscriptSegment[]
  fullText: string
  generatedAt: number
}

export interface TranscriptSegment {
  id: string
  start: number
  end: number
  text: string
  confidence: number
  speaker?: string
  words?: TranscriptWord[]
}

export interface TranscriptWord {
  word: string
  start: number
  end: number
  confidence: number
}

export interface SilenceRegion {
  start: number
  end: number
  duration: number
  averageDb: number
}

export interface SceneDetectionResult {
  mediaId: string
  scenes: SceneBoundary[]
}

export interface SceneBoundary {
  time: number
  score: number
  type: 'cut' | 'gradual'
  thumbnailPath: string | null
}
