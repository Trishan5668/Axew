import { create } from 'zustand'
import type { ExportJob, ExportPreset } from '@shared/export'
import { DEFAULT_EXPORT_PRESETS } from '@shared/export'

interface ExportState {
  jobs: ExportJob[]
  activeJobId: string | null
  presets: ExportPreset[]
  selectedPresetId: string
}

interface ExportActions {
  addJob: (job: ExportJob) => void
  updateJob: (jobId: string, updates: Partial<ExportJob>) => void
  removeJob: (jobId: string) => void
  setActiveJob: (jobId: string | null) => void
  setSelectedPreset: (presetId: string) => void
}

export const useExportStore = create<ExportState & ExportActions>()((set) => ({
  jobs: [],
  activeJobId: null,
  presets: DEFAULT_EXPORT_PRESETS,
  selectedPresetId: 'h264-1080p',

  addJob: (job) => set((state) => ({ jobs: [...state.jobs, job] })),
  updateJob: (jobId, updates) =>
    set((state) => ({
      jobs: state.jobs.map((j) => (j.id === jobId ? { ...j, ...updates } : j)),
    })),
  removeJob: (jobId) =>
    set((state) => ({ jobs: state.jobs.filter((j) => j.id !== jobId) })),
  setActiveJob: (jobId) => set({ activeJobId: jobId }),
  setSelectedPreset: (presetId) => set({ selectedPresetId: presetId }),
}))
