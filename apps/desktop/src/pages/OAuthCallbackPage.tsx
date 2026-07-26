/**
 * OAuthCallbackPage — finishes the Supabase PKCE exchange.
 *
 * Two code-arrival paths are supported:
 *
 *   1. **Dev / browser**: Supabase redirects the in-app window to
 *      `http://localhost:5173/auth/callback?code=…`. We pick the code out
 *      of `window.location.href` on mount and call `exchangeOAuthCode()`.
 *
 *   2. **Packaged Electron**: Supabase cannot redirect to `file://`. We
 *      configured Supabase to redirect to `axew://auth/callback?code=…`.
 *      The OS opens that URL, electron/services/oauthHandler.ts forwards
 *      the full URL to the renderer over IPC channel `oauth:deep-link`,
 *      and we handle it here.
 *
 * On success we redirect to /dashboard. On failure we surface the error
 * inline with a back-to-login button.
 */

import { Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { exchangeOAuthCode } from '../lib/auth'

export function OAuthCallbackPage(): JSX.Element {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const handled = useRef(false)

  useEffect(() => {
    const tryExchange = async (url: string) => {
      if (handled.current) return
      handled.current = true
      try {
        await exchangeOAuthCode(url)
        navigate('/dashboard', { replace: true })
      } catch (err) {
        handled.current = false
        setError(err instanceof Error ? err.message : String(err))
      }
    }

    // Path 0: deep-link arrived BEFORE this page mounted — App-level
    // OAuthDeepLinkRouter stashed the URL on window for us.
    const pending = (window as unknown as { __axewPendingOAuthUrl?: string }).__axewPendingOAuthUrl
    if (pending) {
      delete (window as unknown as { __axewPendingOAuthUrl?: string }).__axewPendingOAuthUrl
      tryExchange(pending)
    }

    // Path 1: URL is already in window.location (dev or web build).
    const current = window.location.href
    if (!handled.current && (current.includes('code=') || current.includes('error='))) {
      tryExchange(current)
    }

    // Path 2: listen for the deep-link IPC event (packaged Electron).
    const axew = (window as unknown as {
      axew?: {
        ipc?: {
          on?: (channel: string, listener: (...args: unknown[]) => void) => () => void
        }
      }
    }).axew
    const off = axew?.ipc?.on?.('oauth:deep-link', (...args: unknown[]) => {
      const url = args[args.length - 1]
      if (typeof url === 'string') tryExchange(url)
    })
    return () => {
      try { off?.() } catch { /* noop */ }
    }
  }, [navigate])

  if (error) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-axew-bg px-6">
        <div className="max-w-sm rounded-lg border border-red-500/40 bg-red-500/10 p-6 text-center">
          <h2 className="text-sm font-semibold text-red-200">Sign-in failed</h2>
          <p className="mt-2 text-2xs text-red-200/90">{error}</p>
          <button
            type="button"
            className="mt-4 rounded bg-axew-accent px-3 py-1.5 text-xs text-white hover:bg-axew-accentHover"
            onClick={() => navigate('/login', { replace: true })}
          >
            Back to sign in
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full w-full items-center justify-center bg-axew-bg">
      <div className="flex items-center gap-2 text-axew-textMuted">
        <Loader2 size={16} className="animate-spin" />
        <span className="text-sm">Completing sign-in…</span>
      </div>
    </div>
  )
}
