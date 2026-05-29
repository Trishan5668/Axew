import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { subscribeWithSelector } from 'zustand/middleware'
import { nanoid } from 'nanoid'
import type { Clip, Marker, Timeline, Track, TrackType } from '@shared/timeline'
import { canDropMediaOnTrack } from '../lib/mediaValidation'
import {
  computeTimelineDuration,
  resolveNonOverlappingStart,
} from '../lib/timelineIntelligence'
import { useProjectStore } from './projectStore'

interface TimelineSnapshot {
  timestamp: number
  description: string
  timeline: Timeline
}

interface TimelineState {
  selectedClipIds: string[]
  selectedTrackId: string | null
  hoveredClipId: string | null
  zoom: number
  scrollX: number
  scrollY: number
  snapEnabled: boolean
  rippleEnabled: boolean
  undoStack: TimelineSnapshot[]
  redoStack: TimelineSnapshot[]
}

interface TimelineActions {
  selectClip: (clipId: string, multi?: boolean) => void
  deselectAll: () => void
  setZoom: (zoom: number) => void
  setScrollX: (x: number) => void
  setScrollY: (y: number) => void
  toggleSnap: () => void
  toggleRipple: () => void
  addTrack: (type: TrackType, name?: string) => void
  deleteTrack: (trackId: string) => void
  updateTrack: (trackId: string, updates: Partial<Track>) => void
  moveTrack: (trackId: string, newIndex: number) => void
  addClip: (
    trackId: string,
    clip: Omit<Clip, 'id' | 'trackId'>,
    options?: { recordUndo?: boolean },
  ) => string
  deleteClip: (clipId: string) => void
  updateClip: (clipId: string, updates: Partial<Clip>) => void
  moveClip: (clipId: string, trackId: string, startTime: number) => void
  splitClip: (clipId: string, time: number) => void
  trimClipIn: (clipId: string, deltaTime: number) => void
  trimClipOut: (clipId: string, deltaTime: number) => void
  addMarker: (marker: Omit<Marker, 'id'>) => void
  deleteMarker: (markerId: string) => void
  updateMarker: (markerId: string, updates: Partial<Marker>) => void
  pushUndoSnapshot: (description: string) => void
  undo: () => void
  redo: () => void
  syncTimelineDuration: () => void
}

const getTimeline = (): Timeline | null =>
  useProjectStore.getState().currentProject?.timeline ?? null

const setTimeline = (updater: (timeline: Timeline) => void) => {
  useProjectStore.setState((state) => {
    if (state.currentProject) {
      updater(state.currentProject.timeline)
      state.isDirty = true
    }
  })
}

