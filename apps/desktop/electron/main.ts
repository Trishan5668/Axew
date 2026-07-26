import { app, BrowserWindow, dialog, ipcMain, Menu, protocol, shell } from 'electron'
import { encodePathForMediaUrl, registerMediaProtocol } from './mediaProtocol'
import { execSync, spawn, spawnSync, type ChildProcess } from 'child_process'
import net from 'net'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { runBootstrap } from './services/bootstrapManager'
import { setupAutoUpdater } from './services/autoUpdater'
import {
  attachOAuthDeepLinkListeners,
  oauthRedirectUrl,
  registerOAuthProtocol,
} from './services/oauthHandler'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged

let mainWindow: BrowserWindow | null = null
let rustProcess: ChildProcess | null = null
let aiProcess: ChildProcess | null = null

const RUST_PORT = process.env.AXEW_RUST_PORT || '7001'
const AI_PORT = process.env.AXEW_AI_PORT || '7002'

protocol.registerSchemesAsPrivileged([
  {
    scheme: 'axew-media',
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
      bypassCSP: true,
      corsEnabled: true,
    },
  },
])

// Register axew:// OAuth protocol BEFORE app.whenReady() so single-instance
// lock acquisition + cold-start argv parsing happen at the right moment.
registerOAuthProtocol()
attachOAuthDeepLinkListeners({
  getMainWindow: () => mainWindow,
})

function getPreloadPath(): string {
  const candidates = [
    path.join(__dirname, '../electron/preload.cjs'),
    path.join(__dirname, 'preload.cjs'),
  ]
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate
  }
  return path.join(__dirname, '../electron/preload.cjs')
}

