/**
 * Zustand slice for the OpusClip processing queue + active job.
 *
 * Lifecycle:
 *   1. User right-clicks a timeline range -> addClipRange()
 *   2. User clicks "Enhance with OpusClip" in the panel
 *        -> submitJob() (calls POST /opusclip/process, stores jobId)
 *   3. useOpusclipJobPoller polls GET /opusclip/status/:id every 4s
 *        -> setJobStatus() updates `jobStatus` + derives per-project progress
 *   4. When jobStatus.stage === 'completed', poller calls GET /opusclip/result/:id
 *        -> setResults() + setStage('done')
 *   5. On error, setStage('error', message)
 *
 * The slice intentionally does NOT issue any HTTP itself — that belongs
 * to the React hook so React Query / cleanup-on-unmount semantics work.
 */

import { create } from 'zustand'
import type {
  ClipRange,
  JobStatusResponse,
  OpusClipResult,
  PerProjectStatus,
} from '../lib/opusclipClient'

export type ProcessingStatus = 'idle' | 'submitting' | 'processing' | 'done' | 'error'

interface OpusClipState {
  /** Ranges the user has queued for the next submission. */
  pendingClips: ClipRange[]
  /** Currently active AXEW job id (server-issued). */
  jobId: string | null
  /** Last status payload from /opusclip/status — drives progress UI. */
  jobStatus: JobStatusResponse | null
  /** Final results once the job completes. */
  results: OpusClipResult[]
  /** Coarse UI state; derived from jobStatus.stage but stored for ergonomics. */
  processingStatus: ProcessingStatus
  /** Inline error message, shown below the queue list. */
  errorMessage: string | null
  /** Per-project progress 0..1, indexed by source range index. */
  perClipProgress: Record<number, number>
}

interface OpusClipActions {
  addClipRange: (range: ClipRange) => void
  removeClipRange: (index: number) => void
  clearClips: () => void

  startSubmission: () => void
  setActiveJob: (jobId: string) => void
  setJobStatus: (status: JobStatusResponse) => void
  setResults: (results: OpusClipResult[]) => void
  setStatus: (status: ProcessingStatus, error?: string) => void
  setClipProgress: (index: number, progress: number) => void
  reset: () => void
}

const _equalRange = (a: ClipRange, b: ClipRange): boolean =>
  Math.abs(a.start_seconds - b.start_seconds) < 0.005 &&
  Math.abs(a.end_seconds - b.end_seconds) < 0.005

/**
 * Convert a per-project status array into a per-index progress map.
 * Exported so `useOpusclipJobPoller` (and tests) can call it directly.
 */
import { stageToProgress } from '../lib/opusclipClient'
export function deriveProgressFromStatus(
  status: JobStatusResponse | null,
): Record<number, number> {
  if (!status) return {}
  const map: Record<number, number> = {}
  status.projects.forEach((p: PerProjectStatus, idx: number) => {
    map[idx] = stageToProgress(p.stage)
  })
  return map
}

export const useOpusclipStore = create<OpusClipState & OpusClipActions>((set) => ({
  pendingClips: [],
  jobId: null,
  jobStatus: null,
  results: [],
  processingStatus: 'idle',
  errorMessage: null,
  perClipProgress: {},

  addClipRange: (range) =>
    set((state) => {
      if (state.pendingClips.some((c) => _equalRange(c, range))) return state
      return { pendingClips: [...state.pendingClips, range] }
    }),

  removeClipRange: (index) =>
    set((state) => ({
      pendingClips: state.pendingClips.filter((_, i) => i !== index),
    })),

  clearClips: () => set({ pendingClips: [], perClipProgress: {} }),

  startSubmission: () =>
    set((state) => ({
      processingStatus: 'submitting',
      errorMessage: null,
      results: [],
      jobStatus: null,
      jobId: null,
      perClipProgress: Object.fromEntries(state.pendingClips.map((_, i) => [i, 0])),
    })),

  setActiveJob: (jobId) => set({ jobId, processingStatus: 'processing' }),

  setJobStatus: (status) =>
    set({
      jobStatus: status,
      perClipProgress: deriveProgressFromStatus(status),
      // mirror the server-side stage onto the UI status enum
      processingStatus:
        status.stage === 'completed'
          ? 'done'
          : status.stage === 'failed' || status.stage === 'expired'
            ? 'error'
            : 'processing',
      errorMessage:
        status.stage === 'failed' || status.stage === 'expired'
          ? (status.error_message ?? 'OpusClip job failed.')
          : null,
    }),

  setResults: (results) => set({ results, processingStatus: 'done' }),

  setStatus: (status, error) =>
    set((state) => ({
      processingStatus: status,
      errorMessage: error ?? (status === 'error' ? state.errorMessage : null),
    })),

  setClipProgress: (index, progress) =>
    set((state) => ({
      perClipProgress: {
        ...state.perClipProgress,
        [index]: Math.max(0, Math.min(1, progress)),
      },
    })),

  reset: () =>
    set({
      pendingClips: [],
      jobId: null,
      jobStatus: null,
      results: [],
      processingStatus: 'idle',
      errorMessage: null,
      perClipProgress: {},
    }),
}))
