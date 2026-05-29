import type { Transcript } from './ai'
import type { Timeline } from './timeline'
import type { MediaFile, MediaBinFolder } from './media'

export interface Project {
  id: string
  name: string
  description: string
  path: string
  timeline: Timeline
  mediaFiles: Record<string, MediaFile>
  mediaBin: {
    rootFolder: MediaBinFolder
    folders: Record<string, MediaBinFolder>
  }
  transcripts: Record<string, Transcript>
  settings: ProjectSettings
  createdAt: number
  updatedAt: number
  version: string
}

export interface ProjectSettings {
  timeline: {
    frameRate: number
    width: number
    height: number
    sampleRate: number
  }
  playback: {
    proxyEnabled: boolean
    proxyResolution: number
    cacheSize: number
  }
  ai: {
    preferredModel: string
    autoTranscribe: boolean
    silenceThresholdDb: number
    sceneDetectionSensitivity: number
  }
  export: {
    defaultPreset: string
    outputDirectory: string
  }
}

export interface RecentProject {
  id: string
  name: string
  path: string
  thumbnail: string | null
  lastOpenedAt: number
}
