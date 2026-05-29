import { motion } from 'framer-motion'
import { Layers, Plus } from 'lucide-react'

const MOCK_TRACKS = [
  { name: 'V1', type: 'video', color: '#1e3a5f' },
  { name: 'V2', type: 'video', color: '#1e3a5f' },
  { name: 'A1', type: 'audio', color: '#1e4f3a' },
  { name: 'A2', type: 'audio', color: '#1e4f3a' },
]

export function TimelinePlaceholder() {
  return (
    <div className="flex h-full flex-col bg-axew-timeline">
      <div className="flex h-7 flex-shrink-0 items-center justify-between border-b border-axew-border px-3">
        <span className="text-xs font-medium uppercase tracking-wider text-axew-textMuted">
          Timeline
        </span>
        <button
          type="button"
          className="flex items-center gap-1 rounded px-2 py-0.5 text-2xs text-axew-textMuted transition-colors hover:bg-axew-panel hover:text-axew-text"
        >
          <Plus size={10} />
          Add track
        </button>
      </div>

      <div className="relative flex flex-1 overflow-hidden">
        <div className="flex w-[180px] flex-shrink-0 flex-col border-r border-axew-border">
          {MOCK_TRACKS.map((track) => (
            <div
              key={track.name}
              className="flex h-[52px] flex-shrink-0 items-center gap-2 border-b border-axew-border/50 px-2"
            >
              <div
                className="h-3 w-1 rounded-full"
                style={{ backgroundColor: track.color }}
              />
              <span className="font-mono text-2xs text-axew-textMuted">{track.name}</span>
            </div>
          ))}
        </div>

        <div className="relative flex-1 overflow-hidden">
          <div
            className="absolute inset-0 opacity-30"
            style={{
              backgroundImage:
                'repeating-linear-gradient(90deg, #22222a 0px, #22222a 1px, transparent 1px, transparent 80px)',
            }}
          />

          {MOCK_TRACKS.map((track, i) => (
            <div
              key={track.name}
              className="relative h-[52px] flex-shrink-0 border-b border-axew-border/30"
            >
              {i === 0 && (
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: '35%' }}
                  transition={{ duration: 0.6, ease: 'easeOut' }}
                  className="absolute left-[8%] top-2 h-[calc(100%-16px)] rounded border border-axew-accent/40 bg-axew-accent/20"
                  style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.5)' }}
                />
              )}
            </div>
          ))}

          <div
            className="absolute bottom-0 top-0 z-10 w-px bg-axew-playhead"
            style={{ left: '28%' }}
          >
            <div className="absolute -left-1.5 -top-0 h-2 w-3 bg-axew-playhead" style={{ clipPath: 'polygon(50% 100%, 0 0, 100% 0)' }} />
          </div>
        </div>
      </div>

      <div className="flex h-6 flex-shrink-0 items-center justify-center gap-1.5 border-t border-axew-border text-2xs text-axew-textDim">
        <Layers size={10} />
        <span>Timeline engine — Phase 2</span>
      </div>
    </div>
  )
}
