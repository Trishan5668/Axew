import fs from 'fs'
import path from 'path'
import { protocol, net } from 'electron'
import { pathToFileURL } from 'url'

/** Base64url-encode path for axew-media://play/ URLs (Node Buffer). */
export function encodePathForMediaUrl(filePath: string): string {
  const b64 = Buffer.from(filePath, 'utf8').toString('base64')
  return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

const MIME_BY_EXT: Record<string, string> = {
  '.mp4': 'video/mp4',
  '.m4v': 'video/mp4',
  '.mov': 'video/quicktime',
  '.webm': 'video/webm',
  '.mkv': 'video/x-matroska',
  '.avi': 'video/x-msvideo',
  '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav',
  '.aac': 'audio/aac',
  '.ogg': 'audio/ogg',
  '.flac': 'audio/flac',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
}

function mimeFor(filePath: string): string {
  return MIME_BY_EXT[path.extname(filePath).toLowerCase()] ?? 'application/octet-stream'
}

/** Decode path from axew-media://play/<base64url> */
export function decodeMediaUrl(requestUrl: string): string | null {
  try {
    const url = new URL(requestUrl)
    if (url.hostname === 'play') {
      const segment = url.pathname.replace(/^\//, '')
      if (!segment) return null
      const b64 = segment.replace(/-/g, '+').replace(/_/g, '/')
      const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
      return Buffer.from(padded, 'base64').toString('utf8')
    }
    // Legacy: axew-media://local/<encoded path>
    if (url.hostname === 'local') {
      let filePath = decodeURIComponent(url.pathname.replace(/^\//, ''))
      if (process.platform === 'win32') {
        if (/^[a-zA-Z]:/.test(filePath)) {
          filePath = filePath.replace(/\//g, '\\')
        } else if (/^[a-zA-Z]\//.test(filePath)) {
          filePath = filePath.replace(/\//g, '\\')
        }
      }
      return filePath
    }
  } catch {
    return null
  }
  return null
}

function parseRangeHeader(
  range: string,
  size: number,
): { start: number; end: number } | null {
  const match = /^bytes=(\d*)-(\d*)$/.exec(range.trim())
  if (!match) return null
  let start = match[1] ? parseInt(match[1], 10) : 0
  let end = match[2] ? parseInt(match[2], 10) : size - 1
  if (Number.isNaN(start) || Number.isNaN(end)) return null
  start = Math.max(0, Math.min(start, size - 1))
  end = Math.max(start, Math.min(end, size - 1))
  return { start, end }
}

function nodeStreamToWeb(stream: fs.ReadStream): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      stream.on('data', (chunk: string | Buffer) => {
        const buf = typeof chunk === 'string' ? Buffer.from(chunk) : chunk
        controller.enqueue(new Uint8Array(buf))
      })
      stream.on('end', () => controller.close())
      stream.on('error', (err) => controller.error(err))
    },
    cancel() {
      stream.destroy()
    },
  })
}

async function serveFileWithRanges(filePath: string, request: Request): Promise<Response> {
  const normalized = path.normalize(filePath)
  if (!fs.existsSync(normalized)) {
    console.error('[axew-media] File not found:', normalized)
    return new Response('Not Found', { status: 404 })
  }

  const stat = fs.statSync(normalized)
  const contentType = mimeFor(normalized)
  const rangeHeader = request.headers.get('Range')

  if (rangeHeader && stat.size > 0) {
    const range = parseRangeHeader(rangeHeader, stat.size)
    if (range) {
      const { start, end } = range
      const chunkSize = end - start + 1
      const stream = fs.createReadStream(normalized, { start, end })
      return new Response(nodeStreamToWeb(stream), {
        status: 206,
        headers: {
          'Content-Type': contentType,
          'Content-Length': String(chunkSize),
          'Content-Range': `bytes ${start}-${end}/${stat.size}`,
          'Accept-Ranges': 'bytes',
        },
      })
    }
  }

  // Full file — use net.fetch(fileURL) for efficiency on small files / images
  try {
    const fileUrl = pathToFileURL(normalized).href
    const response = await net.fetch(fileUrl, {
      method: request.method,
      headers: request.headers,
    })
    const headers = new Headers(response.headers)
    headers.set('Accept-Ranges', 'bytes')
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', contentType)
    }
    return new Response(response.body, { status: response.status, headers })
  } catch (err) {
    console.error('[axew-media] net.fetch failed, streaming:', err)
    const stream = fs.createReadStream(normalized)
    return new Response(nodeStreamToWeb(stream), {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(stat.size),
        'Accept-Ranges': 'bytes',
      },
    })
  }
}

export function registerMediaProtocol(): void {
  protocol.handle('axew-media', async (request) => {
    const filePath = decodeMediaUrl(request.url)
    if (!filePath) {
      console.error('[axew-media] Invalid URL:', request.url)
      return new Response('Bad Request', { status: 400 })
    }
    return serveFileWithRanges(filePath, request)
  })
  console.log('[axew-media] Protocol registered (range-aware)')
}
