import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { subscribeWithSelector } from 'zustand/middleware'
import type { Transcript } from '@shared/ai'
import type { MediaFile } from '@shared/media'
import type { Project, ProjectSettings } from '@shared/project'
import { getAxew } from '../lib/axewBridge'
import { createDefaultProject } from '../lib/projectFactory'

interface ProjectState {
  currentProject: Project | null
  isLoading: boolean
  isDirty: boolean
  error: string | null
}

interface ProjectActions {
  createProject: (name: string, settings?: Partial<ProjectSettings>) => void
  loadProject: (projectPath: string) => Promise<void>
  saveProject: () => Promise<void>
  closeProject: () => void
  addMediaFile: (file: MediaFile) => void
  removeMediaFile: (fileId: string) => void
  updateMediaFile: (fileId: string, updates: Partial<MediaFile>) => void
  setTranscript: (mediaId: string, transcript: Transcript) => void
  setDirty: (dirty: boolean) => void
  clearError: () => void
}

export const useProjectStore = create<ProjectState & ProjectActions>()(
  subscribeWithSelector(
    immer((set, get) => ({
      currentProject: null,
      isLoading: false,
      isDirty: false,
      error: null,

      createProject: (name, settings) => {
        const project = createDefaultProject(name, settings)
        set((state) => {
          state.currentProject = project
          state.isDirty = false
          state.error = null
        })
      },

      loadProject: async (projectPath) => {
        set((state) => {
          state.isLoading = true
          state.error = null
        })
        try {
          const result = await getAxew().fs.readFile(projectPath)
          if (!result.success || !result.data) throw new Error(result.error ?? 'Read failed')
          const data = atob(result.data)
          const project: Project = JSON.parse(data)
          if (!project.transcripts) project.transcripts = {}
          set((state) => {
            state.currentProject = project
            state.isLoading = false
            state.isDirty = false
          })
        } catch (err) {
          set((state) => {
            state.error = String(err)
            state.isLoading = false
          })
        }
      },

      saveProject: async () => {
        const { currentProject } = get()
        if (!currentProject) return
        try {
          const data = JSON.stringify(currentProject, null, 2)
          const result = await getAxew().fs.writeFile(currentProject.path, data)
          if (!result.success) throw new Error(result.error)
          set((state) => {
            state.isDirty = false
          })
        } catch (err) {
          set((state) => {
            state.error = String(err)
          })
        }
      },

      closeProject: () => {
        set((state) => {
          state.currentProject = null
          state.isDirty = false
          state.error = null
        })
      },

      addMediaFile: (file) => {
        set((state) => {
          if (state.currentProject) {
            state.currentProject.mediaFiles[file.id] = file
            state.currentProject.mediaBin.rootFolder.mediaIds.push(file.id)
            state.isDirty = true
          }
        })
      },

      removeMediaFile: (fileId) => {
        set((state) => {
          if (state.currentProject) {
            delete state.currentProject.mediaFiles[fileId]
            const folder = state.currentProject.mediaBin.rootFolder
            folder.mediaIds = folder.mediaIds.filter((id) => id !== fileId)
            state.isDirty = true
          }
        })
      },

      updateMediaFile: (fileId, updates) => {
        set((state) => {
          if (state.currentProject?.mediaFiles[fileId]) {
            Object.assign(state.currentProject.mediaFiles[fileId], updates)
            state.isDirty = true
          }
        })
      },

      setTranscript: (mediaId, transcript) => {
        set((state) => {
          if (state.currentProject) {
            if (!state.currentProject.transcripts) {
              state.currentProject.transcripts = {}
            }
            state.currentProject.transcripts[mediaId] = transcript
            state.isDirty = true
          }
        })
      },

      setDirty: (dirty) => {
        set((state) => {
          state.isDirty = dirty
        })
      },

      clearError: () => {
        set((state) => {
          state.error = null
        })
      },
    })),
  ),
)
