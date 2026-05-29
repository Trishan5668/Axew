import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { PreviewFitMode } from '../lib/previewFit'

export type PanelId = 'mediaBin' | 'inspector' | 'ai' | 'export' | 'effects'
export type ActiveTool = 'select' | 'blade' | 'hand'

export interface PreviewMonitorSettings {
  fitMode: PreviewFitMode
  zoomPercent: number
  showSafeArea: boolean
}

interface PanelLayout {
  leftWidth: number
  rightWidth: number
  timelineHeight: number
  aiPanelOpen: boolean
  inspectorPanelOpen: boolean
}

interface Notification {
  id: string
  type: 'info' | 'success' | 'warning' | 'error'
  message: string
  timestamp: number
  duration?: number
}

interface UIState {
  layout: PanelLayout
  preview: PreviewMonitorSettings
  activePanel: PanelId | null
  activeTool: ActiveTool
  showWelcome: boolean
  showExportDialog: boolean
  notifications: Notification[]
  statusMessage: string | null
  isMediaImporting: boolean
}

interface UIActions {
  setLayout: (layout: Partial<PanelLayout>) => void
  togglePanel: (panelId: PanelId) => void
  setActivePanel: (panelId: PanelId | null) => void
  setActiveTool: (tool: ActiveTool) => void
  setShowWelcome: (show: boolean) => void
  setShowExportDialog: (show: boolean) => void
  addNotification: (notification: Omit<Notification, 'id' | 'timestamp'>) => string
  removeNotification: (id: string) => void
  setStatusMessage: (message: string | null) => void
  setIsMediaImporting: (importing: boolean) => void
  setPreviewSettings: (settings: Partial<PreviewMonitorSettings>) => void
  cyclePreviewFitMode: () => void
}

const generateId = () => Math.random().toString(36).slice(2)

export const useUIStore = create<UIState & UIActions>()(
  persist(
    (set, get) => ({
      layout: {
        leftWidth: 260,
        rightWidth: 280,
        timelineHeight: 320,
        aiPanelOpen: false,
        inspectorPanelOpen: true,
      },
      preview: {
        fitMode: 'fit',
        zoomPercent: 100,
        showSafeArea: false,
      },
      activePanel: 'mediaBin',
      activeTool: 'select',
      showWelcome: true,
      showExportDialog: false,
      notifications: [],
      statusMessage: null,
      isMediaImporting: false,

      setLayout: (layout) =>
        set((state) => ({
          layout: { ...state.layout, ...layout },
        })),

      togglePanel: (panelId) =>
        set((state) => {
          if (panelId === 'ai') {
            return { layout: { ...state.layout, aiPanelOpen: !state.layout.aiPanelOpen } }
          }
          if (panelId === 'inspector') {
            return {
              layout: {
                ...state.layout,
                inspectorPanelOpen: !state.layout.inspectorPanelOpen,
              },
            }
          }
          return { activePanel: state.activePanel === panelId ? null : panelId }
        }),

      setActivePanel: (panelId) => set({ activePanel: panelId }),
      setActiveTool: (tool) => set({ activeTool: tool }),
      setShowWelcome: (show) => set({ showWelcome: show }),
      setShowExportDialog: (show) => set({ showExportDialog: show }),

      addNotification: (notification) => {
        const id = generateId()
        set((state) => ({
          notifications: [...state.notifications, { id, timestamp: Date.now(), ...notification }],
        }))
        const duration = notification.duration ?? 4000
        if (duration > 0) {
          setTimeout(() => get().removeNotification(id), duration)
        }
        return id
      },

      removeNotification: (id) =>
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id),
        })),

      setStatusMessage: (message) => set({ statusMessage: message }),
      setIsMediaImporting: (importing) => set({ isMediaImporting: importing }),

      setPreviewSettings: (settings) =>
        set((state) => ({
          preview: { ...state.preview, ...settings },
        })),

      cyclePreviewFitMode: () =>
        set((state) => {
          const order: PreviewFitMode[] = ['fit', 'fill', '100']
          const idx = order.indexOf(state.preview.fitMode)
          const next = order[(idx + 1) % order.length]
          return {
            preview: {
              ...state.preview,
              fitMode: next,
              zoomPercent: next === '100' ? 100 : state.preview.zoomPercent,
            },
          }
        }),
    }),
    {
      name: 'axew-ui-layout',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ layout: state.layout, preview: state.preview }),
    },
  ),
)
