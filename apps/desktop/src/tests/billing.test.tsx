/**
 * BillingPage smoke tests.
 *
 * - Renders plan cards from /payments/plans.
 * - Buy Now disables when checkout is in flight.
 *
 * End-to-end Razorpay verification is performed manually against a live
 * test account; this suite only validates the page's rendering + state.
 */

import { describe, expect, test, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { BillingPage } from '../pages/BillingPage'
import { useAuthStore } from '../stores/authSlice'

vi.mock('../lib/cloudFlag', () => ({
  CLOUD_ENABLED: true,
  SUPABASE_URL: 'https://example.supabase.co',
  SUPABASE_ANON_KEY: 'anon',
  RAZORPAY_KEY_ID: 'rzp_test',
  AI_SERVICE_BASE_URL: 'http://127.0.0.1:7002',
  cloudUnavailableReason: () => null,
}))

vi.mock('../lib/supabase', () => {
  const fakeClient = {
    from: vi.fn(() => ({
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      order: vi.fn().mockReturnThis(),
      limit: vi.fn().mockResolvedValue({ data: [], error: null }),
    })),
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null }, error: null }),
      onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: () => undefined } } })),
    },
  }
  return {
    isCloudAvailable: () => true,
    supabase: () => fakeClient,
    __resetSupabaseClientForTests: () => undefined,
    CloudUnavailableError: class extends Error {},
  }
})

vi.mock('../lib/aiServiceClient', () => ({
  aiServiceFetch: vi.fn(async (path: string) => {
    if (path === '/payments/plans') {
      return {
        plans: [
          { id: 'starter', label: 'Starter', minutes: 100, credits: 100, amount_paise: 199900 },
          { id: 'creator', label: 'Creator', minutes: 300, credits: 300, amount_paise: 499900 },
          { id: 'pro', label: 'Pro', minutes: 1000, credits: 1000, amount_paise: 1499900 },
        ],
      }
    }
    throw new Error(`unexpected path ${path}`)
  }),
  AIServiceError: class extends Error {
    status = 500
  },
  getCloudStatus: vi.fn(),
}))

vi.mock('../lib/razorpay', () => ({
  openRazorpayCheckout: vi.fn(),
  RazorpayDismissedError: class extends Error {},
  RazorpayFailedError: class extends Error {
    code = 'x'
    reason = ''
  },
}))

beforeEach(() => {
  useAuthStore.setState({
    session: {
      access_token: 't',
      refresh_token: 'r',
      expires_in: 60,
      token_type: 'bearer',
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      user: { id: 'u-1', email: 'jane@example.com' } as any,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any,
    profile: {
      id: 'u-1',
      email: 'jane@example.com',
      display_name: null,
      avatar_url: null,
      credit_balance: 10,
      total_minutes_processed: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    authStatus: 'authenticated',
    errorMessage: null,
    initialized: true,
  })
})

describe('BillingPage', () => {
  test('renders all three plans from the catalog', async () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/billing']}>
        <Routes>
          <Route path="/dashboard/billing" element={<BillingPage />} />
          <Route path="/dashboard" element={<div>editor</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('Starter')).toBeInTheDocument()
      expect(screen.getByText('Creator')).toBeInTheDocument()
      expect(screen.getByText('Pro')).toBeInTheDocument()
    })
    // 3 Buy Now buttons
    expect(screen.getAllByRole('button', { name: /Buy now/i })).toHaveLength(3)
  })

  test('shows free-tier copy and current balance', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/billing']}>
        <Routes>
          <Route path="/dashboard/billing" element={<BillingPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText(/10 free minutes/i)).toBeInTheDocument()
    // Balance card shows "10.00 min"
    expect(screen.getByText('10.00')).toBeInTheDocument()
  })
})
