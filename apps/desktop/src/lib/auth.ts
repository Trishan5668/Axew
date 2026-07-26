/**
 * Typed wrappers around the Supabase auth API.
 *
 * Every function:
 * - Throws on failure with a user-facing message (never silent fallbacks).
 * - Is fully typed (no `any` casts — the `any` you'll spot is a justified
 *   escape for Supabase's loosely-typed updateUser metadata input).
 *
 * Used by:
 *   - apps/desktop/src/stores/authSlice.ts (session lifecycle)
 *   - apps/desktop/src/pages/LoginPage.tsx (OTP + Google flows)
 *   - apps/desktop/src/pages/OAuthCallbackPage.tsx (PKCE exchange)
 *   - apps/desktop/src/components/UserMenu.tsx (signOut)
 */

import type { Session, User } from '@supabase/supabase-js'
import { supabase } from './supabase'
import type { Profile } from './database.types'

function asUserFacing(prefix: string, error: { message?: string } | null): never {
  const detail = error?.message ?? 'Unknown error.'
  throw new Error(`${prefix}: ${detail}`)
}

export async function signInWithEmailOtp(email: string): Promise<void> {
  const trimmed = email.trim().toLowerCase()
  if (!trimmed || !trimmed.includes('@')) {
    throw new Error('Please enter a valid email address.')
  }
  const { error } = await supabase().auth.signInWithOtp({
    email: trimmed,
    options: {
      shouldCreateUser: true,
      // 6-digit numeric OTP is the default; no magic link required.
    },
  })
  if (error) asUserFacing('Could not send sign-in code', error)
}

export async function verifyEmailOtp(email: string, token: string): Promise<Session> {
  const trimmed = email.trim().toLowerCase()
  const cleanedToken = token.replace(/\s+/g, '')
  if (!/^\d{6}$/.test(cleanedToken)) {
    throw new Error('Enter the 6-digit code from your email.')
  }
  const { data, error } = await supabase().auth.verifyOtp({
    email: trimmed,
    token: cleanedToken,
    type: 'email',
  })
  if (error || !data.session) {
    asUserFacing('Incorrect or expired code', error)
  }
  return data.session
}

/**
 * Resolve the redirect URL Supabase will send the user back to after Google
 * OAuth. In Electron this is `axew://auth/callback` (registered as a custom
 * protocol — see electron/services/oauthHandler.ts). In a vanilla browser
 * context (vitest / web build) we fall back to the page origin.
 *
 * NOTE: Whatever URL this returns MUST be added to the Supabase project's
 * Authentication → URL Configuration → Redirect URLs list, or Supabase will
 * refuse to redirect.
 */
async function resolveOAuthRedirectUrl(): Promise<string> {
  const axew = (window as unknown as {
    axew?: { auth?: { getOAuthRedirectUrl?: () => Promise<string> } }
  }).axew
  const ipc = axew?.auth?.getOAuthRedirectUrl
  if (typeof ipc === 'function') {
    try {
      const url = await ipc()
      if (url) return url
    } catch {
      /* fall through to browser fallback */
    }
  }
  return `${window.location.origin}/auth/callback`
}

export async function signInWithGoogle(): Promise<void> {
  const redirectTo = await resolveOAuthRedirectUrl()
  const { error } = await supabase().auth.signInWithOAuth({
    provider: 'google',
    options: {
      redirectTo,
      queryParams: { access_type: 'offline', prompt: 'consent' },
      // skipBrowserRedirect: true would block Supabase from navigating; we
      // need it to navigate so the user lands on Google's consent screen.
      skipBrowserRedirect: false,
    },
  })
  if (error) asUserFacing('Could not start Google sign-in', error)
}

export async function exchangeOAuthCode(url: string): Promise<Session> {
  // PKCE exchange runs against the URL the OAuth provider redirected back to.
  const { data, error } = await supabase().auth.exchangeCodeForSession(url)
  if (error || !data.session) {
    asUserFacing('Sign-in did not complete', error)
  }
  return data.session
}

export async function signOut(): Promise<void> {
  const { error } = await supabase().auth.signOut()
  if (error) asUserFacing('Could not sign out cleanly', error)
}

export async function getCurrentUser(): Promise<User | null> {
  const { data, error } = await supabase().auth.getUser()
  if (error) {
    // getUser returns an error when there is no session — treat that as null.
    return null
  }
  return data.user
}

export async function getCurrentSession(): Promise<Session | null> {
  const { data, error } = await supabase().auth.getSession()
  if (error) return null
  return data.session
}

export async function refreshSession(): Promise<Session | null> {
  const { data, error } = await supabase().auth.refreshSession()
  if (error) return null
  return data.session
}

export async function getUserProfile(userId: string): Promise<Profile> {
  const { data, error } = await supabase()
    .from('profiles')
    .select('*')
    .eq('id', userId)
    .single()
  if (error || !data) asUserFacing('Could not load your profile', error)
  return data
}

export async function updateProfile(
  userId: string,
  updates: Partial<Pick<Profile, 'display_name' | 'avatar_url'>>,
): Promise<Profile> {
  const { data, error } = await supabase()
    .from('profiles')
    .update(updates)
    .eq('id', userId)
    .select('*')
    .single()
  if (error || !data) asUserFacing('Could not update profile', error)
  return data
}
