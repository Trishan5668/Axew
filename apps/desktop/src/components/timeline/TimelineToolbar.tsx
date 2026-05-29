import { Film, Music, Plus, Trash2, Type } from 'lucide-react'
import type { TrackType } from '@shared/timeline'
import { useTimelineStore } from '../../stores/timelineStore'

export function TimelineToolbar() {
  const { addTrack, deleteClip, selectedClipIds } = useTimelineStore()

  const handleAddTrack = (type: TrackType) => addTrack(type)

  const handleDeleteSelected = () => {
    for (const id of selectedClipIds) {
      deleteClip(id)
    }
  }

  return (
    <div className="flex h-7 flex-shrink-0 items-center gap-1 border-b border-axew-border bg-axew-surface px-2">
      <span className="mr-1 text-2xs uppercase tracking-wider text-axew-textDim">Tracks</span>
      <button
        type="button"
        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-axew-textMuted transition-colors hover:bg-axew-panel hover:text-axew-text"
        onClick={() => handleAddTrack('video')}
      >
        <Plus size={10} />
        <Film size={9} />
        <span>Video</span>
      </button>
      <button
        type="button"
        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-axew-textMuted transition-colors hover:bg-axew-panel hover:text-axew-text"
        onClick={() => handleAddTrack('audio')}
      >
        <Plus size={10} />
        <Music size={9} />
        <span>Audio</span>
      </button>
      <button
        type="button"
        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-axew-textMuted transition-colors hover:bg-axew-panel hover:text-axew-text"
        onClick={() => handleAddTrack('subtitle')}
      >
        <Plus size={10} />
        <Type size={9} />
        <span>Sub</span>
      </button>
      <div className="flex-1" />
      {selectedClipIds.length > 0 && (
        <button
          type="button"
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-axew-error transition-colors hover:bg-red-950 hover:text-red-400"
          onClick={handleDeleteSelected}
        >
          <Trash2 size={10} />
          <span>Delete ({selectedClipIds.length})</span>
        </button>
      )}
    </div>
  )
}
