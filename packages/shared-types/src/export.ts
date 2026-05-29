export interface ExportJob {
  id: string
  projectId: string
  timelineId: string
  outputPath: string
  preset: ExportPreset
  status: ExportStatus
  progress: number
  currentFrame: number
  totalFrames: number
  startedAt: number | null
  completedAt: number | null
  error: string | null
  estimatedTimeRemaining: number | null
}

export type ExportStatus =
  | 'queued'
  | 'preparing'
  | 'rendering'
  | 'encoding'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface ExportPreset {
  id: string
  name: string
  container: ExportContainer
  videoCodec: VideoCodec
  audioCodec: AudioCodec
  width: number
  height: number
  frameRate: number
  videoBitrate: number
  audioBitrate: number
  quality: number
  hardwareAcceleration: boolean
  customFFmpegArgs: string[]
}

export type ExportContainer = 'mp4' | 'mov' | 'mkv' | 'webm' | 'avi' | 'prores'
export type VideoCodec = 'h264' | 'h265' | 'vp9' | 'av1' | 'prores422' | 'prores4444'
export type AudioCodec = 'aac' | 'mp3' | 'opus' | 'pcm' | 'flac'

export const DEFAULT_EXPORT_PRESETS: ExportPreset[] = [
  {
    id: 'h264-1080p',
    name: 'H.264 1080p (YouTube)',
    container: 'mp4',
    videoCodec: 'h264',
    audioCodec: 'aac',
    width: 1920,
    height: 1080,
    frameRate: 30,
    videoBitrate: 8000,
    audioBitrate: 192,
    quality: 23,
    hardwareAcceleration: false,
    customFFmpegArgs: [],
  },
  {
    id: 'h265-4k',
    name: 'H.265 4K (Master)',
    container: 'mp4',
    videoCodec: 'h265',
    audioCodec: 'aac',
    width: 3840,
    height: 2160,
    frameRate: 30,
    videoBitrate: 20000,
    audioBitrate: 256,
    quality: 18,
    hardwareAcceleration: false,
    customFFmpegArgs: [],
  },
  {
    id: 'prores-proxy',
    name: 'ProRes 422 Proxy',
    container: 'mov',
    videoCodec: 'prores422',
    audioCodec: 'pcm',
    width: 1920,
    height: 1080,
    frameRate: 30,
    videoBitrate: 45000,
    audioBitrate: 1536,
    quality: 0,
    hardwareAcceleration: false,
    customFFmpegArgs: ['-profile:v', '0'],
  },
]
