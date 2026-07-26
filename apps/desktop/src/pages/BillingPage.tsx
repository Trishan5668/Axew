/**
 * BillingPage — credit balance, plan cards, Razorpay checkout, payment history.
 *
 * Flow:
 *   1. POST /payments/create-order with plan_id
 *   2. Open Razorpay checkout modal
 *   3. On success, poll Supabase profiles every 2s (max 10 attempts) for the
 *      credit increase, then show success.
 *   4. On error, show inline message with the Razorpay error description.
 */

import { ArrowLeft, CheckCircle2, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AIServiceError, aiServiceFetch } from '../lib/aiServiceClient'
import {
  RazorpayDismissedError,
  RazorpayFailedError,
  openRazorpayCheckout,
} from '../lib/razorpay'
import { supabase, isCloudAvailable } from '../lib/supabase'
import type { Payment, PlanId } from '../lib/database.types'
import { useAuthStore } from '../stores/authSlice'
import { useCredits } from '../hooks/useCredits'

interface PlanInfo {
  id: PlanId
  label: string
  minutes: number
  credits: number
  amount_paise: number
}

interface PlansResponse {
  plans: PlanInfo[]
  currency: string
}

interface CreateOrderResponse {
  order_id: string
  payment_id: string
  amount: number
  currency: string
  key_id: string
  plan_label: string
  credits_purchased: number
}

interface PaymentStatus {
  payment_id: string
  status: 'created' | 'paid' | 'failed' | 'refunded'
  failure_reason: string | null
}

/**
 * Poll the reconciliation endpoint until the payment row reaches a terminal
 * state, or until we run out of attempts. Resolves with the final status
 * (or null on timeout).
 */
async function pollPaymentStatus(
  paymentId: string,
  maxAttempts = 10,
  intervalMs = 2000,
): Promise<PaymentStatus | null> {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
    try {
      const status = await aiServiceFetch<PaymentStatus>(`/payments/${paymentId}/status`)
      if (status.status === 'paid' || status.status === 'failed' || status.status === 'refunded') {
        return status
      }
    } catch {
      // 404 during the very first attempt is possible if the webhook beats
      // our select-after-insert; keep polling.
    }
  }
  return null
}

