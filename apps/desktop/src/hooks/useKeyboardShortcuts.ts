import { useEffect } from 'react'
import { usePlaybackStore } from '../stores/playbackStore'
import { useTimelineStore } from '../stores/timelineStore'
import { useAIStore } from '../stores/aiStore'

export function useKeyboardShortcuts() {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        return
      }

      const playback = usePlaybackStore.getState()
      const timeline = useTimelineStore.getState()

      if (e.code === 'Space') {
        e.preventDefault()
        playback.togglePlay()
        return
      }

      if (e.key === 'j' || e.key === 'J') {
        e.preventDefault()
        playback.previousFrame()
        return
      }

      if (e.key === 'k' || e.key === 'K') {
        e.preventDefault()
        playback.pause()
        return
      }

      if (e.key === 'l' || e.key === 'L') {
        e.preventDefault()
        if (playback.playing) playback.nextFrame()
        else playback.play()
        return
      }

      if (e.key === 'Home') {
        e.preventDefault()
        playback.setCurrentTime(0)
        return
      }

      if (e.key === 'End') {
        e.preventDefault()
        playback.setCurrentTime(playback.duration)
        return
      }

      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'd') {
        e.preventDefault()
        const ai = useAIStore.getState()
        ai.setDebugPanelOpen(!ai.debugPanelOpen)
        return
      }

      if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault()
        timeline.undo()
        return
      }

      if ((e.metaKey || e.ctrlKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
        e.preventDefault()
        timeline.redo()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])
}
