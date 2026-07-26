/**
 * LoginPage — two-step email OTP flow + Google OAuth.
 *
 * Visual style:
 *   - dark AXEW theme
 *   - monospace OTP input with subtle glow on focus
 *   - inline error messages adjacent to the triggering input (NEVER toasts)
 */

import { ArrowRight, Loader2, Mail } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { signInWithEmailOtp, signInWithGoogle, verifyEmailOtp } from '../lib/auth'
import { cloudUnavailableReason } from '../lib/cloudFlag'

type Step = 'email' | 'otp'

interface LocationState {
  from?: string
}

const RESEND_COOLDOWN_SECONDS = 30

const SIGN_IN_ERROR_MESSAGES: Record<string, string> = {
  session_expired: 'Your session expired. Please sign in again.',
  oauth_failed: 'Google sign-in did not complete. Please try again.',
}

export function LoginPage(): JSX.Element {
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState('')
  const [otp, setOtp] = useState('')
  const [emailError, setEmailError] = useState<string | null>(null)
  const [otpError, setOtpError] = useState<string | null>(null)
  const [googleError, setGoogleError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [resendCooldown, setResendCooldown] = useState(0)

  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const redirectTo = (location.state as LocationState | null)?.from ?? '/dashboard'

  const cloudReason = cloudUnavailableReason()
  const queryError = useMemo(() => {
    const code = searchParams.get('error')
    if (!code) return null
    return SIGN_IN_ERROR_MESSAGES[code] ?? code
  }, [searchParams])

  // Resend cooldown countdown
  useEffect(() => {
    if (resendCooldown <= 0) return
    const id = window.setInterval(() => {
      setResendCooldown((s) => Math.max(0, s - 1))
    }, 1000)
    return () => window.clearInterval(id)
  }, [resendCooldown])

  const handleSendCode = async (e: React.FormEvent) => {
    e.preventDefault()
    setEmailError(null)
    if (busy || resendCooldown > 0) return
    setBusy(true)
    try {
      await signInWithEmailOtp(email)
      setStep('otp')
      setResendCooldown(RESEND_COOLDOWN_SECONDS)
    } catch (err) {
      setEmailError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const handleResendCode = async () => {
    if (busy || resendCooldown > 0 || !email) return
    setOtpError(null)
    setBusy(true)
    try {
      await signInWithEmailOtp(email)
      setResendCooldown(RESEND_COOLDOWN_SECONDS)
    } catch (err) {
      setOtpError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    setOtpError(null)
    if (busy) return
    setBusy(true)
    try {
      await verifyEmailOtp(email, otp)
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setOtpError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const handleGoogle = async () => {
    setGoogleError(null)
    if (busy) return
    setBusy(true)
    try {
      await signInWithGoogle()
      // The redirect happens out-of-band; we won't reach this line.
    } catch (err) {
      setGoogleError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full w-full items-center justify-center bg-axew-bg px-6">
      <div className="w-full max-w-sm rounded-lg border border-axew-border bg-axew-surface p-6 shadow-xl">
        <header className="mb-5">
          <h1 className="text-lg font-semibold text-axew-text">Welcome to AXEW</h1>
          <p className="mt-1 text-xs text-axew-textMuted">
            Sign in to enable cloud features. AXEW also works fully offline if you skip this step.
          </p>
        </header>

        {cloudReason && (
          <div
            role="alert"
            className="mb-4 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-2xs text-amber-200"
          >
            {cloudReason}
          </div>
        )}

        {queryError && (
          <div
            role="alert"
            className="mb-4 rounded border border-red-500/40 bg-red-500/10 p-3 text-2xs text-red-200"
          >
            {queryError}
          </div>
        )}

        {step === 'email' && (
          <form onSubmit={handleSendCode} noValidate>
            <label className="block text-2xs font-medium text-axew-textDim" htmlFor="email">
              Email address
            </label>
            <div className="mt-1 flex gap-2">
              <div className="relative flex-1">
                <Mail
                  size={12}
                  className="pointer-events-none absolute left-2 top-2 text-axew-textDim"
                />
                <input
                  id="email"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  required
                  className="w-full rounded border border-axew-border bg-axew-panel py-1.5 pl-6 pr-2 text-xs text-axew-text outline-none focus:border-axew-accent"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  disabled={busy}
                  aria-invalid={emailError ? 'true' : 'false'}
                  aria-describedby={emailError ? 'email-error' : undefined}
                />
              </div>
              <button
                type="submit"
                className="flex items-center gap-1 rounded bg-axew-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-axew-accentHover disabled:opacity-40"
                disabled={busy || !email}
              >
                {busy ? <Loader2 size={12} className="animate-spin" /> : <ArrowRight size={12} />}
                Send code
              </button>
            </div>
            {emailError && (
              <p id="email-error" role="alert" className="mt-2 text-2xs text-red-300">
                {emailError}
              </p>
            )}
          </form>
        )}

        {step === 'otp' && (
          <form onSubmit={handleVerify} noValidate>
            <p className="text-2xs text-axew-textMuted">
              We sent a 6-digit code to <span className="text-axew-text">{email}</span>.
              <button
                type="button"
                className="ml-1 text-axew-accent hover:underline"
                onClick={() => {
                  setStep('email')
                  setOtp('')
                  setOtpError(null)
                  setResendCooldown(0)
                }}
              >
                Use a different email
              </button>
            </p>
            <button
              type="button"
              onClick={handleResendCode}
              disabled={busy || resendCooldown > 0}
              className="mt-1 text-2xs text-axew-textDim hover:text-axew-text disabled:opacity-60"
            >
              {resendCooldown > 0
                ? `Resend code in ${resendCooldown}s`
                : 'Resend code'}
            </button>
            <label className="mt-3 block text-2xs font-medium text-axew-textDim" htmlFor="otp">
              Verification code
            </label>
            <input
              id="otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              pattern="\d{6}"
              className="mt-1 w-full rounded border border-axew-border bg-axew-panel px-3 py-2 text-center font-mono text-lg tracking-[0.4em] text-axew-text outline-none transition-shadow focus:border-axew-accent focus:shadow-[0_0_0_3px_rgba(99,179,237,0.2)]"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="••••••"
              disabled={busy}
              aria-invalid={otpError ? 'true' : 'false'}
              aria-describedby={otpError ? 'otp-error' : undefined}
            />
            {otpError && (
              <p id="otp-error" role="alert" className="mt-2 text-2xs text-red-300">
                {otpError}
              </p>
            )}
            <button
              type="submit"
              className="mt-3 flex w-full items-center justify-center gap-1 rounded bg-axew-accent px-3 py-2 text-xs font-medium text-white hover:bg-axew-accentHover disabled:opacity-40"
              disabled={busy || otp.length !== 6}
            >
              {busy ? <Loader2 size={12} className="animate-spin" /> : null}
              Verify and continue
            </button>
          </form>
        )}

        <div className="my-5 flex items-center gap-2 text-2xs text-axew-textDim">
          <span className="h-px flex-1 bg-axew-border" />
          <span>or</span>
          <span className="h-px flex-1 bg-axew-border" />
        </div>

        <button
          type="button"
          onClick={handleGoogle}
          disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded border border-axew-border bg-axew-panel px-3 py-2 text-xs text-axew-text hover:border-axew-ai/40 disabled:opacity-40"
          aria-describedby={googleError ? 'google-error' : undefined}
        >
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-white text-[10px] font-bold text-[#4285F4]">
            G
          </span>
          Continue with Google
        </button>
        {googleError && (
          <p id="google-error" role="alert" className="mt-2 text-2xs text-red-300">
            {googleError}
          </p>
        )}

        <p className="mt-5 text-center text-2xs text-axew-textDim">
          Cloud sign-in is optional — AXEW runs fully offline without it.
        </p>
      </div>
    </div>
  )
}
