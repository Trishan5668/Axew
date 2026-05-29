import type { PreviewFitMode } from './previewFit'

export type { PreviewFitMode } from './previewFit'

export interface Size2D {
  width: number
  height: number
}

export interface MonitorTransform {
  /** Rendered width of media in CSS pixels */
  width: number
  height: number
  /** Top-left offset within viewport */
  offsetX: number
  offsetY: number
  /** Uniform scale applied to source */
  scale: number
  /** Scale to fit entire frame in viewport (before zoom) */
  fitScale: number
  /** True when viewport or source not yet measurable */
  useFallback: boolean
  /** Enable scroll container (100% mode, oversized) */
  scrollable: boolean
  /** Content area size for scroll container */
  scrollWidth: number
  scrollHeight: number
}

/**
 * Professional monitor transform — mathematically correct letterbox/fill/native sizing.
 */
export function computeMonitorTransform(
  viewport: Size2D,
  source: Size2D,
  mode: PreviewFitMode,
  zoomPercent: number,
): MonitorTransform {
  const vw = viewport.width
  const vh = viewport.height
  const sw = Math.max(1, source.width)
  const sh = Math.max(1, source.height)

  if (vw < 2 || vh < 2) {
    return {
      width: 0,
      height: 0,
      offsetX: 0,
      offsetY: 0,
      scale: 1,
      fitScale: 1,
      useFallback: true,
      scrollable: false,
      scrollWidth: 0,
      scrollHeight: 0,
    }
  }

  const fitScale = Math.min(vw / sw, vh / sh)

  if (mode === 'fill') {
    const scale = Math.max(vw / sw, vh / sh)
    const width = sw * scale
    const height = sh * scale
    return {
      width,
      height,
      offsetX: (vw - width) / 2,
      offsetY: (vh - height) / 2,
      scale,
      fitScale,
      useFallback: false,
      scrollable: false,
      scrollWidth: vw,
      scrollHeight: vh,
    }
  }

  if (mode === '100') {
    const scale = zoomPercent / 100
    const width = sw * scale
    const height = sh * scale
    const scrollable = width > vw + 1 || height > vh + 1
    return {
      width,
      height,
      offsetX: scrollable ? 0 : (vw - width) / 2,
      offsetY: scrollable ? 0 : (vh - height) / 2,
      scale,
      fitScale,
      useFallback: false,
      scrollable,
      scrollWidth: Math.max(vw, width),
      scrollHeight: Math.max(vh, height),
    }
  }

  // fit — entire frame visible, letterboxed
  const scale = fitScale * (zoomPercent / 100)
  const width = sw * scale
  const height = sh * scale
  return {
    width,
    height,
    offsetX: (vw - width) / 2,
    offsetY: (vh - height) / 2,
    scale,
    fitScale,
    useFallback: false,
    scrollable: false,
    scrollWidth: vw,
    scrollHeight: vh,
  }
}

export function formatMonitorDebug(
  mode: PreviewFitMode,
  viewport: Size2D,
  source: Size2D,
  transform: MonitorTransform,
  playing: boolean,
): string[] {
  return [
    `mode: ${mode}`,
    `viewport: ${viewport.width}×${viewport.height}`,
    `source: ${source.width}×${source.height}`,
    `render: ${Math.round(transform.width)}×${Math.round(transform.height)}`,
    `offset: ${Math.round(transform.offsetX)},${Math.round(transform.offsetY)}`,
    `scale: ${transform.scale.toFixed(4)} (fit ${transform.fitScale.toFixed(4)})`,
    `fallback: ${transform.useFallback}`,
    `playing: ${playing}`,
  ]
}
