import type { MediaFile } from '@shared/media'

import { nanoid } from 'nanoid'

import { basename } from './pathUtils'

import { defaultClipDuration, detectMediaType } from './mediaTypeDetection'

import { generateThumbnail, probeMedia } from './rustClient'



const importedPaths = new Set<string>()



export function clearImportCache(): void {

  importedPaths.clear()

}



export function isPathAlreadyImported(path: string, existing: Record<string, MediaFile>): boolean {

  const normalized = path.replace(/\\/g, '/').toLowerCase()

  if (importedPaths.has(normalized)) return true

  return Object.values(existing).some(

    (m) => m.path.replace(/\\/g, '/').toLowerCase() === normalized,

  )

}



export async function importMediaFiles(

  filePaths: string[],

  existing: Record<string, MediaFile> = {},

): Promise<MediaFile[]> {

  const results: MediaFile[] = []



  for (const filePath of filePaths) {

    const normalized = filePath.replace(/\\/g, '/').toLowerCase()

    if (isPathAlreadyImported(filePath, existing)) continue



    const id = nanoid()

    const name = basename(filePath)

    const now = Date.now()



    const probeData = await probeMedia(filePath)

    const type = detectMediaType(filePath, probeData)

    const duration = defaultClipDuration(type, probeData?.duration ?? 0)



    let thumbnail: string | null = null

    if (type === 'video' || type === 'sequence') {

      thumbnail = await generateThumbnail(filePath, 1.0)

    } else if (type === 'image') {

      thumbnail = filePath

    }



    const mediaFile: MediaFile = {

      id,

      name,

      path: filePath,

      type,

      duration,

      width: probeData?.width ?? 0,

      height: probeData?.height ?? 0,

      fps: probeData?.fps ?? 30,

      codec: probeData?.video_codec ?? probeData?.audio_codec ?? 'unknown',

      audioCodec: probeData?.audio_codec ?? null,

      sampleRate: probeData?.sample_rate ?? null,

      channels: probeData?.channels ?? null,

      bitrate: probeData?.bitrate ?? 0,

      fileSize: 0,

      thumbnail,

      createdAt: now,

      updatedAt: now,

      metadata: probeData

        ? { probed: true, has_video: probeData.has_video ?? false, has_audio: probeData.has_audio ?? false }

        : {},

    }



    importedPaths.add(normalized)

    results.push(mediaFile)

  }



  return results

}

function detectBrowserMediaType(file: File): MediaFile['type'] {
  if (file.type.startsWith('video/')) return 'video'
  if (file.type.startsWith('audio/')) return 'audio'
  if (file.type.startsWith('image/')) return 'image'
  return detectMediaType(file.name, null)
}

function probeBrowserMedia(_file: File, url: string, type: MediaFile['type']): Promise<{
  duration: number
  width: number
  height: number
}> {
  if (type === 'image') {
    return new Promise((resolve) => {
      const img = new Image()
      img.onload = () => resolve({ duration: 0, width: img.naturalWidth, height: img.naturalHeight })
      img.onerror = () => resolve({ duration: 0, width: 0, height: 0 })
      img.src = url
    })
  }

  if (type === 'video' || type === 'audio') {
    return new Promise((resolve) => {
      const media = document.createElement(type === 'video' ? 'video' : 'audio')
      media.preload = 'metadata'
      media.onloadedmetadata = () => {
        resolve({
          duration: Number.isFinite(media.duration) ? media.duration : 0,
          width: type === 'video' && media instanceof HTMLVideoElement ? media.videoWidth : 0,
          height: type === 'video' && media instanceof HTMLVideoElement ? media.videoHeight : 0,
        })
      }
      media.onerror = () => resolve({ duration: 0, width: 0, height: 0 })
      media.src = url
    })
  }

  return Promise.resolve({ duration: 0, width: 0, height: 0 })
}

export async function importBrowserMediaFiles(
  files: File[],
  existing: Record<string, MediaFile> = {},
): Promise<MediaFile[]> {
  const results: MediaFile[] = []

  for (const file of files) {
    const signature = `${file.name}:${file.size}:${file.lastModified}`.toLowerCase()
    if (importedPaths.has(signature)) continue
    if (Object.values(existing).some((m) => m.metadata.browserFileSignature === signature)) continue

    const id = nanoid()
    const url = URL.createObjectURL(file)
    const type = detectBrowserMediaType(file)
    const probe = await probeBrowserMedia(file, url, type)
    const now = Date.now()

    const mediaFile: MediaFile = {
      id,
      name: file.name,
      path: url,
      type,
      duration: defaultClipDuration(type, probe.duration),
      width: probe.width,
      height: probe.height,
      fps: 30,
      codec: file.type || 'browser',
      audioCodec: type === 'audio' ? file.type || null : null,
      sampleRate: null,
      channels: null,
      bitrate: 0,
      fileSize: file.size,
      thumbnail: type === 'image' ? url : null,
      createdAt: now,
      updatedAt: now,
      metadata: {
        browserImported: true,
        browserFileSignature: signature,
        mimeType: file.type || null,
        objectUrl: url,
      },
    }

    importedPaths.add(signature)
    results.push(mediaFile)
  }

  return results
}

