import { CheckCircle2, Cloud, Mail, Server } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { CLOUD_ENABLED } from '../lib/cloudFlag'

export function FirstRunWizard(): JSX.Element {
  const navigate = useNavigate()

  return (
    <div className="flex h-full w-full items-center justify-center bg-axew-bg px-6">
      <div className="w-full max-w-md rounded-lg border border-axew-border bg-axew-surface p-6 shadow-xl">
        <header className="mb-4">
          <h1 className="text-lg font-semibold text-axew-text">Welcome to Axew</h1>
          <p className="mt-1 text-xs text-axew-textMuted">
            Axew now runs as a browser app. Start the FastAPI backend locally before using
            transcription or AI-assisted editing.
          </p>
        </header>

        <div className="space-y-3">
          <div className="flex items-start gap-2 rounded border border-axew-border bg-axew-panel p-3">
            <Server size={16} className="mt-0.5 text-axew-ai" />
            <div>
              <p className="text-xs font-medium text-axew-text">Backend</p>
              <p className="mt-1 font-mono text-2xs text-axew-textDim">
                uvicorn main:app --host 127.0.0.1 --port 7002
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 text-xs text-axew-success">
            <CheckCircle2 size={14} /> Browser setup is ready.
          </div>

          {CLOUD_ENABLED && (
            <button
              type="button"
              onClick={() => navigate('/login', { replace: true })}
              className="flex w-full items-center justify-center gap-1 rounded border border-axew-border bg-axew-panel px-3 py-2 text-xs text-axew-text hover:border-axew-ai/40"
            >
              <Mail size={12} /> Continue with Email or Google
            </button>
          )}

          <button
            type="button"
            onClick={() => navigate(CLOUD_ENABLED ? '/dashboard' : '/', { replace: true })}
            className="flex w-full items-center justify-center gap-1 rounded bg-axew-accent px-3 py-2 text-xs font-medium text-white hover:bg-axew-accentHover"
          >
            <Cloud size={12} /> Continue to Axew
          </button>
        </div>
      </div>
    </div>
  )
}
