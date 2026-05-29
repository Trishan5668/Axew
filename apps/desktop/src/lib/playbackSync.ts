import type { Clip, Timeline } from '@shared/timeline'

function effectiveSpeed(clip: Clip): number {
  return Number.isFinite(clip.speed) && clip.speed > 0 ? clip.speed : 1
}

/** Convert timeline playhead time to source media time for a clip. */
export function timelineToSourceTime(clip: Clip, timelineTime: number): number {
  const offset = Math.max(0, timelineTime - clip.startTime)
  return clip.mediaInPoint + offset * effectiveSpeed(clip)
}

/** Convert source media time back to timeline playhead time. */
export function sourceToTimelineTime(clip: Clip, sourceTime: number): number {
  return clip.startTime + (sourceTime - clip.mediaInPoint) / effectiveSpeed(clip)
}

export function isTimeInClip(clip: Clip, timelineTime: number): boolean {
  return timelineTime >= clip.startTime && timelineTime < clip.startTime + clip.duration
}

/** Topmost visible video track clip at playhead (first matching track in stack order). */
export function getActiveVideoClipAtTime(timeline: Timeline, time: number): Clip | null {
  for (const track of timeline.tracks) {
    if (track.type !== 'video' || !track.visible) continue
    for (const clip of track.clips) {
      if (!clip.disabled && isTimeInClip(clip, time)) return clip
    }
  }
  return null
}

/** Clip to show in preview: active at playhead, or first visible video clip on timeline. */
export function getPreviewVideoClip(timeline: Timeline, time: number): Clip | null {
  const active = getActiveVideoClipAtTime(timeline, time)
  if (active) return active
  for (const track of timeline.tracks) {
    if (track.type !== 'video' || !track.visible) continue
    const sorted = [...track.clips].filter((c) => !c.disabled).sort((a, b) => a.startTime - b.startTime)
    if (sorted.length > 0) return sorted[0]
  }
  return null
}

/** First audible audio clip at playhead. */
export function getActiveAudioClipAtTime(timeline: Timeline, time: number): Clip | null {
  for (const track of timeline.tracks) {
    if (track.type !== 'audio' || !track.visible || track.muted) continue
    for (const clip of track.clips) {
      if (isTimeInClip(clip, time)) return clip
    }
  }
  return null
}
