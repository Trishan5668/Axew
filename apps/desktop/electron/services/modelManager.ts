/**
 * Whisper model manager — detects installed models, downloads missing ones
 * with HTTP Range-based resume support, and reports progress via IPC.
 *
 * Storage:
 *   - Models live in %APPDATA%/Axew/models/ (Windows), ~/.axew/models/ on POSIX.
 *   - Filename matches openai-whisper's convention so the Python service
 *     picks them up automatically.
 *
 * Verification-pending: download of multi-GB files over flaky networks +
 * SHA-256 integrity check. The size + URL constants below are taken from
 * OpenAI's published Whisper checkpoint list — keep them in sync.
 */

import { app, ipcMain } from 'electron'
import fs from 'fs'
import https from 'https'
import path from 'path'
import { URL } from 'url'

export type ModelId = 'turbo' | 'large-v3' | 'large-v3-turbo' | 'small' | 'base' | 'tiny'

export interface ModelDescriptor {
  id: ModelId
  label: string
  url: string
  approxBytes: number
  filename: string
  // SHA-256 of the model file. Verification-pending: populated when we
  // confirm checkpoints against the official OpenAI Whisper release.
  sha256?: string
}

// Subset of the Whisper checkpoints AXEW exposes in the first-run wizard.
// We deliberately ship only two options to keep the UI clean — Turbo (fast)
// and Large-v3 (best quality). Other ids are accepted programmatically.
export const MODEL_CATALOG: Record<ModelId, ModelDescriptor> = {
  turbo: {
    id: 'turbo',
    label: 'Turbo (faster, ~1.5 GB)',
    url: 'https://openaipublic.azureedge.net/main/whisper/models/aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt',
    approxBytes: 1_550_000_000,
    filename: 'large-v3-turbo.pt',
  },
  'large-v3': {
    id: 'large-v3',
    label: 'Large-v3 (best quality, ~3 GB)',
    url: 'https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt',
    approxBytes: 3_100_000_000,
    filename: 'large-v3.pt',
  },
  'large-v3-turbo': {
    id: 'large-v3-turbo',
    label: 'Large-v3 Turbo',
    url: 'https://openaipublic.azureedge.net/main/whisper/models/aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt',
    approxBytes: 1_550_000_000,
    filename: 'large-v3-turbo.pt',
  },
  small: {
    id: 'small',
    label: 'Small (~470 MB)',
    url: 'https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt',
    approxBytes: 470_000_000,
    filename: 'small.pt',
  },
  base: {
    id: 'base',
    label: 'Base (~140 MB)',
    url: 'https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt',
    approxBytes: 140_000_000,
    filename: 'base.pt',
  },
  tiny: {
    id: 'tiny',
    label: 'Tiny (~75 MB)',
    url: 'https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e7e3acaeb5b2dc4b5e1ed4dba/tiny.pt',
    approxBytes: 75_000_000,
    filename: 'tiny.pt',
  },
}

export interface DownloadProgress {
  modelId: ModelId
  bytesReceived: number
  bytesTotal: number
  percent: number
  speedBytesPerSec: number
}

function modelsDir(): string {
  // Mirror apps/ai-service/config.py: AXEW_MODELS_DIR or ~/.axew/models
  const override = process.env.AXEW_MODELS_DIR
  if (override) return override
  const appData = process.env.APPDATA ?? app.getPath('appData')
  return path.join(appData, 'Axew', 'models')
}

function modelPath(modelId: ModelId): string {
  const desc = MODEL_CATALOG[modelId]
  if (!desc) throw new Error(`Unknown model id: ${modelId}`)
  return path.join(modelsDir(), desc.filename)
}

export function installedModels(): ModelId[] {
  try {
    const dir = modelsDir()
    if (!fs.existsSync(dir)) return []
    const present: ModelId[] = []
    for (const id of Object.keys(MODEL_CATALOG) as ModelId[]) {
      const p = modelPath(id)
      if (fs.existsSync(p) && fs.statSync(p).size > 1_000_000) {
        present.push(id)
      }
    }
    return present
  } catch (err) {
    console.warn('[ModelManager] installedModels() failed:', err)
    return []
  }
}

export function hasAnyModel(): boolean {
  return installedModels().length > 0
}

/**
 * Resumable download. Uses HTTP Range to continue from the existing partial
 * file (".part" suffix) if one is present.
 */
