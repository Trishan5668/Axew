/**
 * ClipCard — one enhanced clip in the OpusClip panel result list.
 *
 * Buttons:
 *   Preview      — opens the clip's preview URL (CDN-hosted, fast).
 *   Import       — registers the clip's high-res URL as a MediaFile and
 *                  appends it to the first video track on the timeline.
 *   Download MP4 — same URL, but with the download attribute hint.
 *
 * "Preview" + "Import" map directly onto the user-visible requirements
 * ("Allow preview and import into timeline") in the integration spec.
 */

import { Check, Download, Play, Plus } from 'lucide-react'
import type { OpusClipResult } from '../../lib/opusclipClient'
import { ViralScoreBadge } from './ViralScoreBadge'

interface ClipCardProps {
  result: OpusClipResult
  /** True once the user has imported this clip into the timeline. */
  imported?: boolean
  onPreview: () => void
  onImport: () => void
}

function formatSeconds(s: number): string {
  if (!Number.isFinite(s) || s < 0) return '0:00'
  const minutes = Math.floor(s / 60)
  const seconds = Math.floor(s % 60)
    .toString()
    .padStart(2, '0')
  return `${minutes}:${seconds}`
}

export function ClipCard({
  result,
  imported = false,
  onPreview,
  onImport,
}: ClipCardProps): JSX.Element {
  const start = result.source_range.start_seconds
  const end = result.source_range.end_seconds
  const headline =
    result.title ?? result.source_range.label ?? 'Enhanced clip'

  return (
    <article className="rounded border border-axew-border bg-axew-surface p-2">
      <header className="mb-1 flex items-start justify-between gap-2">
        <h3 className="line-clamp-2 text-2xs font-medium text-axew-text">{headline}</h3>
        <ViralScoreBadge score={result.viral_score} />
      </header>

      {result.description && (
        <p className="mb-1 line-clamp-2 text-2xs text-axew-textMuted">{result.description}</p>
      )}

      <p className="text-2xs text-axew-textDim">
        <span className="text-axew-textMuted">Source:</span>{' '}
        {start.toFixed(1)}s – {end.toFixed(1)}s
        <span className="ml-2 text-axew-textMuted">Duration:</span>{' '}
        {formatSeconds(result.duration_seconds)}
      </p>

      {result.hashtags && (
        <p className="mt-1 truncate text-2xs text-axew-textMuted" title={result.hashtags}>
          {result.hashtags}
        </p>
      )}

      <footer className="mt-2 flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={onPreview}
          className="flex items-center gap-1 rounded border border-axew-border bg-axew-panel px-2 py-1 text-2xs text-axew-text hover:bg-axew-panel/70"
          aria-label={`Preview ${headline}`}
        >
          <Play size={10} /> Preview
        </button>

        <button
          type="button"
          onClick={onImport}
          disabled={imported}
          className={`flex items-center gap-1 rounded px-2 py-1 text-2xs font-medium ${
            imported
              ? 'cursor-default border border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
              : 'bg-axew-accent text-white hover:bg-axew-accentHover'
          }`}
          aria-label={imported ? 'Already imported' : `Import ${headline} into timeline`}
        >
          {imported ? (
            <>
              <Check size={10} /> Imported
            </>
          ) : (
            <>
              <Plus size={10} /> Import to Timeline
            </>
          )}
        </button>

        <a
          href={result.clip_url}
          target="_blank"
          rel="noreferrer"
          download
          className="flex items-center gap-1 rounded border border-axew-border px-2 py-1 text-2xs text-axew-textMuted hover:text-axew-text"
          aria-label={`Download ${headline} as MP4`}
        >
          <Download size={10} /> MP4
        </a>
      </footer>
    </article>
  )
}
