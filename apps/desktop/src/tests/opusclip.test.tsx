/**
 * Frontend tests for the OpusClip integration.
 *
 * Covers:
 *   - opusclipSlice: deriveProgressFromStatus maps stages to fractions.
 *   - opusclipSlice: dedup of ranges, lifecycle transitions, error mapping.
 *   - opusclipClient: stageToProgress mapping is monotonically increasing.
 *   - useOpusclipJobPoller: polls status, fetches result on completion,
 *     stops on terminal stages, surfaces errors after repeated failures.
 *   - ClipCard: renders viral score badge only when score is present,
 *     "Import to Timeline" calls the callback, "Imported" state sticks.
 *
 * We do NOT cover the full OpusClipPanel here because it pulls in
 * auth + cloud + project stores which are exercised by the e2e tests.
 */

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'

import {
  deriveProgressFromStatus,
  useOpusclipStore,
} from '../stores/opusclipSlice'
import type {
  JobResultResponse,
  JobStatusResponse,
  OpusClipResult,
} from '../lib/opusclipClient'
import { stageToProgress } from '../lib/opusclipClient'
import { ClipCard } from '../components/OpusClipPanel/ClipCard'

// ---------------------------------------------------------------------------
// Mocks for the AI-service client used by useOpusclipJobPoller
// ---------------------------------------------------------------------------

const fakeStatus = vi.fn<() => Promise<JobStatusResponse>>()
const fakeResult = vi.fn<() => Promise<JobResultResponse>>()

vi.mock('../lib/opusclipClient', async () => {
  const actual = await vi.importActual<typeof import('../lib/opusclipClient')>(
    '../lib/opusclipClient',
  )
  return {
    ...actual,
    getJobStatus: (..._args: unknown[]) => fakeStatus(),
    getJobResult: (..._args: unknown[]) => fakeResult(),
  }
})

// useOpusclipJobPoller imports from opusclipClient — it must be imported AFTER
// the mock above is installed.
import { useOpusclipJobPoller } from '../hooks/useOpusclipJobPoller'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeStatus(
  jobId: string,
  stage: JobStatusResponse['stage'],
  projectStages: string[] = ['QUEUED'],
): JobStatusResponse {
  return {
    job_id: jobId,
    stage,
    minutes_required: 1.0,
    submitted_at: 0,
    updated_at: 1,
    projects: projectStages.map((s, idx) => ({
      project_id: `P_${idx}`,
      source_range: { start_seconds: idx * 60, end_seconds: idx * 60 + 60, label: null },
      stage: s,
      last_error: null,
    })),
    error_message: null,
  }
}

function makeResult(jobId: string, clips: OpusClipResult[]): JobResultResponse {
  return {
    job_id: jobId,
    stage: 'completed',
    minutes_processed: 1.0,
    credits_remaining: 9.0,
    results: clips,
  }
}

function makeClip(overrides: Partial<OpusClipResult> = {}): OpusClipResult {
  return {
    opusclip_id: 'P_0.CU0',
    project_id: 'P_0',
    clip_url: 'https://cdn.opus.pro/P_0/export.mp4',
    preview_url: 'https://cdn.opus.pro/P_0/preview.mp4',
    duration_seconds: 30,
    title: 'A funny moment',
    description: 'Description here',
    hashtags: '#axew #opus',
    keywords: ['axew'],
    transcript_text: 'hello world',
    viral_score: 82,
    source_range: { start_seconds: 0, end_seconds: 60, label: 'intro' },
    ...overrides,
  }
}

