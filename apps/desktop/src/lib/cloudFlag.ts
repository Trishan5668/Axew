/**
 * Single source of truth for whether AXEW's cloud features (Supabase auth,
 * Razorpay billing, OpusClip post-processing) are enabled in this build.
 *
 * AXEW is local-first by default. When VITE_AXEW_CLOUD_ENABLED !== 'true',
 * every cloud route, hook, and component renders nothing or short-circuits
 * to its local equivalent. NEVER read import.meta.env for these values
 * from anywhere else in the renderer.
 */

const isTrueFlag = (value: string | undefined): boolean =>
  typeof value === 'string' && ['1', 'true', 'yes', 'on'].includes(value.toLowerCase())

export const CLOUD_ENABLED: boolean = isTrueFlag(import.meta.env.VITE_AXEW_CLOUD_ENABLED as string | undefined)

export const SUPABASE_URL: string = (import.meta.env.VITE_SUPABASE_URL as string | undefined) ?? ''
export const SUPABASE_ANON_KEY: string = (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) ?? ''
export const RAZORPAY_KEY_ID: string = (import.meta.env.VITE_RAZORPAY_KEY_ID as string | undefined) ?? ''

export const AI_SERVICE_BASE_URL: string =
  (import.meta.env.VITE_AXEW_AI_BASE_URL as string | undefined) ?? 'http://127.0.0.1:7002'

/**
 * Returns a human-readable reason cloud features are unavailable, or null
 * if everything is in place. Used by RequireAuth and the BillingPage to
 * surface configuration errors with actionable copy instead of crashing.
 */
export function cloudUnavailableReason(): string | null {
  if (!CLOUD_ENABLED) {
    return 'Cloud mode is disabled in this build (set VITE_AXEW_CLOUD_ENABLED=true and rebuild).'
  }
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    return 'Supabase URL or anon key is not configured. Check VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.'
  }
  return null
}
