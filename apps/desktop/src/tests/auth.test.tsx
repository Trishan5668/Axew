/**
 * Auth flow tests.
 *
 * - LoginPage: email -> OTP step renders, then verify redirects.
 * - RequireAuth: unauthenticated -> redirects to /login with `from` preserved.
 *
 * The Supabase client is fully mocked. We intentionally do NOT touch
 * the real signInWithOtp / verifyOtp implementations — those are tested
 * server-side by the test_profile_created_on_signup integration test
 * (verification-pending; runs against a live Supabase project).
 */

import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { LoginPage } from '../pages/LoginPage'
import { RequireAuth } from '../components/RequireAuth'
import { useAuthStore } from '../stores/authSlice'

// Mock the supabase client. Every test resets the mock state.
vi.mock('../lib/supabase', () => {
  const subscribers: Array<(event: string, session: unknown) => void> = []
  const fakeClient = {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null }, error: null }),
      signInWithOtp: vi.fn().mockResolvedValue({ data: {}, error: null }),
      verifyOtp: vi.fn().mockResolvedValue({
        data: {
          session: {
            access_token: 'tok',
            refresh_token: 'r',
            expires_in: 3600,
            token_type: 'bearer',
            user: { id: 'u-1', email: 'jane@example.com' },
          },
          user: { id: 'u-1', email: 'jane@example.com' },
        },
        error: null,
      }),
      signInWithOAuth: vi.fn().mockResolvedValue({ data: {}, error: null }),
      signOut: vi.fn().mockResolvedValue({ error: null }),
      onAuthStateChange: vi.fn((cb: (event: string, s: unknown) => void) => {
        subscribers.push(cb)
        return { data: { subscription: { unsubscribe: () => undefined } } }
      }),
      exchangeCodeForSession: vi.fn(),
      refreshSession: vi.fn(),
      getUser: vi.fn().mockResolvedValue({ data: { user: null }, error: null }),
    },
    from: vi.fn(() => ({
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      single: vi.fn().mockResolvedValue({
        data: {
          id: 'u-1',
          email: 'jane@example.com',
          credit_balance: 10,
          total_minutes_processed: 0,
          display_name: null,
          avatar_url: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
        error: null,
      }),
      update: vi.fn().mockReturnThis(),
      order: vi.fn().mockReturnThis(),
      limit: vi.fn().mockReturnThis(),
    })),
    channel: vi.fn().mockReturnThis(),
    removeChannel: vi.fn(),
  }
  return {
    isCloudAvailable: () => true,
    supabase: () => fakeClient,
    __resetSupabaseClientForTests: () => undefined,
    CloudUnavailableError: class extends Error {},
  }
})

vi.mock('../lib/cloudFlag', () => ({
  CLOUD_ENABLED: true,
  SUPABASE_URL: 'https://example.supabase.co',
  SUPABASE_ANON_KEY: 'anon',
  RAZORPAY_KEY_ID: 'rzp',
  AI_SERVICE_BASE_URL: 'http://127.0.0.1:7002',
  cloudUnavailableReason: () => null,
}))

