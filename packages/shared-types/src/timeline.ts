export type TrackType = 'video' | 'audio' | 'subtitle' | 'fx'

export interface Timeline {
  id: string
  projectId: string
  name: string
  duration: number
  frameRate: number
  width: number
  height: number
  sampleRate: number
  tracks: Track[]
  markers: Marker[]
  createdAt: number
  updatedAt: number
}

export interface Track {
  id: string
  timelineId: string
  name: string
  type: TrackType
  index: number
  height: number
  locked: boolean
  muted: boolean
  visible: boolean
  solo: boolean
  color: string
  clips: Clip[]
}

export interface Clip {
  id: string
  trackId: string
  mediaId: string
  name: string
  startTime: number
  duration: number
  mediaInPoint: number
  mediaOutPoint: number
  speed: number
  opacity: number
  volume: number
  disabled: boolean
  color: string | null
  effects: ClipEffect[]
  transitions: {
    in: Transition | null
    out: Transition | null
  }
  keyframes: Keyframe[]
  /** AI retrieval confidence when clip was placed by the engine */
  aiConfidence?: number
  aiConfidenceGrade?: 'HIGH' | 'MEDIUM' | 'LOW'
}

export interface ClipEffect {
  id: string
  type: string
  enabled: boolean
  params: Record<string, unknown>
}

export interface Transition {
  type: string
  duration: number
  params: Record<string, unknown>
}

export interface Keyframe {
  id: string
  property: string
  time: number
  value: unknown
  easing: 'linear' | 'ease-in' | 'ease-out' | 'ease-in-out' | 'bezier'
  bezierHandles?: [number, number, number, number]
}

export interface Marker {
  id: string
  time: number
  duration: number
  name: string
  color: string
  type: 'comment' | 'chapter' | 'sync' | 'ai'
  notes: string
}

export interface PlayheadState {
  currentTime: number
  playing: boolean
  loop: boolean
  loopIn: number | null
  loopOut: number | null
  speed: number
}
