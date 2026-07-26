/**
 * useCredits — live credit balance for the signed-in user.
 *
 * Uses Supabase Realtime to subscribe to UPDATE events on the user's
 * profile row. Falls back to a single fetch when realtime isn't available.
 *
 * In local-only mode (no cloud), returns { creditBalance: Infinity,
 * loading: false } so any component using this hook never accidentally
 * blocks processing.
 */

import { useEffect, useState } from 'react'
import { getUserProfile } from '../lib/auth'
import { isCloudAvailable, supabase } from '../lib/supabase'
import { useAuthStore } from '../stores/authSlice'

interface UseCreditsResult {
  creditBalance: number
  totalMinutesProcessed: number
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

const LOCAL_RESULT: UseCreditsResult = {
  creditBalance: Number.POSITIVE_INFINITY,
  totalMinutesProcessed: 0,
  loading: false,
  error: null,
  refresh: async () => undefined,
}

export function useCredits(): UseCreditsResult {
  const { session, profile, refreshProfile } = useAuthStore()
  const [creditBalance, setCreditBalance] = useState<number>(profile?.credit_balance ?? 0)
  const [totalMinutesProcessed, setTotalMinutesProcessed] = useState<number>(
    profile?.total_minutes_processed ?? 0,
  )
  const [loading, setLoading] = useState<boolean>(!profile)
  const [error, setError] = useState<string | null>(null)

  // Keep state in sync with the auth slice's profile snapshot
  useEffect(() => {
    if (profile) {
      setCreditBalance(profile.credit_balance)
      setTotalMinutesProcessed(profile.total_minutes_processed)
      setLoading(false)
    }
  }, [profile])

  useEffect(() => {
    if (!isCloudAvailable() || !session?.user.id) {
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)

    getUserProfile(session.user.id)
      .then((p) => {
        if (cancelled) return
        setCreditBalance(p.credit_balance)
        setTotalMinutesProcessed(p.total_minutes_processed)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    let unsubscribe: (() => void) | null = null
    try {
      const channel = supabase()
        .channel(`profile:${session.user.id}`)
        .on(
          'postgres_changes',
          {
            event: 'UPDATE',
            schema: 'public',
            table: 'profiles',
            filter: `id=eq.${session.user.id}`,
          },
          (payload) => {
            const next = payload.new as
              | { credit_balance?: number; total_minutes_processed?: number }
              | null
            if (!next) return
            if (typeof next.credit_balance === 'number') {
              setCreditBalance(next.credit_balance)
            }
            if (typeof next.total_minutes_processed === 'number') {
              setTotalMinutesProcessed(next.total_minutes_processed)
            }
            // Keep auth slice profile coherent too
            refreshProfile().catch(() => undefined)
          },
        )
        .subscribe()
      unsubscribe = () => {
        try {
          supabase().removeChannel(channel)
        } catch {
          /* channel already gone */
        }
      }
    } catch {
      // Realtime unavailable — fall back to polling
      const id = window.setInterval(() => {
        refreshProfile().catch(() => undefined)
      }, 5000)
      unsubscribe = () => window.clearInterval(id)
    }

    return () => {
      cancelled = true
      unsubscribe?.()
    }
  }, [session?.user.id, refreshProfile])

  if (!isCloudAvailable()) {
    return LOCAL_RESULT
  }

  return {
    creditBalance,
    totalMinutesProcessed,
    loading,
    error,
    refresh: refreshProfile,
  }
}