function rustBinaryPath(): string {
  const base = isDev
    ? path.join(__dirname, '../../../crates/axew-core/target/debug/axew-core')
    : path.join(process.resourcesPath, 'axew-core')
  return process.platform === 'win32' ? `${base}.exe` : base
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1200,
    minHeight: 700,
    backgroundColor: '#0A0A0C',
    titleBarStyle: process.platform === 'darwin' ? 'hidden' : 'default',
    titleBarOverlay:
      process.platform !== 'darwin'
        ? {
            color: '#0A0A0C',
            symbolColor: '#E8E8F0',
            height: 36,
          }
        : undefined,
    trafficLightPosition: { x: 16, y: 10 },
    webPreferences: {
      preload: getPreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      sandbox: false,
    },
    frame: process.platform !== 'darwin',
    show: false,
  })

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
    if (isDev) {
      mainWindow?.webContents.openDevTools({ mode: 'detach' })
    }
  })

  const devUrl = process.env.VITE_DEV_SERVER_URL || 'http://localhost:5173'

  if (isDev) {
    mainWindow.loadURL(devUrl)
    mainWindow.webContents.on('did-fail-load', (_event, code, description, url) => {
      if (url === devUrl && code !== -3) {
        console.warn('[Main] Dev server load failed, retrying:', description)
        setTimeout(() => mainWindow?.loadURL(devUrl), 1500)
      }
    })
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  mainWindow.webContents.on('console-message', (_event, level, message) => {
    if (level >= 2) {
      console.log(`[Renderer] ${message}`)
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  setupMenu()
}

function setupMenu(): void {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: 'AXEW',
      submenu: [
        { label: 'About AXEW', role: 'about' },
        { type: 'separator' },
        { label: 'Quit', accelerator: 'CmdOrCtrl+Q', click: () => app.quit() },
      ],
    },
    {
      label: 'File',
      submenu: [
        {
          label: 'New Project',
          accelerator: 'CmdOrCtrl+N',
          click: () => mainWindow?.webContents.send('menu:new-project'),
        },
        {
          label: 'Open Project',
          accelerator: 'CmdOrCtrl+O',
          click: () => mainWindow?.webContents.send('menu:open-project'),
        },
        {
          label: 'Save Project',
          accelerator: 'CmdOrCtrl+S',
          click: () => mainWindow?.webContents.send('menu:save-project'),
        },
        { type: 'separator' },
        {
          label: 'Import Media',
          accelerator: 'CmdOrCtrl+I',
          click: () => mainWindow?.webContents.send('menu:import-media'),
        },
        { type: 'separator' },
        {
          label: 'Export',
          accelerator: 'CmdOrCtrl+E',
          click: () => mainWindow?.webContents.send('menu:export'),
        },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
  ]

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

let rustRestartCount = 0
const RUST_MAX_RESTARTS = 3

function findFfmpegPath(): string {
  // Check common bundled/system locations
  const candidates = [
    process.env.AXEW_FFMPEG_PATH,
    'ffmpeg',
    ...(process.platform === 'win32'
      ? [
          path.join(process.env.LOCALAPPDATA ?? '', 'ffmpeg', 'bin', 'ffmpeg.exe'),
          'C:\\ffmpeg\\bin\\ffmpeg.exe',
        ]
      : ['/usr/local/bin/ffmpeg', '/opt/homebrew/bin/ffmpeg']),
  ].filter(Boolean) as string[]

  for (const candidate of candidates) {
    try {
      const { status } = spawnSync(candidate, ['-version'], {
        stdio: 'ignore',
        timeout: 5000,
      })
      if (status === 0) return candidate
    } catch {
      continue
    }
  }
  return 'ffmpeg'
}

function startRustService(): void {
  const rustBin = rustBinaryPath()
  if (!fs.existsSync(rustBin)) {
    console.warn('[Main] Rust binary not found, skipping service start:', rustBin)
    return
  }

  const ffmpegPath = findFfmpegPath()
  const ffprobePath = ffmpegPath.replace(/ffmpeg(\.exe)?$/, 'ffprobe$1')
  console.log(`[Main] Using ffmpeg: ${ffmpegPath}, ffprobe: ${ffprobePath}`)

  rustProcess = spawn(rustBin, [], {
    env: {
      ...process.env,
      AXEW_PORT: RUST_PORT,
      AXEW_FFMPEG_PATH: ffmpegPath,
      AXEW_FFPROBE_PATH: ffprobePath,
    },
    stdio: 'pipe',
  })

  rustProcess.stdout?.on('data', (data) => console.log('[Rust]', data.toString()))
  rustProcess.stderr?.on('data', (data) => console.error('[Rust Error]', data.toString()))
  rustProcess.on('exit', (code) => {
    console.log(`[Rust] Process exited with code ${code}`)
    rustProcess = null
    if (code !== 0 && code !== null && rustRestartCount < RUST_MAX_RESTARTS) {
      rustRestartCount++
      console.log(`[Main] Rust service crashed — restarting (attempt ${rustRestartCount}/${RUST_MAX_RESTARTS})`)
      setTimeout(startRustService, 2000 * rustRestartCount)
    }
  })
}

// ---------------------------------------------------------------------------
// AI service lifecycle — robust startup orchestration with restart-loop prevention
// ---------------------------------------------------------------------------

let aiRestartCount = 0
const AI_MAX_RESTARTS = 5
const AI_BASE_RESTART_DELAY_MS = 3000
let aiHealthInterval: ReturnType<typeof setInterval> | null = null

type AIServicePhase =
  | 'offline'
  | 'spawning'
  | 'initializing'
  | 'model_loading'
  | 'online'
  | 'degraded'
  | 'crashed'
let aiServicePhase: AIServicePhase = 'offline'

const AI_STARTUP_GRACE_MS = 30_000
const AI_LIVENESS_TIMEOUT_MS = 90_000
const AI_READINESS_TIMEOUT_MS = 120_000
const AI_STEADY_STATE_INTERVAL_MS = 20_000
const AI_HEALTH_FAILURE_THRESHOLD = 8
const AI_RESTART_COOLDOWN_MS = 120_000

let aiLastSuccessfulHealthTime = 0
let aiLastRestartTime = 0
let aiSpawnTime = 0
let aiUsingExistingProcess = false
let aiStartupSequenceAbort: AbortController | null = null

function setAIPhase(phase: AIServicePhase, reason?: string): void {
  const prev = aiServicePhase
  aiServicePhase = phase
  const pid = aiProcess?.pid ?? 'none'
  console.log(
    `[Supervisor][AI] Phase: ${prev} -> ${phase} | pid=${pid} | restarts=${aiRestartCount}/${AI_MAX_RESTARTS}${reason ? ` | reason=${reason}` : ''}`,
  )
}

function emitAIStatus(payload: { online: boolean; phase: string; reason?: string; memory?: unknown; failures?: number; exitCode?: number | null }): void {
  mainWindow?.webContents.send('ai:status', payload)
}

function isPortInUse(port: string | number): Promise<boolean> {
  return new Promise((resolve) => {
    const tester = net.createServer()
      .once('error', (err: NodeJS.ErrnoException) => {
        resolve(err.code === 'EADDRINUSE')
      })
      .once('listening', () => {
        tester.close(() => resolve(false))
      })
      .listen(parseInt(String(port), 10), '127.0.0.1')
  })
}

async function existingAIServiceHealth(port: string | number): Promise<'ready' | 'live' | null> {
  try {
    const live = await fetch(`http://127.0.0.1:${port}/health/live`, {
      signal: AbortSignal.timeout(3000),
    })
    if (!live.ok) return null
    try {
      const ready = await fetch(`http://127.0.0.1:${port}/health/ready`, {
        signal: AbortSignal.timeout(3000),
      })
      return ready.ok ? 'ready' : 'live'
    } catch {
      return 'live'
    }
  } catch {
    return null
  }
}

async function killExistingOnPort(port: string | number): Promise<void> {
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/health/live`, {
      signal: AbortSignal.timeout(3000),
    })
    if (resp.ok) {
      console.log(`[Supervisor][AI] Found healthy existing process on port ${port} — reusing`)
      return
    }
  } catch {
    // Not a healthy AXEW process — may be a stale binding
  }

  if (process.platform === 'win32') {
    try {
      const output = execSync(`netstat -ano | findstr :${port} | findstr LISTENING`, {
        encoding: 'utf-8',
        timeout: 5000,
      })
      const lines = output.trim().split('\n')
      for (const line of lines) {
        const parts = line.trim().split(/\s+/)
        const pid = parts[parts.length - 1]
        if (pid && pid !== '0') {
          console.log(`[Supervisor][AI] Killing stale process on port ${port} (pid=${pid})`)
          try {
            execSync(`taskkill /F /PID ${pid}`, { timeout: 5000 })
          } catch { /* process may already be gone */ }
        }
      }
    } catch { /* no process found on port */ }
  } else {
    try {
      const output = execSync(`lsof -ti :${port}`, { encoding: 'utf-8', timeout: 5000 })
      const pids = output.trim().split('\n').filter(Boolean)
      for (const pid of pids) {
        console.log(`[Supervisor][AI] Killing stale process on port ${port} (pid=${pid})`)
        try {
          execSync(`kill -9 ${pid}`, { timeout: 5000 })
        } catch { /* process may already be gone */ }
      }
    } catch { /* no process found on port */ }
  }

  await sleep(1000)
}

async function waitForPortRelease(port: string | number, timeoutMs = 10_000): Promise<boolean> {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const inUse = await isPortInUse(port)
    if (!inUse) return true
    await sleep(500)
  }
  return false
}

function computeRestartDelay(): number {
  return AI_BASE_RESTART_DELAY_MS * Math.pow(2, Math.min(aiRestartCount, 4))
}

function shouldAllowRestart(reason: string): boolean {
  if (aiRestartCount >= AI_MAX_RESTARTS) {
    console.error(
      `[Supervisor][AI] Max restarts (${AI_MAX_RESTARTS}) reached — NOT restarting. Reason: ${reason}`,
    )
    setAIPhase('crashed', 'max_restarts_exhausted')
    emitAIStatus({ online: false, phase: 'crashed', reason: 'max_restarts_exhausted' })
    return false
  }

  const timeSinceLastRestart = Date.now() - aiLastRestartTime
  if (aiLastRestartTime > 0 && timeSinceLastRestart < AI_RESTART_COOLDOWN_MS && aiRestartCount >= 3) {
    console.error(
      `[Supervisor][AI] Restart cooldown active (${Math.round(timeSinceLastRestart / 1000)}s < ${AI_RESTART_COOLDOWN_MS / 1000}s) — NOT restarting`,
    )
    return false
  }

  return true
}

async function startAIService(): Promise<void> {
  const aiDir = isDev
    ? path.join(__dirname, '../../../apps/ai-service')
    : path.join(process.resourcesPath, 'ai-service')

  if (!fs.existsSync(aiDir)) {
    console.warn('[Supervisor][AI] AI service directory not found, skipping:', aiDir)
    setAIPhase('crashed', 'directory_missing')
    emitAIStatus({ online: false, phase: 'crashed', reason: 'directory_missing' })
    return
  }

  // Prevent duplicate spawns
  if (aiProcess && !aiProcess.killed) {
    console.warn('[Supervisor][AI] Process already running (pid=%d) — skipping spawn', aiProcess.pid)
    return
  }

  // Check and clear port before spawning
  const portBusy = await isPortInUse(AI_PORT)
  if (portBusy) {
    const existing = await existingAIServiceHealth(AI_PORT)
    if (existing) {
      aiUsingExistingProcess = true
      aiLastSuccessfulHealthTime = Date.now()
      setAIPhase(existing === 'ready' ? 'online' : 'degraded', 'reusing_existing_process')
      emitAIStatus({
        online: true,
        phase: existing === 'ready' ? 'online' : 'degraded',
        reason: 'reusing_existing_process',
      })
      console.log(`[Supervisor][AI] Port ${AI_PORT} already has a live AXEW AI service - reusing it`)
      startAISteadyStateMonitor()
      return
    }
    console.warn(`[Supervisor][AI] Port ${AI_PORT} is already in use — attempting cleanup`)
    await killExistingOnPort(AI_PORT)
    const released = await waitForPortRelease(AI_PORT, 8000)
    if (!released) {
      console.error(`[Supervisor][AI] Port ${AI_PORT} still occupied after cleanup — cannot start`)
      setAIPhase('crashed', 'port_unavailable')
      emitAIStatus({ online: false, phase: 'crashed', reason: 'port_unavailable' })
      return
    }
    console.log(`[Supervisor][AI] Port ${AI_PORT} released successfully`)
  }

  setAIPhase('spawning')
  aiUsingExistingProcess = false
  aiSpawnTime = Date.now()
  aiLastRestartTime = Date.now()

  const pythonBin = process.platform === 'win32' ? 'python' : 'python3'

  console.log(
    `[Supervisor][AI] Spawning: ${pythonBin} -m uvicorn main:app --host 127.0.0.1 --port ${AI_PORT}`,
  )
  console.log(`[Supervisor][AI] CWD: ${aiDir}`)

  aiProcess = spawn(
    pythonBin,
    ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', AI_PORT, '--timeout-keep-alive', '120'],
    {
      cwd: aiDir,
      env: { ...process.env, AXEW_MAX_MODELS: '3' },
      stdio: 'pipe',
    },
  )

  const pid = aiProcess.pid
  console.log(`[Supervisor][AI] Process spawned successfully (pid=${pid})`)
  emitAIStatus({ online: false, phase: 'spawning', reason: 'process_spawned' })

  aiProcess.stdout?.on('data', (data: Buffer) => {
    const msg = data.toString().trimEnd()
    if (msg) console.log(`[AI:${pid}:stdout]`, msg)
  })

  aiProcess.stderr?.on('data', (data: Buffer) => {
    const msg = data.toString().trimEnd()
    if (msg) {
      console.error(`[AI:${pid}:stderr]`, msg)
      if (msg.includes('Address already in use') || msg.includes('address already in use')) {
        console.error(`[Supervisor][AI] Port binding failed — address already in use`)
      }
    }
  })

  aiProcess.on('error', (err) => {
    console.error(`[Supervisor][AI] Spawn error:`, err.message)
    aiProcess = null
    setAIPhase('crashed', `spawn_error: ${err.message}`)
    emitAIStatus({ online: false, phase: 'crashed', reason: 'spawn_error' })
  })

  aiProcess.on('exit', (code, signal) => {
    const uptime = Math.round((Date.now() - aiSpawnTime) / 1000)
    console.log(
      `[Supervisor][AI] Process exited | pid=${pid} | code=${code} | signal=${signal} | uptime=${uptime}s | phase=${aiServicePhase}`,
    )
    aiProcess = null

    if (aiStartupSequenceAbort) {
      aiStartupSequenceAbort.abort()
      aiStartupSequenceAbort = null
    }

    if (aiHealthInterval) {
      clearInterval(aiHealthInterval)
      aiHealthInterval = null
    }

    setAIPhase('crashed', `exit_code=${code}_signal=${signal}`)
    emitAIStatus({
      online: false,
      phase: 'crashed',
      reason: 'process_exited',
      exitCode: code,
    })

    // Only restart on abnormal exit (actual crashes)
    const isAbnormalExit = code !== 0 && code !== null
    if (isAbnormalExit && shouldAllowRestart('process_crashed')) {
      aiRestartCount++
      const delay = computeRestartDelay()
      console.log(
        `[Supervisor][AI] Scheduling restart in ${delay}ms (attempt ${aiRestartCount}/${AI_MAX_RESTARTS})`,
      )
      setTimeout(startAIService, delay)
    } else if (!isAbnormalExit) {
      console.log('[Supervisor][AI] Clean exit (code=0) — not restarting automatically')
    }
  })

  startAIStartupSequence()
}

/**
 * Orchestrates the startup polling sequence:
 * 1. Grace period (30s — no polling, no restart attempts)
 * 2. Poll /health/live with exponential backoff until liveness confirmed
 * 3. Poll /health/ready — but readiness failure does NOT trigger restarts
 * 4. Transition to steady-state health monitoring
 */
async function startAIStartupSequence(): Promise<void> {
  if (aiHealthInterval) {
    clearInterval(aiHealthInterval)
    aiHealthInterval = null
  }

  if (aiStartupSequenceAbort) {
    aiStartupSequenceAbort.abort()
  }
  aiStartupSequenceAbort = new AbortController()
  const { signal } = aiStartupSequenceAbort

  console.log(`[Supervisor][AI] Startup grace period: ${AI_STARTUP_GRACE_MS / 1000}s (no health checks)`)
  setAIPhase('initializing', 'grace_period')
  emitAIStatus({ online: false, phase: 'initializing', reason: 'grace_period' })

  await sleep(AI_STARTUP_GRACE_MS)

  if (signal.aborted || !aiProcess || aiProcess.killed) {
    console.log('[Supervisor][AI] Process died during grace period — aborting startup sequence')
    return
  }

  // Phase 1: Wait for liveness (/health/live returns 200)
  // This confirms HTTP is bound — the PROCESS is alive
  console.log('[Supervisor][AI] Phase 1: Polling /health/live for process liveness')
  const livenessStart = Date.now()
  let backoff = 2000
  let livenessOk = false

  while (Date.now() - livenessStart < AI_LIVENESS_TIMEOUT_MS) {
    if (signal.aborted || !aiProcess || aiProcess.killed) {
      console.log('[Supervisor][AI] Process died during liveness polling')
      return
    }

    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 5000)
      const resp = await fetch(`http://127.0.0.1:${AI_PORT}/health/live`, {
        signal: controller.signal,
      })
      clearTimeout(timeout)

      if (resp.ok) {
        const data = (await resp.json()) as { phase?: string; uptime_sec?: number }
        console.log(
          `[Supervisor][AI] Liveness confirmed (phase=${data.phase}, uptime=${data.uptime_sec}s)`,
        )
        livenessOk = true
        break
      }
    } catch {
      const elapsed = Math.round((Date.now() - livenessStart) / 1000)
      console.log(
        `[Supervisor][AI] Liveness poll failed (elapsed=${elapsed}s, next in ${Math.round(backoff / 1000)}s)`,
      )
    }

    await sleep(backoff)
    backoff = Math.min(backoff * 1.5, 10_000)
  }

  if (!livenessOk) {
    console.error(
      `[Supervisor][AI] Failed to become live within ${AI_LIVENESS_TIMEOUT_MS / 1000}s — likely startup crash`,
    )
    setAIPhase('crashed', 'liveness_timeout')
    emitAIStatus({ online: false, phase: 'crashed', reason: 'liveness_timeout' })
    return
  }

  // Phase 2: Wait for readiness (/health/ready returns 200)
  // IMPORTANT: readiness failure does NOT kill/restart — it just means models are still loading
  setAIPhase('model_loading', 'waiting_for_models')
  emitAIStatus({ online: false, phase: 'model_loading', reason: 'waiting_for_ready' })
  console.log('[Supervisor][AI] Phase 2: Polling /health/ready for model readiness')

  const readinessStart = Date.now()
  backoff = 3000
  let readinessOk = false

  while (Date.now() - readinessStart < AI_READINESS_TIMEOUT_MS) {
    if (signal.aborted || !aiProcess || aiProcess.killed) {
      console.log('[Supervisor][AI] Process died during readiness polling')
      return
    }

    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 8000)
      const resp = await fetch(`http://127.0.0.1:${AI_PORT}/health/ready`, {
        signal: controller.signal,
      })
      clearTimeout(timeout)

      if (resp.ok) {
        const data = (await resp.json()) as { phase?: string }
        console.log(`[Supervisor][AI] Readiness confirmed (phase=${data.phase})`)
        readinessOk = true
        break
      } else if (resp.status === 503) {
        const data = (await resp.json()) as { phase?: string }
        const elapsed = Math.round((Date.now() - readinessStart) / 1000)
        console.log(
          `[Supervisor][AI] Not yet ready (phase=${data.phase}, elapsed=${elapsed}s) — this is normal`,
        )
      }
    } catch {
      const elapsed = Math.round((Date.now() - readinessStart) / 1000)
      console.log(
        `[Supervisor][AI] Readiness poll exception (elapsed=${elapsed}s) — continuing to wait`,
      )
    }

    await sleep(backoff)
    backoff = Math.min(backoff * 1.5, 10_000)
  }

  if (!readinessOk) {
    // Service is LIVE but not READY — mark as DEGRADED, do NOT restart
    console.warn(
      `[Supervisor][AI] Not ready after ${AI_READINESS_TIMEOUT_MS / 1000}s — marking DEGRADED (process stays alive)`,
    )
    setAIPhase('degraded', 'readiness_timeout_but_live')
    emitAIStatus({ online: true, phase: 'degraded', reason: 'models_still_loading' })
  } else {
    setAIPhase('online')
    aiRestartCount = 0
    aiLastSuccessfulHealthTime = Date.now()
    emitAIStatus({ online: true, phase: 'online' })
    console.log('[Supervisor][AI] Fully ONLINE — entering steady-state monitoring')
  }

  startAISteadyStateMonitor()
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Steady-state health monitoring.
 *
 * Key design decisions to prevent restart loops:
 * 1. Uses /health/live (lightweight) to determine if process is alive
 * 2. Uses /health (full) only for status reporting to frontend
 * 3. Only triggers restart when the PROCESS is confirmed dead (not just busy)
 * 4. Restart count is NOT reset on every success — uses cooldown window instead
 * 5. Requires CONSECUTIVE liveness failures before restarting
 */
