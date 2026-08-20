import { useCallback } from 'react'
import { Download, X } from 'lucide-react'
import { downloadProjectFile } from '../../lib/browserProjectStorage'
import { useProjectStore } from '../../stores/projectStore'
import { useUIStore } from '../../stores/uiStore'

export function ExportDialog() {
  const { showExportDialog, setShowExportDialog, addNotification } = useUIStore()
  const { currentProject } = useProjectStore()

  const handleDownload = useCallback(() => {
    if (!currentProject) return
    downloadProjectFile(currentProject)
    addNotification({ type: 'success', message: 'Project downloaded' })
    setShowExportDialog(false)
  }, [addNotification, currentProject, setShowExportDialog])

  if (!showExportDialog) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-lg border border-axew-border bg-axew-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-axew-border px-4 py-3">
          <h2 className="text-sm font-medium text-axew-text">Export Project</h2>
          <button
            type="button"
            className="text-axew-textDim hover:text-axew-text"
            onClick={() => setShowExportDialog(false)}
          >
            <X size={16} />
          </button>
        </div>
        <div className="space-y-2 p-4">
          <p className="text-xs text-axew-textMuted">
            Download the current AXEW project as a portable JSON file. Browser mode keeps
            project data in local storage; downloading creates a backup you can reopen later.
          </p>
          <p className="text-2xs text-axew-textDim">
            Rendered video export will be handled by the backend export service in a future
            deployment step.
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-axew-border px-4 py-3">
          <button
            type="button"
            className="rounded px-3 py-1.5 text-2xs text-axew-textMuted hover:text-axew-text"
            onClick={() => setShowExportDialog(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="flex items-center gap-1.5 rounded bg-axew-accent px-3 py-1.5 text-2xs text-white hover:bg-axew-accentHover disabled:opacity-50"
            onClick={handleDownload}
            disabled={!currentProject}
          >
            <Download size={12} />
            Download
          </button>
        </div>
      </div>
    </div>
  )
}
