import { useCallback, useEffect, useState } from 'react'
import type { MediaFile } from '@shared/media'
import { resolveMediaPlaybackUrl } from '../lib/mediaPath'
import { playbackLog, playbackWarn } from '../lib/playbackDebug'

export type PreviewMediaStatus =
  | 'idle'
  | 'resolving'
  | 'ready'
  | 'error'
  | 'missing'

export interface PreviewMediaState {
  status: PreviewMediaStatus
  playbackUrl: string | null
  error: string | null
}

export function usePreviewMedia(media: MediaFile | null | undefined): PreviewMediaState & {
  retry: () => void
} {
  const [retryKey, setRetryKey] = useState(0)
  const [state, setState] = useState<PreviewMediaState>({
    status: 'idle',
    playbackUrl: null,
    error: null,
  })

  const retry = useCallback(() => setRetryKey((k) => k + 1), [])

  useEffect(() => {
    if (!media?.path) {
      setState({ status: 'idle', playbackUrl: null, error: null })
      return
    }

    let cancelled = false
    setState({ status: 'resolving', playbackUrl: null, error: null })

    resolveMediaPlaybackUrl(media.path).then((result) => {
      if (cancelled) return
      if (result.url && result.exists) {
        playbackLog('usePreviewMedia ready', { name: media.name })
        setState({ status: 'ready', playbackUrl: result.url, error: null })
      } else {
        playbackWarn('usePreviewMedia failed', { path: media.path, error: result.error })
        setState({
          status: result.error?.toLowerCase().includes('not found') ? 'missing' : 'error',
          playbackUrl: null,
          error: result.error ?? 'Could not resolve media URL',
        })
      }
    })

    return () => {
      cancelled = true
    }
  }, [media?.path, media?.id, media?.name, retryKey])

  return { ...state, retry }
}
