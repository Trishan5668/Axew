/**
 * OAuth deep-link handler.
 *
 * Supabase's PKCE flow needs to redirect back to a URL it knows about. In a
 * browser SPA that's `https://yourdomain/auth/callback`. In a packaged Electron
 * app the renderer loads from `file://` — Supabase will not redirect there.
 *
 * Solution: register `axew://` as a custom URL protocol with the OS.  Configure
 * Supabase to redirect to `axew://auth/callback`. When the OS hands the URL
 * back to us (via `app.requestSingleInstanceLock()` on Windows/Linux or the
 * `open-url` event on macOS), we focus the existing window and forward the
 * URL to the renderer over IPC. The renderer's `OAuthCallbackPage` finishes
 * the PKCE exchange.
 *
 * In dev mode we keep using `http://localhost:5173/auth/callback` because
 * the renderer is served by Vite, and Supabase accepts http://localhost
 * redirects out of the box.
 */

import { app, BrowserWindow } from 'electron'
import path from 'path'

const OAUTH_PROTOCOL = 'axew'
const OAUTH_PATH = '/auth/callback'

export interface OAuthHandlerOptions {
  getMainWindow: () => BrowserWindow | null
  /** Called when the OS hands us a `axew://` URL. Renderer listens for `oauth:deep-link`. */
  onDeepLink?: (url: string) => void
}

let installed = false

/**
 * Returns the redirect URL the renderer should hand to Supabase. Dev uses
 * Vite's HTTP origin; production uses the custom protocol.
 */
export function oauthRedirectUrl(isDev: boolean, devOrigin = 'http://localhost:5173'): string {
  if (isDev) return `${devOrigin}${OAUTH_PATH}`
  return `${OAUTH_PROTOCOL}:/${OAUTH_PATH}`
}

/**
 * Register the custom `axew://` protocol so the OS routes axew://… URLs back
 * to this app. Idempotent — safe to call multiple times.
 */
export function registerOAuthProtocol(): void {
  if (installed) return
  installed = true

  if (process.defaultApp) {
    // Dev — Electron is launched via `electron .`. The OS needs the full
    // argv so it re-launches us correctly.
    if (process.argv.length >= 2) {
      app.setAsDefaultProtocolClient(OAUTH_PROTOCOL, process.execPath, [
        path.resolve(process.argv[1]),
      ])
    }
  } else {
    app.setAsDefaultProtocolClient(OAUTH_PROTOCOL)
  }
}

/**
 * Wire up listeners that receive deep links and forward them to the renderer.
 *
 * Behavior:
 *   - Windows/Linux: deep links arrive as command-line args on the SECOND
 *     launch of the app. We use `requestSingleInstanceLock` to make sure
 *     only one instance runs; the second instance's argv lands in the
 *     `second-instance` event.
 *   - macOS: deep links arrive via the `open-url` event before/after `ready`.
 *   - Either way: we focus the existing window and post the URL via IPC.
 */
export function attachOAuthDeepLinkListeners({ getMainWindow, onDeepLink }: OAuthHandlerOptions): void {
  const forward = (deepLink: string) => {
    const win = getMainWindow()
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
      win.webContents.send('oauth:deep-link', deepLink)
    }
    onDeepLink?.(deepLink)
  }

  const extractFromArgv = (argv: string[]): string | null => {
    for (const arg of argv) {
      if (typeof arg === 'string' && arg.startsWith(`${OAUTH_PROTOCOL}://`)) {
        return arg
      }
    }
    return null
  }

  // Windows / Linux
  const gotLock = app.requestSingleInstanceLock()
  if (!gotLock) {
    // Another instance already owns the lock — quit so its second-instance
    // handler can pick up our argv (which contains the deep link).
    app.quit()
    return
  }
  app.on('second-instance', (_event, argv) => {
    const link = extractFromArgv(argv)
    if (link) forward(link)
    else {
      const win = getMainWindow()
      if (win) {
        if (win.isMinimized()) win.restore()
        win.focus()
      }
    }
  })

  // macOS
  app.on('open-url', (event, url) => {
    event.preventDefault()
    forward(url)
  })

  // Cold-start (the very first launch may already carry the deep link).
  const initialLink = extractFromArgv(process.argv)
  if (initialLink) {
    app.whenReady().then(() => {
      // Defer so the window is up and IPC is alive.
      setTimeout(() => forward(initialLink), 800)
    })
  }
}
