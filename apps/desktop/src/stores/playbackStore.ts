import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'
import type { Clip } from '@shared/timeline'
import type { PlayheadState } from '@shared/timeline'
import { playbackLog, playbackWarn } from '../lib/playbackDebug'
import { timelineToSourceTime } from '../lib/playbackSync'

interface PlaybackState extends PlayheadState {
  videoRef: HTMLVideoElement | null
  audioRef: HTMLAudioElement | null
  activeClip: Clip | null
  previewReady: boolean
  mediaReady: boolean
  frameRate: number
  duration: number
  volume: number
  muted: boolean
  buffering: boolean
  playbackError: string | null
}

interface PlaybackActions {
  setCurrentTime: (time: number, options?: { syncVideo?: boolean }) => void
  setActiveClip: (clip: Clip | null) => void
  play: () => void
  pause: () => void
  togglePlay: () => void
  stop: () => void
  seekToFrame: (frame: number) => void
  nextFrame: () => void
  previousFrame: () => void
  setVolume: (volume: number) => void
  setMuted: (muted: boolean) => void
  setLoop: (loop: boolean) => void
  setLoopPoints: (inPoint: number | null, outPoint: number | null) => void
  setSpeed: (speed: number) => void
  setDuration: (duration: number) => void
  setFrameRate: (fps: number) => void
  setVideoRef: (ref: HTMLVideoElement | null) => void
  setAudioRef: (ref: HTMLAudioElement | null) => void
  setPreviewReady: (ready: boolean) => void
  setMediaReady: (ready: boolean) => void
  setBuffering: (buffering: boolean) => void
  setPlaybackError: (error: string | null) => void
  syncMediaToPlayhead: () => void
}

function mediaElementReady(el: HTMLMediaElement | null): boolean {
  return el !== null && el.readyState >= HTMLMediaElement.HAVE_METADATA
}

function syncVideoElement(
  videoRef: HTMLVideoElement | null,
  clip: Clip | null,
  timelineTime: number,
): void {
  if (!videoRef || !clip || !mediaElementReady(videoRef)) return
  const sourceTime = timelineToSourceTime(clip, timelineTime)
  const maxOut = clip.mediaOutPoint > clip.mediaInPoint ? clip.mediaOutPoint - 0.04 : undefined
  const clamped = Math.max(
    clip.mediaInPoint,
    maxOut !== undefined ? Math.min(maxOut, sourceTime) : sourceTime,
  )
  if (Math.abs(videoRef.currentTime - clamped) > 0.08) {
    try {
      videoRef.currentTime = clamped
      playbackLog('sync video currentTime', { clamped, timelineTime })
    } catch (err) {
      playbackWarn('sync video seek failed', err)
    }
  }
}

function syncAudioElement(
  audioRef: HTMLAudioElement | null,
  clip: Clip | null,
  timelineTime: number,
): void {
  if (!audioRef || !clip || !mediaElementReady(audioRef)) return
  const sourceTime = timelineToSourceTime(clip, timelineTime)
  const maxOut = clip.mediaOutPoint > clip.mediaInPoint ? clip.mediaOutPoint - 0.04 : undefined
  const clamped = Math.max(
    clip.mediaInPoint,
    maxOut !== undefined ? Math.min(maxOut, sourceTime) : sourceTime,
  )
  if (Math.abs(audioRef.currentTime - clamped) > 0.08) {
    try {
      audioRef.currentTime = clamped
    } catch {
      /* ignore */
    }
  }
}

