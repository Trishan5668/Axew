import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, RefreshCw, VolumeX } from 'lucide-react'
import { cn } from '../../lib/cn'
import { useDebugStore, type ExtractionDiagnostics } from '../../stores/debugStore'
import { toMediaUrl } from '../../lib/mediaPath'

interface ClipPlayerProps {
  outputPath: string
  actualStart: number
  actualDuration: number
  extractionResult: ExtractionDiagnostics
  onRetryReencode?: () => void
  className?: string
}

export function ClipPlayer({
  outputPath,
  actualStart,
  actualDuration,
  extractionResult,
  onRetryReencode,
  className,
}: ClipPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playbackError, setPlaybackError] = useState<string | null>(null)

  const validation = extractionResult.validation
  const isPlayable = validation?.is_playable ?? false
  const hasAudio = validation?.has_audio_stream ?? false

  // Store extraction diagnostics for the debug panel
  const setExtractionResult = useDebugStore((s) => s.setExtractionResult)
  useEffect(() => {
    setExtractionResult(extractionResult)
  }, [extractionResult, setExtractionResult])

  const handleVideoError = useCallback((e: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = e.currentTarget
    const err = video.error
    setPlaybackError(
      err ? `Playback error: ${err.message} (code ${err.code})` : 'Unknown playback error'
    )
  }, [])

  // If validation says not playable, render error card instead
  if (!isPlayable) {
    return (
      <ExtractionErrorCard
        extractionResult={extractionResult}
        onRetryReencode={onRetryReencode}
        className={className}
      />
    )
  }

  return (
    <div className={cn('relative rounded overflow-hidden', className)}>
      {/* No audio warning badge */}
      {!hasAudio && (
        <div className="absolute top-1 right-1 z-10 flex items-center gap-0.5 rounded bg-amber-600/90 px-1.5 py-0.5 text-[9px] font-bold text-white">
          <VolumeX size={10} />
          No audio
        </div>
      )}

      {playbackError ? (
        <div className="flex flex-col items-center justify-center p-4 bg-red-950/30 border border-red-500/40 rounded text-center">
          <AlertTriangle size={20} className="text-red-400 mb-1" />
          <p className="text-2xs text-red-300">{playbackError}</p>
          {onRetryReencode && (
            <button
              type="button"
              className="mt-2 flex items-center gap-1 rounded border border-axew-border px-2 py-1 text-2xs hover:border-axew-ai/50"
              onClick={onRetryReencode}
            >
              <RefreshCw size={10} />
              Retry with Re-encode
            </button>
          )}
        </div>
      ) : (
        <video
          ref={videoRef}
          src={toMediaUrl(outputPath)}
          className="w-full h-full object-contain"
          onError={handleVideoError}
          controls
          preload="metadata"
        />
      )}

      {/* Actual timestamp info from extraction result, not requested timestamps */}
      <div className="absolute bottom-0 left-0 right-0 bg-black/60 px-1.5 py-0.5 text-[9px] text-white/70 flex justify-between">
        <span>{actualStart.toFixed(2)}s</span>
        <span>{actualDuration.toFixed(2)}s</span>
      </div>
    </div>
  )
}

function ExtractionErrorCard({
  extractionResult,
  onRetryReencode,
  className,
}: {
  extractionResult: ExtractionDiagnostics
  onRetryReencode?: () => void
  className?: string
}) {
  const [showDetails, setShowDetails] = useState(false)
  const validation = extractionResult.validation
  const warnings = validation?.warnings ?? []

  return (
    <div className={cn(
      'rounded border border-red-500/60 bg-red-950/20 p-3 space-y-2',
      className,
    )}>
      <div className="flex items-center gap-2 text-red-300">
        <AlertTriangle size={16} />
        <span className="text-xs font-medium">Extraction produced unplayable output</span>
      </div>

      {warnings.length > 0 && (
        <ul className="text-2xs text-red-200 space-y-0.5 pl-5 list-disc">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2 text-2xs">
        {validation && (
          <>
            <span className={validation.has_video_stream ? 'text-emerald-300' : 'text-red-300'}>
              video: {validation.has_video_stream ? 'yes' : 'NO'}
            </span>
            <span className={validation.has_audio_stream ? 'text-emerald-300' : 'text-red-300'}>
              audio: {validation.has_audio_stream ? 'yes' : 'NO'}
            </span>
            <span className="text-axew-textMuted">
              dur: {validation.duration_seconds.toFixed(2)}s
            </span>
          </>
        )}
      </div>

      <div className="flex gap-2">
        {onRetryReencode && (
          <button
            type="button"
            className="flex items-center gap-1 rounded border border-emerald-500/40 px-2 py-1 text-2xs text-emerald-300 hover:bg-emerald-500/10"
            onClick={onRetryReencode}
          >
            <RefreshCw size={10} />
            Retry with Re-encode
          </button>
        )}
        <button
          type="button"
          className="text-2xs text-axew-textDim hover:text-axew-text"
          onClick={() => setShowDetails(!showDetails)}
        >
          {showDetails ? 'Hide' : 'Show'} FFmpeg details
        </button>
      </div>

      {showDetails && (
        <div className="space-y-2 border-t border-red-500/20 pt-2">
          {extractionResult.ffmpegCommand && (
            <pre className="rounded bg-axew-panel p-2 text-2xs font-mono text-axew-textMuted overflow-x-auto whitespace-pre-wrap break-all">
              {extractionResult.ffmpegCommand}
            </pre>
          )}
          {extractionResult.ffmpegStderr && (
            <pre className="rounded bg-axew-panel p-2 text-2xs font-mono text-axew-textMuted max-h-32 overflow-y-auto whitespace-pre-wrap">
              {extractionResult.ffmpegStderr.slice(0, 2000)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
