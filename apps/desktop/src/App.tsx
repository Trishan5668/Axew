import { AnimatePresence } from 'framer-motion'
import { useEffect } from 'react'
import { MainLayout } from './components/layout/MainLayout'
import { NotificationStack } from './components/ui/NotificationStack'
import { WelcomeScreen } from './components/welcome/WelcomeScreen'
import { useAIServiceCheck } from './hooks/useAIServiceCheck'
import { ExportDialog } from './components/panels/ExportDialog'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { useMenuActions } from './hooks/useMenuActions'
import { usePlaybackLoop } from './hooks/usePlaybackLoop'
import { useProjectStore } from './stores/projectStore'
import { useUIStore } from './stores/uiStore'

export default function App() {
  const { showWelcome, setShowWelcome } = useUIStore()
  const { currentProject } = useProjectStore()

  useMenuActions()
  usePlaybackLoop()
  useKeyboardShortcuts()
  useAIServiceCheck()

  useEffect(() => {
    if (currentProject && showWelcome) {
      setShowWelcome(false)
    }
  }, [currentProject, showWelcome, setShowWelcome])

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-axew-bg text-axew-text">
      <MainLayout />
      <AnimatePresence>{showWelcome && <WelcomeScreen />}</AnimatePresence>
      <NotificationStack />
      <ExportDialog />
    </div>
  )
}
