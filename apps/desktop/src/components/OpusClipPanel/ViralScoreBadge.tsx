/**
 * ViralScoreBadge — pill that visualises OpusClip's virality score (0..99).
 *
 * Renders `null` when the API didn't return a score. The public OpusClip
 * REST API does not always include virality in /api/exportable-clips, so
 * the field is optional on the wire.
 */

interface ViralScoreBadgeProps {
  /** 0..100, or null if OpusClip did not return one. */
  score: number | null
}

function tierFor(score: number): { label: string; classes: string } {
  // OpusClip publishes a 0..99 scale; 80+ are flagged "strong picks"
  // and 60+ are "above-median platform performance".
  if (score >= 80) {
    return { label: 'Excellent', classes: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-200' }
  }
  if (score >= 60) {
    return { label: 'Strong', classes: 'border-sky-500/40 bg-sky-500/15 text-sky-200' }
  }
  if (score >= 40) {
    return { label: 'Decent', classes: 'border-amber-500/40 bg-amber-500/15 text-amber-200' }
  }
  return { label: 'Weak', classes: 'border-zinc-500/40 bg-zinc-500/15 text-zinc-300' }
}

export function ViralScoreBadge({ score }: ViralScoreBadgeProps): JSX.Element | null {
  if (score === null || Number.isNaN(score)) return null
  const { label, classes } = tierFor(score)
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-medium ${classes}`}
      title={`Virality: ${Math.round(score)}/99`}
    >
      <span aria-hidden>★</span>
      {Math.round(score)} {label}
    </span>
  )
}
