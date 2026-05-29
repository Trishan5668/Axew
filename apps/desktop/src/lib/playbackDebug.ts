const DEBUG =
  import.meta.env.DEV &&
  (import.meta.env.VITE_DEBUG_PLAYBACK === 'true' ||
    (typeof localStorage !== 'undefined' && localStorage.getItem('axew-debug-playback') === '1'))

export function playbackLog(message: string, data?: unknown): void {
  if (!DEBUG) return
  if (data !== undefined) {
    console.log(`[AXEW Playback] ${message}`, data)
  } else {
    console.log(`[AXEW Playback] ${message}`)
  }
}

export function playbackWarn(message: string, data?: unknown): void {
  console.warn(`[AXEW Playback] ${message}`, data ?? '')
}

export function playbackError(message: string, data?: unknown): void {
  console.error(`[AXEW Playback] ${message}`, data ?? '')
}
