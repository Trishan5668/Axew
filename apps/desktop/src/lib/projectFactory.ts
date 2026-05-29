import { nanoid } from 'nanoid'
import type { Project, ProjectSettings } from '@shared/project'
import type { Timeline } from '@shared/timeline'

export function createDefaultProject(
  name: string,
  settingsOverride?: Partial<ProjectSettings>,
): Project {
  const id = nanoid()
  const timelineId = nanoid()
  const now = Date.now()

  const settings: ProjectSettings = {
    timeline: {
      frameRate: 30,
      width: 1920,
      height: 1080,
      sampleRate: 48000,
    },
    playback: {
      proxyEnabled: false,
      proxyResolution: 720,
      cacheSize: 4096,
    },
    ai: {
      preferredModel: 'llama3',
      autoTranscribe: false,
      silenceThresholdDb: -40,
      sceneDetectionSensitivity: 0.4,
    },
    export: {
      defaultPreset: 'h264-1080p',
      outputDirectory: '',
    },
    ...settingsOverride,
  }

  const timeline: Timeline = {
    id: timelineId,
    projectId: id,
    name: 'Timeline 1',
    duration: 300,
    frameRate: settings.timeline.frameRate,
    width: settings.timeline.width,
    height: settings.timeline.height,
    sampleRate: settings.timeline.sampleRate,
    tracks: [
      {
        id: nanoid(),
        timelineId,
        name: 'Video 1',
        type: 'video',
        index: 0,
        height: 80,
        locked: false,
        muted: false,
        visible: true,
        solo: false,
        color: '#1E3A5F',
        clips: [],
      },
      {
        id: nanoid(),
        timelineId,
        name: 'Audio 1',
        type: 'audio',
        index: 1,
        height: 60,
        locked: false,
        muted: false,
        visible: true,
        solo: false,
        color: '#1E4F3A',
        clips: [],
      },
    ],
    markers: [],
    createdAt: now,
    updatedAt: now,
  }

  const rootFolderId = nanoid()

  return {
    id,
    name,
    description: '',
    path: `${name.replace(/[^a-zA-Z0-9-_]/g, '_')}.axew`,
    timeline,
    mediaFiles: {},
    transcripts: {},
    mediaBin: {
      rootFolder: {
        id: rootFolderId,
        name: 'Root',
        parentId: null,
        children: [],
        mediaIds: [],
      },
      folders: {},
    },
    settings,
    createdAt: now,
    updatedAt: now,
    version: '0.1.0',
  }
}
