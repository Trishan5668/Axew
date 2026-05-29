import { useCallback, useRef, useState } from 'react'
import type { Clip, Track } from '@shared/timeline'
import { cn } from '../../lib/cn'
import { getClipTypeIndicator } from '../../lib/mediaValidation'
import { toMediaUrl } from '../../lib/mediaPath'
import { useProjectStore } from '../../stores/projectStore'
import { useTimelineStore } from '../../stores/timelineStore'

interface ClipItemProps {
  clip: Clip
  track: Track
  zoom: number
  scrollX: number
}

const HANDLE_WIDTH = 6

export function ClipItem({ clip, track, zoom, scrollX }: ClipItemProps) {
  const { selectedClipIds, selectClip, trimClipIn, trimClipOut, splitClip, deleteClip } =
    useTimelineStore()
  const { currentProject } = useProjectStore()
  const isSelected = selectedClipIds.includes(clip.id)
  const [isDragging, setIsDragging] = useState(false)
  const [isTrimming, setIsTrimming] = useState<'in' | 'out' | null>(null)
  const dragStartRef = useRef({ x: 0, startTime: 0 })

  const left = clip.startTime * zoom
  const width = clip.duration * zoom
  const visibleLeft = left - scrollX
  const media = currentProject?.mediaFiles[clip.mediaId]

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      selectClip(clip.id, e.metaKey || e.ctrlKey)
    },
    [clip.id, selectClip],
  )

  const handleDragStart = useCallback(
    (e: React.DragEvent) => {
      e.stopPropagation()
      setIsDragging(true)
      dragStartRef.current = { x: e.clientX, startTime: clip.startTime }
      e.dataTransfer.setData(
        'application/axew-clip',
        JSON.stringify({ clipId: clip.id, trackId: track.id, startTime: clip.startTime }),
      )
      e.dataTransfer.effectAllowed = 'move'
    },
    [clip.id, clip.startTime, track.id],
  )

  const handleTrimMouseDown = useCallback(
    (e: React.MouseEvent, side: 'in' | 'out') => {
      e.stopPropagation()
      e.preventDefault()
      setIsTrimming(side)
      useTimelineStore.getState().pushUndoSnapshot('Trim clip')
      let lastX = e.clientX

      const onMove = (me: MouseEvent) => {
        const delta = (me.clientX - lastX) / zoom
        lastX = me.clientX
        if (side === 'in') trimClipIn(clip.id, delta)
        else trimClipOut(clip.id, delta)
      }

      const onUp = () => {
        setIsTrimming(null)
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }

      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [clip.id, zoom, trimClipIn, trimClipOut],
  )

  const handleDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      const rect = e.currentTarget.getBoundingClientRect()
      const x = e.clientX - rect.left
      splitClip(clip.id, clip.startTime + x / zoom)
    },
    [clip.id, clip.startTime, zoom, splitClip],
  )

  if (visibleLeft + width < -50 || visibleLeft > 3000) return null

  const aiGrade = clip.aiConfidenceGrade
  const gradeStyles =
    aiGrade === 'HIGH'
      ? 'border-emerald-500/60'
      : aiGrade === 'MEDIUM'
        ? 'border-amber-500/60'
        : aiGrade === 'LOW'
          ? 'border-red-500/60'
          : ''

  return (
    <div
      className={cn(
        'group absolute bottom-1 top-1 cursor-pointer overflow-hidden rounded border clip-shadow',
        isSelected
          ? 'z-10 border-axew-accent ring-1 ring-axew-accent/50'
          : cn('border-axew-clipBorder hover:border-axew-accent/50', gradeStyles),
        isDragging && 'opacity-60',
        track.type === 'video' ? 'bg-axew-clip' : 'bg-[#1A3A2F]',
      )}
      style={{ left: visibleLeft, width: Math.max(4, width) }}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      draggable
      onDragStart={handleDragStart}
      onDragEnd={() => setIsDragging(false)}
      tabIndex={0}
      onKeyDown={(e) => {
        if (isSelected && (e.key === 'Delete' || e.key === 'Backspace')) {
          e.preventDefault()
          deleteClip(clip.id)
        }
      }}
    >
      {track.type === 'video' && media?.thumbnail && (
        <div className="absolute inset-0 opacity-30">
          <img
            src={toMediaUrl(media.thumbnail)}
            alt=""
            className="h-full w-full object-cover object-left"
            draggable={false}
          />
        </div>
      )}
      <div className="absolute inset-x-0 top-0 flex items-center gap-1 px-1.5 pt-0.5">
        {media && (
          <span className="flex-shrink-0 rounded bg-black/50 px-0.5 text-[9px] font-bold text-white/70">
            {getClipTypeIndicator(media.type)}
          </span>
        )}
        <span className="truncate text-2xs font-medium leading-tight text-white/80 drop-shadow">
          {clip.name}
        </span>
        {aiGrade && clip.aiConfidence != null && (
          <span
            className={cn(
              'ml-auto flex-shrink-0 rounded px-1 text-[9px] font-bold',
              aiGrade === 'HIGH' && 'bg-emerald-600/80 text-white',
              aiGrade === 'MEDIUM' && 'bg-amber-600/80 text-white',
              aiGrade === 'LOW' && 'bg-red-600/80 text-white',
            )}
            title={`AI confidence ${Math.round(clip.aiConfidence * 100)}%`}
          >
            {aiGrade}
          </span>
        )}
      </div>
      <div
        className={cn(
          'absolute bottom-0 left-0 top-0 z-20 cursor-col-resize bg-white/20 opacity-0 hover:bg-axew-accent/60 group-hover:opacity-100',
          isTrimming === 'in' && 'opacity-100',
        )}
        style={{ width: HANDLE_WIDTH }}
        onMouseDown={(e) => handleTrimMouseDown(e, 'in')}
      />
      <div
        className={cn(
          'absolute bottom-0 right-0 top-0 z-20 cursor-col-resize bg-white/20 opacity-0 hover:bg-axew-accent/60 group-hover:opacity-100',
          isTrimming === 'out' && 'opacity-100',
        )}
        style={{ width: HANDLE_WIDTH }}
        onMouseDown={(e) => handleTrimMouseDown(e, 'out')}
      />
    </div>
  )
}
