import { ArrowRight, Loader2, Mail } from 'lucide-react'
import { type FormEvent, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { signInWithEmail, signInWithGoogle } from '../lib/auth'
import { isFirebaseEnabled } from '../firebase/firebase'

interface LocationState {
  from?: string
}

const SIGN_IN_ERROR_MESSAGES: Record<string, string> = {
  session_expired: 'Your session expired. Please sign in again.',
}

export function LoginPage(): JSX.Element {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const redirectTo = (location.state as LocationState | null)?.from ?? '/'

  const queryError = useMemo(() => {
    const code = searchParams.get('error')
    if (!code) return null
    return SIGN_IN_ERROR_MESSAGES[code] ?? code
  }, [searchParams])

  const handleEmailLogin = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return

    setError(null)
    setBusy(true)
    try {
      await signInWithEmail(email.trim(), password)
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const handleGoogle = async () => {
    if (busy) return
    setError(null)
    setBusy(true)
    try {
      await signInWithGoogle()
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full w-full items-center justify-center bg-axew-bg px-6">
      <div className="w-full max-w-md rounded-2xl border border-axew-border bg-axew-surface p-8 shadow-2xl">
        <div className="mb-8 flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-axew-ai/40 bg-axew-ai/10 text-xl font-black text-axew-ai">
            AX
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-axew-text">Axew</h1>
            <p className="mt-1 text-xs text-axew-textMuted">Workspace portal</p>
          </div>
        </div>

        {queryError && (
          <div className="mb-4 rounded border border-red-500/40 bg-red-500/10 p-3 text-2xs text-red-200">
            {queryError}
          </div>
        )}

        {!isFirebaseEnabled && (
          <div role="alert" className="mb-4 rounded border border-red-500/40 bg-red-500/10 p-3 text-2xs text-red-200">
            Firebase Authentication is not configured. Set all required VITE_FIREBASE_* variables and restart Axew.
          </div>
        )}

        <div className="mb-6">
          <h2 className="text-2xl font-semibold text-axew-text">Welcome back</h2>
          <p className="mt-2 text-sm text-axew-textMuted">Sign in to continue to Axew.</p>
        </div>

        <button
          type="button"
          onClick={handleGoogle}
          disabled={busy}
          className="flex w-full items-center justify-center gap-3 rounded-xl border border-axew-border bg-axew-panel px-4 py-3 text-sm font-medium text-axew-text transition hover:border-axew-ai/60 hover:bg-axew-panel/80 disabled:opacity-50"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white text-[10px] font-black text-[#4285F4]">
            G
          </span>
          Continue with Google
        </button>

        <div className="my-6 flex items-center gap-3">
          <span className="h-px flex-1 bg-axew-border" />
          <span className="text-2xs uppercase tracking-[0.2em] text-axew-textDim">or</span>
          <span className="h-px flex-1 bg-axew-border" />
        </div>

        <form className="space-y-4" onSubmit={handleEmailLogin} noValidate>
          <div>
            <label htmlFor="login-email" className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-axew-textDim">
              Email address
            </label>
            <div className="relative">
              <Mail size={14} className="pointer-events-none absolute left-3 top-3 text-axew-textDim" />
              <input
                id="login-email"
                type="email"
                autoComplete="email"
                className="w-full rounded-xl border border-axew-border bg-axew-panel py-2 pl-10 pr-3 text-sm text-axew-text outline-none transition focus:border-axew-accent focus:ring-2 focus:ring-axew-accent/30"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                required
              />
            </div>
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <label htmlFor="login-password" className="text-2xs font-semibold uppercase tracking-wide text-axew-textDim">
                Password
              </label>
              <Link to="/forgot-password" className="text-2xs text-axew-ai hover:underline">
                Forgot password?
              </Link>
            </div>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              className="w-full rounded-xl border border-axew-border bg-axew-panel px-3 py-2 text-sm text-axew-text outline-none transition focus:border-axew-accent focus:ring-2 focus:ring-axew-accent/30"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="��������"
              required
            />
          </div>

          {error && (
            <div role="alert" className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-2xs text-red-200">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-axew-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-axew-accentHover disabled:opacity-50"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            Sign in
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-axew-textMuted">
          New to Axew?{' '}
          <Link className="font-semibold text-axew-ai hover:underline" to="/signup">
            Create account
          </Link>
        </p>
      </div>
    </div>
  )
}
