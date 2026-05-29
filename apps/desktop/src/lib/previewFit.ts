export type PreviewFitMode = 'fit' | 'fill' | '100'

export interface Size2D {
  width: number
  height: number
}

export interface PreviewMediaLayout {
  width: number
  height: number
  /** Display zoom relative to fit-to-window (100 = fit baseline for fit mode) */
  displayZoomPercent: number
}

/**
 * Compute pixel dimensions for media inside the monitor viewport.
 * Fit: letterbox/pillarbox — entire frame visible.
 * Fill: cover viewport — may crop edges.
 * 100: native resolution × zoom (scroll if larger than viewport).
 */
export function computePreviewMediaLayout(
  viewport: Size2D,
  media: Size2D,
  mode: PreviewFitMode,
  zoomPercent: number,
): PreviewMediaLayout {
  const vw = Math.max(1, viewport.width)
  const vh = Math.max(1, viewport.height)
  const mw = Math.max(1, media.width)
  const mh = Math.max(1, media.height)

  const fitScale = Math.min(vw / mw, vh / mh)

  if (mode === 'fill') {
    const scale = Math.max(vw / mw, vh / mh)
    return {
      width: mw * scale,
      height: mh * scale,
      displayZoomPercent: Math.round((scale / fitScale) * 100),
    }
  }

  if (mode === '100') {
    const nativeScale = zoomPercent / 100
    return {
      width: mw * nativeScale,
      height: mh * nativeScale,
      displayZoomPercent: zoomPercent,
    }
  }

  // fit (default) — scale to fit entirely inside viewport
  const scale = fitScale * (zoomPercent / 100)
  return {
    width: mw * scale,
    height: mh * scale,
    displayZoomPercent: zoomPercent,
  }
}

export function getFitModeLabel(mode: PreviewFitMode): string {
  switch (mode) {
    case 'fit':
      return 'Fit'
    case 'fill':
      return 'Fill'
    case '100':
      return '100%'
    default:
      return 'Fit'
  }
}
