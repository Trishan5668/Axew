#!/usr/bin/env node
/* eslint-disable no-console */

/**
 * build-installer.mjs — produces release/AxewSetup-${version}.exe.
 *
 * Sequence (matches docs/CLOUD_INTEGRATION.md):
 *   1. Build the React renderer + Electron main (pnpm build).
 *   2. Build the Rust media engine in release mode.
 *   3. Bundle the embedded Python runtime + FFmpeg into build/runtime/.
 *   4. Invoke electron-builder with config from electron-builder.yml.
 *
 * Verification-pending: run on a clean Windows VM with no Node/Python/Rust.
 * Steps 2 and 3 are gated by env vars so this script can also drive the
 * "frontend-only" packaging path used during smoke tests.
 *
 * Required env vars (set non-empty to enable each step):
 *   AXEW_BUILD_RUST=1          run cargo build --release
 *   AXEW_BUILD_RUNTIME=1       populate build/runtime/python + ffmpeg
 */

import { spawnSync } from 'child_process'
import { existsSync, mkdirSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const DESKTOP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(DESKTOP_ROOT, '..', '..')

function run(cmd, args, opts = {}) {
  console.log(`\n[build-installer] ${cmd} ${args.join(' ')}`)
  const result = spawnSync(cmd, args, { stdio: 'inherit', shell: true, ...opts })
  if (result.status !== 0) {
    console.error(`[build-installer] Command failed with exit code ${result.status}`)
    process.exit(result.status ?? 1)
  }
}

console.log('[build-installer] AXEW Windows installer build')
console.log(`[build-installer] desktop root: ${DESKTOP_ROOT}`)
console.log(`[build-installer] repo root:    ${REPO_ROOT}`)

// 1. Build renderer + electron main
run('pnpm', ['--filter', '@axew/desktop', 'build'], { cwd: REPO_ROOT })

// 2. Optional: Build Rust release binary
if (process.env.AXEW_BUILD_RUST) {
  console.log('[build-installer] Building Rust media engine (axew-core)')
  run('cargo', ['build', '--release'], { cwd: path.join(REPO_ROOT, 'crates', 'axew-core') })
} else {
  console.log('[build-installer] Skipping Rust build (set AXEW_BUILD_RUST=1 to enable)')
}

// 3. Optional: bundle embedded runtimes
const runtimeDir = path.join(DESKTOP_ROOT, 'build', 'runtime')
if (process.env.AXEW_BUILD_RUNTIME) {
  console.log('[build-installer] Bundling Python runtime + FFmpeg into build/runtime/')
  mkdirSync(runtimeDir, { recursive: true })
  run('node', [path.join(DESKTOP_ROOT, 'scripts', 'bundle-runtime.mjs')])
} else {
  console.log('[build-installer] Skipping runtime bundling (set AXEW_BUILD_RUNTIME=1 to enable)')
  // Touch placeholder dirs so electron-builder doesn't blow up on missing files.
  if (!existsSync(path.join(runtimeDir, 'python'))) {
    mkdirSync(path.join(runtimeDir, 'python'), { recursive: true })
  }
  if (!existsSync(path.join(runtimeDir, 'ffmpeg'))) {
    mkdirSync(path.join(runtimeDir, 'ffmpeg'), { recursive: true })
  }
}

// 4. electron-builder
const builderArgs = ['exec', '--', 'electron-builder', '--win', '--config', 'electron-builder.yml']
run('pnpm', builderArgs, { cwd: DESKTOP_ROOT })

console.log('\n[build-installer] Done.')
console.log(`[build-installer] Output: ${path.join(DESKTOP_ROOT, 'release')}`)
