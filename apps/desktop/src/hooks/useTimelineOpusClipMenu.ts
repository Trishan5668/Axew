<<<<<<< HEAD
import { useCallback, useEffect, useMemo, useState } from 'react'
import { isCloudEnabled } from '../lib/cloudConfig'
import { useOpusclipHealth, type OpusClipHealthState } from './useOpusclipHealth'

export interface OpusClipMenuItem {
  id: string
  label: string
  disabled: boolean
  onSelect: () => void
}

export interface TimelineOpusClipMenuState {
  open: boolean
  x: number
  y: number
  clipId: string | null
}

export interface TimelineOpusClipMenu {
  /** Whether the OpusClip cloud integration is enabled in this build. */
  enabled: boolean
  /** Current OpusClip API health (loading/online/offline). */
  status: OpusClipHealthState
  /** Context-menu open state + position. */
  state: TimelineOpusClipMenuState
  /** Menu items to render. Empty when cloud is disabled. */
  items: OpusClipMenuItem[]
  /** Open the OpusClip context menu for a clip. No-op when cloud disabled. */
  openMenu: (event: { clientX: number; clientY: number; preventDefault?: () => void }, clipId: string) => void
  /** Close the context menu. */
  closeMenu: () => void
}

const CLOSED: TimelineOpusClipMenuState = { open: false, x: 0, y: 0, clipId: null }

export interface UseTimelineOpusClipMenuOptions {
  /** Callback invoked when the user requests sending a clip to OpusClip. */
  onSendToOpusClip?: (clipId: string) => void
}

/**
 * Timeline ⇄ OpusClip context-menu controller.
 *
 * HOOK-SAFETY CONTRACT (this is the fix for the EXE-only crash):
 *   - Every hook below (`useOpusclipHealth`, `useState`, `useCallback`,
 *     `useMemo`, `useEffect`) is called UNCONDITIONALLY on every render.
 *   - The `cloudEnabled` flag is computed from a plain function and only used
 *     to change *behaviour* (no-op handlers, empty menu) — never to decide
 *     whether a hook runs.
 *
 * This guarantees the renderer executes an identical hook sequence in
 * development (`pnpm dev` / `pnpm electron:dev`) and in the packaged
 * production EXE, eliminating "Rendered more hooks than during the previous
 * render".
 */
export function useTimelineOpusClipMenu(
  options: UseTimelineOpusClipMenuOptions = {},
): TimelineOpusClipMenu {
  const { onSendToOpusClip } = options

  // Plain function — safe to read during render without affecting hook order.
  const cloudEnabled = isCloudEnabled()

  // Always called; internally no-ops (no polling) when cloud is disabled.
  const health = useOpusclipHealth({ enabled: cloudEnabled })

  const [state, setState] = useState<TimelineOpusClipMenuState>(CLOSED)

  const closeMenu = useCallback(() => {
    setState((prev) => (prev.open ? CLOSED : prev))
  }, [])

  const openMenu = useCallback<TimelineOpusClipMenu['openMenu']>(
    (event, clipId) => {
      event.preventDefault?.()
      if (!cloudEnabled) return
      setState({ open: true, x: event.clientX, y: event.clientY, clipId })
    },
    [cloudEnabled],
  )

  const items = useMemo<OpusClipMenuItem[]>(() => {
    if (!cloudEnabled) return []
    const clipId = state.clipId
    const online = health.state === 'online'
    return [
      {
        id: 'send-to-opusclip',
        label:
          health.state === 'loading'
            ? 'Send to OpusClip (checking…)'
            : online
              ? 'Send to OpusClip'
              : 'Send to OpusClip (offline)',
        disabled: !online || !clipId,
        onSelect: () => {
          if (clipId && online) onSendToOpusClip?.(clipId)
          setState(CLOSED)
        },
      },
    ]
  }, [cloudEnabled, health.state, state.clipId, onSendToOpusClip])

  // Close the menu on Escape or outside interaction. Always registered so the
  // effect count never changes between renders/builds.
  useEffect(() => {
    if (!state.open) return

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeMenu()
    }
    const onPointer = () => closeMenu()

    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerdown', onPointer)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('pointerdown', onPointer)
    }
  }, [state.open, closeMenu])

  return {
    enabled: cloudEnabled,
    status: health.state,
    state,
    items,
    openMenu,
    closeMenu,
=======
/**
 * useTimelineOpusClipMenu — exposes the "Send to OpusClip" action used by
 * Timeline.tsx's right-click context menu.
 *
 * Returns null when cloud mode is disabled, so the consumer simply doesn't
 * render the menu item in that case.
 */

import { useCallback } from 'react'
import { isCloudAvailable } from '../lib/supabase'
import { useAuthStore } from '../stores/authSlice'
import { useOpusclipStore } from '../stores/opusclipSlice'
import { useTimelineStore } from '../stores/timelineStore'
import { useProjectStore } from '../stores/projectStore'
import type { Clip } from '@shared/timeline'

export interface OpusClipMenuItem {
  label: string
  enabled: boolean
  onClick: () => void
}

export function useTimelineOpusClipMenu(): OpusClipMenuItem | null {
  const addClipRange = useOpusclipStore((s) => s.addClipRange)
  const selectedClipIds = useTimelineStore((s) => s.selectedClipIds)
  const authStatus = useAuthStore((s) => s.authStatus)

  const handler = useCallback(() => {
    const project = useProjectStore.getState().currentProject
    if (!project) return
    const selectedClips: Clip[] = []
    for (const track of project.timeline.tracks) {
      for (const clip of track.clips) {
        if (selectedClipIds.includes(clip.id)) selectedClips.push(clip)
      }
    }
    for (const clip of selectedClips) {
      addClipRange({
        start_seconds: clip.startTime,
        end_seconds: clip.startTime + clip.duration,
        label: clip.name ?? null,
      })
    }
  }, [addClipRange, selectedClipIds])

  if (!isCloudAvailable()) return null

  return {
    label: 'Send to OpusClip',
    enabled: authStatus === 'authenticated' && selectedClipIds.length > 0,
    onClick: handler,
>>>>>>> 1267c0e (v1.1)
  }
}
