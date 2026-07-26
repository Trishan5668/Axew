/**
 * CreditMeter — non-blocking banner shown when credit balance is low.
 *
 * Renders nothing when:
 *   - cloud features are disabled, OR
 *   - user is unauthenticated, OR
 *   - balance >= 5 minutes (the "low-credit" threshold per the spec).
 *
 * At balance == 0 it disables all processing buttons via uiStore.
 * Pure presentational here; deduction is gated server-side too.
 */

import { AlertTriangle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useCredits } from '../hooks/useCredits'
import { useAuthStore } from '../stores/authSlice'

const LOW_THRESHOLD = 5
const EMPTY_THRESHOLD = 0

export function CreditMeter(): JSX.Element | null {
  const authStatus = useAuthStore((s) => s.authStatus)
  const { creditBalance, loading } = useCredits()
  const navigate = useNavigate()

  if (authStatus !== 'authenticated' || loading) return null
  if (creditBalance > LOW_THRESHOLD) return null

  const isEmpty = creditBalance <= EMPTY_THRESHOLD

  return (
    <button
      type="button"
      onClick={() => navigate('/dashboard/billing')}
      className={
        isEmpty
          ? 'flex items-center gap-1.5 rounded border border-red-500/40 bg-red-500/15 px-2 py-1 text-2xs font-medium text-red-200 hover:bg-red-500/25'
          : 'flex items-center gap-1.5 rounded border border-amber-500/40 bg-amber-500/15 px-2 py-1 text-2xs font-medium text-amber-200 hover:bg-amber-500/25'
      }
      title={isEmpty ? 'You are out of credits' : `${creditBalance.toFixed(1)} min remaining`}
    >
      <AlertTriangle size={11} />
      {isEmpty
        ? 'No credits — Buy credits'
        : `${creditBalance.toFixed(1)} min left — Buy credits`}
    </button>
  )
}
