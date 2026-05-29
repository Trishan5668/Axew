import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'
import type {
  AIAppliedOperation,
  AIEditAction,
  AIExecutionLogEntry,
  AIExecutionPhase,
  AIHighlightRange,
  AIModel,
  SemanticMatch,
} from '@shared/ai'

export interface DebugRetrievalSnapshot {
  query: string
  parsedIntent: Record<string, unknown>
  candidates: {
    chunkId: string
    text: string
    startSec: number
    endSec: number
    scoreBm25: number
    scoreSemantic: number
    scoreReranked: number
    confidence: number
  }[]
  finalWindow: { startSec: number; endSec: number; confidence: number }
  pipelineTrace: string[]
  confidenceGrade?: string | null
  mediaDuration?: number
}

interface AIState {
  models: AIModel[]
  activeModel: string | null
  isThinking: boolean
  pendingActions: AIEditAction[]
  appliedOperations: AIAppliedOperation[]
  executionPhase: AIExecutionPhase
  executionLogs: AIExecutionLogEntry[]
  semanticMatches: SemanticMatch[]
  highlightRanges: AIHighlightRange[]
  ollamaStatus: 'connected' | 'disconnected' | 'checking'
  aiServiceStatus: 'connected' | 'disconnected' | 'checking' | 'starting'
  aiServicePhase: string | null
  debugPanelOpen: boolean
  debugRetrieval: DebugRetrievalSnapshot | null
  retrievalSessionId: string | null
  lastRetrievalQuery: string | null
  suggestedAction: AIEditAction | null
}

interface AIActions {
  setModels: (models: AIModel[]) => void
  setActiveModel: (modelId: string) => void
  setIsThinking: (thinking: boolean) => void
  addPendingAction: (action: AIEditAction) => void
  clearPendingActions: () => void
  removePendingAction: (index: number) => void
  setExecutionPhase: (phase: AIExecutionPhase) => void
  appendExecutionLog: (
    phase: AIExecutionPhase,
    message: string,
    data?: Record<string, unknown>,
  ) => void
  resetExecution: () => void
  setSemanticMatches: (matches: SemanticMatch[]) => void
  setHighlightRanges: (ranges: AIHighlightRange[]) => void
  recordAppliedOperation: (op: AIAppliedOperation) => void
  setOllamaStatus: (status: AIState['ollamaStatus']) => void
  setAIServiceStatus: (status: AIState['aiServiceStatus']) => void
  setAIServicePhase: (phase: string | null) => void
  setDebugPanelOpen: (open: boolean) => void
  setDebugRetrieval: (snapshot: DebugRetrievalSnapshot | null) => void
  setRetrievalSessionId: (id: string | null) => void
  setLastRetrievalQuery: (query: string | null) => void
  setSuggestedAction: (action: AIEditAction | null) => void
}

const genId = () => Math.random().toString(36).slice(2)

export const useAIStore = create<AIState & AIActions>()(
  subscribeWithSelector((set) => ({
    models: [],
    activeModel: null,
    isThinking: false,
    pendingActions: [],
    appliedOperations: [],
    executionPhase: 'idle',
    executionLogs: [],
    semanticMatches: [],
    highlightRanges: [],
    ollamaStatus: 'checking',
    aiServiceStatus: 'checking',
    aiServicePhase: null,
    debugPanelOpen: false,
    debugRetrieval: null,
    retrievalSessionId: null,
    lastRetrievalQuery: null,
    suggestedAction: null,

    setModels: (models) => set({ models }),
    setActiveModel: (modelId) => set({ activeModel: modelId }),
    setIsThinking: (thinking) => set({ isThinking: thinking }),

    addPendingAction: (action) => {
      set((state) => ({ pendingActions: [...state.pendingActions, action] }))
    },

    clearPendingActions: () => set({ pendingActions: [] }),

    removePendingAction: (index) => {
      set((state) => ({
        pendingActions: state.pendingActions.filter((_, i) => i !== index),
      }))
    },

    setExecutionPhase: (phase) => set({ executionPhase: phase }),

    appendExecutionLog: (phase, message, data) => {
      set((state) => ({
        executionLogs: [
          ...state.executionLogs,
          { id: genId(), timestamp: Date.now(), phase, message, data },
        ],
      }))
    },

    resetExecution: () =>
      set({
        executionPhase: 'idle',
        executionLogs: [],
        semanticMatches: [],
        highlightRanges: [],
        pendingActions: [],
        appliedOperations: [],
        suggestedAction: null,
      }),

    setSemanticMatches: (matches) => set({ semanticMatches: matches }),
    setHighlightRanges: (ranges) => set({ highlightRanges: ranges }),

    recordAppliedOperation: (op) => {
      set((state) => ({ appliedOperations: [...state.appliedOperations, op] }))
    },

    setOllamaStatus: (status) => set({ ollamaStatus: status }),
    setAIServiceStatus: (status) => set({ aiServiceStatus: status }),
    setAIServicePhase: (phase) => set({ aiServicePhase: phase }),
    setDebugPanelOpen: (open) => set({ debugPanelOpen: open }),
    setDebugRetrieval: (snapshot) => set({ debugRetrieval: snapshot }),
    setRetrievalSessionId: (id) => set({ retrievalSessionId: id }),
    setLastRetrievalQuery: (query) => set({ lastRetrievalQuery: query }),
    setSuggestedAction: (action) => set({ suggestedAction: action }),
  })),
)
