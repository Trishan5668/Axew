import { useCallback, useState } from 'react'

import type { Track } from '@shared/timeline'

import { snapTime } from '../../lib/timelineIntelligence'

import { validateMediaDrop } from '../../lib/mediaValidation'

import { defaultClipDuration } from '../../lib/mediaTypeDetection'

import { cn } from '../../lib/cn'

import { useProjectStore } from '../../stores/projectStore'

import { useTimelineStore } from '../../stores/timelineStore'

import { useUIStore } from '../../stores/uiStore'

import { ClipItem } from './ClipItem'



interface TrackLaneProps {

  track: Track

  zoom: number

  scrollX: number

}



export function TrackLane({ track, zoom, scrollX }: TrackLaneProps) {

  const { addClip, moveClip, snapEnabled } = useTimelineStore()

  const { currentProject } = useProjectStore()

  const { addNotification } = useUIStore()

  const [dropState, setDropState] = useState<'none' | 'valid' | 'invalid'>('none')



  const timeFromEvent = useCallback(

    (e: React.DragEvent<HTMLDivElement>) => {

      const rect = e.currentTarget.getBoundingClientRect()

      const x = e.clientX - rect.left + scrollX

      let startTime = x / zoom

      const fps = currentProject?.timeline.frameRate ?? 30

      if (snapEnabled) {

        startTime = snapTime(startTime, fps, true)

      }

      return Math.max(0, startTime)

    },

    [currentProject, scrollX, snapEnabled, zoom],

  )



  const handleDragOver = useCallback(

    (e: React.DragEvent<HTMLDivElement>) => {

      e.preventDefault()

      const mediaData = e.dataTransfer.getData('application/axew-media')

      const clipData = e.dataTransfer.types.includes('application/axew-clip')



      if (mediaData) {

        try {

          const { mediaId } = JSON.parse(mediaData) as { mediaId: string }

          const media = currentProject?.mediaFiles[mediaId]

          if (!media) {

            setDropState('invalid')

            e.dataTransfer.dropEffect = 'none'

            return

          }

          const validation = validateMediaDrop(media, track.type)

          if (validation.valid) {

            setDropState('valid')

            e.dataTransfer.dropEffect = 'copy'

          } else {

            setDropState('invalid')

            e.dataTransfer.dropEffect = 'none'

          }

        } catch {

          setDropState('invalid')

          e.dataTransfer.dropEffect = 'none'

        }

      } else if (clipData) {

        setDropState('valid')

        e.dataTransfer.dropEffect = 'move'

      } else {

        setDropState('none')

      }

    },

    [currentProject, track.type],

  )



  const handleDragLeave = useCallback(() => {

    setDropState('none')

  }, [])



  const handleDrop = useCallback(

    (e: React.DragEvent<HTMLDivElement>) => {

      e.preventDefault()

      setDropState('none')



      const clipPayload = e.dataTransfer.getData('application/axew-clip')

      if (clipPayload) {

        try {

          const { clipId } = JSON.parse(clipPayload) as { clipId: string }

          const startTime = timeFromEvent(e)

          moveClip(clipId, track.id, startTime)

        } catch {

          /* ignore */

        }

        return

      }



      const mediaPayload = e.dataTransfer.getData('application/axew-media')

      if (!mediaPayload) return



      try {

        const { mediaId } = JSON.parse(mediaPayload) as { mediaId: string }

        const media = currentProject?.mediaFiles[mediaId]

        if (!media) return



        const validation = validateMediaDrop(media, track.type)

        if (!validation.valid) {

          addNotification({ type: 'error', message: validation.reason })

          return

        }



        const startTime = timeFromEvent(e)

        const clipDuration = defaultClipDuration(media.type, media.duration)



        addClip(track.id, {

          mediaId,

          name: media.name,

          startTime,

          duration: clipDuration,

          mediaInPoint: 0,

          mediaOutPoint: media.duration > 0 ? media.duration : clipDuration,

          speed: 1,

          opacity: 1,

          volume: 1,

          disabled: false,

          color: null,

          effects: [],

          transitions: { in: null, out: null },

          keyframes: [],

        })

      } catch {

        /* ignore */

      }

    },

    [addClip, addNotification, currentProject, moveClip, timeFromEvent, track.id, track.type],

  )



  return (

    <div

      className={cn(

        'relative overflow-hidden border-b border-axew-border select-none transition-colors',

        track.locked && 'pointer-events-none opacity-60',

        !track.visible && 'opacity-30',

        track.type === 'video' ? 'bg-axew-timeline' : 'bg-[#0C0C10]',

        dropState === 'valid' && 'bg-axew-accent/10 ring-1 ring-inset ring-axew-accent/40',

        dropState === 'invalid' && 'bg-red-950/30 ring-1 ring-inset ring-red-500/50 cursor-no-drop',

      )}

      style={{ height: track.height }}

      onDragOver={handleDragOver}

      onDragLeave={handleDragLeave}

      onDrop={handleDrop}

    >

      <div

        className="absolute inset-0 opacity-10"

        style={{

          backgroundImage: `repeating-linear-gradient(90deg, transparent, transparent ${zoom - 1}px, #444 ${zoom}px)`,

          backgroundSize: `${zoom}px 100%`,

          backgroundPositionX: -scrollX % zoom,

        }}

      />

      {track.clips.map((clip) => (

        <ClipItem key={clip.id} clip={clip} track={track} zoom={zoom} scrollX={scrollX} />

      ))}

    </div>

  )

}

