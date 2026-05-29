import { Zap } from 'lucide-react'
import { useProjectStore } from '../../stores/projectStore'

export function TitleBar() {
  const isMac = navigator.platform.toLowerCase().includes('mac')
  const { currentProject, isDirty } = useProjectStore()

  return (
    <div
      className="drag-region flex h-9 flex-shrink-0 select-none items-center border-b border-axew-border bg-axew-bg px-3"
      style={{ paddingLeft: isMac ? '80px' : '12px' }}
    >
      <div className="no-drag mr-4 flex items-center gap-1.5">
        <Zap size={14} className="text-axew-accent" />
        <span className="text-xs font-semibold uppercase tracking-widest text-axew-text">
          AXEW
        </span>
      </div>

      <div className="flex flex-1 items-center justify-center">
        <span className="text-xs text-axew-textMuted">
          {currentProject?.name ?? 'No Project'}
          {isDirty ? ' •' : ''}
        </span>
      </div>

      {!isMac && (
        <div className="no-drag flex items-center gap-1">
          <span className="font-mono text-2xs text-axew-textDim">v0.1.0</span>
        </div>
      )}
    </div>
  )
}
