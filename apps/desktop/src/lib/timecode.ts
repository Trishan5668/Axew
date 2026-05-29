export function formatTimecode(
  seconds: number,
  frameRate = 30,
  includeFrames = true,
): string {
  const safe = Math.max(0, seconds)
  const h = Math.floor(safe / 3600)
  const m = Math.floor((safe % 3600) / 60)
  const s = Math.floor(safe % 60)
  const f = Math.floor((safe % 1) * frameRate)

  if (!includeFrames) {
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
    }
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}:${f.toString().padStart(2, '0')}`
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}:${f.toString().padStart(2, '0')}`
}
