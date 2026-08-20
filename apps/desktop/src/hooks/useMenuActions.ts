import { useCallback, useEffect } from 'react'
import { pickMediaFiles } from '../lib/browserFilePicker'
import { pickProjectFile } from '../lib/browserProjectStorage'
import { useProjectStore } from '../stores/projectStore'
import { useUIStore } from '../stores/uiStore'

export function useMenuActions() {
  const { currentProject, createProject, openProject, saveProject, addMediaFile } =
    useProjectStore()
  const { setShowWelcome, setShowExportDialog, setIsMediaImporting, addNotification } =
    useUIStore()

  const handleNewProject = useCallback(() => {
    createProject('Untitled Project')
    setShowWelcome(false)
  }, [createProject, setShowWelcome])

  const handleOpenProject = useCallback(async () => {
    const project = await pickProjectFile()
    if (!project) return
    openProject(project)
    setShowWelcome(false)
    addNotification({ type: 'success', message: 'Project opened' })
  }, [addNotification, openProject, setShowWelcome])

  const handleSaveProject = useCallback(async () => {
    if (!currentProject) return
    await saveProject()
    addNotification({ type: 'success', message: 'Project saved in this browser' })
  }, [currentProject, saveProject, addNotification])

  const handleImportMedia = useCallback(async () => {
    setIsMediaImporting(true)
    try {
      const existing = currentProject?.mediaFiles ?? {}
      const files = await pickMediaFiles(existing)
      for (const file of files) addMediaFile(file)
      addNotification({
        type: files.length > 0 ? 'success' : 'info',
        message:
          files.length > 0
            ? `Imported ${files.length} file(s)`
            : 'No new files imported',
      })
    } catch (err) {
      addNotification({ type: 'error', message: String(err) })
    } finally {
      setIsMediaImporting(false)
    }
  }, [addMediaFile, addNotification, currentProject, setIsMediaImporting])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return
      }
      if (!event.ctrlKey && !event.metaKey) return

      const key = event.key.toLowerCase()
      if (key === 'n') {
        event.preventDefault()
        handleNewProject()
      } else if (key === 'o') {
        event.preventDefault()
        void handleOpenProject()
      } else if (key === 's') {
        event.preventDefault()
        void handleSaveProject()
      } else if (key === 'i') {
        event.preventDefault()
        void handleImportMedia()
      } else if (key === 'e') {
        event.preventDefault()
        setShowExportDialog(true)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [
    handleImportMedia,
    handleNewProject,
    handleOpenProject,
    handleSaveProject,
    setShowExportDialog,
  ])
}
