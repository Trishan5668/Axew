import { useMemo } from 'react'
import { formatTimecode } from '../../lib/timecode'

interface TimelineRulerProps {
  zoom: number
  scrollX: number
  duration: number
  width: number
  frameRate?: number
}

export function TimelineRuler({
  zoom,
  scrollX,
  duration,
  width,
  frameRate = 30,
}: TimelineRulerProps) {
  const markers = useMemo(() => {
    const result: { time: number; major: boolean; label: string }[] = []
    if (width <= 0 || zoom <= 0) return result

    const visibleStart = scrollX / zoom
    const visibleEnd = visibleStart + width / zoom

    let interval: number
    if (zoom > 400) interval = 1 / frameRate
    else if (zoom > 100) interval = 1
    else if (zoom > 50) interval = 2
    else if (zoom > 20) interval = 5
    else if (zoom > 10) interval = 10
    else if (zoom > 5) interval = 30
    else interval = 60

    const majorInterval = interval * 5
    const start = Math.floor(visibleStart / interval) * interval

    for (let t = start; t <= Math.min(duration, visibleEnd + interval); t += interval) {
      const major = Math.abs(t % majorInterval) < 0.001
      result.push({
        time: t,
        major,
        label: major ? formatTimecode(t, frameRate, false) : '',
      })
    }
    return result
  }, [zoom, scrollX, duration, width, frameRate])

  return (
    <div className="relative h-full w-full overflow-hidden bg-axew-surface">
      <svg className="absolute inset-0 h-full w-full" style={{ overflow: 'visible' }}>
        {markers.map(({ time, major, label }) => {
          const x = time * zoom - scrollX
          if (x < -20 || x > width + 20) return null
          return (
            <g key={time}>
              <line
                x1={x}
                y1={major ? 0 : 12}
                x2={x}
                y2={24}
                stroke={major ? '#3E3E4E' : '#22222A'}
                strokeWidth={major ? 1 : 0.5}
              />
              {label && (
                <text x={x + 2} y={10} fill="#4B4B5E" fontSize="9" fontFamily="JetBrains Mono, monospace">
                  {label}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
