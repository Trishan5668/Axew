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

