import { useCallback, useEffect, useMemo, useState } from 'react'
import { isCloudEnabled } from '../lib/cloudConfig'
import { useAuthStore } from '../stores/authSlice'
import { useOpusclipStore } from '../stores/opusclipSlice'
import { useProjectStore } from '../stores/projectStore'
import { useOpusclipHealth, type OpusClipHealthState } from './useOpusclipHealth'

export interface OpusClipMenuItem {
  id: string
  label: string
  disabled: boolean
  hint?: string
  onSelect: () => void
}

export interface TimelineOpusClipMenuState {
  open: boolean
  x: number
  y: number
  clipId: string | null
}

export interface TimelineOpusClipMenu {
  enabled: boolean
  status: OpusClipHealthState
  state: TimelineOpusClipMenuState
  items: OpusClipMenuItem[]
  openMenu: (event: { clientX: number; clientY: number; preventDefault?: () => void }, clipId: string) => void
  closeMenu: () => void
}

export interface UseTimelineOpusClipMenuOptions {
  onSendToOpusClip?: (clipId: string) => void
}

const CLOSED: TimelineOpusClipMenuState = { open: false, x: 0, y: 0, clipId: null }

function queueClipForOpusClip(clipId: string): void {
  const project = useProjectStore.getState().currentProject
  if (!project) return

  for (const track of project.timeline.tracks) {
    const clip = track.clips.find((candidate) => candidate.id === clipId)
    if (!clip) continue

    useOpusclipStore.getState().addClipRange({
      start_seconds: clip.startTime,
      end_seconds: clip.startTime + clip.duration,
      label: clip.name ?? null,
    })
    return
  }
}

/**
 * Timeline <-> OpusClip context-menu controller.
 *
 * Hook-safety contract: every hook below is called unconditionally on every
 * render. Runtime flags only change behavior, never which hooks run.
 */
export function useTimelineOpusClipMenu(
  options: UseTimelineOpusClipMenuOptions = {},
): TimelineOpusClipMenu {
  const { onSendToOpusClip } = options
  const cloudEnabled = isCloudEnabled()
  const health = useOpusclipHealth({ enabled: cloudEnabled })
  const authStatus = useAuthStore((s) => s.authStatus)
  const [state, setState] = useState<TimelineOpusClipMenuState>(CLOSED)

  const closeMenu = useCallback(() => {
    setState((prev) => (prev.open ? CLOSED : prev))
  }, [])

  const openMenu = useCallback<TimelineOpusClipMenu['openMenu']>(
    (event, clipId) => {
      event.preventDefault?.()
      if (!cloudEnabled || !clipId) return
      setState({ open: true, x: event.clientX, y: event.clientY, clipId })
    },
    [cloudEnabled],
  )

  const items = useMemo<OpusClipMenuItem[]>(() => {
    if (!cloudEnabled) return []

    const clipId = state.clipId
    const online = health.state === 'online'
    const authenticated = authStatus === 'authenticated'
    const disabled = !online || !authenticated || !clipId
    const hint = !clipId
      ? 'Select a clip first'
      : !authenticated
        ? 'Sign in required'
        : !online
          ? 'Offline'
          : undefined

    return [
      {
        id: 'send-to-opusclip',
        label:
          health.state === 'loading'
            ? 'Send to OpusClip (checking...)'
            : online
              ? 'Send to OpusClip'
              : 'Send to OpusClip (offline)',
        disabled,
        hint,
        onSelect: () => {
          if (clipId && !disabled) {
            if (onSendToOpusClip) onSendToOpusClip(clipId)
            else queueClipForOpusClip(clipId)
          }
          setState(CLOSED)
        },
      },
    ]
  }, [authStatus, cloudEnabled, health.state, state.clipId, onSendToOpusClip])

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
  }
}
