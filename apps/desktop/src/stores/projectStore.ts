import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { subscribeWithSelector } from 'zustand/middleware'
import type { Transcript } from '@shared/ai'
import type { MediaFile } from '@shared/media'
import type { Project, ProjectSettings } from '@shared/project'
import { loadLastProjectFromBrowser, saveProjectToBrowser } from '../lib/browserProjectStorage'
import { createDefaultProject } from '../lib/projectFactory'

interface ProjectState {
  currentProject: Project | null
  isLoading: boolean
  isDirty: boolean
  error: string | null
}

interface ProjectActions {
  createProject: (name: string, settings?: Partial<ProjectSettings>) => void
  openProject: (project: Project) => void
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
        saveProjectToBrowser(project)
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
          const project = loadLastProjectFromBrowser()
          if (!project || (projectPath && project.path !== projectPath && project.id !== projectPath)) {
            throw new Error('Project is not available in browser storage')
          }
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
          saveProjectToBrowser(currentProject)
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
            saveProjectToBrowser(state.currentProject)
          }
        })
      },

      openProject: (project) => {
        if (!project.transcripts) project.transcripts = {}
        saveProjectToBrowser(project)
        set((state) => {
          state.currentProject = project
          state.isDirty = false
          state.error = null
        })
      },

      removeMediaFile: (fileId) => {
        set((state) => {
          if (state.currentProject) {
            delete state.currentProject.mediaFiles[fileId]
            const folder = state.currentProject.mediaBin.rootFolder
            folder.mediaIds = folder.mediaIds.filter((id) => id !== fileId)
            state.isDirty = true
            saveProjectToBrowser(state.currentProject)
          }
        })
      },

      updateMediaFile: (fileId, updates) => {
        set((state) => {
          if (state.currentProject?.mediaFiles[fileId]) {
            Object.assign(state.currentProject.mediaFiles[fileId], updates)
            state.isDirty = true
            saveProjectToBrowser(state.currentProject)
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
            saveProjectToBrowser(state.currentProject)
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
