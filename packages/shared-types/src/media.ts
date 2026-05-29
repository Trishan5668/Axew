export type MediaType = 'video' | 'audio' | 'image' | 'sequence'

export interface MediaMetadata {
  [key: string]: string | number | boolean | null
}

export interface MediaFile {
  id: string
  name: string
  path: string
  type: MediaType
  duration: number
  width: number
  height: number
  fps: number
  codec: string
  audioCodec: string | null
  sampleRate: number | null
  channels: number | null
  bitrate: number
  fileSize: number
  thumbnail: string | null
  createdAt: number
  updatedAt: number
  metadata: MediaMetadata
}

export interface MediaBinFolder {
  id: string
  name: string
  parentId: string | null
  children: string[]
  mediaIds: string[]
}
