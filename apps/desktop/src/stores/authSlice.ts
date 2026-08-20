/**
 * Zustand slice mirroring Firebase auth state.
 *
 * Subscribes to Firebase's auth state observer, so every login/logout event
 * flows into the store as a single source of truth. Components should only
 * read the store state and never interrogate Firebase directly in render.
 */

import type { User } from 'firebase/auth'
import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'
import { getUserProfile } from '../lib/auth'
import { firebaseAuth } from '../firebase/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import type { Profile } from '../lib/database.types'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'disabled'

interface AuthState {
  session: User | null
  profile: Profile | null
  authStatus: AuthStatus
  errorMessage: string | null
  initialized: boolean
  lastRefreshAttempt: number | null
}

interface AuthActions {
  setSession: (session: User | null) => void
  setProfile: (profile: Profile | null) => void
  setAuthStatus: (status: AuthStatus) => void
  setError: (message: string | null) => void
  initialize: () => Promise<void>
  refreshProfile: () => Promise<void>
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

      if (!firebaseAuth) {
        // Cloud features (including Firebase auth) are not configured for this build.
        // Mark auth as 'disabled' so RequireAuth allows the local app to run.
        set({ authStatus: 'disabled', session: null, profile: null })
        return
      }

      // Wait for Firebase to invoke the auth-state observer once. onAuthStateChanged
      // is guaranteed to call the callback immediately with the current user or null.
      const auth = firebaseAuth!
      await new Promise<void>((resolve) => {
        let initialStateResolved = false
        onAuthStateChanged(auth, async (user) => {
          if (user) {
            set({ session: user, authStatus: 'authenticated', errorMessage: null })
            try {
              const profile = await getUserProfile(user.uid)
              set({ profile })
            } catch (err) {
              set({ errorMessage: err instanceof Error ? err.message : String(err) })
            }
          } else {
            set({ session: null, profile: null, authStatus: 'unauthenticated' })
          }
          if (!initialStateResolved) {
            initialStateResolved = true
            resolve()
          }
        })
      })
    },

    refreshProfile: async () => {
      const session = get().session
      if (!session) return
      try {
        const profile = await getUserProfile(session.uid)
        set({ profile })
      } catch (err) {
        set({ errorMessage: err instanceof Error ? err.message : String(err) })
      }
    },

    ensureFreshSession: async () => {
      const { session } = get()
      if (!session) return false
      await session.getIdToken(true)
      return true
    },
  })),
)