let aiHealthFailures = 0
let aiLivenessFailures = 0

function startAISteadyStateMonitor(): void {
  if (aiHealthInterval) clearInterval(aiHealthInterval)
  aiHealthFailures = 0
  aiLivenessFailures = 0

  aiHealthInterval = setInterval(async () => {
    if ((!aiProcess || aiProcess.killed) && !aiUsingExistingProcess) {
      emitAIStatus({ online: false, phase: 'crashed', reason: 'process_gone' })
      if (aiHealthInterval) {
        clearInterval(aiHealthInterval)
        aiHealthInterval = null
      }
      return
    }

    // Step 1: Lightweight liveness check — is the process responsive at all?
    let processAlive = false
    try {
      const resp = await fetch(`http://127.0.0.1:${AI_PORT}/health/live`, {
        signal: AbortSignal.timeout(8000),
      })
      processAlive = resp.ok
    } catch {
      processAlive = false
    }

    if (!processAlive) {
      aiLivenessFailures++
      aiHealthFailures++
      console.warn(
        `[Supervisor][AI] Liveness check FAILED (consecutive=${aiLivenessFailures}, total_health_failures=${aiHealthFailures}/${AI_HEALTH_FAILURE_THRESHOLD})`,
      )
      emitAIStatus({
        online: false,
        phase: aiServicePhase,
        reason: 'liveness_failed',
        failures: aiLivenessFailures,
      })

      // Only restart after sustained liveness failures (process truly unresponsive)
      if (aiLivenessFailures >= AI_HEALTH_FAILURE_THRESHOLD) {
        if (!shouldAllowRestart('sustained_liveness_failure')) return

        console.error(
          `[Supervisor][AI] ${aiLivenessFailures} consecutive liveness failures — process is dead, forcing restart`,
        )
        if (aiHealthInterval) {
          clearInterval(aiHealthInterval)
          aiHealthInterval = null
        }
        try {
          aiProcess?.kill('SIGKILL')
        } catch { /* already dead */ }
        aiUsingExistingProcess = false
        aiProcess = null
        aiRestartCount++
        const delay = computeRestartDelay()
        console.log(`[Supervisor][AI] Restart scheduled in ${delay}ms`)
        setTimeout(startAIService, delay)
      }
      return
    }

    // Liveness OK — reset consecutive liveness failure counter
    aiLivenessFailures = 0
    aiLastSuccessfulHealthTime = Date.now()

    // Decay restart count over time (if stable for 2+ minutes, allow future restarts)
    if (aiRestartCount > 0 && Date.now() - aiLastRestartTime > AI_RESTART_COOLDOWN_MS) {
      const prev = aiRestartCount
      aiRestartCount = Math.max(0, aiRestartCount - 1)
      if (prev !== aiRestartCount) {
        console.log(
          `[Supervisor][AI] Restart count decayed: ${prev} -> ${aiRestartCount} (stable for ${Math.round((Date.now() - aiLastRestartTime) / 1000)}s)`,
        )
      }
    }

    // Step 2: Full health check for status reporting (does NOT trigger restarts)
    try {
      const resp = await fetch(`http://127.0.0.1:${AI_PORT}/health`, {
        signal: AbortSignal.timeout(12000),
      })

      if (resp.ok) {
        const data = (await resp.json()) as {
          status?: string
          phase?: string
          is_ready?: boolean
          memory?: { pressure?: string; used_percent?: number }
        }
        aiHealthFailures = 0

        const isFullyReady = data.is_ready !== false
        if (isFullyReady && aiServicePhase !== 'online') {
          setAIPhase('online', 'recovered')
        } else if (!isFullyReady && aiServicePhase === 'online') {
          setAIPhase('degraded', 'models_unavailable')
        }

        // Service is ONLINE as long as process is alive (liveness passed above)
        emitAIStatus({
          online: true,
          phase: isFullyReady ? 'online' : 'degraded',
          memory: data.memory,
        })

        if (data.memory?.pressure === 'critical' || data.memory?.pressure === 'high') {
          mainWindow?.webContents.send('ai:memory-pressure', data.memory)
        }
      } else {
        // /health returned non-200 but process is alive — report degraded, do NOT restart
        console.warn(`[Supervisor][AI] /health returned ${resp.status} — process alive but degraded`)
        emitAIStatus({ online: true, phase: 'degraded', reason: 'health_non_200' })
      }
    } catch {
      // /health timed out but liveness passed — process alive but busy, do NOT restart
      console.warn('[Supervisor][AI] /health timed out but liveness OK — process is busy, not dead')
      emitAIStatus({ online: true, phase: 'degraded', reason: 'health_timeout_but_alive' })
    }
  }, AI_STEADY_STATE_INTERVAL_MS)
}

