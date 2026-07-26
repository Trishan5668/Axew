import { useCallback, useRef, useState } from 'react'
import { AIPanel } from '../panels/AIPanel'
import { MediaBin } from '../panels/MediaBin'
import { PreviewPanel } from '../preview/PreviewPanel'
import { Timeline } from '../timeline/Timeline'
import { Toolbar } from '../toolbar/Toolbar'
import { StatusBar } from './StatusBar'
import { TitleBar } from './TitleBar'
import { RetrievalDebugPanel } from '../RetrievalDebugPanel'
import { OpusClipPanel } from '../OpusClipPanel'
import { isCloudAvailable } from '../../lib/supabase'
import { useUIStore } from '../../stores/uiStore'
import { useAIStore } from '../../stores/aiStore'

export function MainLayout() {
  const { layout, setLayout } = useUIStore()
  const debugPanelOpen = useAIStore((s) => s.debugPanelOpen)
  const containerRef = useRef<HTMLDivElement>(null)
  const [isResizingLeft, setIsResizingLeft] = useState(false)
  const [isResizingTimeline, setIsResizingTimeline] = useState(false)
  const [isResizingRight, setIsResizingRight] = useState(false)

  const handleLeftResize = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      setIsResizingLeft(true)
      const startX = e.clientX
      const startWidth = layout.leftWidth

      const onMove = (me: MouseEvent) => {
        const delta = me.clientX - startX
        setLayout({ leftWidth: Math.max(200, Math.min(420, startWidth + delta)) })
      }

      const onUp = () => {
        setIsResizingLeft(false)
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }

      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [layout.leftWidth, setLayout],
  )

  const handleRightResize = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      setIsResizingRight(true)
      const startX = e.clientX
      const startWidth = layout.rightWidth

      const onMove = (me: MouseEvent) => {
        const delta = startX - me.clientX
        setLayout({ rightWidth: Math.max(220, Math.min(480, startWidth + delta)) })
      }

      const onUp = () => {
        setIsResizingRight(false)
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }

      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [layout.rightWidth, setLayout],
  )

  const handleTimelineResize = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      setIsResizingTimeline(true)
      const startY = e.clientY
      const startHeight = layout.timelineHeight

      const onMove = (me: MouseEvent) => {
        const delta = startY - me.clientY
        setLayout({ timelineHeight: Math.max(180, Math.min(500, startHeight + delta)) })
      }

      const onUp = () => {
        setIsResizingTimeline(false)
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }

      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [layout.timelineHeight, setLayout],
  )

  const resizeCursor = isResizingLeft
    ? 'col-resize'
    : isResizingTimeline
      ? 'row-resize'
      : isResizingRight
        ? 'col-resize'
        : undefined

  return (
    <div ref={containerRef} className="flex h-full w-full flex-col overflow-hidden">
      <TitleBar />
      <Toolbar />

      <div className="flex flex-1 overflow-hidden" style={{ cursor: resizeCursor }}>
        <div
          className="flex flex-shrink-0 flex-col overflow-hidden border-r border-axew-border"
          style={{ width: layout.leftWidth }}
        >
          <MediaBin />
        </div>

        <div className="resize-handle-x z-10 flex-shrink-0" onMouseDown={handleLeftResize} />

        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <div className="min-h-0 flex-1 overflow-hidden">
            <PreviewPanel />
          </div>

          <div
            className="resize-handle-y z-10 flex-shrink-0 border-t border-axew-border"
            onMouseDown={handleTimelineResize}
          />

          <div
            className="relative flex-shrink-0 overflow-hidden border-t border-axew-border"
            style={{ height: layout.timelineHeight }}
          >
            <Timeline />
            {debugPanelOpen && <RetrievalDebugPanel />}
          </div>
        </div>

        {layout.aiPanelOpen && (
          <>
            <div className="resize-handle-x z-10 flex-shrink-0" onMouseDown={handleRightResize} />
            <div
              className="flex flex-shrink-0 flex-col overflow-hidden border-l border-axew-border"
              style={{ width: layout.rightWidth }}
            >
              <div className="min-h-0 flex-1 overflow-hidden">
                <AIPanel />
              </div>
              {isCloudAvailable() && (
                <div className="min-h-[200px] flex-shrink-0 overflow-hidden">
                  <OpusClipPanel />
                </div>
              )}
            </div>
          </>
        )}
      </div>

      <StatusBar />
    </div>
  )
}
