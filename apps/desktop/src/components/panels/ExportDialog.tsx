import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, X } from 'lucide-react'
import { nanoid } from 'nanoid'
import type { ExportJob } from '@shared/export'
import { getAxew } from '../../lib/axewBridge'
import { getActiveVideoClipAtTime } from '../../lib/playbackSync'
import { getExportStatus, startExport } from '../../lib/rustClient'
import { useExportStore } from '../../stores/exportStore'
import { useProjectStore } from '../../stores/projectStore'
import { useUIStore } from '../../stores/uiStore'

const FFMPEG_VIDEO_CODECS: Record<string, string> = {
  h264: 'libx264',
  h265: 'libx265',
  vp9: 'libvpx-vp9',
  av1: 'libaom-av1',
  prores422: 'prores_ks',
  prores4444: 'prores_ks',
}

const FFMPEG_AUDIO_CODECS: Record<string, string> = {
  aac: 'aac',
  mp3: 'libmp3lame',
  opus: 'libopus',
  pcm: 'pcm_s16le',
  flac: 'flac',
}

export function ExportDialog() {
  const { showExportDialog, setShowExportDialog, addNotification } = useUIStore()
  const { currentProject } = useProjectStore()
  const { presets, selectedPresetId, addJob, updateJob, setActiveJob } = useExportStore()
  const [exporting, setExporting] = useState(false)
  const [progress, setProgress] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const preset = presets.find((p) => p.id === selectedPresetId) ?? presets[0]

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => () => stopPolling(), [stopPolling])

  const handleExport = useCallback(async () => {
    if (!currentProject || !preset) return

    const timeline = currentProject.timeline
    const clip = getActiveVideoClipAtTime(timeline, 0) ?? timeline.tracks.find((t) => t.type === 'video')?.clips[0]
    const media = clip ? currentProject.mediaFiles[clip.mediaId] : Object.values(currentProject.mediaFiles).find((m) => m.type === 'video')

    if (!media) {
      addNotification({ type: 'error', message: 'No video media on timeline to export' })
      return
    }

    const saveResult = await getAxew().dialog.saveFile({
      filters: [{ name: 'Video', extensions: [preset.container] }],
      defaultPath: `${currentProject.name}.${preset.container}`,
    })
    if (saveResult.canceled || !saveResult.filePath) return

    const jobId = nanoid()
    const job: ExportJob = {
      id: jobId,
      projectId: currentProject.id,
      timelineId: timeline.id,
      outputPath: saveResult.filePath,
      preset,
      status: 'queued',
      progress: 0,
      currentFrame: 0,
      totalFrames: Math.ceil(timeline.duration * timeline.frameRate),
      startedAt: Date.now(),
      completedAt: null,
      error: null,
      estimatedTimeRemaining: null,
    }

    addJob(job)
    setActiveJob(jobId)
    setExporting(true)
    setProgress(0)

    try {
      await startExport({
        job_id: jobId,
        input_path: media.path,
        output_path: saveResult.filePath,
        video_codec: FFMPEG_VIDEO_CODECS[preset.videoCodec] ?? 'libx264',
        audio_codec: FFMPEG_AUDIO_CODECS[preset.audioCodec] ?? 'aac',
        width: preset.width,
        height: preset.height,
        frame_rate: preset.frameRate,
        video_bitrate: preset.videoBitrate,
        audio_bitrate: preset.audioBitrate,
        crf: preset.quality,
        extra_args: preset.customFFmpegArgs,
      })

      updateJob(jobId, { status: 'rendering' })

      pollRef.current = setInterval(async () => {
        try {
          const status = await getExportStatus(jobId)
          setProgress(status.progress ?? 0)
          updateJob(jobId, {
            progress: status.progress,
            status: status.status === 'completed' ? 'completed' : status.status === 'failed' ? 'failed' : 'rendering',
            error: status.error ?? null,
          })

          if (status.status === 'completed') {
            stopPolling()
            setExporting(false)
            addNotification({ type: 'success', message: 'Export completed' })
            setShowExportDialog(false)
          } else if (status.status === 'failed' || status.status === 'cancelled') {
            stopPolling()
            setExporting(false)
            addNotification({
              type: 'error',
              message: status.error ?? 'Export failed',
            })
          }
        } catch {
          /* retry poll */
        }
      }, 500)
    } catch (err) {
      setExporting(false)
      updateJob(jobId, { status: 'failed', error: String(err) })
      addNotification({ type: 'error', message: String(err) })
    }
  }, [
    addJob,
    addNotification,
    currentProject,
    preset,
    setActiveJob,
    setShowExportDialog,
    stopPolling,
    updateJob,
  ])

  if (!showExportDialog) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-lg border border-axew-border bg-axew-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-axew-border px-4 py-3">
          <h2 className="text-sm font-medium text-axew-text">Export</h2>
          <button
            type="button"
            className="text-axew-textDim hover:text-axew-text"
            onClick={() => !exporting && setShowExportDialog(false)}
          >
            <X size={16} />
          </button>
        </div>
        <div className="space-y-3 p-4">
          <label className="block text-2xs text-axew-textMuted">Preset</label>
          <select
            className="w-full rounded border border-axew-border bg-axew-panel px-2 py-1.5 text-xs text-axew-text"
            value={selectedPresetId}
            onChange={(e) => useExportStore.getState().setSelectedPreset(e.target.value)}
            disabled={exporting}
          >
            {presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.width}×{p.height})
              </option>
            ))}
          </select>
          {exporting && (
            <div className="space-y-1">
              <div className="h-1.5 w-full rounded-full bg-axew-panel">
                <div
                  className="h-full rounded-full bg-axew-accent transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="text-2xs text-axew-textDim">Exporting… {Math.round(progress)}%</p>
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-axew-border px-4 py-3">
          <button
            type="button"
            className="rounded px-3 py-1.5 text-2xs text-axew-textMuted hover:text-axew-text"
            onClick={() => setShowExportDialog(false)}
            disabled={exporting}
          >
            Cancel
          </button>
          <button
            type="button"
            className="flex items-center gap-1.5 rounded bg-axew-accent px-3 py-1.5 text-2xs text-white hover:bg-axew-accentHover disabled:opacity-50"
            onClick={handleExport}
            disabled={exporting || !currentProject}
          >
            {exporting && <Loader2 size={12} className="animate-spin" />}
            Export
          </button>
        </div>
      </div>
    </div>
  )
}
