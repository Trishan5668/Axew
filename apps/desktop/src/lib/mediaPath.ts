import { playbackLog } from './playbackDebug'

const urlCache = new Map<string, string>()

/** Build a browser-playable media URL from an imported object/data/http URL. */
export function toMediaUrl(filePath: string): string {
  if (!filePath) return ''
  if (
    filePath.startsWith('blob:') ||
    filePath.startsWith('data:') ||
    filePath.startsWith('http://') ||
    filePath.startsWith('https://')
  ) {
    return filePath
  }
  playbackLog('toMediaUrl unsupported browser path', { filePath })
  return filePath
}

export async function resolveMediaPlaybackUrl(filePath: string): Promise<{
  url: string | null
  exists: boolean
  error?: string
}> {
  if (!filePath) return { url: null, exists: false, error: 'Empty path' }

  const cached = urlCache.get(filePath)
  if (cached) return { url: cached, exists: true }

  const url = toMediaUrl(filePath)
  urlCache.set(filePath, url)
  return { url, exists: true }
}

export function clearMediaUrlCache(): void {
  urlCache.clear()
}
