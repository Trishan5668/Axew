/**
 * Thin wrapper around the AXEW AI service (FastAPI) used by cloud features.
 *
 * Adds the Supabase JWT to every cloud-only request. NEVER use this for
 * routes that should work in local mode (e.g. /api/chat, /api/retrieval) —
 * those have their own client in lib/aiClient.ts.
 */

import { AI_SERVICE_BASE_URL } from './cloudFlag'
import { getCurrentSession } from './auth'

export class AIServiceError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'AIServiceError'
    this.status = status
  }
}

interface FetchOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  requireAuth?: boolean
  signal?: AbortSignal
}

export async function aiServiceFetch<TResponse>(
  path: string,
  { method = 'GET', body, requireAuth = true, signal }: FetchOptions = {},
): Promise<TResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  }

  if (requireAuth) {
    const session = await getCurrentSession()
    if (!session) {
      throw new AIServiceError(401, 'You are signed out. Please sign in to continue.')
    }
    headers.Authorization = `Bearer ${session.access_token}`
  }

  const resp = await fetch(`${AI_SERVICE_BASE_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })

  if (!resp.ok) {
    let detail = `Request to ${path} failed (${resp.status}).`
    try {
      const data = (await resp.json()) as { detail?: unknown }
      if (typeof data.detail === 'string' && data.detail) detail = data.detail
    } catch {
      /* response wasn't JSON */
    }
    throw new AIServiceError(resp.status, detail)
  }

  if (resp.status === 204) {
    return undefined as TResponse
  }

  return (await resp.json()) as TResponse
}

export interface CloudStatusResponse {
  enabled: boolean
  supabase_configured: boolean
  razorpay_configured: boolean
  opusclip_configured: boolean
}

export async function getCloudStatus(): Promise<CloudStatusResponse | null> {
  try {
    return await aiServiceFetch<CloudStatusResponse>('/cloud/status', { requireAuth: false })
  } catch {
    return null
  }
}
