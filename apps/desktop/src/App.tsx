import { AnimatePresence } from 'framer-motion'
import { useEffect } from 'react'
import {
  HashRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom'
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
import { CLOUD_ENABLED } from './lib/cloudFlag'
import { BillingPage } from './pages/BillingPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { OAuthCallbackPage } from './pages/OAuthCallbackPage'
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

function FirstRunRedirect(): JSX.Element | null {
  // If the renderer was launched into Electron and no Whisper model exists yet,
  // route the user through the wizard exactly once. Detection lives in the
  // electron main process; here we just listen for the IPC ready signal.
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    if (typeof window === 'undefined') return
    const axew = (window as unknown as {
      axew?: { ipc?: { on?: (channel: string, cb: (...args: unknown[]) => void) => () => void } }
    }).axew
    if (!axew?.ipc?.on) return
    const off = axew.ipc.on('app:first-run-required', () => {
      if (location.pathname !== '/first-run') navigate('/first-run', { replace: true })
    })
    return () => {
      try { off?.() } catch { /* noop */ }
    }
  }, [navigate, location.pathname])

  return null
}

/**
 * Routes the user to /auth/callback as soon as the OS hands us an
 * `axew://auth/callback?code=…` deep link, regardless of which page they
 * happen to be on (usually /login).
 */
function OAuthDeepLinkRouter(): JSX.Element | null {
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    if (typeof window === 'undefined') return
    const axew = (window as unknown as {
      axew?: { ipc?: { on?: (channel: string, cb: (...args: unknown[]) => void) => () => void } }
    }).axew
    if (!axew?.ipc?.on) return
    const off = axew.ipc.on('oauth:deep-link', (...args: unknown[]) => {
      const url = args[args.length - 1]
      if (typeof url !== 'string') return
      // OAuthCallbackPage subscribes to the same IPC event; we just need to
      // make sure the user is ON that page so it can run the exchange.
      if (location.pathname !== '/auth/callback') {
        navigate('/auth/callback', { replace: true })
      }
      // Stash the URL on window so the page can read it synchronously after
      // mount (covers the race between IPC arriving and the page mounting).
      ;(window as unknown as { __axewPendingOAuthUrl?: string }).__axewPendingOAuthUrl = url
    })
    return () => {
      try { off?.() } catch { /* noop */ }
    }
  }, [navigate, location.pathname])

  return null
}

function CloudShell(): JSX.Element {
  const showWelcome = useUIStore((s) => s.showWelcome)
  return (
    <HashRouter>
      <FirstRunRedirect />
      <OAuthDeepLinkRouter />
      <GlobalHooks />
      <div className="flex h-full w-full flex-col overflow-hidden bg-axew-bg text-axew-text">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<OAuthCallbackPage />} />
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
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
        <NotificationStack />
        <ExportDialog />
        <AnimatePresence>{showWelcome && <WelcomeScreen />}</AnimatePresence>
      </div>
    </HashRouter>
  )
}

function LocalShell(): JSX.Element {
  // Local-first mode (the original behavior). No router, no auth, no
  // OpusClipPanel — just the editor.
  const { showWelcome } = useUIStore()
  return (
    <>
      <GlobalHooks />
      <div className="flex h-full w-full flex-col overflow-hidden bg-axew-bg text-axew-text">
        <MainLayout />
        <AnimatePresence>{showWelcome && <WelcomeScreen />}</AnimatePresence>
        <NotificationStack />
        <ExportDialog />
      </div>
    </>
  )
}

export default function App(): JSX.Element {
  // Kick off auth initialization eagerly in cloud mode so RequireAuth doesn't
  // spend its first paint in 'loading'.
  const initializeAuth = useAuthStore((s) => s.initialize)
  useEffect(() => {
    if (CLOUD_ENABLED) initializeAuth().catch(() => undefined)
  }, [initializeAuth])

  return CLOUD_ENABLED ? <CloudShell /> : <LocalShell />
}
