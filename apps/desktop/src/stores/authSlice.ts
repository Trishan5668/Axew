/**
 * Zustand slice mirroring Supabase auth state.
 *
 * Subscribes to supabase.auth.onAuthStateChange on first use, so every
 * SIGNED_IN / TOKEN_REFRESHED / SIGNED_OUT event flows into the store
 * automatically. Components should ONLY read state via the selectors;
 * never call supabase.auth from a render path.
 */

import type { Session } from '@supabase/supabase-js'
import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'
import { getUserProfile, refreshSession as refreshSupabaseSession } from '../lib/auth'
import { isCloudAvailable, supabase } from '../lib/supabase'
import type { Profile } from '../lib/database.types'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'disabled'

/**
 * Refresh tokens this many seconds before they expire. Supabase issues
 * 1-hour access tokens by default; refreshing at T-120 leaves a healthy
 * buffer for slow networks without thrashing the refresh endpoint.
 */
const REFRESH_LEAD_SECONDS = 120

interface AuthState {
  session: Session | null
  profile: Profile | null
  authStatus: AuthStatus
  errorMessage: string | null
  initialized: boolean
  /** Last attempt to refresh the access token; null = never tried. */
  lastRefreshAttempt: number | null
}

interface AuthActions {
  setSession: (session: Session | null) => void
  setProfile: (profile: Profile | null) => void
  setAuthStatus: (status: AuthStatus) => void
  setError: (message: string | null) => void
  initialize: () => Promise<void>
  refreshProfile: () => Promise<void>
  /**
   * Returns true if the current session is still valid for at least
   * REFRESH_LEAD_SECONDS more seconds. Used by RequireAuth before
   * granting access to a protected route.
   */
  ensureFreshSession: () => Promise<boolean>
}

export const useAuthStore = create<AuthState & AuthActions>()(
  subscribeWithSelector((set, get) => ({
    session: null,
    profile: null,
    authStatus: 'loading',
    errorMessage: null,
    initialized: false,
    lastRefreshAttempt: null,

    setSession: (session) => set({ session }),
    setProfile: (profile) => set({ profile }),
    setAuthStatus: (status) => set({ authStatus: status }),
    setError: (message) => set({ errorMessage: message }),

    initialize: async () => {
      if (get().initialized) return
      set({ initialized: true })

      if (!isCloudAvailable()) {
        set({ authStatus: 'disabled' })
        return
      }

      const client = supabase()
      try {
        const { data } = await client.auth.getSession()
        const session = data.session ?? null
        set({
          session,
          authStatus: session ? 'authenticated' : 'unauthenticated',
        })

        if (session) {
          try {
            const profile = await getUserProfile(session.user.id)
            set({ profile })
          } catch (err) {
            // Profile load failure isn't fatal — surface it but keep the
            // user signed in so they can retry from the dashboard.
            set({ errorMessage: err instanceof Error ? err.message : String(err) })
          }
        }

        client.auth.onAuthStateChange((event, nextSession) => {
          if (event === 'SIGNED_OUT' || !nextSession) {
            set({ session: null, profile: null, authStatus: 'unauthenticated' })
            return
          }
          set({ session: nextSession, authStatus: 'authenticated', errorMessage: null })
          // Profile refresh is fire-and-forget; UI shows skeleton until it lands.
          getUserProfile(nextSession.user.id)
            .then((profile) => set({ profile }))
            .catch((err) => set({
              errorMessage: err instanceof Error ? err.message : String(err),
            }))
        })
      } catch (err) {
        set({
          authStatus: 'unauthenticated',
          errorMessage: err instanceof Error ? err.message : String(err),
        })
      }
    },

    refreshProfile: async () => {
      const session = get().session
      if (!session) return
      try {
        const profile = await getUserProfile(session.user.id)
        set({ profile })
      } catch (err) {
        set({ errorMessage: err instanceof Error ? err.message : String(err) })
      }
    },

    ensureFreshSession: async () => {
      const { session } = get()
      if (!session) return false

      // Compute remaining lifetime. Supabase sessions carry `expires_at` as
      // a unix timestamp (seconds). Older versions only have `expires_in` —
      // we treat the lack of `expires_at` as "treat it as fresh."
      const expiresAt = session.expires_at
      if (!expiresAt) return true

      const nowSec = Math.floor(Date.now() / 1000)
      const secondsRemaining = expiresAt - nowSec
      if (secondsRemaining > REFRESH_LEAD_SECONDS) return true

      // Throttle: do not attempt a refresh more than once every 10s. Prevents
      // a render loop from hammering Supabase if refresh keeps failing.
      const last = get().lastRefreshAttempt
      if (last !== null && Date.now() - last < 10_000) {
        return secondsRemaining > 0
      }
      set({ lastRefreshAttempt: Date.now() })

      try {
        const fresh = await refreshSupabaseSession()
        if (!fresh) {
          set({
            session: null,
            profile: null,
            authStatus: 'unauthenticated',
            errorMessage: 'Your session expired. Please sign in again.',
          })
          return false
        }
        set({ session: fresh, errorMessage: null })
        return true
      } catch (err) {
        set({
          session: null,
          profile: null,
          authStatus: 'unauthenticated',
          errorMessage: err instanceof Error ? err.message : String(err),
        })
        return false
      }
    },
  })),
)
