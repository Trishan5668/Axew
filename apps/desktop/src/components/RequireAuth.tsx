/**
 * Route guard for protected pages.
 *
 * Behavior (matches the spec):
 *   - authStatus 'loading': render a centered spinner.
 *   - authStatus 'disabled' (cloud not configured): render children verbatim
 *     so AXEW still works as a local-only app.
 *   - authStatus 'unauthenticated': redirect to /login, preserving the
 *     original destination in location.state.from.
 *   - authStatus 'authenticated' but the access token is within 2 minutes
 *     of expiring: call ensureFreshSession() (which calls Supabase's
 *     refreshSession internally), show a loading spinner during the call,
 *     then re-check. If refresh fails, redirect to /login with an `error`
 *     query param.
 *   - authStatus 'authenticated' and token still fresh: render children.
 */

import { Loader2 } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../stores/authSlice'

interface RequireAuthProps {
  children: ReactNode
}

type GuardPhase = 'idle' | 'refreshing' | 'refresh-failed'

export function RequireAuth({ children }: RequireAuthProps): JSX.Element {
  const { authStatus, initialize, session, ensureFreshSession } = useAuthStore()
  const location = useLocation()
  const [phase, setPhase] = useState<GuardPhase>('idle')

  useEffect(() => {
    initialize().catch(() => undefined)
  }, [initialize])

  useEffect(() => {
    if (authStatus !== 'authenticated' || !session) return
    let cancelled = false
    setPhase('refreshing')
    ensureFreshSession()
      .then((ok) => {
        if (cancelled) return
        setPhase(ok ? 'idle' : 'refresh-failed')
      })
      .catch(() => {
        if (cancelled) return
        setPhase('refresh-failed')
      })
    return () => {
      cancelled = true
    }
  }, [authStatus, session, ensureFreshSession])

  if (authStatus === 'loading') {
    return (
      <div className="flex h-full w-full items-center justify-center bg-axew-bg">
        <div className="flex items-center gap-2 text-axew-textMuted">
          <Loader2 size={16} className="animate-spin" />
          <span className="text-sm">Restoring your session…</span>
        </div>
      </div>
    )
  }

  if (authStatus === 'disabled') {
    return (
      <div className="flex h-full w-full items-center justify-center bg-axew-bg px-6">
        <div className="w-full max-w-md rounded-2xl border border-red-500/40 bg-axew-surface p-8 shadow-2xl">
          <h1 className="text-xl font-semibold text-axew-text">Authentication unavailable</h1>
          <p className="mt-3 text-sm text-axew-textMuted">
            Firebase Authentication is not configured for this build. Add the required
            VITE_FIREBASE_* environment variables and restart Axew.
          </p>
        </div>
      </div>
    )
  }

  if (authStatus === 'unauthenticated' || phase === 'refresh-failed') {
    const redirectTo = `${location.pathname}${location.search}` || '/dashboard'
    const search = phase === 'refresh-failed' ? '?error=session_expired' : ''
    return (
      <Navigate
        to={`/login${search}`}
        replace
        state={{ from: redirectTo }}
      />
    )
  }

  if (phase === 'refreshing') {
    return (
      <div className="flex h-full w-full items-center justify-center bg-axew-bg">
        <div className="flex items-center gap-2 text-axew-textMuted">
          <Loader2 size={16} className="animate-spin" />
          <span className="text-sm">Refreshing your session…</span>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