export const usePlaybackStore = create<PlaybackState & PlaybackActions>()(
  subscribeWithSelector((set, get) => ({
    currentTime: 0,
    playing: false,
    loop: false,
    loopIn: null,
    loopOut: null,
    speed: 1,
    videoRef: null,
    audioRef: null,
    activeClip: null,
    previewReady: false,
    mediaReady: false,
    frameRate: 30,
    duration: 0,
    volume: 1,
    muted: false,
    buffering: false,
    playbackError: null,

    setActiveClip: (clip) => set({ activeClip: clip }),

    setCurrentTime: (time, options) => {
      const { duration, videoRef, audioRef, activeClip } = get()
      const syncVideo = options?.syncVideo !== false
      const clampedTime = Math.max(0, Math.min(duration || Infinity, time))
      set({ currentTime: clampedTime })
      if (syncVideo) {
        syncVideoElement(videoRef, activeClip, clampedTime)
        syncAudioElement(audioRef, activeClip, clampedTime)
      }
    },

    syncMediaToPlayhead: () => {
      const { currentTime, videoRef, audioRef, activeClip, mediaReady } = get()
      if (!mediaReady && !mediaElementReady(videoRef) && !mediaElementReady(audioRef)) return
      syncVideoElement(videoRef, activeClip, currentTime)
      syncAudioElement(audioRef, activeClip, currentTime)
    },

    play: () => {
      const { videoRef, audioRef, activeClip, speed } = get()
      if (!activeClip) {
        playbackWarn('play() called without active clip')
        return
      }
      set({ playing: true, playbackError: null })
      const rate = speed * (activeClip.speed ?? 1)

      const tryPlay = (el: HTMLMediaElement | null) => {
        if (!el) return
        el.playbackRate = rate
        const p = el.play()
        if (p) {
          p.catch((err) => {
            playbackWarn('play() rejected', err)
            set({ playing: false, playbackError: String(err) })
          })
        }
      }

      if (videoRef && mediaElementReady(videoRef)) tryPlay(videoRef)
      else if (audioRef && mediaElementReady(audioRef)) tryPlay(audioRef)
      else {
        playbackLog('play deferred until media ready')
      }
    },

    pause: () => {
      const { videoRef, audioRef } = get()
      set({ playing: false })
      videoRef?.pause()
      audioRef?.pause()
    },

    togglePlay: () => {
      const { playing } = get()
      if (playing) get().pause()
      else get().play()
    },

    stop: () => {
      const { videoRef, audioRef } = get()
      set({ playing: false, currentTime: 0 })
      videoRef?.pause()
      audioRef?.pause()
      if (videoRef && mediaElementReady(videoRef)) videoRef.currentTime = 0
      if (audioRef && mediaElementReady(audioRef)) audioRef.currentTime = 0
    },

    seekToFrame: (frame) => {
      const { frameRate } = get()
      get().pause()
      get().setCurrentTime(frame / frameRate)
    },

    nextFrame: () => {
      const { currentTime, frameRate } = get()
      get().pause()
      get().setCurrentTime(currentTime + 1 / frameRate)
    },

    previousFrame: () => {
      const { currentTime, frameRate } = get()
      get().pause()
      get().setCurrentTime(currentTime - 1 / frameRate)
    },

    setVolume: (volume) => {
      const { videoRef, audioRef } = get()
      const v = Math.max(0, Math.min(1, volume))
      set({ volume: v })
      if (videoRef) videoRef.volume = v
      if (audioRef) audioRef.volume = v
    },

    setMuted: (muted) => {
      const { videoRef, audioRef } = get()
      set({ muted })
      if (videoRef) videoRef.muted = muted
      if (audioRef) audioRef.muted = muted
    },

    setLoop: (loop) => set({ loop }),
    setLoopPoints: (inPoint, outPoint) => set({ loopIn: inPoint, loopOut: outPoint }),
    setSpeed: (speed) => {
      const { videoRef, audioRef, activeClip } = get()
      set({ speed })
      const rate = speed * (activeClip?.speed ?? 1)
      if (videoRef) videoRef.playbackRate = rate
      if (audioRef) audioRef.playbackRate = rate
    },

    setDuration: (duration) => set({ duration }),
    setFrameRate: (fps) => set({ frameRate: fps }),
    setVideoRef: (ref) =>
      set((state) => (state.videoRef === ref ? state : { videoRef: ref })),
    setAudioRef: (ref) =>
      set((state) => (state.audioRef === ref ? state : { audioRef: ref })),
    setPreviewReady: (ready) => set({ previewReady: ready }),
    setMediaReady: (ready) => set({ mediaReady: ready }),
    setBuffering: (buffering) => set({ buffering }),
    setPlaybackError: (error) => set({ playbackError: error }),
  })),
)
