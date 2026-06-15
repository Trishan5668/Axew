import type { AIEditAction, SilenceRegion } from '@shared/ai'
import type { Clip } from '@shared/timeline'
import { detectScenes, detectSilence, transcribeMedia } from './aiClient'
import { useAIStore } from '../stores/aiStore'
import { usePlaybackStore } from '../stores/playbackStore'
import { useProjectStore } from '../stores/projectStore'
import { useTimelineStore } from '../stores/timelineStore'
import { useUIStore } from '../stores/uiStore'

function findClipsForMedia(mediaId: string): { trackId: string; clip: Clip }[] {
  const project = useProjectStore.getState().currentProject
  if (!project) return []
  const found: { trackId: string; clip: Clip }[] = []
  for (const track of project.timeline.tracks) {
    for (const clip of track.clips) {
      if (clip.mediaId === mediaId) found.push({ trackId: track.id, clip })
    }
  }
  return found
}

export async function applyAIAction(action: AIEditAction): Promise<void> {
  const project = useProjectStore.getState().currentProject
  if (!project) return

  const { addClip, deleteClip, addMarker, splitClip, pushUndoSnapshot } =
    useTimelineStore.getState()
  const { addNotification } = useUIStore.getState()
  const isPreviewOnly = action.type === 'highlight-segment'
  if (!isPreviewOnly) {
    pushUndoSnapshot(`AI: ${action.type}`)
  }

  switch (action.type) {
    case 'cut-silence': {
      const mediaId = action.params.mediaId as string | undefined
      const media = mediaId ? project.mediaFiles[mediaId] : Object.values(project.mediaFiles)[0]
      if (!media) break

      const silences: SilenceRegion[] = await detectSilence(
        media.path,
        project.settings.ai.silenceThresholdDb,
      )

      const videoTrack = project.timeline.tracks.find((t) => t.type === 'video')
      if (!videoTrack) break

      let offset = 0
      for (const region of silences) {
        const clipStart = region.end - offset
        if (clipStart < media.duration - region.end) {
          addClip(videoTrack.id, {
            mediaId: media.id,
            name: media.name,
            startTime: clipStart,
            duration: media.duration - region.end - offset,
            mediaInPoint: region.end,
            mediaOutPoint: media.duration,
            speed: 1,
            opacity: 1,
            volume: 1,
            disabled: false,
            color: null,
            effects: [],
            transitions: { in: null, out: null },
            keyframes: [],
          }, { recordUndo: false })
        }
        offset += region.duration
      }

      addNotification({ type: 'success', message: `Removed ${silences.length} silent regions` })
      break
    }

    case 'detect-scenes': {
      const media = Object.values(project.mediaFiles).find((m) => m.type === 'video')
      if (!media) break
      const result = await detectScenes(media.path, project.settings.ai.sceneDetectionSensitivity)
      for (const scene of result.scenes ?? []) {
        addMarker({
          time: scene.time,
          duration: 0,
          name: `Scene ${scene.time.toFixed(1)}s`,
          color: '#A855F7',
          type: 'ai',
          notes: '',
        })
      }
      addNotification({ type: 'success', message: `Added ${result.count ?? 0} scene markers` })
      break
    }

    case 'add-subtitle': {
      const media = Object.values(project.mediaFiles).find((m) => m.type === 'video')
      if (!media) break
      const result = await transcribeMedia(media.path)
      const subTrack = project.timeline.tracks.find((t) => t.type === 'subtitle')
      if (subTrack) {
        for (const seg of result.segments ?? []) {
          addClip(subTrack.id, {
            mediaId: media.id,
            name: seg.text.slice(0, 32),
            startTime: seg.start,
            duration: seg.end - seg.start,
            mediaInPoint: seg.start,
            mediaOutPoint: seg.end,
            speed: 1,
            opacity: 1,
            volume: 1,
            disabled: false,
            color: '#4F1E3A',
            effects: [],
            transitions: { in: null, out: null },
            keyframes: [],
          }, { recordUndo: false })
        }
      }
      addNotification({ type: 'success', message: 'Transcript added to timeline' })
      break
    }

    case 'split-clip': {
      const clipId = action.clipIds?.[0] ?? action.params.clipId
      const time = action.params.time as number | undefined
      if (typeof clipId === 'string' && typeof time === 'number') {
        splitClip(clipId, time)
      }
      break
    }

    case 'delete-clip': {
      for (const clipId of action.clipIds ?? []) {
        deleteClip(clipId)
      }
      break
    }

    case 'add-marker': {
      const markerTime =
        (action.params.time as number) ?? (action.params.start as number) ?? 0
      addMarker({
        time: markerTime,
        duration: 0,
        name: (action.params.name as string) ?? 'AI Marker',
        color: '#22C55E',
        type: 'ai',
        notes: (action.params.matchText as string) ?? action.description,
      })
      break
    }

    case 'keep-segment':
    case 'isolate-segment':
    case 'extract-clip': {
      const mediaId = (action.params.mediaId as string) ?? undefined
      const media = mediaId
        ? project.mediaFiles[mediaId]
        : Object.values(project.mediaFiles).find((m) => m.type === 'video')
      if (!media) break

      const segStart = action.params.start as number
      const segEnd = action.params.end as number
      if (typeof segStart !== 'number' || typeof segEnd !== 'number' || segEnd <= segStart) break

      const grade =
        action.confidence >= 0.7 ? 'HIGH' : action.confidence >= 0.4 ? 'MEDIUM' : 'LOW'

      const segmentDuration = segEnd - segStart
      const videoTrack = project.timeline.tracks.find((t) => t.type === 'video')
      const audioTrack = project.timeline.tracks.find((t) => t.type === 'audio')
      if (!videoTrack) break

      const mediaClips = findClipsForMedia(media.id)
      for (const { clip } of mediaClips) {
        deleteClip(clip.id)
      }

      const clipTemplate = mediaClips[0]?.clip
      addClip(
        videoTrack.id,
        {
          mediaId: media.id,
          name: (action.params.name as string) ?? `Extract ${segStart.toFixed(1)}s`,
          startTime: 0,
          duration: segmentDuration,
          mediaInPoint: segStart,
          mediaOutPoint: segEnd,
          speed: clipTemplate?.speed ?? 1,
          opacity: clipTemplate?.opacity ?? 1,
          volume: clipTemplate?.volume ?? 1,
          disabled: false,
          color: '#5B5BFF',
          effects: [],
          transitions: { in: null, out: null },
          keyframes: [],
          aiConfidence: action.confidence,
          aiConfidenceGrade: grade,
        },
        { recordUndo: false },
      )

      if (audioTrack) {
        const audioClips = audioTrack.clips.filter((c) => c.mediaId === media.id)
        for (const clip of audioClips) {
          deleteClip(clip.id)
        }
        addClip(
          audioTrack.id,
          {
            mediaId: media.id,
            name: media.name,
            startTime: 0,
            duration: segmentDuration,
            mediaInPoint: segStart,
            mediaOutPoint: segEnd,
            speed: 1,
            opacity: 1,
            volume: 1,
            disabled: false,
            color: null,
            effects: [],
            transitions: { in: null, out: null },
            keyframes: [],
          },
          { recordUndo: false },
        )
      }

      useTimelineStore.getState().syncTimelineDuration()
      useAIStore.getState().setHighlightRanges([
        {
          start: 0,
          end: segmentDuration,
          confidence: action.confidence,
          label: (action.params.matchText as string) ?? action.description,
        },
      ])
      usePlaybackStore.getState().setCurrentTime(0, { syncVideo: true })
      usePlaybackStore.getState().setLoopPoints(0, segmentDuration)
      usePlaybackStore.getState().setLoop(true)

      addMarker({
        time: 0,
        duration: segmentDuration,
        name: 'AI Extract',
        color: '#22C55E',
        type: 'ai',
        notes: (action.params.matchText as string) ?? '',
      })
      addMarker({
        time: segmentDuration,
        duration: 0,
        name: 'Extract end',
        color: '#22C55E',
        type: 'ai',
        notes: '',
      })

      addNotification({
        type: 'success',
        message: `Kept segment ${segStart.toFixed(1)}s–${segEnd.toFixed(1)}s (${Math.round(action.confidence * 100)}% match)`,
      })
      useAIStore.getState().setSuggestedAction(null)
      break
    }

    case 'highlight-segment': {
      const segStart = action.params.start as number
      const segEnd = action.params.end as number
      if (typeof segStart !== 'number' || typeof segEnd !== 'number' || segEnd <= segStart) break

      useAIStore.getState().setHighlightRanges([
        {
          start: segStart,
          end: segEnd,
          confidence: action.confidence,
          label:
            (action.params.matchText as string)
            ?? (action.params.reasoning as string)
            ?? action.description,
        },
      ])
      addNotification({
        type: 'info',
        message: 'Candidate extraction highlighted. Review and confirm to apply it to the timeline.',
      })
      break
    }

    default:
      addNotification({ type: 'info', message: `Action "${action.type}" queued for review` })
  }
}

export async function applyPromptToTimeline(prompt: string): Promise<void> {
  const { executePromptPipeline } = await import('./actionExecutionEngine')
  useAIStore.getState().setIsThinking(true)
  try {
    await executePromptPipeline(prompt)
  } finally {
    useAIStore.getState().setIsThinking(false)
  }
}

export async function confirmSuggestedAction(): Promise<void> {
  const suggested = useAIStore.getState().suggestedAction
  if (!suggested) return
  await applyAIAction({
    ...suggested,
    type: 'keep-segment',
    params: {
      ...suggested.params,
      name: (suggested.params.name as string) ?? 'Confirmed Extract',
    },
  })
}

export { getActiveVideoClipAtTime, getActiveAudioClipAtTime } from './playbackSync'
