/**
 * UserMenu — sits in the top-right corner of the global nav bar.
 * Shows the user's avatar (or initials), email, and credit balance.
 * Provides Billing and Logout actions.
 *
 * Renders nothing when authStatus is 'disabled' (local-only build).
 */

import { CreditCard, LogOut, User as UserIcon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { signOut } from '../lib/auth'
import { useAuthStore } from '../stores/authSlice'

function initialsOf(email: string | undefined, displayName: string | null | undefined): string {
  if (displayName && displayName.trim()) {
    return displayName
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? '')
      .join('')
  }
  if (email) return email[0]?.toUpperCase() ?? '?'
  return '?'
}

export function UserMenu(): JSX.Element | null {
  const { session, profile, authStatus } = useAuthStore()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (authStatus !== 'authenticated' || !session) return null

  const handleLogout = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await signOut()
      setOpen(false)
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign out failed. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const email = profile?.email ?? session.email ?? ''
  const balance = profile?.credit_balance ?? 0
  const avatar = profile?.avatar_url ?? session.photoURL ?? undefined

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((s) => !s)}
        className="flex items-center gap-2 rounded border border-axew-border bg-axew-panel px-2 py-1 text-xs text-axew-text hover:border-axew-ai/40"
        aria-haspopup="true"
        aria-expanded={open}
      >
        {avatar ? (
          <img src={avatar} alt="" className="h-5 w-5 rounded-full" />
        ) : (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-axew-ai/20 text-2xs font-semibold text-axew-ai">
            {initialsOf(email, profile?.display_name)}
          </span>
        )}
        <span className="hidden text-2xs text-axew-textMuted sm:inline">{email}</span>
        <span className="rounded bg-axew-ai/10 px-1.5 py-0.5 text-2xs font-medium text-axew-ai">
          {balance.toFixed(1)} min
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-1 w-60 rounded border border-axew-border bg-axew-surface p-1 shadow-lg"
        >
          <div className="border-b border-axew-border px-3 py-2">
            <p className="text-xs font-medium text-axew-text">{profile?.display_name ?? email}</p>
            <p className="truncate text-2xs text-axew-textDim">{email}</p>
            <p className="mt-1 text-2xs text-axew-textMuted">
              Credit balance: <span className="text-axew-ai">{balance.toFixed(2)} min</span>
            </p>
          </div>
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-xs text-axew-text hover:bg-axew-panel"
            onClick={() => {
              setOpen(false)
              navigate('/dashboard/billing')
            }}
          >
            <CreditCard size={12} /> Billing & credits
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-xs text-axew-text hover:bg-axew-panel"
            onClick={() => {
              setOpen(false)
              navigate('/dashboard')
            }}
          >
            <UserIcon size={12} /> Dashboard
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-xs text-red-300 hover:bg-red-900/20 disabled:opacity-50"
            onClick={handleLogout}
            disabled={busy}
          >
            <LogOut size={12} /> {busy ? 'Signing out…' : 'Sign out'}
          </button>
          {error && (
            <p className="px-3 py-1.5 text-2xs text-red-300" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