ipcMain.handle('dialog:openFile', async (_, options: Electron.OpenDialogOptions) => {
  return dialog.showOpenDialog(mainWindow!, options)
})

ipcMain.handle('dialog:saveFile', async (_, options: Electron.SaveDialogOptions) => {
  return dialog.showSaveDialog(mainWindow!, options)
})

ipcMain.handle('shell:openExternal', async (_, url: string) => {
  await shell.openExternal(url)
})

ipcMain.handle('app:getVersion', () => app.getVersion())

ipcMain.handle('app:getPaths', () => ({
  userData: app.getPath('userData'),
  documents: app.getPath('documents'),
  downloads: app.getPath('downloads'),
  home: app.getPath('home'),
  temp: app.getPath('temp'),
}))

ipcMain.handle('auth:getOAuthRedirectUrl', () => oauthRedirectUrl(isDev))

ipcMain.handle('fs:readFile', async (_, filePath: string) => {
  try {
    const content = fs.readFileSync(filePath)
    return { success: true, data: content.toString('base64') }
  } catch (err) {
    return { success: false, error: String(err) }
  }
})

ipcMain.handle('fs:writeFile', async (_, filePath: string, content: string) => {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    fs.writeFileSync(filePath, content, 'utf-8')
    return { success: true }
  } catch (err) {
    return { success: false, error: String(err) }
  }
})

