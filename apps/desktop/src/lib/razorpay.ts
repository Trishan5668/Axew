/**
 * Razorpay checkout integration.
 *
 * Dynamically loads checkout.js so the script never blocks page load and
 * never breaks the local-only build. openRazorpayCheckout() resolves to
 * a typed result on success and rejects with a structured Error on failure.
 */

import { RAZORPAY_KEY_ID } from './cloudFlag'

const SCRIPT_URL = 'https://checkout.razorpay.com/v1/checkout.js'
let scriptPromise: Promise<void> | null = null

function loadScript(): Promise<void> {
  if (scriptPromise) return scriptPromise
  scriptPromise = new Promise<void>((resolve, reject) => {
    if (typeof document === 'undefined') {
      reject(new Error('Razorpay checkout requires a browser environment.'))
      return
    }
    if (document.getElementById('axew-razorpay-script')) {
      resolve()
      return
    }
    const script = document.createElement('script')
    script.id = 'axew-razorpay-script'
    script.src = SCRIPT_URL
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => {
      scriptPromise = null
      reject(new Error('Could not load Razorpay checkout. Check your internet connection.'))
    }
    document.head.appendChild(script)
  })
  return scriptPromise
}

export interface RazorpayPrefill {
  name?: string
  email?: string
  contact?: string
}

export interface RazorpayOpenOptions {
  orderId: string
  amount: number
  currency?: string
  description: string
  prefill?: RazorpayPrefill
  notes?: Record<string, string>
  keyId?: string
}

export interface RazorpayPaymentResult {
  razorpay_payment_id: string
  razorpay_order_id: string
  razorpay_signature: string
}

interface RazorpayCheckoutOptions {
  key: string
  order_id: string
  amount: number
  currency: string
  name: string
  description: string
  prefill: RazorpayPrefill
  notes: Record<string, string>
  handler: (response: RazorpayPaymentResult) => void
  modal: {
    ondismiss: () => void
    escape: boolean
    backdropclose: boolean
  }
  theme: { color: string }
}

interface RazorpayErrorPayload {
  error: {
    code: string
    description: string
    source: string
    step: string
    reason: string
    metadata: Record<string, unknown>
  }
}

interface RazorpayInstance {
  open: () => void
  on: (event: 'payment.failed', handler: (payload: RazorpayErrorPayload) => void) => void
}

interface RazorpayConstructor {
  new (options: RazorpayCheckoutOptions): RazorpayInstance
}

declare global {
  interface Window {
    Razorpay?: RazorpayConstructor
  }
}

export class RazorpayDismissedError extends Error {
  constructor() {
    super('Payment cancelled.')
    this.name = 'RazorpayDismissedError'
  }
}

export class RazorpayFailedError extends Error {
  code: string
  reason: string
  constructor(code: string, description: string, reason: string) {
    super(description)
    this.name = 'RazorpayFailedError'
    this.code = code
    this.reason = reason
  }
}

export async function openRazorpayCheckout(
  options: RazorpayOpenOptions,
): Promise<RazorpayPaymentResult> {
  await loadScript()
  const RazorpayCtor = window.Razorpay
  if (!RazorpayCtor) {
    throw new Error('Razorpay SDK did not initialize. Refresh the page and try again.')
  }
  const keyId = options.keyId ?? RAZORPAY_KEY_ID
  if (!keyId) {
    throw new Error('Razorpay key id is not configured (VITE_RAZORPAY_KEY_ID).')
  }

  return new Promise<RazorpayPaymentResult>((resolve, reject) => {
    let settled = false
    const settleResolve = (result: RazorpayPaymentResult) => {
      if (settled) return
      settled = true
      resolve(result)
    }
    const settleReject = (err: Error) => {
      if (settled) return
      settled = true
      reject(err)
    }

    const instance = new RazorpayCtor({
      key: keyId,
      order_id: options.orderId,
      amount: options.amount,
      currency: options.currency ?? 'INR',
      name: 'AXEW',
      description: options.description,
      prefill: options.prefill ?? {},
      notes: options.notes ?? {},
      handler: (response) => settleResolve(response),
      modal: {
        escape: true,
        backdropclose: false,
        ondismiss: () => settleReject(new RazorpayDismissedError()),
      },
      theme: { color: '#1E3A5F' },
    })
    instance.on('payment.failed', (payload) => {
      const { code, description, reason } = payload.error
      settleReject(new RazorpayFailedError(code, description, reason))
    })
    instance.open()
  })
}
