import { AnimatePresence } from 'framer-motion'
import { useEffect } from 'react'
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import { NotificationStack } from './components/ui/NotificationStack'
import { WelcomeScreen } from './components/welcome/WelcomeScreen'
import { useAIServiceCheck } from './hooks/useAIServiceCheck'
import { ExportDialog } from './components/panels/ExportDialog'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { useMenuActions } from './hooks/useMenuActions'
import { usePlaybackLoop } from './hooks/usePlaybackLoop'
import { useProjectStore } from './stores/projectStore'
import { useUIStore } from './stores/uiStore'
import { BillingPage } from './pages/BillingPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { SignupPage } from './pages/SignupPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { FirstRunWizard } from './pages/FirstRunWizard'
import { RequireAuth } from './components/RequireAuth'
import { useAuthStore } from './stores/authSlice'

function GlobalHooks(): null {
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

  return null
}

function CloudShell(): JSX.Element {
  const showWelcome = useUIStore((s) => s.showWelcome)
  return (
    <HashRouter>
      <GlobalHooks />
      <div className="flex h-full w-full flex-col overflow-hidden bg-axew-bg text-axew-text">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/first-run" element={<FirstRunWizard />} />
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <DashboardPage />
              </RequireAuth>
            }
          />
          <Route
            path="/dashboard/billing"
            element={
              <RequireAuth>
                <BillingPage />
              </RequireAuth>
            }
          />
          <Route
            path="/"
            element={
              <RequireAuth>
                <DashboardPage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
        <NotificationStack />
        <ExportDialog />
        <AnimatePresence>{showWelcome && <WelcomeScreen />}</AnimatePresence>
      </div>
    </HashRouter>
  )
}

export default function App(): JSX.Element {
  const initializeAuth = useAuthStore((s) => s.initialize)
  useEffect(() => {
    initializeAuth().catch(() => undefined)
  }, [initializeAuth])

  return <CloudShell />
}
