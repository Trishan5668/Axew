import type { Clip, Timeline } from '@shared/timeline'

export function snapTime(time: number, frameRate: number, enabled: boolean): number {
  if (!enabled) return Math.max(0, time)
  return Math.round(time * frameRate) / frameRate
}

export function computeTimelineDuration(timeline: Timeline): number {
  let maxEnd = timeline.duration
  for (const track of timeline.tracks) {
    for (const clip of track.clips) {
      maxEnd = Math.max(maxEnd, clip.startTime + clip.duration)
    }
  }
  return maxEnd
}

export function findClipGaps(clips: Clip[]): { start: number; end: number; duration: number }[] {
  const sorted = [...clips].sort((a, b) => a.startTime - b.startTime)
  const gaps: { start: number; end: number; duration: number }[] = []
  let cursor = 0

  for (const clip of sorted) {
    if (clip.startTime > cursor) {
      gaps.push({
        start: cursor,
        end: clip.startTime,
        duration: clip.startTime - cursor,
      })
    }
    cursor = Math.max(cursor, clip.startTime + clip.duration)
  }

  return gaps
}

export function detectOverlaps(clips: Clip[]): [string, string][] {
  const overlaps: [string, string][] = []
  const sorted = [...clips].sort((a, b) => a.startTime - b.startTime)

  for (let i = 0; i < sorted.length; i++) {
    for (let j = i + 1; j < sorted.length; j++) {
      const a = sorted[i]
      const b = sorted[j]
      if (b.startTime < a.startTime + a.duration) {
        overlaps.push([a.id, b.id])
      } else {
        break
      }
    }
  }

  return overlaps
}

export function suggestRippleShift(clips: Clip[], deletedDuration: number, fromTime: number): Clip[] {
  return clips.map((clip) =>
    clip.startTime >= fromTime
      ? { ...clip, startTime: Math.max(0, clip.startTime - deletedDuration) }
      : clip,
  )
}

/** Resolve start time to avoid overlapping existing clips on the same track. */
export function resolveNonOverlappingStart(
  clips: Clip[],
  startTime: number,
  duration: number,
  excludeClipId?: string,
): number {
  let t = Math.max(0, startTime)
  const others = clips
    .filter((c) => c.id !== excludeClipId)
    .sort((a, b) => a.startTime - b.startTime)

  let changed = true
  while (changed) {
    changed = false
    for (const other of others) {
      const otherEnd = other.startTime + other.duration
      if (t < otherEnd && t + duration > other.startTime) {
        t = otherEnd
        changed = true
      }
    }
  }
  return t
}

export function clipWouldOverlap(
  clips: Clip[],
  startTime: number,
  duration: number,
  excludeClipId?: string,
): boolean {
  return resolveNonOverlappingStart(clips, startTime, duration, excludeClipId) !== startTime
}
