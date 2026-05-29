import type { MediaFile, MediaType } from '@shared/media'
import type { TrackType } from '@shared/timeline'

export type DropValidationResult =
  | { valid: true }
  | { valid: false; reason: string }

/** Whether media can be placed on a track type. */
export function canDropMediaOnTrack(mediaType: MediaType, trackType: TrackType): boolean {
  switch (trackType) {
    case 'video':
      return mediaType === 'video' || mediaType === 'image' || mediaType === 'sequence'
    case 'audio':
      return mediaType === 'audio'
    case 'subtitle':
      return false
    default:
      return false
  }
}

export function validateMediaDrop(
  media: MediaFile,
  trackType: TrackType,
): DropValidationResult {
  if (canDropMediaOnTrack(media.type, trackType)) {
    return { valid: true }
  }

  const mediaLabel = media.type
  const trackLabel =
    trackType === 'video' ? 'video/image' : trackType === 'audio' ? 'audio' : 'subtitle'

  return {
    valid: false,
    reason: `${mediaLabel} media cannot be placed on ${trackType} tracks (expects ${trackLabel})`,
  }
}

export function getClipTypeIndicator(mediaType: MediaType): string {
  switch (mediaType) {
    case 'video':
      return 'VID'
    case 'audio':
      return 'AUD'
    case 'image':
      return 'IMG'
    case 'sequence':
      return 'SEQ'
    default:
      return '?'
  }
}
