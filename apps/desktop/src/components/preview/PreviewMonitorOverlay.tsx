import { Grid3x3, Maximize2, Minimize2 } from 'lucide-react'
import type { PreviewFitMode } from '../../lib/previewFit'
import { getFitModeLabel } from '../../lib/previewFit'
import { cn } from '../../lib/cn'

interface PreviewMonitorOverlayProps {
  fitMode: PreviewFitMode
  zoomPercent: number
  displayZoomPercent: number
  showSafeArea: boolean
  isFullscreen: boolean
  onToggleFitMode: (mode: PreviewFitMode) => void
  onToggleSafeArea: () => void
  onToggleFullscreen: () => void
}

const FIT_MODES: PreviewFitMode[] = ['fit', 'fill', '100']

export function PreviewMonitorOverlay({
  fitMode,
  zoomPercent,
  displayZoomPercent,
  showSafeArea,
  isFullscreen,
  onToggleFitMode,
  onToggleSafeArea,
  onToggleFullscreen,
}: PreviewMonitorOverlayProps) {
  const zoomLabel =
    fitMode === '100' ? `${zoomPercent}%` : fitMode === 'fill' ? `~${displayZoomPercent}%` : `${zoomPercent}%`

  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between p-2">
      <div className="pointer-events-auto flex items-center gap-1 rounded-md bg-black/55 px-1 py-0.5 backdrop-blur-sm">
        {FIT_MODES.map((mode) => (
          <button
            key={mode}
            type="button"
            title={`${getFitModeLabel(mode)} view`}
            className={cn(
              'rounded px-2 py-0.5 text-2xs font-medium transition-colors',
              fitMode === mode
                ? 'bg-axew-accent text-white'
                : 'text-white/70 hover:bg-white/10 hover:text-white',
            )}
            onClick={() => onToggleFitMode(mode)}
          >
            {getFitModeLabel(mode)}
          </button>
        ))}
      </div>

      <div className="pointer-events-auto flex items-center gap-1.5">
        <span className="rounded bg-black/55 px-2 py-0.5 font-mono text-2xs text-white/70 backdrop-blur-sm">
          {zoomLabel}
        </span>
        <button
          type="button"
          title="Toggle safe area guides"
          className={cn(
            'rounded p-1 backdrop-blur-sm transition-colors',
            showSafeArea
              ? 'bg-axew-accent/80 text-white'
              : 'bg-black/55 text-white/70 hover:text-white',
          )}
          onClick={onToggleSafeArea}
        >
          <Grid3x3 size={13} />
        </button>
        <button
          type="button"
          title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen preview'}
          className="rounded bg-black/55 p-1 text-white/70 backdrop-blur-sm transition-colors hover:text-white"
          onClick={onToggleFullscreen}
        >
          {isFullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
        </button>
      </div>
    </div>
  )
}
