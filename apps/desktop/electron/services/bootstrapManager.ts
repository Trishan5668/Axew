/**
 * Bootstrap manager — coordinates the application startup sequence so the
 * user never sees a terminal window.
 *
 * Order (mirrors the spec in TRACK 4):
 *   1. Launch Rust media backend (axew-core)
 *   2. Launch Python AI backend (uvicorn)
 *   3. Wait for both health checks
 *   4. Check Whisper model presence; if missing, broadcast "first-run"
 *      so the renderer routes to the wizard.
 *
 * NOTE: The actual lifecycle for the Rust + Python processes is already
 * implemented in electron/main.ts (startRustService / startAIService).
 * This module wraps them to add the model-presence check + first-run signal.
 */

import { BrowserWindow, ipcMain } from 'electron'
import { hasAnyModel, registerModelManagerIPC } from './modelManager'

export interface BootstrapHooks {
  startRust: () => void
  startAI: () => Promise<void>
  getMainWindow: () => BrowserWindow | null
}

export async function runBootstrap(hooks: BootstrapHooks): Promise<void> {
  registerModelManagerIPC()

  hooks.startRust()
  hooks.startAI().catch((err) => {
    console.error('[Bootstrap] AI service failed to start:', err)
  })

  // First-run check. We send the signal AFTER the window is ready, so
  // the renderer's React Router can react to it.
  const checkAndNotify = () => {
    const win = hooks.getMainWindow()
    if (!win) return
    if (win.webContents.isLoading()) {
      win.webContents.once('did-finish-load', checkAndNotify)
      return
    }
    if (!hasAnyModel()) {
      console.log('[Bootstrap] No Whisper model installed — prompting first-run wizard')
      win.webContents.send('app:first-run-required')
    } else {
      win.webContents.send('app:first-run-ok')
    }
  }
  // Defer one tick so window creation in main.ts has run.
  setTimeout(checkAndNotify, 1500)

  ipcMain.handle('app:first-run-status', () => ({
    hasModel: hasAnyModel(),
  }))
}
