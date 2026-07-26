/**
 * Supabase client (browser/renderer process).
 *
 * Lazily constructed so importing this module never throws — required so
 * that AXEW's local-only build (without VITE_SUPABASE_* set) still loads.
 * Callers MUST handle the null-return case; the safe wrapper supabase()
 * surfaces a structured error.
 */

import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import { CLOUD_ENABLED, SUPABASE_ANON_KEY, SUPABASE_URL } from './cloudFlag'
import type { Database } from './database.types'

let _client: SupabaseClient<Database> | null = null

export class CloudUnavailableError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'CloudUnavailableError'
  }
}

export function isCloudAvailable(): boolean {
  return CLOUD_ENABLED && Boolean(SUPABASE_URL) && Boolean(SUPABASE_ANON_KEY)
}

export function supabase(): SupabaseClient<Database> {
  if (_client) return _client
  if (!isCloudAvailable()) {
    throw new CloudUnavailableError(
      'AXEW cloud mode is not configured. Set VITE_AXEW_CLOUD_ENABLED=true, VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY before launching.',
    )
  }
  _client = createClient<Database>(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: {
      autoRefreshToken: true,
      persistSession: true,
      detectSessionInUrl: true,
      flowType: 'pkce',
      storageKey: 'axew.auth.session',
    },
    global: {
      headers: { 'x-axew-client': 'desktop@0.1.0' },
    },
  })
  return _client
}

/**
 * Test-only helper to reset the singleton between specs.
 * @internal
 */
export function __resetSupabaseClientForTests(client: SupabaseClient<Database> | null): void {
  _client = client
}