ipcMain.handle('fs:exists', async (_, filePath: string) => fs.existsSync(filePath))

ipcMain.handle('media:resolvePlaybackUrl', async (_, filePath: string) => {
  try {
    const normalized = path.normalize(filePath)
    if (!fs.existsSync(normalized)) {
      return { exists: false, url: null, error: `File not found: ${normalized}` }
    }
    const url = `axew-media://play/${encodePathForMediaUrl(normalized)}`
    return { exists: true, url, error: null }
  } catch (err) {
    return { exists: false, url: null, error: String(err) }
  }
})

ipcMain.handle('services:restartAI', async () => {
  console.log('[Supervisor][AI] Manual restart requested by user')
  if (aiStartupSequenceAbort) {
    aiStartupSequenceAbort.abort()
    aiStartupSequenceAbort = null
  }
  if (aiHealthInterval) {
    clearInterval(aiHealthInterval)
    aiHealthInterval = null
  }
  try {
    aiProcess?.kill()
  } catch { /* already dead */ }
  aiProcess = null
  aiUsingExistingProcess = false
  aiRestartCount = 0
  aiHealthFailures = 0
  aiLivenessFailures = 0
  setAIPhase('offline', 'manual_restart')
  emitAIStatus({ online: false, phase: 'offline', reason: 'manual_restart' })
  await sleep(500)
  startAIService()
  return { ok: true }
})

