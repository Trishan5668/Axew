import type { MediaFile } from '@shared/media'
import { importBrowserMediaFiles } from './mediaImport'

export const MEDIA_ACCEPT = [
  'video/mp4',
  'video/quicktime',
  'video/x-matroska',
  'video/x-msvideo',
  'video/webm',
  'audio/mpeg',
  'audio/wav',
  'audio/aac',
  'image/jpeg',
  'image/png',
].join(',')

export function pickMediaFiles(existing: Record<string, MediaFile> = {}): Promise<MediaFile[]> {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.multiple = true
    input.accept = MEDIA_ACCEPT
    input.onchange = async () => {
      const files = Array.from(input.files ?? [])
      input.remove()
      if (files.length === 0) {
        resolve([])
        return
      }
      try {
        resolve(await importBrowserMediaFiles(files, existing))
      } catch (err) {
        reject(err)
      }
    }
    input.click()
  })
}
