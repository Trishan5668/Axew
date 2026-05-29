import { useCallback, useEffect } from 'react'
import { getAxew, isAxewAvailable } from '../lib/axewBridge'
import { importMediaFiles } from '../lib/mediaImport'
import { useProjectStore } from '../stores/projectStore'
import { useUIStore } from '../stores/uiStore'

export function useMenuActions() {
  const { currentProject, createProject, loadProject, saveProject, addMediaFile } =
    useProjectStore()
  const { setShowWelcome, setShowExportDialog, setIsMediaImporting, addNotification } =
    useUIStore()

  const handleNewProject = useCallback(() => {
    createProject('Untitled Project')
    setShowWelcome(false)
  }, [createProject, setShowWelcome])

  const handleOpenProject = useCallback(async () => {
    const result = await getAxew().dialog.openFile({
      filters: [{ name: 'AXEW Project', extensions: ['axew', 'json'] }],
      properties: ['openFile'],
    })
    if (!result.canceled && result.filePaths[0]) {
      await loadProject(result.filePaths[0])
      setShowWelcome(false)
    }
  }, [loadProject, setShowWelcome])

  const handleSaveProject = useCallback(async () => {
    if (!currentProject) return
    if (currentProject.path.endsWith('.axew')) {
      await saveProject()
      addNotification({ type: 'success', message: 'Project saved' })
      return
    }
    const result = await getAxew().dialog.saveFile({
      filters: [{ name: 'AXEW Project', extensions: ['axew'] }],
      defaultPath: currentProject.path,
    })
    if (!result.canceled && result.filePath) {
      useProjectStore.setState((state) => {
        if (state.currentProject) {
          state.currentProject.path = result.filePath!
          state.isDirty = true
        }
      })
      await saveProject()
      addNotification({ type: 'success', message: 'Project saved' })
    }
  }, [currentProject, saveProject, addNotification])

  const handleImportMedia = useCallback(async () => {
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
      for (const file of files) {
        addMediaFile(file)
      }
      const skipped = result.filePaths.length - files.length
      addNotification({
        type: files.length > 0 ? 'success' : 'info',
        message:
          files.length > 0
            ? `Imported ${files.length} file(s)${skipped > 0 ? ` (${skipped} duplicate(s) skipped)` : ''}`
            : 'No new files imported (duplicates skipped)',
      })
    } catch (err) {
      addNotification({ type: 'error', message: String(err) })
    } finally {
      setIsMediaImporting(false)
    }
  }, [addMediaFile, addNotification, currentProject, setIsMediaImporting])

  useEffect(() => {
    if (!isAxewAvailable()) return

    const axew = getAxew()
    const handlers: [string, () => void][] = [
      ['new-project', handleNewProject],
      ['open-project', handleOpenProject],
      ['save-project', handleSaveProject],
      ['import-media', handleImportMedia],
      ['export', () => setShowExportDialog(true)],
    ]

    for (const [event, handler] of handlers) {
      axew.menu.on(event, handler)
    }

    return () => {
      for (const [event, handler] of handlers) {
        axew.menu.off(event, handler)
      }
    }
  }, [
    handleNewProject,
    handleOpenProject,
    handleSaveProject,
    handleImportMedia,
    setShowExportDialog,
  ])
}