ipcMain.handle('services:restartRust', async () => {
  console.log('[Main] Manual Rust service restart requested')
  try {
    rustProcess?.kill()
  } catch { /* already dead */ }
  rustProcess = null
  rustRestartCount = 0
  setTimeout(startRustService, 500)
  return { ok: true }
})

ipcMain.handle('services:getStatus', async () => {
  const aiRunning = (aiProcess !== null && !aiProcess.killed) || aiUsingExistingProcess
  let aiHealthy = false
  let aiMemory: Record<string, unknown> | null = null
  let aiPhase: string | null = null
  let aiIsReady = false

  if (aiRunning) {
    try {
      const resp = await fetch(`http://127.0.0.1:${AI_PORT}/health`, {
        signal: AbortSignal.timeout(5000),
      })
      if (resp.ok) {
        const data = (await resp.json()) as {
          status?: string
          phase?: string
          is_ready?: boolean
          memory?: Record<string, unknown>
          tasks?: Record<string, unknown>
        }
        aiHealthy = data.status === 'ok' || data.status === 'degraded'
        aiMemory = (data.memory as Record<string, unknown>) ?? null
        aiPhase = data.phase ?? null
        aiIsReady = data.is_ready ?? false
      }
    } catch {
      // Health check timed out — process may still be starting, not a failure
      aiHealthy = aiServicePhase === 'online' || aiServicePhase === 'degraded'
    }
  }

  return {
    rust: { running: rustProcess !== null && !rustProcess.killed, port: RUST_PORT },
    ai: {
      running: aiRunning,
      healthy: aiHealthy,
      ready: aiIsReady,
      phase: aiPhase ?? aiServicePhase,
      port: AI_PORT,
      restarts: aiRestartCount,
      maxRestarts: AI_MAX_RESTARTS,
      memory: aiMemory,
      lastHealthTime: aiLastSuccessfulHealthTime,
      uptime: aiSpawnTime > 0 ? Math.round((Date.now() - aiSpawnTime) / 1000) : 0,
    },
  }
})

app.whenReady().then(async () => {
  registerMediaProtocol()
  createWindow()

  // Bootstrap manager handles Rust + AI start AND broadcasts the first-run
  // signal if no Whisper model is installed yet. This replaces the previous
  // direct startRustService() / startAIService() calls.
  await runBootstrap({
    startRust: startRustService,
    startAI: startAIService,
    getMainWindow: () => mainWindow,
  })

  // Auto-update — no-op in dev, no-op if no publish channel is configured.
  const updater = await setupAutoUpdater(() => mainWindow)
  updater.start()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

function cleanupProcesses(): void {
  if (aiStartupSequenceAbort) {
    aiStartupSequenceAbort.abort()
    aiStartupSequenceAbort = null
  }
  if (aiHealthInterval) {
    clearInterval(aiHealthInterval)
    aiHealthInterval = null
  }
  try { rustProcess?.kill() } catch { /* already dead */ }
  try { aiProcess?.kill() } catch { /* already dead */ }
  rustProcess = null
  aiProcess = null
  aiUsingExistingProcess = false
}

app.on('window-all-closed', () => {
  cleanupProcesses()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  cleanupProcesses()
})
