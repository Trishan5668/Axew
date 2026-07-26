import { useCallback, useEffect, useRef, useState } from 'react'
import { useProjectStore } from '../../stores/projectStore'
import { usePlaybackStore } from '../../stores/playbackStore'
import { useAIStore } from '../../stores/aiStore'
import { useTimelineStore } from '../../stores/timelineStore'
import { useTimelineOpusClipMenu } from '../../hooks/useTimelineOpusClipMenu'
<<<<<<< HEAD
=======
import { useOpusclipStore } from '../../stores/opusclipSlice'
>>>>>>> 1267c0e (v1.1)
import { TimelineRuler } from './TimelineRuler'
import { TimelineToolbar } from './TimelineToolbar'
import { TrackHeader } from './TrackHeader'
import { TrackLane } from './TrackLane'

const TRACK_HEADER_WIDTH = 180

export function Timeline() {
  const { currentProject } = useProjectStore()
  const { zoom, scrollX, scrollY, setScrollX, setScrollY, setZoom, selectedClipIds } =
    useTimelineStore()
  const { highlightRanges } = useAIStore()
  const { currentTime, duration, setCurrentTime, frameRate } = usePlaybackStore()
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)
  const [timelineWidth, setTimelineWidth] = useState(0)

  // IMPORTANT: this hook is called unconditionally, before any early return,
  // so it runs in identical order in dev and in the packaged production EXE.
  // It internally no-ops when cloud features are disabled.
  const opusClipMenu = useTimelineOpusClipMenu()

  const timeline = currentProject?.timeline
  const tracks = timeline?.tracks ?? []
  const totalDuration = Math.max(duration, timeline?.duration ?? 0, 30)
  const totalWidth = totalDuration * zoom

  const handleClipContextMenu = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      opusClipMenu.openMenu(
        { clientX: e.clientX, clientY: e.clientY, preventDefault: () => e.preventDefault() },
        selectedClipIds[0] ?? '',
      )
    },
    [opusClipMenu, selectedClipIds],
  )

  useEffect(() => {
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setTimelineWidth(entry.contentRect.width - TRACK_HEADER_WIDTH)
      }
    })
    if (timelineRef.current) observer.observe(timelineRef.current)
    return () => observer.disconnect()
  }, [])

  const handleRulerClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const rect = e.currentTarget.getBoundingClientRect()
      const x = e.clientX - rect.left + scrollX
      const time = x / zoom
      setCurrentTime(Math.max(0, Math.min(totalDuration, time)))
    },
    [scrollX, zoom, totalDuration, setCurrentTime],
  )

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        const factor = e.deltaY > 0 ? 0.85 : 1.18
        setZoom(zoom * factor)
      } else if (e.shiftKey) {
        e.preventDefault()
        setScrollX(scrollX + e.deltaY)
      } else {
        setScrollY(scrollY + e.deltaY)
      }
    },
    [zoom, scrollX, scrollY, setScrollX, setScrollY, setZoom],
  )

  const handleScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      setScrollX(e.currentTarget.scrollLeft)
    },
    [setScrollX],
  )

  // OpusClip context-menu hooks. These MUST run on every render in a
  // stable order, so they live ABOVE the early `!currentProject` return
  // below. `useTimelineOpusClipMenu` is itself a no-op (returns null) when
  // cloud mode is off, but it always calls the same hooks internally.
  const opusMenu = useTimelineOpusClipMenu()
  const pendingClipsCount = useOpusclipStore((s) => s.pendingClips.length)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null)

  const handleContextMenu = useCallback(
    (e: React.MouseEvent) => {
      if (!opusMenu) return
      e.preventDefault()
      setContextMenu({ x: e.clientX, y: e.clientY })
    },
    [opusMenu],
  )

  useEffect(() => {
    if (!contextMenu) return
    const close = () => setContextMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('blur', close)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('blur', close)
    }
  }, [contextMenu])

  if (!currentProject) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-axew-timeline text-2xs text-axew-textDim">
        No project open — create a project to begin editing
      </div>
    )
  }

  const playheadX = currentTime * zoom - scrollX
  const tracksHeight = tracks.reduce((sum, t) => sum + t.height, 0)

  return (
    <div
      ref={timelineRef}
      className="flex h-full w-full flex-col overflow-hidden bg-axew-timeline"
      onWheel={handleWheel}
      onContextMenu={handleContextMenu}
    >
      <TimelineToolbar />
      <div className="flex flex-1 overflow-hidden">
        <div
          className="flex flex-shrink-0 flex-col overflow-hidden border-r border-axew-border"
          style={{ width: TRACK_HEADER_WIDTH }}
        >
          <div className="h-6 flex-shrink-0 border-b border-axew-border bg-axew-surface" />
          <div className="flex-1 overflow-hidden" style={{ transform: `translateY(-${scrollY}px)` }}>
            {tracks.map((track) => (
              <TrackHeader key={track.id} track={track} />
            ))}
          </div>
        </div>
        <div className="relative flex flex-1 flex-col overflow-hidden">
          <div
            className="relative h-6 flex-shrink-0 cursor-pointer overflow-hidden border-b border-axew-border"
            onClick={handleRulerClick}
          >
            <TimelineRuler
              zoom={zoom}
              scrollX={scrollX}
              duration={totalDuration}
              width={timelineWidth}
              frameRate={frameRate}
            />
            <div
              className="pointer-events-none absolute bottom-0 top-0 z-10 w-px bg-axew-playhead"
              style={{ left: playheadX }}
            />
          </div>
          <div
            ref={scrollContainerRef}
            className="relative flex-1 overflow-x-scroll overflow-y-hidden"
            style={{ scrollbarWidth: 'thin' }}
            onScroll={handleScroll}
            onContextMenu={opusClipMenu.enabled ? handleClipContextMenu : undefined}
          >
            <div
              className="pointer-events-none absolute bottom-0 top-0 z-20 w-px bg-axew-playhead"
              style={{ left: currentTime * zoom }}
            />
            <div
              className="relative"
              style={{
                width: totalWidth + timelineWidth,
                transform: `translateY(-${scrollY}px)`,
              }}
            >
              {highlightRanges.map((range, i) => (
                <div
                  key={`ai-highlight-${i}`}
                  className="pointer-events-none absolute z-[15] border border-axew-ai/50 bg-axew-ai/20"
                  style={{
                    left: range.start * zoom,
                    top: 0,
                    width: Math.max(2, (range.end - range.start) * zoom),
                    height: tracksHeight,
                  }}
                  title={`${range.label} (${Math.round(range.confidence * 100)}%)`}
                />
              ))}
              {tracks.map((track) => (
                <TrackLane key={track.id} track={track} zoom={zoom} scrollX={scrollX} />
              ))}
              {tracks.length === 0 && (
                <div className="flex h-20 items-center justify-center text-2xs text-axew-textDim">
                  Add tracks to start editing
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

<<<<<<< HEAD
      {opusClipMenu.state.open && opusClipMenu.items.length > 0 && (
        <div
          data-testid="opusclip-context-menu"
          className="fixed z-50 min-w-44 rounded border border-axew-border bg-axew-surface py-1 shadow-lg"
          style={{ left: opusClipMenu.state.x, top: opusClipMenu.state.y }}
          onContextMenu={(e) => e.preventDefault()}
        >
          {opusClipMenu.items.map((item) => (
            <button
              key={item.id}
              type="button"
              disabled={item.disabled}
              className="flex w-full items-center px-3 py-1.5 text-left text-2xs text-axew-textMuted hover:bg-axew-panel hover:text-axew-text disabled:opacity-40"
              onClick={() => item.onSelect()}
            >
              {item.label}
            </button>
          ))}
=======
      {pendingClipsCount > 0 && (
        <div
          aria-label="Queued for OpusClip"
          className="pointer-events-none absolute bottom-2 left-[200px] z-30 rounded border border-axew-ai/40 bg-axew-ai/15 px-2 py-0.5 text-2xs text-axew-ai"
        >
          {pendingClipsCount} clip{pendingClipsCount === 1 ? '' : 's'} queued for OpusClip
        </div>
      )}

      {contextMenu && opusMenu && (
        <div
          role="menu"
          className="fixed z-50 min-w-[180px] rounded border border-axew-border bg-axew-surface p-1 text-2xs shadow-lg"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            role="menuitem"
            disabled={!opusMenu.enabled}
            onClick={() => {
              opusMenu.onClick()
              setContextMenu(null)
            }}
            className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-axew-text hover:bg-axew-panel disabled:opacity-40"
          >
            {opusMenu.label}
            {!opusMenu.enabled && (
              <span className="text-2xs text-axew-textDim">
                {useTimelineStore.getState().selectedClipIds.length === 0
                  ? 'Select a clip first'
                  : 'Sign in required'}
              </span>
            )}
          </button>
>>>>>>> 1267c0e (v1.1)
        </div>
      )}
    </div>
  )
}
