import { memo, useCallback, useRef, type CSSProperties, type VideoHTMLAttributes } from 'react'

export interface MonitorVideoProps {
  src: string
  style: CSSProperties
  onAttachRef?: (el: HTMLVideoElement | null) => void
  videoProps?: VideoHTMLAttributes<HTMLVideoElement>
}

/**
 * Isolated video element with a stable ref callback (prevents ref→setState loops).
 */
export const MonitorVideo = memo(function MonitorVideo({
  src,
  style,
  onAttachRef,
  videoProps,
}: MonitorVideoProps) {
  const attachedElRef = useRef<HTMLVideoElement | null>(null)
  const onAttachRefRef = useRef(onAttachRef)
  onAttachRefRef.current = onAttachRef

  const attachRef = useCallback((el: HTMLVideoElement | null) => {
    if (attachedElRef.current === el) return
    attachedElRef.current = el
    onAttachRefRef.current?.(el)
  }, [])

  const { style: vpStyle, ...restVideoProps } = videoProps ?? {}

  return (
    <video
      ref={attachRef}
      src={src}
      preload="auto"
      playsInline
      {...restVideoProps}
      style={{ ...style, ...vpStyle }}
    />
  )
})
