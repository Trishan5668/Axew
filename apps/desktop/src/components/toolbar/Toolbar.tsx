import { motion } from 'framer-motion'
import {
  ChevronLeft,
  ChevronRight,
  Hand,
  Magnet,
  MousePointer2,
  Pause,
  Play,
  Redo2,
  Scissors,
  Sparkles,
  Square,
  Undo2,
  Upload,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { cn } from '../../lib/cn'
import { getAxew } from '../../lib/axewBridge'
import { importMediaFiles } from '../../lib/mediaImport'
import { usePlaybackStore } from '../../stores/playbackStore'
import { useProjectStore } from '../../stores/projectStore'
import { useTimelineStore } from '../../stores/timelineStore'
import { useUIStore } from '../../stores/uiStore'

const tools = [
  { id: 'select' as const, icon: MousePointer2, label: 'Select', shortcut: 'V' },
  { id: 'blade' as const, icon: Scissors, label: 'Blade', shortcut: 'B' },
  { id: 'hand' as const, icon: Hand, label: 'Hand', shortcut: 'H' },
]

export function Toolbar() {
  const { playing, togglePlay, stop, nextFrame, previousFrame } = usePlaybackStore()
  const { activeTool, setActiveTool, togglePanel, layout, addNotification, setIsMediaImporting } =
    useUIStore()
  const { zoom, setZoom, snapEnabled, toggleSnap, undo, redo, undoStack, redoStack } =
    useTimelineStore()

  const { addMediaFile } = useProjectStore()

  const handleImport = async () => {
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
      const files = await importMediaFiles(result.filePaths)
      for (const f of files) addMediaFile(f)
      addNotification({ type: 'success', message: `Imported ${files.length} file(s)` })
    } finally {
      setIsMediaImporting(false)
    }
  }

  return (
    <div className="flex h-10 flex-shrink-0 select-none items-center gap-1 border-b border-axew-border bg-axew-surface px-3">
      <div className="mr-2 flex items-center gap-0.5 rounded bg-axew-panel px-1 py-0.5">
        {tools.map(({ id, icon: Icon, label, shortcut }) => (
          <ToolButton
            key={id}
            active={activeTool === id}
            onClick={() => setActiveTool(id)}
            title={`${label} (${shortcut})`}
          >
            <Icon size={14} />
          </ToolButton>
        ))}
      </div>

      <Divider />

      <ToolButton title="Undo" onClick={undo} disabled={undoStack.length === 0}>
        <Undo2 size={14} />
      </ToolButton>
      <ToolButton title="Redo" onClick={redo} disabled={redoStack.length === 0}>
        <Redo2 size={14} />
      </ToolButton>

      <Divider />

      <ToolButton title="Previous frame" onClick={previousFrame}>
        <ChevronLeft size={14} />
      </ToolButton>
      <ToolButton title="Stop" onClick={stop}>
        <Square size={13} />
      </ToolButton>
      <motion.button
        type="button"
        whileTap={{ scale: 0.92 }}
        className={cn(
          'flex h-7 w-7 items-center justify-center rounded transition-colors',
          playing
            ? 'bg-axew-accent text-white hover:bg-axew-accentHover'
            : 'bg-axew-panel text-axew-text hover:bg-axew-borderLight',
        )}
        onClick={togglePlay}
        title="Play / Pause (Space)"
      >
        {playing ? <Pause size={13} /> : <Play size={13} />}
      </motion.button>
      <ToolButton title="Next frame" onClick={nextFrame}>
        <ChevronRight size={14} />
      </ToolButton>

      <Divider />

      <ToolButton title="Snap" active={snapEnabled} onClick={toggleSnap}>
        <Magnet size={14} />
      </ToolButton>
      <ToolButton title="Zoom out" onClick={() => setZoom(zoom * 0.85)}>
        <ZoomOut size={14} />
      </ToolButton>
      <span className="min-w-[52px] px-1 text-center font-mono text-2xs text-axew-textMuted">
        {Math.round(zoom)}px/s
      </span>
      <ToolButton title="Zoom in" onClick={() => setZoom(zoom * 1.18)}>
        <ZoomIn size={14} />
      </ToolButton>

      <div className="flex-1" />

      <ToolButton title="Import media (Ctrl+I)" onClick={handleImport}>
        <Upload size={14} />
      </ToolButton>
      <ToolButton
        title="AI Engine"
        active={layout.aiPanelOpen}
        onClick={() => togglePanel('ai')}
      >
        <Sparkles size={14} />
      </ToolButton>
    </div>
  )
}

function ToolButton({
  children,
  active = false,
  disabled = false,
  onClick,
  title,
}: {
  children: React.ReactNode
  active?: boolean
  disabled?: boolean
  onClick?: () => void
  title?: string
}) {
  return (
    <motion.button
      type="button"
      whileTap={!disabled ? { scale: 0.92 } : undefined}
      className={cn(
        'flex h-7 w-7 items-center justify-center rounded transition-colors',
        active && 'bg-axew-accentSubtle text-axew-accent',
        !active && !disabled && 'text-axew-textMuted hover:bg-axew-panel hover:text-axew-text',
        disabled && 'cursor-not-allowed text-axew-textDim opacity-50',
      )}
      onClick={!disabled ? onClick : undefined}
      title={title}
      disabled={disabled}
    >
      {children}
    </motion.button>
  )
}

function Divider() {
  return <div className="mx-1 h-4 w-px flex-shrink-0 bg-axew-border" />
}