beforeEach(() => {
  useOpusclipStore.getState().reset()
  fakeStatus.mockReset()
  fakeResult.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

// ---------------------------------------------------------------------------
// stageToProgress + deriveProgressFromStatus
// ---------------------------------------------------------------------------

describe('stageToProgress', () => {
  test('is monotonically non-decreasing across the documented lifecycle', () => {
    const order = ['PENDING', 'QUEUED', 'CURATE', 'REFINE', 'RENDER', 'UPLOAD', 'COMPLETE']
    let prev = -Infinity
    for (const s of order) {
      const p = stageToProgress(s)
      expect(p).toBeGreaterThanOrEqual(prev)
      prev = p
    }
  })

  test('unknown / null stages map to 0', () => {
    expect(stageToProgress(null)).toBe(0)
    expect(stageToProgress(undefined)).toBe(0)
    expect(stageToProgress('SOMETHING_NEW')).toBe(0)
  })

  test('STALLED maps to 0 (no forward motion)', () => {
    expect(stageToProgress('STALLED')).toBe(0)
  })
})

describe('deriveProgressFromStatus', () => {
  test('maps each project stage into a progress map indexed by position', () => {
    const status = makeStatus('j1', 'processing', ['CURATE', 'RENDER'])
    const map = deriveProgressFromStatus(status)
    expect(map[0]).toBeCloseTo(stageToProgress('CURATE'))
    expect(map[1]).toBeCloseTo(stageToProgress('RENDER'))
  })

  test('returns empty map for null status', () => {
    expect(deriveProgressFromStatus(null)).toEqual({})
  })
})

// ---------------------------------------------------------------------------
// opusclipSlice
// ---------------------------------------------------------------------------

describe('opusclipSlice', () => {
  test('addClipRange dedups identical ranges within 5ms tolerance', () => {
    const { addClipRange } = useOpusclipStore.getState()
    addClipRange({ start_seconds: 1.0, end_seconds: 5.0 })
    addClipRange({ start_seconds: 1.001, end_seconds: 5.001 })
    expect(useOpusclipStore.getState().pendingClips).toHaveLength(1)
  })

  test('setJobStatus maps stage=completed -> done, failed -> error', () => {
    const { setJobStatus } = useOpusclipStore.getState()

    setJobStatus(makeStatus('j', 'processing', ['RENDER']))
    expect(useOpusclipStore.getState().processingStatus).toBe('processing')

    setJobStatus({ ...makeStatus('j', 'completed', ['COMPLETE']) })
    expect(useOpusclipStore.getState().processingStatus).toBe('done')

    setJobStatus({
      ...makeStatus('j', 'failed', ['STALLED']),
      error_message: 'boom',
    })
    expect(useOpusclipStore.getState().processingStatus).toBe('error')
    expect(useOpusclipStore.getState().errorMessage).toBe('boom')
  })

  test('startSubmission clears stale state and resets per-clip progress', () => {
    const store = useOpusclipStore.getState()
    store.addClipRange({ start_seconds: 0, end_seconds: 60 })
    store.addClipRange({ start_seconds: 100, end_seconds: 200 })
    store.startSubmission()
    const after = useOpusclipStore.getState()
    expect(after.processingStatus).toBe('submitting')
    expect(after.results).toEqual([])
    expect(after.errorMessage).toBeNull()
    expect(after.perClipProgress).toEqual({ 0: 0, 1: 0 })
  })

  test('reset returns to a clean slate', () => {
    const store = useOpusclipStore.getState()
    store.addClipRange({ start_seconds: 0, end_seconds: 60 })
    store.setActiveJob('jx')
    store.reset()
    const after = useOpusclipStore.getState()
    expect(after.pendingClips).toEqual([])
    expect(after.jobId).toBeNull()
    expect(after.processingStatus).toBe('idle')
  })
})

// ---------------------------------------------------------------------------
// useOpusclipJobPoller
// ---------------------------------------------------------------------------

describe('useOpusclipJobPoller', () => {
  test('does nothing while jobId is null', async () => {
    renderHook(() => useOpusclipJobPoller())
    // wait a tick to give a stray microtask a chance to fire
    await new Promise((r) => setTimeout(r, 0))
    expect(fakeStatus).not.toHaveBeenCalled()
  })

  test('polls status and fetches result on completion', async () => {
    let call = 0
    fakeStatus.mockImplementation(async () => {
      call += 1
      if (call === 1) return makeStatus('jx', 'processing', ['RENDER'])
      return makeStatus('jx', 'completed', ['COMPLETE'])
    })
    fakeResult.mockResolvedValue(makeResult('jx', [makeClip()]))

    renderHook(() => useOpusclipJobPoller())
    act(() => {
      useOpusclipStore.getState().setActiveJob('jx')
    })

    // Polling backs off 3s+jitter between ticks; give it ~5s budget.
    await waitFor(
      () => {
        expect(useOpusclipStore.getState().processingStatus).toBe('done')
      },
      { timeout: 5000, interval: 100 },
    )
    expect(useOpusclipStore.getState().results).toHaveLength(1)
    expect(fakeResult).toHaveBeenCalledTimes(1)
  })

  test('stops polling on stage=failed and surfaces error_message', async () => {
    fakeStatus.mockResolvedValueOnce({
      ...makeStatus('jx', 'failed', ['STALLED']),
      error_message: 'OpusClip stalled.',
    })

    renderHook(() => useOpusclipJobPoller())
    act(() => {
      useOpusclipStore.getState().setActiveJob('jx')
    })

    await waitFor(() => {
      expect(useOpusclipStore.getState().processingStatus).toBe('error')
    })
    expect(useOpusclipStore.getState().errorMessage).toBe('OpusClip stalled.')
    expect(fakeResult).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// ClipCard
// ---------------------------------------------------------------------------

describe('ClipCard', () => {
  test('renders viral score badge when score is present', () => {
    render(
      <ClipCard result={makeClip({ viral_score: 88 })} onPreview={() => {}} onImport={() => {}} />,
    )
    expect(screen.getByText(/88/)).toBeInTheDocument()
  })

  test('omits viral score badge when score is null (public API common case)', () => {
    render(
      <ClipCard result={makeClip({ viral_score: null })} onPreview={() => {}} onImport={() => {}} />,
    )
    expect(screen.queryByText(/Excellent|Strong|Decent|Weak/)).not.toBeInTheDocument()
  })

  test('clicking Import calls onImport', () => {
    const onImport = vi.fn()
    render(
      <ClipCard result={makeClip()} onPreview={() => {}} onImport={onImport} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Import.*Timeline/i }))
    expect(onImport).toHaveBeenCalledTimes(1)
  })

  test('disables Import button once imported=true and labels it "Imported"', () => {
    render(
      <ClipCard
        result={makeClip()}
        imported
        onPreview={() => {}}
        onImport={() => {}}
      />,
    )
    const btn = screen.getByRole('button', { name: /already imported/i })
    expect(btn).toBeDisabled()
    expect(screen.getByText('Imported')).toBeInTheDocument()
  })

  test('clicking Preview calls onPreview', () => {
    const onPreview = vi.fn()
    render(
      <ClipCard result={makeClip()} onPreview={onPreview} onImport={() => {}} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Preview/i }))
    expect(onPreview).toHaveBeenCalledTimes(1)
  })
})
