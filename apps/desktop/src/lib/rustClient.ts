const RUST_URL = 'http://localhost:7001/api'

export interface MediaProbeResult {
  duration: number
  width: number
  height: number
  fps: number
  video_codec?: string
  audio_codec?: string
  sample_rate?: number
  channels?: number
  bitrate: number
  has_video?: boolean
  has_audio?: boolean
}

export async function probeMedia(path: string): Promise<MediaProbeResult | null> {
  try {
    const response = await fetch(`${RUST_URL}/media/probe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
    if (!response.ok) return null
    return response.json()
  } catch {
    return null
  }
}

export async function generateThumbnail(
  path: string,
  time = 1.0,
): Promise<string | null> {
  try {
    const response = await fetch(`${RUST_URL}/media/thumbnail`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, time }),
    })
    if (!response.ok) return null
    const data = await response.json()
    return data.thumbnail_path ?? null
  } catch {
    return null
  }
}

export async function startExport(job: {
  job_id: string
  input_path: string
  output_path: string
  video_codec: string
  audio_codec: string
  width: number
  height: number
  frame_rate: number
  video_bitrate: number
  audio_bitrate: number
  crf: number
  extra_args: string[]
}) {
  const response = await fetch(`${RUST_URL}/export/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(job),
  })
  if (!response.ok) throw new Error('Export start failed')
  return response.json()
}

export async function getExportStatus(jobId: string) {
  const response = await fetch(`${RUST_URL}/export/status/${jobId}`)
  if (!response.ok) throw new Error('Export status failed')
  return response.json()
}

export interface ExtractClipResult {
  success: boolean
  output_path?: string
  actual_duration?: number
  ffmpeg_command?: string
  ffmpeg_stderr?: string
  validation?: {
    has_video_stream: boolean
    has_audio_stream: boolean
    video_codec: string
    audio_codec: string
    duration_seconds: number
    frame_count: number
    is_playable: boolean
    container_valid: boolean
    warnings: string[]
  }
  error?: string
}

export async function extractClip(params: {
  media_id: string
  input_path: string
  start_time: number
  end_time: number
  output_name: string
  strategy?: string
}): Promise<ExtractClipResult> {
  const response = await fetch(`${RUST_URL}/media/extract-clip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const text = await response.text()
    return { success: false, error: `HTTP ${response.status}: ${text}` }
  }
  return response.json()
}

export async function checkRustHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${RUST_URL}/health`, { signal: AbortSignal.timeout(3000) })
    return response.ok
  } catch {
    return false
  }
}