export async function downloadModel(
  modelId: ModelId,
  onProgress: (progress: DownloadProgress) => void,
  signal?: AbortSignal,
): Promise<string> {
  const desc = MODEL_CATALOG[modelId]
  if (!desc) throw new Error(`Unknown model id: ${modelId}`)
  fs.mkdirSync(modelsDir(), { recursive: true })

  const finalPath = modelPath(modelId)
  const partPath = `${finalPath}.part`

  let resumeFrom = 0
  if (fs.existsSync(partPath)) {
    resumeFrom = fs.statSync(partPath).size
    console.log(`[ModelManager] Resuming download at ${resumeFrom} bytes`)
  }

  await downloadWithResume(desc.url, partPath, resumeFrom, desc.approxBytes, (received, total, speed) => {
    onProgress({
      modelId,
      bytesReceived: received,
      bytesTotal: total,
      percent: total > 0 ? received / total : 0,
      speedBytesPerSec: speed,
    })
  }, signal)

  fs.renameSync(partPath, finalPath)
  return finalPath
}

function downloadWithResume(
  url: string,
  destPath: string,
  resumeFrom: number,
  approxBytes: number,
  onProgress: (bytesReceived: number, bytesTotal: number, speedBytesPerSec: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const parsed = new URL(url)
    const headers: Record<string, string> = {
      'User-Agent': 'AXEW/1.0 (+https://axew.app)',
    }
    if (resumeFrom > 0) {
      headers.Range = `bytes=${resumeFrom}-`
    }

    const request = https.request(
      {
        method: 'GET',
        hostname: parsed.hostname,
        path: `${parsed.pathname}${parsed.search}`,
        headers,
      },
      (resp) => {
        if (resp.statusCode === 302 || resp.statusCode === 301) {
          const next = resp.headers.location
          if (!next) {
            reject(new Error(`Redirect with no Location header (status ${resp.statusCode})`))
            return
          }
          downloadWithResume(next, destPath, resumeFrom, approxBytes, onProgress, signal).then(resolve, reject)
          return
        }
        if (resp.statusCode !== 200 && resp.statusCode !== 206) {
          reject(new Error(`Download failed: HTTP ${resp.statusCode}`))
          return
        }
        const contentLength = Number(resp.headers['content-length'] ?? 0)
        const totalBytes =
          resp.statusCode === 206 ? resumeFrom + contentLength : Math.max(contentLength, approxBytes)
        const fileFlags = resp.statusCode === 206 ? 'a' : 'w'
        const out = fs.createWriteStream(destPath, { flags: fileFlags })

        let received = resumeFrom
        let lastTick = Date.now()
        let bytesSinceTick = 0

        resp.on('data', (chunk: Buffer) => {
          received += chunk.length
          bytesSinceTick += chunk.length
          const now = Date.now()
          if (now - lastTick >= 500) {
            const speed = (bytesSinceTick / (now - lastTick)) * 1000
            onProgress(received, totalBytes, speed)
            lastTick = now
            bytesSinceTick = 0
          }
        })

        resp.on('end', () => {
          out.end(() => {
            onProgress(received, totalBytes, 0)
            resolve()
          })
        })

        resp.on('error', (err) => {
          out.end()
          reject(err)
        })

        out.on('error', (err) => reject(err))

        resp.pipe(out)
      },
    )

    if (signal) {
      signal.addEventListener('abort', () => {
        request.destroy(new Error('Download cancelled'))
      })
    }

    request.on('error', (err) => reject(err))
    request.end()
  })
}

/**
 * Register all model-manager IPC handlers. Call once from electron/main.ts
 * during app startup.
 */
export function registerModelManagerIPC(): void {
  ipcMain.handle('models:list', () => ({
    installed: installedModels(),
    catalog: Object.values(MODEL_CATALOG).map((m) => ({
      id: m.id,
      label: m.label,
      approxBytes: m.approxBytes,
    })),
    modelsDir: modelsDir(),
  }))

  ipcMain.handle('models:has-any', () => hasAnyModel())

  ipcMain.handle('models:download', async (event, modelId: ModelId) => {
    const abort = new AbortController()
    const aborter = () => abort.abort()
    event.sender.once('destroyed', aborter)
    try {
      const target = await downloadModel(
        modelId,
        (progress) => {
          if (!event.sender.isDestroyed()) {
            event.sender.send('models:download-progress', progress)
          }
        },
        abort.signal,
      )
      return { ok: true, path: target }
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) }
    } finally {
      event.sender.off('destroyed', aborter)
    }
  })
}
