import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  Film,
  Loader2,
  Music,
  Pause,
  Play,
  RefreshCw,
  Volume2,
} from 'lucide-react'
import { usePreviewMedia } from '../../hooks/usePreviewMedia'
import {
  getActiveAudioClipAtTime,
  getPreviewVideoClip,
} from '../../lib/playbackSync'
import { playbackError as logPlaybackError, playbackLog } from '../../lib/playbackDebug'
import { computeMonitorTransform } from '../../lib/monitorScale'
import type { PreviewFitMode } from '../../lib/previewFit'
import { formatTimecode } from '../../lib/timecode'
import { usePlaybackStore } from '../../stores/playbackStore'
import { useProjectStore } from '../../stores/projectStore'
import { useUIStore } from '../../stores/uiStore'
import { MonitorViewport } from './MonitorViewport'
import { PreviewMonitorOverlay } from './PreviewMonitorOverlay'

const LOAD_TIMEOUT_MS = 15000

export function PreviewPanel() {
  const monitorRootRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const loadTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [showDebug, setShowDebug] = useState(
    () => import.meta.env.DEV && localStorage.getItem('axew-monitor-debug') === '1',
  )
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [sourceSize, setSourceSize] = useState({ width: 1920, height: 1080 })
  const sourceSizeRef = useRef(sourceSize)
  sourceSizeRef.current = sourceSize
  const mediaReadyFiredRef = useRef(false)
  const attachedVideoElRef = useRef<HTMLVideoElement | null>(null)

  const { preview, setPreviewSettings } = useUIStore()
  const { currentProject } = useProjectStore()
  const {
    playing,
    currentTime,
    duration,
    frameRate,
    buffering,
    playbackError,
    togglePlay,
    setVideoRef,
    setAudioRef,
    setPreviewReady,
    setMediaReady,
    setDuration,
    setFrameRate,
    setActiveClip,
    setBuffering,
    setPlaybackError,
    syncMediaToPlayhead,
    setCurrentTime,
    play,
  } = usePlaybackStore()

  const timeline = currentProject?.timeline

  const previewVideoClip = useMemo(() => {
    if (!timeline) return null
    return getPreviewVideoClip(timeline, currentTime)
  }, [timeline, currentTime])

  const activeAudioClip = useMemo(() => {
    if (!timeline) return null
    return getActiveAudioClipAtTime(timeline, currentTime)
  }, [timeline, currentTime])

  const previewClip = previewVideoClip ?? activeAudioClip
  const activeMedia = previewClip ? currentProject?.mediaFiles[previewClip.mediaId] : null

  const previewMode = useMemo(() => {
    if (!activeMedia) return 'empty' as const
    if (activeMedia.type === 'image') return 'image' as const
    if (activeMedia.type === 'video' || activeMedia.type === 'sequence') return 'video' as const
    if (activeMedia.type === 'audio') return 'audio' as const
    return 'empty' as const
  }, [activeMedia])

  const { status: mediaStatus, playbackUrl, error: mediaResolveError, retry } =
    usePreviewMedia(activeMedia)

  useEffect(() => {
    if (activeMedia?.width && activeMedia?.height) {
      const next = { width: activeMedia.width, height: activeMedia.height }
      const prev = sourceSizeRef.current
      if (prev.width !== next.width || prev.height !== next.height) {
        setSourceSize(next)
      }
    }
  }, [activeMedia?.width, activeMedia?.height, activeMedia?.id])

  const displayZoomPercent = useMemo(() => {
    const t = computeMonitorTransform(
      { width: 800, height: 450 },
      sourceSize,
      preview.fitMode,
      preview.zoomPercent,
    )
    return Math.round((t.scale / t.fitScale) * 100) || preview.zoomPercent
  }, [sourceSize, preview.fitMode, preview.zoomPercent])

  const clearLoadTimeout = useCallback(() => {
    if (loadTimeoutRef.current) {
      clearTimeout(loadTimeoutRef.current)
      loadTimeoutRef.current = null
    }
  }, [])

  const startLoadTimeout = useCallback(() => {
    clearLoadTimeout()
    loadTimeoutRef.current = setTimeout(() => {
      setBuffering(false)
      setPlaybackError('Media load timed out — check file path or codec')
      logPlaybackError('load timeout', { url: playbackUrl })
    }, LOAD_TIMEOUT_MS)
  }, [clearLoadTimeout, playbackUrl, setBuffering, setPlaybackError])

  useEffect(() => {
    setActiveClip(previewClip)
    setMediaReady(false)
    setPreviewReady(false)
    setPlaybackError(null)
  }, [previewClip?.id, previewClip?.mediaId, setActiveClip, setMediaReady, setPreviewReady, setPlaybackError])

  const bindVideoRef = useCallback(
    (el: HTMLVideoElement | null) => {
      if (attachedVideoElRef.current === el) return
      attachedVideoElRef.current = el
      ;(videoRef as React.MutableRefObject<HTMLVideoElement | null>).current = el
      setVideoRef(el)
    },
    [setVideoRef],
  )

  useEffect(
    () => () => {
      attachedVideoElRef.current = null
      ;(videoRef as React.MutableRefObject<HTMLVideoElement | null>).current = null
      setVideoRef(null)
    },
    [setVideoRef],
  )

  useEffect(() => {
    const el = audioRef.current
    if (el) setAudioRef(el)
    return () => setAudioRef(null)
  }, [setAudioRef, playbackUrl])

  useEffect(() => {
    if (currentProject) {
      setFrameRate(currentProject.timeline.frameRate)
      setDuration(Math.max(currentProject.timeline.duration, 0.01))
    }
  }, [currentProject, setDuration, setFrameRate])

  useEffect(() => {
    const onFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === monitorRootRef.current)
    }
    document.addEventListener('fullscreenchange', onFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange)
  }, [])

  const handleMediaReady = useCallback(() => {
    if (mediaReadyFiredRef.current) return
    mediaReadyFiredRef.current = true
    clearLoadTimeout()
    setBuffering(false)
    setMediaReady(true)
    setPreviewReady(true)
    setPlaybackError(null)
    syncMediaToPlayhead()
    if (usePlaybackStore.getState().playing) play()
  }, [clearLoadTimeout, play, setBuffering, setMediaReady, setPreviewReady, setPlaybackError, syncMediaToPlayhead])

  const handleVideoError = useCallback(
    (e: React.SyntheticEvent<HTMLVideoElement>) => {
      clearLoadTimeout()
      const el = e.currentTarget
      const code = el.error?.code
      const msg =
        code === 4
          ? 'Unsupported video codec or container'
          : code === 2
            ? 'Network error loading media — file may be inaccessible'
            : `Video error (code ${code ?? 'unknown'})`
      setBuffering(false)
      setMediaReady(false)
      setPreviewReady(false)
      setPlaybackError(msg)
      logPlaybackError('video element error', { code, src: el.src?.slice(0, 120) })
    },
    [clearLoadTimeout, setBuffering, setMediaReady, setPreviewReady, setPlaybackError],
  )

  const onVideoMetadata = useCallback((e: React.SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget
    if (v.videoWidth > 0 && v.videoHeight > 0) {
      const next = { width: v.videoWidth, height: v.videoHeight }
      const prev = sourceSizeRef.current
      if (prev.width !== next.width || prev.height !== next.height) {
        setSourceSize(next)
        playbackLog('source dimensions', next)
      }
    }
  }, [])

  useEffect(() => {
    mediaReadyFiredRef.current = false
  }, [playbackUrl])

  const handleImageLoad = useCallback(
    (w: number, h: number) => {
      const prev = sourceSizeRef.current
      if (prev.width !== w || prev.height !== h) {
        setSourceSize({ width: w, height: h })
      }
      setPreviewReady(true)
      setMediaReady(true)
    },
    [setMediaReady, setPreviewReady],
  )

  const toggleFullscreen = useCallback(async () => {
    const root = monitorRootRef.current
    if (!root) return
    try {
      if (document.fullscreenElement === root) await document.exitFullscreen()
      else await root.requestFullscreen()
    } catch (err) {
      logPlaybackError('fullscreen failed', err)
    }
  }, [])

  const handleFitMode = useCallback(
    (mode: PreviewFitMode) => {
      setPreviewSettings({
        fitMode: mode,
        zoomPercent: mode === '100' ? 100 : preview.zoomPercent,
      })
    },
    [preview.zoomPercent, setPreviewSettings],
  )

  useEffect(() => () => clearLoadTimeout(), [clearLoadTimeout])

  const displayError = playbackError ?? mediaResolveError
  const isLoading =
    (buffering || mediaStatus === 'resolving') && previewMode !== 'empty' && !displayError
  const progress = duration > 0 ? (currentTime / duration) * 100 : 0
  const hasVisualMedia =
    (previewMode === 'video' || previewMode === 'image') &&
    playbackUrl &&
    mediaStatus === 'ready'

  const videoEventHandlers = useMemo(
    () => ({
      onLoadStart: () => {
        setBuffering(true)
        startLoadTimeout()
      },
      onLoadedMetadata: onVideoMetadata,
      onCanPlay: handleMediaReady,
      onWaiting: () => setBuffering(true),
      onPlaying: () => {
        setBuffering(false)
        clearLoadTimeout()
      },
      onEnded: () => usePlaybackStore.getState().pause(),
      onError: handleVideoError,
    }),
    [
      clearLoadTimeout,
      handleMediaReady,
      handleVideoError,
      onVideoMetadata,
      setBuffering,
      startLoadTimeout,
    ],
  )

  return (
    <div
      ref={monitorRootRef}
      className="relative flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden bg-black"
    >
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <PreviewMonitorOverlay
          fitMode={preview.fitMode}
          zoomPercent={preview.zoomPercent}
          displayZoomPercent={displayZoomPercent}
          showSafeArea={preview.showSafeArea}
          isFullscreen={isFullscreen}
          onToggleFitMode={handleFitMode}
          onToggleSafeArea={() =>
            setPreviewSettings({ showSafeArea: !preview.showSafeArea })
          }
          onToggleFullscreen={toggleFullscreen}
        />

        {hasVisualMedia ? (
          <MonitorViewport
            fitMode={preview.fitMode}
            zoomPercent={preview.zoomPercent}
            sourceWidth={sourceSize.width}
            sourceHeight={sourceSize.height}
            showSafeArea={preview.showSafeArea}
            showDebug={showDebug}
            playing={playing}
            onVideoAttachRef={previewMode === 'video' ? bindVideoRef : undefined}
            videoSrc={previewMode === 'video' ? playbackUrl : undefined}
            imageSrc={previewMode === 'image' ? playbackUrl : undefined}
            imageAlt={activeMedia?.name}
            videoProps={previewMode === 'video' ? videoEventHandlers : undefined}
            onImageLoad={handleImageLoad}
          />
        ) : previewMode === 'audio' && playbackUrl && mediaStatus === 'ready' ? (
          <div className="relative min-h-0 min-w-0 flex-1 bg-black">
            <audio
              ref={audioRef}
              src={playbackUrl}
              preload="auto"
              className="hidden"
              onLoadStart={() => {
                setBuffering(true)
                startLoadTimeout()
              }}
              onLoadedMetadata={handleMediaReady}
              onCanPlay={handleMediaReady}
              onError={handleVideoError}
            />
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
              <div className="flex h-20 w-20 items-center justify-center rounded-2xl border border-axew-border bg-axew-panel/80">
                <Music size={32} className="text-axew-accent" />
              </div>
              <p className="text-sm text-axew-textMuted">{activeMedia?.name ?? 'Audio'}</p>
            </div>
          </div>
        ) : (
          <div className="relative min-h-0 min-w-0 flex-1 bg-black">
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
              <div className="flex h-20 w-20 items-center justify-center rounded-2xl border border-axew-border bg-axew-panel/80">
                <Film size={32} className="text-axew-textDim" />
              </div>
              <div className="text-center">
                <p className="text-sm text-axew-textMuted">Preview monitor</p>
                <p className="mt-1 text-2xs text-axew-textDim">
                  {timeline &&
                  previewVideoClip === null &&
                  timeline.tracks.some((t) => t.clips.length > 0)
                    ? 'Move playhead over a clip to preview'
                    : 'Import media and add clips to the timeline'}
                </p>
              </div>
            </div>
          </div>
        )}

        {(displayError || mediaStatus === 'missing' || mediaStatus === 'error') && (
          <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-black/85 p-6">
            <AlertCircle size={32} className="text-red-400" />
            <p className="max-w-sm text-center text-sm text-white/90">
              {displayError ?? 'Media unavailable'}
            </p>
            {activeMedia && (
              <p className="max-w-md truncate text-2xs text-white/50" title={activeMedia.path}>
                {activeMedia.path}
              </p>
            )}
            <button
              type="button"
              className="flex items-center gap-1.5 rounded bg-axew-accent px-3 py-1.5 text-2xs text-white hover:bg-axew-accentHover"
              onClick={retry}
            >
              <RefreshCw size={12} />
              Retry playback
            </button>
          </div>
        )}

        {isLoading && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-black/40">
            <Loader2 size={28} className="animate-spin text-white/70" />
            <span className="text-2xs text-white/50">Loading media…</span>
          </div>
        )}

        {import.meta.env.DEV && (
          <button
            type="button"
            className="absolute bottom-14 right-2 z-40 rounded bg-black/60 px-1.5 py-0.5 text-[9px] text-white/40 hover:text-white/70"
            onClick={() => {
              setShowDebug((d) => {
                const next = !d
                localStorage.setItem('axew-monitor-debug', next ? '1' : '0')
                return next
              })
            }}
          >
            DBG
          </button>
        )}
      </div>

      <div className="relative z-10 flex-shrink-0 bg-gradient-to-t from-black/95 to-black/80 px-3 pb-3 pt-2">
        <div
          className="mb-2 h-1 w-full cursor-pointer rounded-full bg-white/15"
          role="slider"
          aria-valuenow={currentTime}
          aria-valuemin={0}
          aria-valuemax={duration}
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            const ratio = (e.clientX - rect.left) / rect.width
            setCurrentTime(ratio * duration)
          }}
        >
          <div
            className="h-full rounded-full bg-axew-accent transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="text-white/70 transition-colors hover:text-white disabled:opacity-40"
            onClick={togglePlay}
            disabled={!previewClip || mediaStatus !== 'ready'}
          >
            {playing ? <Pause size={15} /> : <Play size={15} />}
          </button>
          <span className="font-mono text-2xs text-white/60">
            {formatTimecode(currentTime, frameRate)}
            <span className="mx-1">/</span>
            {formatTimecode(duration, frameRate)}
          </span>
          {previewClip && (
            <span className="hidden truncate text-2xs text-white/40 sm:inline">
              {previewClip.name}
            </span>
          )}
          <div className="flex-1" />
          {preview.fitMode === '100' && (
            <input
              type="range"
              min={25}
              max={400}
              step={5}
              value={preview.zoomPercent}
              onChange={(e) =>
                setPreviewSettings({ zoomPercent: Number(e.target.value) })
              }
              className="h-1 w-16 accent-axew-accent"
              title="Zoom"
            />
          )}
          <Volume2 size={14} className="text-white/50" />
        </div>
      </div>
    </div>
  )
}
