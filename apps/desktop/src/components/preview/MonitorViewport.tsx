import { useCallback, useMemo, type CSSProperties, type ReactNode } from 'react'
import { useElementSize } from '../../hooks/useElementSize'
import {
  computeMonitorTransform,
  formatMonitorDebug,
  type PreviewFitMode,
} from '../../lib/monitorScale'
import { MonitorVideo } from './MonitorVideo'

export interface MonitorViewportProps {
  fitMode: PreviewFitMode
  zoomPercent: number
  sourceWidth: number
  sourceHeight: number
  showSafeArea: boolean
  showDebug: boolean
  playing: boolean
  onVideoAttachRef?: (el: HTMLVideoElement | null) => void
  imageSrc?: string
  videoSrc?: string
  videoProps?: React.VideoHTMLAttributes<HTMLVideoElement>
  imageAlt?: string
  onImageLoad?: (width: number, height: number) => void
}

function SafeAreaGuides({ width, height }: { width: number; height: number }) {
  return (
    <div
      className="pointer-events-none absolute z-10"
      style={{ left: 0, top: 0, width, height }}
    >
      <div
        className="absolute border border-yellow-400/40"
        style={{ left: '10%', top: '10%', right: '10%', bottom: '10%' }}
      />
      <div
        className="absolute border border-cyan-400/30"
        style={{ left: '5%', top: '5%', right: '5%', bottom: '5%' }}
      />
    </div>
  )
}

function MonitorDebugOverlay({ lines }: { lines: string[] }) {
  return (
    <div className="pointer-events-none absolute bottom-2 left-2 z-30 max-w-[320px] rounded bg-black/85 p-2 font-mono text-[9px] leading-relaxed text-green-400">
      {lines.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  )
}

export function MonitorViewport({
  fitMode,
  zoomPercent,
  sourceWidth,
  sourceHeight,
  showSafeArea,
  showDebug,
  playing,
  onVideoAttachRef,
  imageSrc,
  videoSrc,
  videoProps,
  imageAlt,
  onImageLoad,
}: MonitorViewportProps) {
  const { ref: viewportRef, size: viewportSize } = useElementSize()

  const source = useMemo(
    () => ({
      width: Math.max(1, sourceWidth),
      height: Math.max(1, sourceHeight),
    }),
    [sourceWidth, sourceHeight],
  )

  const transform = useMemo(
    () => computeMonitorTransform(viewportSize, source, fitMode, zoomPercent),
    [viewportSize, source, fitMode, zoomPercent],
  )

  const debugLines = useMemo(
    () => formatMonitorDebug(fitMode, viewportSize, source, transform, playing),
    [fitMode, viewportSize, source, transform, playing],
  )

  const mediaStyle: CSSProperties = useMemo(
    () =>
      transform.useFallback
        ? {
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'contain',
            objectPosition: 'center',
            display: 'block',
          }
        : {
            position: 'absolute',
            left: transform.offsetX,
            top: transform.offsetY,
            width: transform.width,
            height: transform.height,
            maxWidth: 'none',
            maxHeight: 'none',
            objectFit: 'fill',
            objectPosition: 'center',
            display: 'block',
          },
    [transform],
  )

  const handleImageLoad = useCallback(
    (e: React.SyntheticEvent<HTMLImageElement>) => {
      const img = e.currentTarget
      if (img.naturalWidth > 0 && img.naturalHeight > 0) {
        onImageLoad?.(img.naturalWidth, img.naturalHeight)
      }
    },
    [onImageLoad],
  )

  const renderMedia = (): ReactNode => {
    if (videoSrc) {
      return (
        <MonitorVideo
          src={videoSrc}
          style={mediaStyle}
          onAttachRef={onVideoAttachRef}
          videoProps={videoProps}
        />
      )
    }
    if (imageSrc) {
      return (
        <img
          src={imageSrc}
          alt={imageAlt ?? ''}
          style={mediaStyle}
          draggable={false}
          onLoad={handleImageLoad}
        />
      )
    }
    return null
  }

  const stage = (
    <>
      {renderMedia()}
      {showSafeArea && !transform.useFallback && transform.width > 0 && (
        <div
          className="pointer-events-none absolute"
          style={{
            left: transform.offsetX,
            top: transform.offsetY,
            width: transform.width,
            height: transform.height,
          }}
        >
          <SafeAreaGuides width={transform.width} height={transform.height} />
        </div>
      )}
    </>
  )

  return (
    <div
      ref={viewportRef}
      className="relative min-h-0 min-w-0 flex-1 bg-black"
      data-monitor-viewport
    >
      {transform.scrollable ? (
        <div className="absolute inset-0 overflow-auto">
          <div
            className="relative bg-black"
            style={{
              width: transform.scrollWidth,
              height: transform.scrollHeight,
              minWidth: '100%',
              minHeight: '100%',
            }}
          >
            {stage}
          </div>
        </div>
      ) : (
        <div className="absolute inset-0 overflow-hidden">{stage}</div>
      )}
      {showDebug && <MonitorDebugOverlay lines={debugLines} />}
    </div>
  )
}
