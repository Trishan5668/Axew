/**
 * OpusClipPanel — collapsible right-sidebar section.
 *
 * Lifecycle:
 *   - User queues ranges via Timeline right-click ("Send to OpusClip").
 *   - "Enhance with OpusClip" POSTs /opusclip/process and gets back a
 *     job_id (202 Accepted). The slice transitions to 'processing'.
 *   - useOpusclipJobPoller polls /opusclip/status/{id} every ~3s and,
 *     when stage='completed', fetches /opusclip/result/{id} and stores
 *     the normalized results.
 *   - Each finished clip card supports Preview (opens preview_url) and
 *     Import to Timeline (registers a MediaFile in projectStore and
 *     drops a Clip onto the first video track in timelineStore).
 *
 * Hidden entirely when cloud mode is off (renders null).
 */

import { AlertTriangle, Loader2, Sparkles, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { nanoid } from 'nanoid'
import { useNavigate } from 'react-router-dom'
import type { MediaFile } from '@shared/media'
import { useCredits } from '../../hooks/useCredits'
import { useOpusclipJobPoller } from '../../hooks/useOpusclipJobPoller'
import {
  submitClipJob,
  type ClipRange,
  type OpusClipResult,
} from '../../lib/opusclipClient'
import { isCloudAvailable } from '../../lib/supabase'
import { useAuthStore } from '../../stores/authSlice'
import { useOpusclipStore } from '../../stores/opusclipSlice'
import { useProjectStore } from '../../stores/projectStore'
import { useTimelineStore } from '../../stores/timelineStore'
import { ClipCard } from './ClipCard'
import { ProcessingProgress } from './ProcessingProgress'

function totalMinutes(clips: ClipRange[]): number {
  return (
    clips.reduce((sum, c) => sum + Math.max(0, c.end_seconds - c.start_seconds), 0) / 60
  )
}

/**
 * Register an OpusClip output as a MediaFile in the project's MediaBin
 * and append a Clip to the end of the first video track on the timeline.
 * Returns the newly-created media id so callers can show feedback.
 */
function importResultToTimeline(result: OpusClipResult): string | null {
  const project = useProjectStore.getState().currentProject
  if (!project) return null

  const mediaId = nanoid()
  const now = Date.now()
  const labelText =
    result.title ?? result.source_range.label ?? `Enhanced ${mediaId.slice(0, 6)}`

  const media: MediaFile = {
    id: mediaId,
    name: `${labelText}.mp4`,
    path: result.clip_url,
    type: 'video',
    duration: Math.max(0, result.duration_seconds),
    width: 0,
    height: 0,
    fps: 0,
    codec: 'unknown',
    audioCodec: null,
    sampleRate: null,
    channels: null,
    bitrate: 0,
    fileSize: 0,
    thumbnail: result.preview_url ?? null,
    createdAt: now,
    updatedAt: now,
    metadata: {
      source: 'opusclip',
      opusclip_id: result.opusclip_id,
      project_id: result.project_id,
      ...(result.viral_score !== null ? { viral_score: result.viral_score } : {}),
    },
  }
  useProjectStore.getState().addMediaFile(media)

  // Append to the first existing video track, or skip the timeline add
  // if the project has none (the user can still drag from MediaBin).
  const videoTrack = project.timeline.tracks.find((t) => t.type === 'video')
  if (videoTrack) {
    const lastClipEnd = videoTrack.clips.reduce(
      (max, c) => Math.max(max, c.startTime + c.duration),
      0,
    )
    useTimelineStore.getState().addClip(videoTrack.id, {
      mediaId,
      name: media.name,
      startTime: lastClipEnd,
      duration: media.duration || 1,
      mediaInPoint: 0,
      mediaOutPoint: media.duration || 1,
      speed: 1,
      opacity: 1,
      volume: 1,
      disabled: false,
      color: '#a855f7',
      effects: [],
      transitions: { in: null, out: null },
      keyframes: [],
    })
  }
  return mediaId
}

export function OpusClipPanel(): JSX.Element | null {
  const navigate = useNavigate()
  const { session, profile, authStatus } = useAuthStore()
  const { creditBalance } = useCredits()
  const {
    pendingClips,
    results,
    processingStatus,
    errorMessage,
    perClipProgress,
    jobStatus,
    removeClipRange,
    clearClips,
    startSubmission,
    setActiveJob,
    setStatus,
    reset,
  } = useOpusclipStore()
  const { currentProject } = useProjectStore()
  const [sourceVideoUrl, setSourceVideoUrl] = useState('')
  const [importedIds, setImportedIds] = useState<Record<string, string>>({})

  // Drive the polling lifecycle for whichever job is active.
  useOpusclipJobPoller()

  // Auto-derive the source video from the project's first video media file.
  useEffect(() => {
    if (sourceVideoUrl || !currentProject) return
    const firstVideo = Object.values(currentProject.mediaFiles).find(
      (m) => m.type === 'video',
    )
    if (firstVideo?.path) setSourceVideoUrl(firstVideo.path)
  }, [currentProject, sourceVideoUrl])

  if (!isCloudAvailable()) return null
  if (authStatus !== 'authenticated' || !session) return null

  const requiredMinutes = totalMinutes(pendingClips)
  const insufficientCredits = creditBalance < requiredMinutes
  const isRunning =
    processingStatus === 'submitting' || processingStatus === 'processing'
  const ctaDisabled =
    isRunning || pendingClips.length === 0 || !sourceVideoUrl || insufficientCredits

  const runProcessing = async () => {
    if (ctaDisabled) return
    startSubmission()
    try {
      const accepted = await submitClipJob({
        video_url: sourceVideoUrl,
        user_id: session.user.id,
        clips: pendingClips,
      })
      setActiveJob(accepted.job_id)
      // The poller takes over from here.
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setStatus('error', message)
    }
  }

  const handleImport = (result: OpusClipResult) => {
    const id = importResultToTimeline(result)
    if (id) {
      setImportedIds((prev) => ({ ...prev, [result.opusclip_id]: id }))
    }
  }

  const handlePreview = (result: OpusClipResult) => {
    const url = result.preview_url ?? result.clip_url
    if (typeof window !== 'undefined') {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  }

  const stageLabel = jobStatus?.stage ?? processingStatus
  const projectCount = jobStatus?.projects.length ?? pendingClips.length

  return (
    <section className="flex h-full flex-col border-t border-axew-border bg-axew-surface">
      <header className="flex items-center justify-between border-b border-axew-border px-3 py-2">
        <div className="flex items-center gap-1.5">
          <Sparkles size={12} className="text-axew-ai" />
          <span className="text-xs font-medium text-axew-text">OpusClip</span>
        </div>
        <span className="text-2xs text-axew-textDim">
          {profile?.credit_balance?.toFixed(1) ?? '0.0'} min left
        </span>
      </header>

      <div className="px-3 py-2 text-2xs text-axew-textDim">
        <p>
          Forward AXEW-selected ranges to OpusClip for viral curation, dynamic
          captions, filler removal, B-roll, and speaker reframing. Cancel by
          closing the panel — credits are only deducted on success.
        </p>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-3 pb-3">
        <section>
          <header className="mb-1 flex items-center justify-between">
            <p className="text-2xs font-medium uppercase tracking-wide text-axew-textDim">
              Source video
            </p>
          </header>
          <input
            type="url"
            value={sourceVideoUrl}
            onChange={(e) => setSourceVideoUrl(e.target.value)}
            placeholder="https://media.example.com/video.mp4"
            className="w-full rounded border border-axew-border bg-axew-panel px-2 py-1 text-2xs text-axew-text outline-none focus:border-axew-accent"
            aria-label="Source video URL"
            disabled={isRunning}
          />
          <p className="mt-1 text-2xs text-axew-textDim">
            OpusClip fetches the source from this URL — it must be public and
            playable (YouTube, Vimeo, Drive, S3 mp4, etc.).
          </p>
        </section>

        <section>
          <header className="mb-1 flex items-center justify-between">
            <p className="text-2xs font-medium uppercase tracking-wide text-axew-textDim">
              Queued ranges ({pendingClips.length})
            </p>
            {pendingClips.length > 0 && !isRunning && (
              <button
                type="button"
                onClick={clearClips}
                className="text-2xs text-axew-textDim hover:text-axew-text"
              >
                Clear
              </button>
            )}
          </header>

          {pendingClips.length === 0 ? (
            <p className="rounded border border-dashed border-axew-border px-2 py-3 text-center text-2xs text-axew-textDim">
              Right-click a clip on the timeline → &quot;Send to OpusClip&quot;
            </p>
          ) : (
            <ul className="space-y-1">
              {pendingClips.map((clip, idx) => {
                const projectStage = jobStatus?.projects[idx]?.stage
                return (
                  <li
                    key={`${clip.start_seconds}-${clip.end_seconds}-${idx}`}
                    className="flex items-center justify-between gap-2 rounded border border-axew-border bg-axew-panel px-2 py-1 text-2xs"
                  >
                    <div className="min-w-0 flex-1 truncate">
                      <span className="text-axew-text">
                        {clip.start_seconds.toFixed(1)}s – {clip.end_seconds.toFixed(1)}s
                      </span>
                      {clip.label && (
                        <span className="ml-1 text-axew-textDim">· {clip.label}</span>
                      )}
                      {projectStage && (
                        <span className="ml-1 text-axew-textMuted">
                          · {projectStage.toLowerCase()}
                        </span>
                      )}
                    </div>
                    {isRunning && (
                      <div className="w-20">
                        <ProcessingProgress progress={perClipProgress[idx] ?? 0} />
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => removeClipRange(idx)}
                      className="text-axew-textDim hover:text-red-300"
                      aria-label="Remove range"
                      disabled={isRunning}
                    >
                      <X size={11} />
                    </button>
                  </li>
                )
              })}
            </ul>
          )}

          {pendingClips.length > 0 && (
            <p className="mt-1 text-2xs text-axew-textDim">
              Total: <span className="text-axew-text">{requiredMinutes.toFixed(2)} min</span>
              {insufficientCredits && !isRunning && (
                <span className="ml-2 text-red-300">
                  · Not enough credits ({creditBalance.toFixed(1)} left)
                </span>
              )}
            </p>
          )}
        </section>

        {isRunning && (
          <div className="rounded border border-axew-border bg-axew-panel px-2 py-1.5 text-2xs text-axew-textDim">
            <p className="flex items-center gap-1">
              <Loader2 size={10} className="animate-spin text-axew-ai" />
              <span>
                OpusClip is {stageLabel}…
                {projectCount > 0 && (
                  <span className="ml-1 text-axew-textMuted">
                    ({projectCount} project{projectCount === 1 ? '' : 's'})
                  </span>
                )}
              </span>
            </p>
            <p className="mt-0.5 text-axew-textMuted">
              You can leave the panel — we&apos;ll keep polling. Credits are only deducted on success.
            </p>
          </div>
        )}

        {errorMessage && (
          <div
            role="alert"
            className="flex items-start gap-1.5 rounded border border-red-500/40 bg-red-500/10 p-2 text-2xs text-red-200"
          >
            <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        {results.length > 0 && (
          <section>
            <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-axew-textDim">
              Enhanced clips ({results.length})
            </p>
            <div className="space-y-1.5">
              {results.map((r, idx) => (
                <ClipCard
                  key={`${r.opusclip_id || r.clip_url}-${idx}`}
                  result={r}
                  imported={Boolean(importedIds[r.opusclip_id])}
                  onPreview={() => handlePreview(r)}
                  onImport={() => handleImport(r)}
                />
              ))}
            </div>
          </section>
        )}
      </div>

      <footer className="flex-shrink-0 border-t border-axew-border p-2">
        {insufficientCredits && pendingClips.length > 0 && !isRunning ? (
          <button
            type="button"
            onClick={() => navigate('/dashboard/billing')}
            className="flex w-full items-center justify-center gap-1 rounded bg-amber-500 px-3 py-1.5 text-xs font-medium text-black hover:bg-amber-400"
          >
            Buy credits to continue
          </button>
        ) : (
          <button
            type="button"
            onClick={runProcessing}
            disabled={ctaDisabled}
            className="flex w-full items-center justify-center gap-1 rounded bg-axew-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-axew-accentHover disabled:opacity-40"
          >
            {isRunning ? (
              <>
                <Loader2 size={12} className="animate-spin" /> Enhancing…
              </>
            ) : (
              <>
                <Sparkles size={12} /> Enhance with OpusClip
              </>
            )}
          </button>
        )}
        {processingStatus === 'done' && (
          <button
            type="button"
            onClick={() => {
              reset()
              setImportedIds({})
            }}
            className="mt-1 flex w-full items-center justify-center gap-1 rounded border border-axew-border px-3 py-1.5 text-2xs text-axew-textMuted hover:text-axew-text"
          >
            <Trash2 size={10} /> Reset queue
          </button>
        )}
      </footer>
    </section>
  )
}
