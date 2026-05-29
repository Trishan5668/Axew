import { useCallback } from 'react'
import { Clapperboard, Film, Music, Plus } from 'lucide-react'
import type { MediaFile } from '@shared/media'
import { cn } from '../../lib/cn'
import { getAxew } from '../../lib/axewBridge'
import { toMediaUrl } from '../../lib/mediaPath'
import { getClipTypeIndicator } from '../../lib/mediaValidation'
import { importMediaFiles } from '../../lib/mediaImport'
import { useProjectStore } from '../../stores/projectStore'
import { useUIStore } from '../../stores/uiStore'

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function MediaItem({ media, onDragStart }: { media: MediaFile; onDragStart: (e: React.DragEvent) => void }) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      className="group flex cursor-grab gap-2 rounded border border-axew-border bg-axew-panel p-2 transition-colors hover:border-axew-accent/40 active:cursor-grabbing"
    >
      <div className="flex h-10 w-14 flex-shrink-0 items-center justify-center overflow-hidden rounded bg-axew-surface">
        {media.thumbnail ? (
          <img src={toMediaUrl(media.thumbnail)} alt="" className="h-full w-full object-cover" draggable={false} />
        ) : media.type === 'audio' ? (
          <Music size={16} className="text-axew-textDim" />
        ) : (
          <Film size={16} className="text-axew-textDim" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs text-axew-text">{media.name}</p>
        <p className="text-2xs text-axew-textDim">
          {getClipTypeIndicator(media.type)} · {media.type} · {formatDuration(media.duration)}
        </p>
      </div>
    </div>
  )
}

export function MediaBin() {
  const { currentProject, addMediaFile } = useProjectStore()
  const { isMediaImporting, setIsMediaImporting, addNotification } = useUIStore()

  const mediaList = currentProject ? Object.values(currentProject.mediaFiles) : []

  const handleImport = useCallback(async () => {
    const result = await getAxew().dialog.openFile({
      filters: [
        {
          name: 'Media',
          extensions: ['mp4', 'mov', 'mkv', 'avi', 'webm', 'mp3', 'wav', 'aac', 'jpg', 'png'],
        },
      ],
      properties: ['openFile', 'multiSelections'],
    })
    if (result.canceled || !result.filePaths.length) return

    setIsMediaImporting(true)
    try {
      const existing = currentProject?.mediaFiles ?? {}
      const files = await importMediaFiles(result.filePaths, existing)
      for (const file of files) addMediaFile(file)
      addNotification({
        type: files.length > 0 ? 'success' : 'info',
        message:
          files.length > 0
            ? `Imported ${files.length} file(s)`
            : 'No new files (duplicates skipped)',
      })
    } catch (err) {
      addNotification({ type: 'error', message: String(err) })
    } finally {
      setIsMediaImporting(false)
    }
  }, [addMediaFile, addNotification, setIsMediaImporting])

  const handleDragStart = (media: MediaFile) => (e: React.DragEvent) => {
    e.dataTransfer.setData('application/axew-media', JSON.stringify({ mediaId: media.id }))
    e.dataTransfer.effectAllowed = 'copy'
  }

  return (
    <div className="flex h-full flex-col bg-axew-surface">
      <div className="flex flex-shrink-0 items-center justify-between border-b border-axew-border px-3 py-2">
        <span className="text-xs font-medium uppercase tracking-wider text-axew-textMuted">Media</span>
        <button
          type="button"
          className="rounded p-1 text-axew-textMuted transition-colors hover:bg-axew-panel hover:text-axew-text"
          onClick={handleImport}
          disabled={isMediaImporting || !currentProject}
          title="Import media"
        >
          <Plus size={12} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {!currentProject ? (
          <p className="p-4 text-center text-2xs text-axew-textDim">Open a project to import media</p>
        ) : mediaList.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 p-6">
            <Clapperboard size={28} className="text-axew-textDim" />
            <p className="text-center text-xs text-axew-textMuted">No media imported</p>
            <button
              type="button"
              className="rounded bg-axew-accent px-3 py-1.5 text-2xs text-white hover:bg-axew-accentHover"
              onClick={handleImport}
            >
              Import files
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {mediaList.map((media) => (
              <MediaItem key={media.id} media={media} onDragStart={handleDragStart(media)} />
            ))}
          </div>
        )}
      </div>

      <div className="flex-shrink-0 border-t border-axew-border px-3 py-1.5">
        <span className={cn('text-2xs', isMediaImporting ? 'text-axew-accent' : 'text-axew-textDim')}>
          {isMediaImporting ? 'Importing…' : `${mediaList.length} items`}
        </span>
      </div>
    </div>
  )
}
