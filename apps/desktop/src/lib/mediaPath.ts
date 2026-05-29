import { getAxew, isAxewAvailable } from './axewBridge'
import { playbackLog } from './playbackDebug'

const urlCache = new Map<string, string>()

/** Base64url-encode a local filesystem path for axew-media://play/ URLs */
export function encodePathForMediaUrl(filePath: string): string {
  const utf8 = unescape(encodeURIComponent(filePath))
  return btoa(utf8).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** Build axew-media playback URL (works in Electron renderer) */
export function toMediaUrl(filePath: string): string {
  if (!filePath) return ''
  if (filePath.startsWith('axew-media://') || filePath.startsWith('file://')) {
    return filePath
  }
  const encoded = encodePathForMediaUrl(filePath)
  const url = `axew-media://play/${encoded}`
  playbackLog('toMediaUrl', { filePath, url: url.slice(0, 80) + '…' })
  return url
}

/** Resolve URL via main process (validates file exists). Cached per path. */
export async function resolveMediaPlaybackUrl(filePath: string): Promise<{
  url: string | null
  exists: boolean
  error?: string
}> {
  if (!filePath) return { url: null, exists: false, error: 'Empty path' }

  const cached = urlCache.get(filePath)
  if (cached) return { url: cached, exists: true }

  if (isAxewAvailable() && getAxew().media) {
    try {
      const result = await getAxew().media.resolvePlaybackUrl(filePath)
      if (result.exists && result.url) {
        urlCache.set(filePath, result.url)
        playbackLog('resolveMediaPlaybackUrl IPC', { filePath, ok: true })
        return { url: result.url, exists: true }
      }
      playbackLog('resolveMediaPlaybackUrl IPC miss', { filePath, error: result.error })
      return { url: null, exists: false, error: result.error ?? 'File not found' }
    } catch (err) {
      playbackLog('resolveMediaPlaybackUrl IPC error', err)
    }
  }

  const url = toMediaUrl(filePath)
  return { url, exists: true }
}

export function clearMediaUrlCache(): void {
  urlCache.clear()
}
