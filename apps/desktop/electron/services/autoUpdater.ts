/**
 * Auto-update integration via electron-updater.
 *
 * Verification-pending: a real publish channel (see electron-builder.yml
 * publish: section). Without it autoUpdater.checkForUpdates() throws —
 * we catch + log it so a misconfigured release channel never breaks
 * normal app launch.
 */

import { app, BrowserWindow, dialog } from 'electron'

interface UpdateBridge {
  start: () => void
  stop: () => void
}

let updaterPromise: Promise<typeof import('electron-updater') | null> | null = null

async function loadUpdater(): Promise<typeof import('electron-updater') | null> {
  if (updaterPromise) return updaterPromise
  updaterPromise = import('electron-updater')
    .then((m) => m)
    .catch((err) => {
      console.warn('[AutoUpdater] electron-updater not available:', err)
      return null
    })
  return updaterPromise
}

export async function setupAutoUpdater(getWindow: () => BrowserWindow | null): Promise<UpdateBridge> {
  if (app.isPackaged === false) {
    console.log('[AutoUpdater] Skipping in dev mode')
    return { start: () => undefined, stop: () => undefined }
  }

  const mod = await loadUpdater()
  if (!mod) {
    return { start: () => undefined, stop: () => undefined }
  }
  const { autoUpdater } = mod

  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = true
  autoUpdater.allowDowngrade = false

  let intervalHandle: ReturnType<typeof setInterval> | null = null

  autoUpdater.on('error', (err) => {
    console.warn('[AutoUpdater] error:', err.message)
  })
  autoUpdater.on('update-available', (info) => {
    getWindow()?.webContents.send('updates:available', info)
  })
  autoUpdater.on('update-not-available', () => {
    getWindow()?.webContents.send('updates:none')
  })
  autoUpdater.on('download-progress', (progress) => {
    getWindow()?.webContents.send('updates:progress', progress)
  })
  autoUpdater.on('update-downloaded', async () => {
    const win = getWindow()
    getWindow()?.webContents.send('updates:downloaded')
    if (!win) return
    const { response } = await dialog.showMessageBox(win, {
      type: 'info',
      title: 'Axew update ready',
      message: 'A new version of Axew has been downloaded. Restart now to install it?',
      buttons: ['Restart', 'Later'],
      defaultId: 0,
      cancelId: 1,
    })
    if (response === 0) autoUpdater.quitAndInstall()
  })

  return {
    start: () => {
      autoUpdater.checkForUpdates().catch((err) => {
        console.warn('[AutoUpdater] checkForUpdates failed:', err.message)
      })
      intervalHandle = setInterval(() => {
        autoUpdater.checkForUpdates().catch(() => undefined)
      }, 6 * 60 * 60 * 1000) // every 6 hours
    },
    stop: () => {
      if (intervalHandle) clearInterval(intervalHandle)
      intervalHandle = null
    },
  }
}
