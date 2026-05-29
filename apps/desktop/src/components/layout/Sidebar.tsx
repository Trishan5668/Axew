import { motion } from 'framer-motion'
import {
  Clapperboard,
  FolderOpen,
  Image,
  Layers,
  Music,
  Plus,
  Search,
  Sparkles,
} from 'lucide-react'
import { cn } from '../../lib/cn'

const navItems = [
  { id: 'media', label: 'Media', icon: FolderOpen, active: true },
  { id: 'effects', label: 'Effects', icon: Sparkles, active: false },
  { id: 'audio', label: 'Audio', icon: Music, active: false },
  { id: 'graphics', label: 'Graphics', icon: Image, active: false },
  { id: 'sequences', label: 'Sequences', icon: Layers, active: false },
]

export function Sidebar() {
  return (
    <div className="flex h-full flex-col bg-axew-surface">
      <div className="flex flex-shrink-0 items-center justify-between border-b border-axew-border px-3 py-2">
        <span className="text-xs font-medium uppercase tracking-wider text-axew-textMuted">
          Project
        </span>
        <button
          type="button"
          className="rounded p-1 text-axew-textMuted transition-colors hover:bg-axew-panel hover:text-axew-text"
          title="Import media"
        >
          <Plus size={12} />
        </button>
      </div>

      <div className="flex flex-shrink-0 gap-0.5 border-b border-axew-border px-2 py-1.5">
        {navItems.map(({ id, label, icon: Icon, active }) => (
          <button
            key={id}
            type="button"
            className={cn(
              'flex flex-1 flex-col items-center gap-0.5 rounded px-1 py-1.5 text-2xs transition-colors',
              active
                ? 'bg-axew-accentSubtle text-axew-accent'
                : 'text-axew-textDim hover:bg-axew-panel hover:text-axew-textMuted',
            )}
          >
            <Icon size={12} />
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className="flex-shrink-0 border-b border-axew-border px-2 py-1.5">
        <div className="flex items-center gap-1.5 rounded bg-axew-panel px-2 py-1">
          <Search size={10} className="flex-shrink-0 text-axew-textDim" />
          <input
            type="text"
            placeholder="Search media..."
            className="flex-1 bg-transparent text-2xs text-axew-text outline-none placeholder:text-axew-textDim"
          />
        </div>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-4">
        <motion.div
          animate={{ opacity: [0.5, 0.85, 0.5] }}
          transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
          className="flex h-14 w-14 items-center justify-center rounded-xl border-2 border-dashed border-axew-border"
        >
          <Clapperboard size={22} className="text-axew-textDim" />
        </motion.div>
        <div className="text-center">
          <p className="text-xs text-axew-textMuted">No media imported</p>
          <p className="mt-0.5 text-2xs text-axew-textDim">Drag files here or click +</p>
        </div>
      </div>

      <div className="flex-shrink-0 border-t border-axew-border px-3 py-1.5">
        <span className="text-2xs text-axew-textDim">0 items</span>
      </div>
    </div>
  )
}
