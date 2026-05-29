import type { AIEditAction, AIEditActionType, StructuredAction } from '@shared/ai'

const ACTION_TYPE_MAP: Record<string, AIEditActionType> = {
  cut_silence: 'cut-silence',
  'cut-silence': 'cut-silence',
  split_clip: 'split-clip',
  'split-clip': 'split-clip',
  delete_clip: 'delete-clip',
  'delete-clip': 'delete-clip',
  trim_clip: 'trim-clip',
  'trim-clip': 'trim-clip',
  add_subtitle: 'add-subtitle',
  'add-subtitle': 'add-subtitle',
  add_marker: 'add-marker',
  'add-marker': 'add-marker',
  detect_scenes: 'detect-scenes',
  'detect-scenes': 'detect-scenes',
  extract_clip: 'extract-clip',
  'extract-clip': 'extract-clip',
  keep_segment: 'keep-segment',
  'keep-segment': 'keep-segment',
  isolate_segment: 'isolate-segment',
  'isolate-segment': 'isolate-segment',
  highlight_segment: 'highlight-segment',
  'highlight-segment': 'highlight-segment',
}

export function structuredToEditAction(raw: StructuredAction): AIEditAction | null {
  const type = ACTION_TYPE_MAP[raw.action]
  if (!type) return null

  const params: Record<string, unknown> = {}
  if (raw.start !== undefined) params.start = raw.start
  if (raw.end !== undefined) params.end = raw.end
  if (raw.time !== undefined) params.time = raw.time
  if (raw.mediaId !== undefined) params.mediaId = raw.mediaId
  if (raw.clipId !== undefined) params.clipId = raw.clipId
  if (raw.name !== undefined) params.name = raw.name
  if (raw.matchText !== undefined) params.matchText = raw.matchText
  if (raw.reasoning !== undefined) params.reasoning = raw.reasoning
  if (raw.requiresConfirmation !== undefined) params.requiresConfirmation = raw.requiresConfirmation

  return {
    type,
    params,
    description: raw.matchText ?? raw.name ?? raw.action,
    confidence: raw.confidence ?? 0.5,
    clipIds: raw.clipId ? [raw.clipId] : undefined,
  }
}

export function parseStructuredActionsFromJson(text: string): StructuredAction[] {
  const actions: StructuredAction[] = []
  const jsonBlock = text.match(/```json\s*([\s\S]*?)```/i)
  const candidates = jsonBlock ? [jsonBlock[1]] : [text]

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate.trim())
      if (Array.isArray(parsed)) {
        actions.push(...parsed)
      } else if (parsed && typeof parsed === 'object' && 'action' in parsed) {
        actions.push(parsed as StructuredAction)
      } else if (parsed?.actions && Array.isArray(parsed.actions)) {
        actions.push(...parsed.actions)
      }
    } catch {
      const re = /\{[^{}]*"action"\s*:\s*"[^"]+"[^{}]*\}/g
      let m: RegExpExecArray | null
      while ((m = re.exec(text)) !== null) {
        try {
          actions.push(JSON.parse(m[0]) as StructuredAction)
        } catch {
          /* skip */
        }
      }
    }
  }
  return actions
}
