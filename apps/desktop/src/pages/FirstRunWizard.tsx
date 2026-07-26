/**
 * FirstRunWizard — runs once on a fresh install when no Whisper model
 * is present. Two flows:
 *
 *  Step 1: model picker — Turbo (faster) vs Large-v3 (best quality)
 *  Step 2: progress + (optional) "Sign in to enable cloud features"
 *
 * The model download is performed by electron/services/modelManager.ts
 * via the IPC channel `models:download`. Progress comes back on
 * `models:download-progress`.
 */

import { CheckCircle2, Cloud, Download, Loader2, Mail } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CLOUD_ENABLED } from '../lib/cloudFlag'

type ModelId = 'turbo' | 'large-v3'

interface AxewIpc {
  ipc?: {
    invoke?: (channel: string, ...args: unknown[]) => Promise<unknown>
    on?: (channel: string, listener: (...args: unknown[]) => void) => () => void
  }
}

function ipc(): AxewIpc['ipc'] {
  const axew = (window as unknown as { axew?: AxewIpc }).axew
  return axew?.ipc
}

interface DownloadProgress {
  modelId: ModelId
  bytesReceived: number
  bytesTotal: number
  percent: number
  speedBytesPerSec: number
}

function formatMb(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(0)} MB`
}

function formatSpeed(bps: number): string {
  if (bps <= 0) return ''
  if (bps > 1_000_000) return `${(bps / 1_000_000).toFixed(1)} MB/s`
  return `${(bps / 1_000).toFixed(0)} KB/s`
}

export function FirstRunWizard(): JSX.Element {
  const navigate = useNavigate()
  const [step, setStep] = useState<'pick' | 'download' | 'done'>('pick')
  const [selected, setSelected] = useState<ModelId>('turbo')
  const [progress, setProgress] = useState<DownloadProgress | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const handle = ipc()?.on?.('models:download-progress', (...args: unknown[]) => {
      const payload = args[args.length - 1] as DownloadProgress
      setProgress(payload)
    })
    return () => {
      try { handle?.() } catch { /* noop */ }
    }
  }, [])

  const startDownload = async () => {
    setError(null)
    setStep('download')
    const invoke = ipc()?.invoke
    if (!invoke) {
      setError('Unable to communicate with the installer process. Please restart Axew.')
      return
    }
    try {
      const result = (await invoke('models:download', selected)) as { ok: boolean; error?: string }
      if (!result.ok) {
        setError(result.error ?? 'Download failed. Please try again.')
        setStep('pick')
        return
      }
      setStep('done')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setStep('pick')
    }
  }

  return (
    <div className="flex h-full w-full items-center justify-center bg-axew-bg px-6">
      <div className="w-full max-w-md rounded-lg border border-axew-border bg-axew-surface p-6 shadow-xl">
        <header className="mb-4">
          <h1 className="text-lg font-semibold text-axew-text">Welcome to Axew</h1>
          <p className="mt-1 text-xs text-axew-textMuted">
            Axew uses an on-device Whisper model for transcription. Pick which one to install —
            you can switch later.
          </p>
        </header>

        {error && (
          <div role="alert" className="mb-3 rounded border border-red-500/40 bg-red-500/10 p-2 text-2xs text-red-200">
            {error}
          </div>
        )}

        {step === 'pick' && (
          <div className="space-y-2">
            <ModelOption
              checked={selected === 'turbo'}
              onSelect={() => setSelected('turbo')}
              title="Turbo"
              subtitle="≈ 1.5 GB · fastest, slightly lower accuracy"
            />
            <ModelOption
              checked={selected === 'large-v3'}
              onSelect={() => setSelected('large-v3')}
              title="Large-v3"
              subtitle="≈ 3 GB · highest accuracy, slower"
            />
            <button
              type="button"
              onClick={startDownload}
              className="mt-3 flex w-full items-center justify-center gap-1 rounded bg-axew-accent px-3 py-2 text-xs font-medium text-white hover:bg-axew-accentHover"
            >
              <Download size={12} /> Install model
            </button>
            <p className="mt-1 text-2xs text-axew-textDim">
              Download is resumable — feel free to close Axew if you need to pause.
            </p>
          </div>
        )}

        {step === 'download' && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs text-axew-textMuted">
              <Loader2 size={14} className="animate-spin" />
              Downloading {selected} model…
            </div>
            <div className="h-2 w-full overflow-hidden rounded bg-axew-panel">
              <div
                className="h-full bg-axew-ai transition-[width] duration-300"
                style={{ width: `${Math.round((progress?.percent ?? 0) * 100)}%` }}
              />
            </div>
            <p className="flex items-center justify-between text-2xs text-axew-textDim">
              <span>
                {progress
                  ? `${formatMb(progress.bytesReceived)} / ${formatMb(progress.bytesTotal)}`
                  : 'Starting…'}
              </span>
              <span>{progress ? formatSpeed(progress.speedBytesPerSec) : ''}</span>
            </p>
          </div>
        )}

        {step === 'done' && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs text-axew-success">
              <CheckCircle2 size={14} /> Model installed. Axew is ready to use.
            </div>
            <div className="space-y-2">
              {CLOUD_ENABLED && (
                <>
                  <p className="text-2xs text-axew-textMuted">
                    Optional: sign in to enable OpusClip-enhanced exports and credit-based billing.
                  </p>
                  <button
                    type="button"
                    onClick={() => navigate('/login', { replace: true })}
                    className="flex w-full items-center justify-center gap-1 rounded border border-axew-border bg-axew-panel px-3 py-2 text-xs text-axew-text hover:border-axew-ai/40"
                  >
                    <Mail size={12} /> Continue with Email or Google
                  </button>
                  <p className="text-center text-2xs text-axew-textDim">— or —</p>
                </>
              )}
              <button
                type="button"
                onClick={() => navigate(CLOUD_ENABLED ? '/dashboard' : '/', { replace: true })}
                className="flex w-full items-center justify-center gap-1 rounded bg-axew-accent px-3 py-2 text-xs font-medium text-white hover:bg-axew-accentHover"
              >
                <Cloud size={12} /> Use Axew offline
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

interface ModelOptionProps {
  checked: boolean
  onSelect: () => void
  title: string
  subtitle: string
}

function ModelOption({ checked, onSelect, title, subtitle }: ModelOptionProps): JSX.Element {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full items-start gap-2 rounded border p-2 text-left transition-colors ${
        checked
          ? 'border-axew-accent bg-axew-accent/10'
          : 'border-axew-border bg-axew-panel hover:border-axew-ai/40'
      }`}
      aria-pressed={checked}
    >
      <span
        className={`mt-1 inline-block h-3 w-3 flex-shrink-0 rounded-full border ${
          checked ? 'border-axew-accent bg-axew-accent' : 'border-axew-textDim'
        }`}
      />
      <span className="flex-1">
        <p className="text-xs font-medium text-axew-text">{title}</p>
        <p className="text-2xs text-axew-textDim">{subtitle}</p>
      </span>
    </button>
  )
}
