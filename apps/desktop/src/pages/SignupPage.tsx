import { ArrowRight, Loader2, Mail } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { signUpWithEmail } from '../lib/auth'

export function SignupPage(): JSX.Element {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return

    setError(null)
    setBusy(true)
    try {
      await signUpWithEmail(email.trim(), password)
      navigate('/login', { replace: true })
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
            <p className="mt-1 text-xs text-axew-textMuted">Create your account</p>
          </div>
        </div>

        <div className="mb-6">
          <h2 className="text-2xl font-semibold text-axew-text">Create account</h2>
          <p className="mt-2 text-sm text-axew-textMuted">Start secure email access instantly.</p>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit} noValidate>
          <div>
            <label htmlFor="signup-email" className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-axew-textDim">
              Email address
            </label>
            <div className="relative">
              <Mail size={14} className="pointer-events-none absolute left-3 top-3 text-axew-textDim" />
              <input
                id="signup-email"
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
            <label htmlFor="signup-password" className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-axew-textDim">
              Password
            </label>
            <input
              id="signup-password"
              type="password"
              autoComplete="new-password"
              className="w-full rounded-xl border border-axew-border bg-axew-panel px-3 py-2 text-sm text-axew-text outline-none transition focus:border-axew-accent focus:ring-2 focus:ring-axew-accent/30"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Minimum 6 characters"
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
            Create account
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-axew-textMuted">
          Already have an account?{' '}
          <Link className="font-semibold text-axew-ai hover:underline" to="/login">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
