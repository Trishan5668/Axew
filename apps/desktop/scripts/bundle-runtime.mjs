#!/usr/bin/env node
/* eslint-disable no-console */

/**
 * bundle-runtime.mjs — fetch and stage:
 *   build/runtime/python/   — a portable embeddable CPython 3.11 with
 *                              AXEW's AI service dependencies pre-installed
 *   build/runtime/ffmpeg/   — static ffmpeg.exe + ffprobe.exe
 *
 * Verification-pending: download URLs need to be pinned to specific versions
 * before shipping. The function below intentionally throws unless the
 * AXEW_PYTHON_EMBED_URL / AXEW_FFMPEG_ZIP_URL env vars are set, so we never
 * silently package whatever happens to be on a CDN that day.
 */

import { existsSync, mkdirSync, createWriteStream, statSync } from 'fs'
import https from 'https'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const RUNTIME_DIR = path.resolve(__dirname, '..', 'build', 'runtime')

const PYTHON_URL = process.env.AXEW_PYTHON_EMBED_URL
const FFMPEG_URL = process.env.AXEW_FFMPEG_ZIP_URL

if (!PYTHON_URL || !FFMPEG_URL) {
  console.error('[bundle-runtime] AXEW_PYTHON_EMBED_URL and AXEW_FFMPEG_ZIP_URL must be set.')
  console.error('  Example (pin to known-good versions before shipping):')
  console.error('    set AXEW_PYTHON_EMBED_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip')
  console.error('    set AXEW_FFMPEG_ZIP_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip')
  process.exit(1)
}

function download(url, destPath) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, (resp) => {
      if (resp.statusCode === 302 || resp.statusCode === 301) {
        const next = resp.headers.location
        if (!next) {
          reject(new Error(`Redirect with no Location (status ${resp.statusCode})`))
          return
        }
        download(next, destPath).then(resolve, reject)
        return
      }
      if (resp.statusCode !== 200) {
        reject(new Error(`Failed ${url}: HTTP ${resp.statusCode}`))
        return
      }
      const out = createWriteStream(destPath)
      resp.pipe(out)
      out.on('finish', () => out.close(() => resolve()))
      out.on('error', reject)
    })
    req.on('error', reject)
  })
}

mkdirSync(RUNTIME_DIR, { recursive: true })
const pythonZip = path.join(RUNTIME_DIR, 'python.zip')
const ffmpegZip = path.join(RUNTIME_DIR, 'ffmpeg.zip')

console.log('[bundle-runtime] Downloading embedded Python from', PYTHON_URL)
await download(PYTHON_URL, pythonZip)
console.log(`[bundle-runtime] Python archive: ${(statSync(pythonZip).size / 1024 / 1024).toFixed(1)} MB`)

console.log('[bundle-runtime] Downloading FFmpeg from', FFMPEG_URL)
await download(FFMPEG_URL, ffmpegZip)
console.log(`[bundle-runtime] FFmpeg archive: ${(statSync(ffmpegZip).size / 1024 / 1024).toFixed(1)} MB`)

console.log('\n[bundle-runtime] Archives downloaded. Manual extraction step required:')
console.log('   1. Unzip', pythonZip, '-> build/runtime/python/')
console.log('   2. Unzip', ffmpegZip, '-> build/runtime/ffmpeg/')
console.log('   3. Run python -m pip install -r ../../apps/ai-service/requirements.txt -t build/runtime/python/Lib/site-packages')
console.log('Verification-pending: a fully automated extract + pip-install step.')

if (!existsSync(path.join(RUNTIME_DIR, 'python'))) {
  mkdirSync(path.join(RUNTIME_DIR, 'python'), { recursive: true })
}
if (!existsSync(path.join(RUNTIME_DIR, 'ffmpeg'))) {
  mkdirSync(path.join(RUNTIME_DIR, 'ffmpeg'), { recursive: true })
}