export const useTimelineStore = create<TimelineState & TimelineActions>()(
  subscribeWithSelector(
    immer((set, get) => ({
      selectedClipIds: [],
      selectedTrackId: null,
      hoveredClipId: null,
      zoom: 100,
      scrollX: 0,
      scrollY: 0,
      snapEnabled: true,
      rippleEnabled: false,
      undoStack: [],
      redoStack: [],

      selectClip: (clipId, multi = false) => {
        set((state) => {
          if (multi) {
            const idx = state.selectedClipIds.indexOf(clipId)
            if (idx >= 0) state.selectedClipIds.splice(idx, 1)
            else state.selectedClipIds.push(clipId)
          } else {
            state.selectedClipIds = [clipId]
          }
        })
      },

      deselectAll: () => {
        set((state) => {
          state.selectedClipIds = []
          state.selectedTrackId = null
        })
      },

      setZoom: (zoom) => set((state) => {
        state.zoom = Math.max(10, Math.min(1000, zoom))
      }),
      setScrollX: (x) => set((state) => {
        state.scrollX = Math.max(0, x)
      }),
      setScrollY: (y) => set((state) => {
        state.scrollY = Math.max(0, y)
      }),
      toggleSnap: () => set((state) => {
        state.snapEnabled = !state.snapEnabled
      }),
      toggleRipple: () => set((state) => {
        state.rippleEnabled = !state.rippleEnabled
      }),

      addTrack: (type, name) => {
        setTimeline((timeline) => {
          const id = nanoid()
          const newTrack: Track = {
            id,
            timelineId: timeline.id,
            name:
              name ||
              `${type.charAt(0).toUpperCase() + type.slice(1)} ${timeline.tracks.filter((t) => t.type === type).length + 1}`,
            type,
            index: timeline.tracks.length,
            height: type === 'video' ? 80 : 60,
            locked: false,
            muted: false,
            visible: true,
            solo: false,
            color:
              type === 'video' ? '#1E3A5F' : type === 'audio' ? '#1E4F3A' : '#4F1E3A',
            clips: [],
          }
          timeline.tracks.push(newTrack)
        })
      },

      deleteTrack: (trackId) => {
        setTimeline((timeline) => {
          timeline.tracks = timeline.tracks.filter((t) => t.id !== trackId)
          timeline.tracks.forEach((t, i) => {
            t.index = i
          })
        })
      },

      updateTrack: (trackId, updates) => {
        setTimeline((timeline) => {
          const track = timeline.tracks.find((t) => t.id === trackId)
          if (track) Object.assign(track, updates)
        })
      },

      moveTrack: (trackId, newIndex) => {
        setTimeline((timeline) => {
          const idx = timeline.tracks.findIndex((t) => t.id === trackId)
          if (idx < 0) return
          const [track] = timeline.tracks.splice(idx, 1)
          timeline.tracks.splice(newIndex, 0, track)
          timeline.tracks.forEach((t, i) => {
            t.index = i
          })
        })
      },

      addClip: (trackId, clipData, options) => {
        if (options?.recordUndo !== false) get().pushUndoSnapshot('Add clip')
        const id = nanoid()
        setTimeline((timeline) => {
          const track = timeline.tracks.find((t) => t.id === trackId)
          if (track) {
            const project = useProjectStore.getState().currentProject
            const media = project?.mediaFiles[clipData.mediaId]
            if (media && !canDropMediaOnTrack(media.type, track.type)) return

            const startTime = resolveNonOverlappingStart(
              track.clips,
              clipData.startTime,
              clipData.duration,
            )
            const clip: Clip = {
              id,
              trackId,
              ...clipData,
              startTime,
              effects: clipData.effects ?? [],
              transitions: clipData.transitions ?? { in: null, out: null },
              keyframes: clipData.keyframes ?? [],
            }
            track.clips.push(clip)
            track.clips.sort((a, b) => a.startTime - b.startTime)
          }
          timeline.duration = computeTimelineDuration(timeline)
        })
        return id
      },

      deleteClip: (clipId) => {
        get().pushUndoSnapshot('Delete clip')
        setTimeline((timeline) => {
          for (const track of timeline.tracks) {
            const idx = track.clips.findIndex((c) => c.id === clipId)
            if (idx >= 0) {
              track.clips.splice(idx, 1)
              break
            }
          }
          timeline.duration = computeTimelineDuration(timeline)
        })
        set((state) => {
          state.selectedClipIds = state.selectedClipIds.filter((id) => id !== clipId)
        })
      },

      updateClip: (clipId, updates) => {
        setTimeline((timeline) => {
          for (const track of timeline.tracks) {
            const clip = track.clips.find((c) => c.id === clipId)
            if (clip) {
              Object.assign(clip, updates)
              track.clips.sort((a, b) => a.startTime - b.startTime)
              break
            }
          }
          timeline.duration = computeTimelineDuration(timeline)
        })
      },

      moveClip: (clipId, targetTrackId, startTime) => {
        get().pushUndoSnapshot('Move clip')
        setTimeline((timeline) => {
          let foundClip: Clip | null = null
          let sourceTrackId: string | null = null
          for (const track of timeline.tracks) {
            const idx = track.clips.findIndex((c) => c.id === clipId)
            if (idx >= 0) {
              sourceTrackId = track.id
              ;[foundClip] = track.clips.splice(idx, 1)
              break
            }
          }
          if (!foundClip || !sourceTrackId) return

          const restoreToSource = () => {
            const sourceTrack = timeline.tracks.find((t) => t.id === sourceTrackId)
            if (sourceTrack) {
              sourceTrack.clips.push(foundClip!)
              sourceTrack.clips.sort((a, b) => a.startTime - b.startTime)
            }
          }

          const targetTrack = timeline.tracks.find((t) => t.id === targetTrackId)
          if (!targetTrack) {
            restoreToSource()
            return
          }

          const project = useProjectStore.getState().currentProject
          const media = project?.mediaFiles[foundClip.mediaId]
          if (media && !canDropMediaOnTrack(media.type, targetTrack.type)) {
            restoreToSource()
            return
          }

          foundClip.trackId = targetTrackId
          foundClip.startTime = resolveNonOverlappingStart(
            targetTrack.clips,
            Math.max(0, startTime),
            foundClip.duration,
            foundClip.id,
          )
          targetTrack.clips.push(foundClip)
          targetTrack.clips.sort((a, b) => a.startTime - b.startTime)
          timeline.duration = computeTimelineDuration(timeline)
        })
      },

      splitClip: (clipId, time) => {
        get().pushUndoSnapshot('Split clip')
        const newId = nanoid()
        setTimeline((timeline) => {
          for (const track of timeline.tracks) {
            const clip = track.clips.find((c) => c.id === clipId)
            if (!clip) continue
            if (time <= clip.startTime || time >= clip.startTime + clip.duration) return
            const splitPoint = time - clip.startTime
            const originalDuration = clip.duration
            const originalOutPoint = clip.mediaOutPoint
            clip.duration = splitPoint
            clip.mediaOutPoint = clip.mediaInPoint + splitPoint
            const newClip: Clip = {
              ...JSON.parse(JSON.stringify(clip)),
              id: newId,
              startTime: time,
              duration: originalDuration - splitPoint,
              mediaInPoint: clip.mediaInPoint + splitPoint,
              mediaOutPoint: originalOutPoint,
            }
            track.clips.push(newClip)
            track.clips.sort((a, b) => a.startTime - b.startTime)
            break
          }
          timeline.duration = computeTimelineDuration(timeline)
        })
      },

      trimClipIn: (clipId, deltaTime) => {
        setTimeline((timeline) => {
          for (const track of timeline.tracks) {
            const clip = track.clips.find((c) => c.id === clipId)
            if (!clip) continue
            const minDuration = 1 / (timeline.frameRate || 30)
            const newDuration = clip.duration - deltaTime
            if (newDuration < minDuration) return
            const newInPoint = clip.mediaInPoint + deltaTime
            if (newInPoint < 0) return
            if (newInPoint >= clip.mediaOutPoint) return
            clip.startTime += deltaTime
            clip.mediaInPoint = newInPoint
            clip.duration = newDuration
            break
          }
          timeline.duration = computeTimelineDuration(timeline)
        })
      },

      trimClipOut: (clipId, deltaTime) => {
        setTimeline((timeline) => {
          for (const track of timeline.tracks) {
            const clip = track.clips.find((c) => c.id === clipId)
            if (!clip) continue
            const minDuration = 1 / (timeline.frameRate || 30)
            const newDuration = clip.duration + deltaTime
            if (newDuration < minDuration) return
            const newOutPoint = clip.mediaOutPoint + deltaTime
            if (newOutPoint <= clip.mediaInPoint) return
            clip.duration = newDuration
            clip.mediaOutPoint = newOutPoint
            break
          }
          timeline.duration = computeTimelineDuration(timeline)
        })
      },

      addMarker: (markerData) => {
        const id = nanoid()
        setTimeline((timeline) => {
          timeline.markers.push({ id, ...markerData })
          timeline.markers.sort((a, b) => a.time - b.time)
        })
      },

      deleteMarker: (markerId) => {
        setTimeline((timeline) => {
          timeline.markers = timeline.markers.filter((m) => m.id !== markerId)
        })
      },

      updateMarker: (markerId, updates) => {
        setTimeline((timeline) => {
          const marker = timeline.markers.find((m) => m.id === markerId)
          if (marker) Object.assign(marker, updates)
        })
      },

      pushUndoSnapshot: (description) => {
        const timeline = getTimeline()
        if (!timeline) return
        set((state) => {
          state.undoStack.push({
            timestamp: Date.now(),
            description,
            timeline: JSON.parse(JSON.stringify(timeline)),
          })
          if (state.undoStack.length > 50) state.undoStack.shift()
          state.redoStack = []
        })
      },

      undo: () => {
        const { undoStack } = get()
        if (undoStack.length === 0) return
        const currentTimeline = getTimeline()
        if (!currentTimeline) return
        const snapshot = undoStack[undoStack.length - 1]
        set((state) => {
          state.undoStack.pop()
          state.redoStack.push({
            timestamp: Date.now(),
            description: 'Redo',
            timeline: JSON.parse(JSON.stringify(currentTimeline)),
          })
        })
        setTimeline((tl) => {
          Object.assign(tl, snapshot.timeline)
        })
      },

      redo: () => {
        const { redoStack } = get()
        if (redoStack.length === 0) return
        const currentTimeline = getTimeline()
        if (!currentTimeline) return
        const snapshot = redoStack[redoStack.length - 1]
        set((state) => {
          state.redoStack.pop()
          state.undoStack.push({
            timestamp: Date.now(),
            description: 'Undo',
            timeline: JSON.parse(JSON.stringify(currentTimeline)),
          })
        })
        setTimeline((tl) => {
          Object.assign(tl, snapshot.timeline)
        })
      },

      syncTimelineDuration: () => {
        setTimeline((timeline) => {
          timeline.duration = computeTimelineDuration(timeline)
        })
      },
    })),
  ),
)
