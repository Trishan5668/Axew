import { Zap } from 'lucide-react'
import { isCloudEnabled } from '../../lib/cloudConfig'
import { useOpusclipHealth } from '../../hooks/useOpusclipHealth'
import { cn } from '../../lib/cn'

const REASON_LABELS: Record<string, string> = {
  missing_api_key: 'No API key configured',
  backend_unreachable: 'Backend unreachable',
  timeout: 'Health check timed out',
  authentication_failed: 'Authentication failed',
  service_unavailable: 'Service unavailable',
  cloud_disabled: 'Cloud features disabled',
}

export function OpusClipStatusBadge() {
  // `isCloudEnabled()` is a plain function (not a hook), so calling the hook
  // unconditionally below keeps hook order stable across dev/prod/EXE builds.
  const cloudEnabled = isCloudEnabled()
  const health = useOpusclipHealth({ enabled: cloudEnabled })

  const label =
    health.state === 'loading'
      ? 'Checking…'
      : health.state === 'online'
        ? 'Online'
        : 'Offline'

  const dot =
    health.state === 'loading' ? '⚪' : health.state === 'online' ? '🟢' : '🔴'

  const title =
    health.state === 'offline' && health.reason
      ? REASON_LABELS[health.reason] ?? health.reason
      : health.state === 'online'
        ? 'OpusClip API reachable'
        : 'Checking OpusClip API status'

  return (
    <span
      data-testid="opusclip-status-badge"
      data-state={health.state}
      title={title}
      className={cn(
        'flex items-center gap-1 text-2xs',
        health.state === 'online' && 'text-axew-success',
        health.state === 'offline' && 'text-red-400',
        health.state === 'loading' && 'text-axew-textDim',
      )}
    >
      <Zap size={10} aria-hidden />
      <span>OpusClip API:</span>
      <span className="font-medium">
        {dot} {label}
      </span>
    </span>
  )
}
