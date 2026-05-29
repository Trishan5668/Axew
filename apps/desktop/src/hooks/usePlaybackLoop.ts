import { useEffect } from 'react'
import {
  getActiveAudioClipAtTime,
  getActiveVideoClipAtTime,
  sourceToTimelineTime,
} from '../lib/playbackSync'
import { usePlaybackStore } from '../stores/playbackStore'
import { useProjectStore } from '../stores/projectStore'



export function usePlaybackLoop() {

  const playing = usePlaybackStore((s) => s.playing)

  const videoRef = usePlaybackStore((s) => s.videoRef)

  const audioRef = usePlaybackStore((s) => s.audioRef)

  const activeClip = usePlaybackStore((s) => s.activeClip)

  const loop = usePlaybackStore((s) => s.loop)

  const loopIn = usePlaybackStore((s) => s.loopIn)

  const loopOut = usePlaybackStore((s) => s.loopOut)

  const duration = usePlaybackStore((s) => s.duration)



  useEffect(() => {

    if (!playing) return



    let raf = 0

    const tick = () => {

      const state = usePlaybackStore.getState()

      const project = useProjectStore.getState().currentProject

      const timeline = project?.timeline



      if (!timeline) {

        raf = requestAnimationFrame(tick)

        return

      }



      const videoClip =

        getActiveVideoClipAtTime(timeline, state.currentTime) ?? state.activeClip

      const audioClip = getActiveAudioClipAtTime(timeline, state.currentTime)



      const ref = state.videoRef && videoClip ? state.videoRef : state.audioRef

      const clip = videoClip ?? audioClip



      if (ref && clip && ref.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && !ref.paused) {

        let timelineTime = sourceToTimelineTime(clip, ref.currentTime)



        if (loop && loopOut !== null && timelineTime >= loopOut) {

          timelineTime = loopIn ?? 0

          ref.currentTime = clip.mediaInPoint

        }



        if (duration > 0 && timelineTime >= duration) {

          if (loop) {

            timelineTime = loopIn ?? 0

            ref.currentTime = clip.mediaInPoint

          } else {

            state.pause()

            state.setCurrentTime(duration, { syncVideo: false })

            return

          }

        }



        if (Math.abs(timelineTime - state.currentTime) > 0.008) {

          state.setCurrentTime(timelineTime, { syncVideo: false })

        }

      } else if (!ref) {

        const { currentTime, frameRate, setCurrentTime, pause } = state

        const next = currentTime + 1 / frameRate

        if (duration > 0 && next >= duration) {

          pause()

          setCurrentTime(duration, { syncVideo: false })

        } else {

          setCurrentTime(next, { syncVideo: false })

        }

      }



      raf = requestAnimationFrame(tick)

    }



    raf = requestAnimationFrame(tick)

    return () => cancelAnimationFrame(raf)

  }, [playing, videoRef, audioRef, activeClip, loop, loopIn, loopOut, duration])

}

