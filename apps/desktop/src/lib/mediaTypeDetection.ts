import type { MediaType } from '@shared/media'
import { extname } from './pathUtils'
import type { MediaProbeResult } from './rustClient'

const VIDEO_EXTS = new Set([
  '.mp4', '.mov', '.mkv', '.avi', '.webm', '.mxf', '.m4v', '.ts', '.wmv', '.flv',
])
const AUDIO_EXTS = new Set([
  '.mp3', '.wav', '.aac', '.flac', '.ogg', '.m4a', '.opus', '.wma', '.aiff',
])
const IMAGE_EXTS = new Set([
  '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.dpx', '.exr', '.gif', '.webp',
])
const SEQUENCE_EXTS = new Set(['.dng', '.cr2', '.nef', '.arw'])

const MIME_MAP: Record<string, MediaType> = {
  'video/mp4': 'video',
  'video/quicktime': 'video',
  'video/x-matroska': 'video',
  'video/webm': 'video',
  'video/x-msvideo': 'video',
  'audio/mpeg': 'audio',
  'audio/wav': 'audio',
  'audio/x-wav': 'audio',
  'audio/flac': 'audio',
  'audio/ogg': 'audio',
  'audio/aac': 'audio',
  'image/jpeg': 'image',
  'image/png': 'image',
  'image/gif': 'image',
  'image/tiff': 'image',
  'image/webp': 'image',
}

function classifyByExtension(filePath: string): MediaType | null {
  const ext = extname(filePath).toLowerCase()
  if (VIDEO_EXTS.has(ext)) return 'video'
  if (AUDIO_EXTS.has(ext)) return 'audio'
  if (IMAGE_EXTS.has(ext)) return 'image'
  if (SEQUENCE_EXTS.has(ext)) return 'sequence'
  return null
}

function classifyByProbe(probe: MediaProbeResult): MediaType {
  const hasVideo = probe.has_video ?? !!(probe.width && probe.width > 0)
  const hasAudio = probe.has_audio ?? !!probe.audio_codec

  if (hasVideo && !hasAudio) return 'video'
  if (hasVideo && hasAudio) return 'video'
  if (hasAudio && !hasVideo) return 'audio'
  if (probe.width && probe.width > 0 && probe.height && probe.height > 0) return 'image'
  return 'video'
}

/** Classify media: ffprobe metadata → extension → safe default (audio if only audio ext hint). */
export function detectMediaType(
  filePath: string,
  probe: MediaProbeResult | null,
  mimeType?: string | null,
): MediaType {
  if (probe) {
    return classifyByProbe(probe)
  }

  if (mimeType && MIME_MAP[mimeType]) {
    return MIME_MAP[mimeType]
  }

  const fromExt = classifyByExtension(filePath)
  if (fromExt) return fromExt

  return 'video'
}

/** Default clip duration when unknown (images / stills). */
export function defaultClipDuration(mediaType: MediaType, probedDuration: number): number {
  if (probedDuration > 0) return probedDuration
  if (mediaType === 'image') return 5
  if (mediaType === 'audio') return 10
  return 5
}
