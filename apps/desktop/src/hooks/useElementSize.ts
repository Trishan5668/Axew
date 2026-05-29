import { useCallback, useEffect, useRef, useState } from 'react'
import type { Size2D } from '../lib/monitorScale'

/**
 * Measures an element via callback ref + ResizeObserver.
 * Re-attaches only when the DOM node changes; debounces resize via rAF.
 */
export function useElementSize(): {
  ref: (node: HTMLDivElement | null) => void
  size: Size2D
} {
  const [size, setSize] = useState<Size2D>({ width: 0, height: 0 })
  const observerRef = useRef<ResizeObserver | null>(null)
  const nodeRef = useRef<HTMLDivElement | null>(null)
  const rafRef = useRef<number>(0)
  const sizeRef = useRef<Size2D>({ width: 0, height: 0 })

  const disconnect = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = 0
    }
    observerRef.current?.disconnect()
    observerRef.current = null
  }, [])

  const applySize = useCallback((w: number, h: number) => {
    if (sizeRef.current.width === w && sizeRef.current.height === h) return
    sizeRef.current = { width: w, height: h }
    setSize(sizeRef.current)
  }, [])

  const measure = useCallback(
    (node: HTMLDivElement) => {
      const rect = node.getBoundingClientRect()
      applySize(Math.round(rect.width), Math.round(rect.height))
    },
    [applySize],
  )

  const scheduleMeasure = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0
      if (nodeRef.current) measure(nodeRef.current)
    })
  }, [measure])

  const ref = useCallback(
    (node: HTMLDivElement | null) => {
      if (nodeRef.current === node) return

      disconnect()
      nodeRef.current = node

      if (!node) {
        applySize(0, 0)
        return
      }

      measure(node)
      const observer = new ResizeObserver(scheduleMeasure)
      observer.observe(node)
      observerRef.current = observer
    },
    [disconnect, measure, scheduleMeasure, applySize],
  )

  useEffect(() => () => disconnect(), [disconnect])

  return { ref, size }
}
