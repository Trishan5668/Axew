/**
 * Per-clip processing progress bar.
 *
 * Progress is derived from the real OpusClip project stage
 * (`PENDING → QUEUED → CURATE → REFINE → RENDER → UPLOAD → COMPLETE`)
 * inside the opusclip slice. See `stageToProgress()` in opusclipClient.ts
 * for the stage → fraction mapping.
 */

interface ProcessingProgressProps {
  progress: number // 0..1
  label?: string
}

export function ProcessingProgress({ progress, label }: ProcessingProgressProps): JSX.Element {
  const clamped = Math.max(0, Math.min(1, progress))
  return (
    <div className="w-full" aria-live="polite">
      {label && <p className="mb-0.5 text-2xs text-axew-textDim">{label}</p>}
      <div
        role="progressbar"
        aria-valuenow={Math.round(clamped * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1 w-full overflow-hidden rounded bg-axew-panel"
      >
        <div
          className="h-full bg-axew-ai transition-[width] duration-300 ease-out"
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
      <p className="mt-0.5 text-right text-2xs text-axew-textDim">{Math.round(clamped * 100)}%</p>
    </div>
  )
}
