import { create } from 'zustand'

export interface ExtractionDiagnostics {
  ffmpegCommand?: string
  ffmpegStderr?: string
  outputPath?: string
  actualDuration?: number
  strategyUsed?: string
  validation?: {
    has_video_stream: boolean
    has_audio_stream: boolean
    video_codec: string
    audio_codec: string
    duration_seconds: number
    frame_count: number
    is_playable: boolean
    container_valid: boolean
    warnings: string[]
  }
}

export interface RetrievalDebugPayload {
  intent_graph: Record<string, unknown>
  semantic_events?: Array<Record<string, unknown>>
  top_k_candidates: Array<{
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
  }>
  reranker_responses: Array<Record<string, unknown>>
  chosen_chunk: Record<string, unknown>
  time_range: Record<string, unknown>
  confidence_gated: boolean
  total_pipeline_ms: number
  action_plan?: Record<string, unknown>
  event_scores?: Array<Record<string, unknown>>
  rejected_actions?: Array<Record<string, unknown>>
  failure_reason?: string | null
  planner_rejection_reason?: string | null
  fallback_activated?: boolean
  execution_mode?: string
  timestamp_propagation?: Record<string, unknown>
  threshold_decision?: Record<string, unknown>
  selection_reason?: string
  why_selected?: string
  rank_before_calibration?: Array<Record<string, unknown>>
  rank_after_calibration?: Array<Record<string, unknown>>
  rank_before_rerank?: Array<Record<string, unknown>>
  pipeline_trace?: Record<string, unknown>
}

interface DebugState {
  lastRetrievalDebug: RetrievalDebugPayload | null
  lastExtractionResult: ExtractionDiagnostics | null
}

interface DebugActions {
  setRetrievalDebug: (payload: RetrievalDebugPayload | null) => void
  setExtractionResult: (result: ExtractionDiagnostics | null) => void
}

export const useDebugStore = create<DebugState & DebugActions>()((set) => ({
  lastRetrievalDebug: null,
  lastExtractionResult: null,

  setRetrievalDebug: (payload) => set({ lastRetrievalDebug: payload }),
  setExtractionResult: (result) => set({ lastExtractionResult: result }),
}))
