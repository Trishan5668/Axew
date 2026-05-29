import { Eye, EyeOff, Film, Lock, Music, Unlock, Volume2, VolumeX } from 'lucide-react'
import type { Track } from '@shared/timeline'
import { cn } from '../../lib/cn'
import { useTimelineStore } from '../../stores/timelineStore'

interface TrackHeaderProps {
  track: Track
}

export function TrackHeader({ track }: TrackHeaderProps) {
  const { updateTrack } = useTimelineStore()
  const isVideo = track.type === 'video'
  const isAudio = track.type === 'audio'

  return (
    <div
      className={cn(
        'flex select-none items-center gap-1.5 border-b border-axew-border bg-axew-surface px-2',
        'transition-colors hover:bg-axew-panel',
      )}
      style={{ height: track.height }}
    >
      <div className="flex-shrink-0 text-axew-textDim">
        {isVideo ? <Film size={11} /> : isAudio ? <Music size={11} /> : null}
      </div>
      <span className="flex-1 truncate text-2xs text-axew-textMuted" title={track.name}>
        {track.name}
      </span>
      <div className="flex flex-shrink-0 items-center gap-0.5">
        {isVideo && (
          <button
            type="button"
            className="rounded p-0.5 text-axew-textDim transition-colors hover:text-axew-text"
            onClick={() => updateTrack(track.id, { visible: !track.visible })}
          >
            {track.visible ? <Eye size={11} /> : <EyeOff size={11} />}
          </button>
        )}
        {isAudio && (
          <button
            type="button"
            className="rounded p-0.5 text-axew-textDim transition-colors hover:text-axew-text"
            onClick={() => updateTrack(track.id, { muted: !track.muted })}
          >
            {track.muted ? <VolumeX size={11} /> : <Volume2 size={11} />}
          </button>
        )}
        <button
          type="button"
          className={cn(
            'rounded p-0.5 transition-colors',
            track.locked ? 'text-axew-accent' : 'text-axew-textDim hover:text-axew-text',
          )}
          onClick={() => updateTrack(track.id, { locked: !track.locked })}
        >
          {track.locked ? <Lock size={11} /> : <Unlock size={11} />}
        </button>
      </div>
    </div>
  )
}
