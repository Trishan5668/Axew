/**
 * Typed wrapper around the AXEW AI service's `/opusclip/*` endpoints.
 *
 * Architecture:
 *   POST  /opusclip/process       -> { job_id, stage: 'queued', ... }   (202)
 *   GET   /opusclip/status/:id    -> { stage, projects, ... }
 *   GET   /opusclip/result/:id    -> { results: OpusClipResult[], ... } (only when stage='completed')
 *
 * The OpusClip API key NEVER lives in the renderer — it stays in the
 * Python service environment. This client only talks to the local AI
 * service, which authenticates with Supabase JWT (handled by aiServiceFetch).
 */

import { aiServiceFetch } from './aiServiceClient'

// ---------------------------------------------------------------------------
// Request models — mirror models/opusclip.py:OpusClipRequest
// ---------------------------------------------------------------------------

export interface ClipRange {
  start_seconds: number
  end_seconds: number
  label?: string | null
}

export type CurationModel = 'ClipBasic' | 'ClipAnything'
export type LayoutAspectRatio = 'portrait' | 'landscape' | 'square'

export interface OpusClipRequestBody {
  video_url: string
  user_id: string
  clips: ClipRange[]
  curation_model?: CurationModel
  aspect_ratio?: LayoutAspectRatio
  source_language?: string
  brand_template_id?: string | null
  topic_keywords?: string[]
  custom_prompt?: string | null
  remove_fillers?: boolean
  enable_broll?: boolean
  enable_captions?: boolean
}

// ---------------------------------------------------------------------------
// Response models — mirror models/opusclip.py
// ---------------------------------------------------------------------------

export type JobStage =
  | 'queued'
  | 'submitting'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'expired'

export interface JobAcceptedResponse {
  job_id: string
  stage: JobStage
  minutes_required: number
  credits_balance_before: number
  poll_status_url: string
  poll_result_url: string
}

export interface PerProjectStatus {
  project_id: string
  source_range: ClipRange
  stage: string
  last_error: string | null
}

export interface JobStatusResponse {
  job_id: string
  stage: JobStage
  minutes_required: number
  submitted_at: number
  updated_at: number
  projects: PerProjectStatus[]
  error_message: string | null
}

export interface OpusClipResult {
  opusclip_id: string
  project_id: string
  clip_url: string
  preview_url: string | null
  duration_seconds: number
  title: string | null
  description: string | null
  hashtags: string | null
  keywords: string[]
  transcript_text: string | null
  /** 0..100, OPTIONAL — public API does not always expose this. */
  viral_score: number | null
  source_range: ClipRange
}

export interface JobResultResponse {
  job_id: string
  stage: JobStage
  minutes_processed: number
  credits_remaining: number
  results: OpusClipResult[]
}

// ---------------------------------------------------------------------------
// API surface
// ---------------------------------------------------------------------------

export async function submitClipJob(
  body: OpusClipRequestBody,
  signal?: AbortSignal,
): Promise<JobAcceptedResponse> {
  return aiServiceFetch<JobAcceptedResponse>('/opusclip/process', {
    method: 'POST',
    body,
    signal,
  })
}

export async function getJobStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatusResponse> {
  return aiServiceFetch<JobStatusResponse>(`/opusclip/status/${jobId}`, {
    method: 'GET',
    signal,
  })
}

export async function getJobResult(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobResultResponse> {
  return aiServiceFetch<JobResultResponse>(`/opusclip/result/${jobId}`, {
    method: 'GET',
    signal,
  })
}

/**
 * Convenience helpers — used by the UI to decide what to render.
 */
export function isJobTerminal(stage: JobStage): boolean {
  return stage === 'completed' || stage === 'failed' || stage === 'expired'
}

export function isJobInProgress(stage: JobStage): boolean {
  return stage === 'queued' || stage === 'submitting' || stage === 'processing'
}

/**
 * Map an OpusClip per-project stage (raw upstream values like 'RENDER')
 * into a coarse progress fraction so the UI can show forward motion
 * even though OpusClip doesn't expose a percentage.
 *
 * The values are an opinionated guess at where each stage sits in the
 * project lifecycle. They animate in one direction only.
 */
export function stageToProgress(stage: string | null | undefined): number {
  const s = (stage ?? '').toUpperCase()
  switch (s) {
    case 'PENDING':
      return 0.05
    case 'QUEUED':
      return 0.15
    case 'CURATE':
      return 0.35
    case 'REFINE':
      return 0.55
    case 'RENDER':
      return 0.75
    case 'UPLOAD':
      return 0.9
    case 'COMPLETE':
      return 1.0
    case 'STALLED':
      return 0
    default:
      return 0.0
  }
}