beforeEach(() => {
  useAuthStore.setState({
    session: null,
    profile: null,
    authStatus: 'unauthenticated',
    errorMessage: null,
    initialized: false,
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('LoginPage OTP flow', () => {
  test('email step renders and advances to OTP after submit', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText(/Email address/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /Send code/i }))

    expect(await screen.findByLabelText(/Verification code/i)).toBeInTheDocument()
    expect(screen.getByText(/jane@example.com/i)).toBeInTheDocument()
  })

  test('valid OTP redirects to dashboard', async () => {
    const user = userEvent.setup()

    function LocationProbe() {
      const loc = useLocation()
      return <div data-testid="loc">{loc.pathname}</div>
    }

    render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/dashboard" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText(/Email address/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /Send code/i }))

    const otpInput = await screen.findByLabelText(/Verification code/i)
    await user.type(otpInput, '123456')
    await user.click(screen.getByRole('button', { name: /Verify and continue/i }))

    await waitFor(() => {
      expect(screen.getByTestId('loc')).toHaveTextContent('/dashboard')
    })
  })
})

function makeSession(overrides: Record<string, unknown> = {}): unknown {
  const nowSec = Math.floor(Date.now() / 1000)
  return {
    access_token: 't',
    refresh_token: 'r',
    expires_in: 3600,
    expires_at: nowSec + 3600,
    token_type: 'bearer',
    user: {
      id: 'u-1',
      email: 'jane@example.com',
      app_metadata: {},
      user_metadata: {},
      aud: 'authenticated',
      created_at: '',
    },
    ...overrides,
  }
}

describe('RequireAuth', () => {
  test('redirects unauthenticated users to /login and preserves `from`', async () => {
    useAuthStore.setState({ authStatus: 'unauthenticated', initialized: true })

    function LocationProbe() {
      const loc = useLocation()
      const state = loc.state as { from?: string } | null
      return (
        <div>
          <span data-testid="path">{loc.pathname}</span>
          <span data-testid="from">{state?.from ?? ''}</span>
        </div>
      )
    }

    render(
      <MemoryRouter initialEntries={['/dashboard/billing']}>
        <Routes>
          <Route
            path="/dashboard/billing"
            element={
              <RequireAuth>
                <div>secret</div>
              </RequireAuth>
            }
          />
          <Route path="/login" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('path')).toHaveTextContent('/login')
    })
    expect(screen.getByTestId('from')).toHaveTextContent('/dashboard/billing')
  })

  test('renders children when authenticated', async () => {
    useAuthStore.setState({
      authStatus: 'authenticated',
      initialized: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      session: makeSession() as any,
    })
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <div data-testid="protected">protected content</div>
              </RequireAuth>
            }
          />
        </Routes>
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(screen.getByTestId('protected')).toBeInTheDocument()
    })
  })

  test('redirects to /login?error=session_expired when refresh fails', async () => {
    // Session that expires in 30s — triggers the refresh path
    const nowSec = Math.floor(Date.now() / 1000)
    useAuthStore.setState({
      authStatus: 'authenticated',
      initialized: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      session: makeSession({ expires_at: nowSec + 30 }) as any,
      ensureFreshSession: async () => false,
    })

    function LoginProbe() {
      const loc = useLocation()
      return <span data-testid="loginpath">{`${loc.pathname}${loc.search}`}</span>
    }

    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <div>secret</div>
              </RequireAuth>
            }
          />
          <Route path="/login" element={<LoginProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('loginpath')).toHaveTextContent('/login?error=session_expired')
    })
  })
})

describe('OAuthCallbackPage', () => {
  test('exchanges the code from window.location and redirects to /dashboard', async () => {
    // Import lazily so the auth.ts mock can settle first.
    const { OAuthCallbackPage } = await import('../pages/OAuthCallbackPage')
    const authMod = await import('../lib/auth')
    const spy = vi.spyOn(authMod, 'exchangeOAuthCode').mockResolvedValue({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      access_token: 't', refresh_token: 'r', token_type: 'bearer', user: {} as any,
      expires_in: 3600,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any)

    const originalHref = window.location.href
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { ...window.location, href: 'http://localhost:5173/auth/callback?code=abc' },
    })

    function Probe() {
      const loc = useLocation()
      return <span data-testid="loc">{loc.pathname}</span>
    }

    render(
      <MemoryRouter initialEntries={['/auth/callback']}>
        <Routes>
          <Route path="/auth/callback" element={<OAuthCallbackPage />} />
          <Route path="/dashboard" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(spy).toHaveBeenCalled()
      expect(screen.getByTestId('loc')).toHaveTextContent('/dashboard')
    })

    Object.defineProperty(window, 'location', {
      writable: true,
      value: { ...window.location, href: originalHref },
    })
  })

  test('surfaces an inline error when the exchange fails', async () => {
    const { OAuthCallbackPage } = await import('../pages/OAuthCallbackPage')
    const authMod = await import('../lib/auth')
    vi.spyOn(authMod, 'exchangeOAuthCode').mockRejectedValueOnce(
      new Error('Sign-in did not complete: Invalid code'),
    )

    Object.defineProperty(window, 'location', {
      writable: true,
      value: { ...window.location, href: 'http://localhost:5173/auth/callback?code=bad' },
    })

    render(
      <MemoryRouter initialEntries={['/auth/callback']}>
        <Routes>
          <Route path="/auth/callback" element={<OAuthCallbackPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText(/Sign-in failed/i)).toBeInTheDocument()
    expect(screen.getByText(/Invalid code/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Back to sign in/i })).toBeInTheDocument()
  })
})

describe('LoginPage error query param', () => {
  test('renders session_expired banner when ?error=session_expired is present', () => {
    render(
      <MemoryRouter initialEntries={['/login?error=session_expired']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText(/session expired/i)).toBeInTheDocument()
  })
})