function formatRupees(paise: number): string {
  const rupees = paise / 100
  return rupees.toLocaleString('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  })
}

export function BillingPage(): JSX.Element {
  const navigate = useNavigate()
  const { session, profile } = useAuthStore()
  const { creditBalance, totalMinutesProcessed, refresh } = useCredits()
  const [plans, setPlans] = useState<PlanInfo[]>([])
  const [history, setHistory] = useState<Payment[]>([])
  const [busyPlan, setBusyPlan] = useState<PlanId | null>(null)
  const [planError, setPlanError] = useState<Record<PlanId, string | null>>({
    starter: null,
    creator: null,
    pro: null,
  })
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [loadingPlans, setLoadingPlans] = useState(true)

  useEffect(() => {
    aiServiceFetch<PlansResponse>('/payments/plans', { requireAuth: false })
      .then((resp) => setPlans(resp.plans))
      .catch((err: unknown) => {
        // Non-fatal — we still render the page.
        const message = err instanceof Error ? err.message : String(err)
        setPlanError((prev) => ({ ...prev, starter: message }))
      })
      .finally(() => setLoadingPlans(false))
  }, [])

  useEffect(() => {
    if (!isCloudAvailable() || !session?.user.id) return
    supabase()
      .from('payments')
      .select('*')
      .eq('user_id', session.user.id)
      .order('created_at', { ascending: false })
      .limit(20)
      .then(({ data, error }) => {
        if (!error && data) setHistory(data as Payment[])
      })
  }, [session?.user.id, successMessage])

  const handleBuy = async (plan: PlanInfo) => {
    setPlanError((prev) => ({ ...prev, [plan.id]: null }))
    setSuccessMessage(null)
    setBusyPlan(plan.id)

    try {
      const order = await aiServiceFetch<CreateOrderResponse>('/payments/create-order', {
        method: 'POST',
        body: { plan_id: plan.id },
      })

      const result = await openRazorpayCheckout({
        orderId: order.order_id,
        amount: order.amount,
        currency: order.currency,
        description: `${order.plan_label} — ${order.credits_purchased} credits`,
        keyId: order.key_id,
        prefill: {
          name: profile?.display_name ?? '',
          email: profile?.email ?? session?.user.email ?? '',
        },
        notes: { axew_plan_id: plan.id, axew_payment_id: order.payment_id },
      })

      // Webhook will apply credits server-side. Use the reconciliation
      // endpoint to track this specific payment's lifecycle — that's
      // more reliable than watching the profile balance (which could
      // already be moving due to OpusClip deductions).
      const final = await pollPaymentStatus(order.payment_id)
      await refresh()

      if (final?.status === 'paid') {
        setSuccessMessage(
          `Payment received. ${plan.credits} credits added to your account.`,
        )
      } else if (final?.status === 'failed') {
        setPlanError((prev) => ({
          ...prev,
          [plan.id]: final.failure_reason ?? 'Payment was declined by the gateway.',
        }))
      } else {
        setSuccessMessage(
          `Payment captured (${result.razorpay_payment_id}). Your credits will appear ` +
          `shortly — refresh this page in a minute if you don't see them.`,
        )
      }
    } catch (err) {
      let message = 'Payment failed. Please try again.'
      if (err instanceof RazorpayDismissedError) {
        message = 'Payment was cancelled. No charge was made.'
      } else if (err instanceof RazorpayFailedError) {
        message = `${err.message} (code: ${err.code})`
      } else if (err instanceof AIServiceError) {
        message = err.message
      } else if (err instanceof Error) {
        message = err.message
      }
      setPlanError((prev) => ({ ...prev, [plan.id]: message }))
    } finally {
      setBusyPlan(null)
    }
  }

  return (
    <div className="h-full w-full overflow-y-auto bg-axew-bg text-axew-text">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <button
          type="button"
          onClick={() => navigate('/dashboard')}
          className="mb-4 flex items-center gap-1 text-2xs text-axew-textMuted hover:text-axew-text"
        >
          <ArrowLeft size={11} /> Back to editor
        </button>

        <header className="mb-6">
          <h1 className="text-xl font-semibold">Billing & credits</h1>
          <p className="mt-1 text-xs text-axew-textMuted">
            Your account includes 10 free minutes. Buy credits to keep enhancing clips with OpusClip.
          </p>
        </header>

        <section className="mb-6 grid grid-cols-2 gap-4">
          <div className="rounded-lg border border-axew-border bg-axew-surface p-4">
            <p className="text-2xs uppercase tracking-wide text-axew-textDim">Credit balance</p>
            <p className="mt-1 text-2xl font-semibold text-axew-ai">
              {creditBalance.toFixed(2)} <span className="text-sm text-axew-textMuted">min</span>
            </p>
          </div>
          <div className="rounded-lg border border-axew-border bg-axew-surface p-4">
            <p className="text-2xs uppercase tracking-wide text-axew-textDim">Total minutes processed</p>
            <p className="mt-1 text-2xl font-semibold text-axew-text">
              {totalMinutesProcessed.toFixed(2)} <span className="text-sm text-axew-textMuted">min</span>
            </p>
          </div>
        </section>

        {successMessage && (
          <div
            role="status"
            className="mb-4 flex items-center gap-2 rounded border border-green-500/40 bg-green-500/10 p-3 text-xs text-green-200"
          >
            <CheckCircle2 size={14} /> {successMessage}
          </div>
        )}

        <section>
          <h2 className="mb-2 text-sm font-medium text-axew-textMuted">Plans</h2>
          {loadingPlans && (
            <p className="text-xs text-axew-textDim">Loading plans…</p>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {plans.map((plan) => {
              const perMin = (plan.amount_paise / 100 / plan.minutes).toFixed(2)
              return (
                <div
                  key={plan.id}
                  className="flex flex-col rounded-lg border border-axew-border bg-axew-surface p-4"
                >
                  <p className="text-sm font-medium text-axew-text">{plan.label}</p>
                  <p className="mt-1 text-xs text-axew-textMuted">{plan.minutes} minutes</p>
                  <p className="mt-3 text-xl font-semibold">
                    {formatRupees(plan.amount_paise)}
                  </p>
                  <p className="mt-0.5 text-2xs text-axew-textDim">≈ ₹{perMin} per minute</p>
                  <button
                    type="button"
                    onClick={() => handleBuy(plan)}
                    disabled={busyPlan !== null}
                    className="mt-3 flex items-center justify-center gap-1 rounded bg-axew-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-axew-accentHover disabled:opacity-40"
                  >
                    {busyPlan === plan.id ? (
                      <>
                        <Loader2 size={12} className="animate-spin" /> Processing…
                      </>
                    ) : (
                      'Buy now'
                    )}
                  </button>
                  {planError[plan.id] && (
                    <p role="alert" className="mt-2 text-2xs text-red-300">
                      {planError[plan.id]}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </section>

        <section className="mt-8">
          <h2 className="mb-2 text-sm font-medium text-axew-textMuted">Payment history</h2>
          {history.length === 0 ? (
            <p className="text-xs text-axew-textDim">No payments yet.</p>
          ) : (
            <table className="w-full border-collapse text-2xs">
              <thead className="border-b border-axew-border text-axew-textDim">
                <tr>
                  <th className="py-1 text-left font-medium">Date</th>
                  <th className="py-1 text-left font-medium">Plan</th>
                  <th className="py-1 text-right font-medium">Amount</th>
                  <th className="py-1 text-right font-medium">Credits</th>
                  <th className="py-1 text-right font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="text-axew-text">
                {history.map((row) => (
                  <tr key={row.id} className="border-b border-axew-border/40">
                    <td className="py-1.5">{new Date(row.created_at).toLocaleString()}</td>
                    <td className="py-1.5 capitalize">{row.plan_id}</td>
                    <td className="py-1.5 text-right">{formatRupees(row.amount_inr)}</td>
                    <td className="py-1.5 text-right">{row.credits_purchased}</td>
                    <td className="py-1.5 text-right capitalize">{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  )
}
