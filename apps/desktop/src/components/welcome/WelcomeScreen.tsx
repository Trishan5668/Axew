import { motion } from 'framer-motion'
import { FolderOpen, Plus, Sparkles } from 'lucide-react'
import { pickProjectFile } from '../../lib/browserProjectStorage'
import { useProjectStore } from '../../stores/projectStore'
import { useUIStore } from '../../stores/uiStore'

export function WelcomeScreen() {
  const { createProject, openProject } = useProjectStore()
  const { setShowWelcome } = useUIStore()

  const handleNew = () => {
    createProject('Untitled Project')
    setShowWelcome(false)
  }

  const handleOpen = async () => {
    const project = await pickProjectFile()
    if (project) {
      openProject(project)
      setShowWelcome(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
      className="absolute inset-0 z-50 flex items-center justify-center bg-[#0A0A0C]/95 backdrop-blur-sm"
    >
      <div className="max-w-md text-center">
        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-axew-accentSubtle">
          <Sparkles size={32} className="text-axew-accent" />
        </div>
        <h1 className="mb-2 text-2xl font-semibold text-axew-text">AXEW</h1>
        <p className="mb-8 text-sm text-axew-textMuted">
          AI-native cinematic video editor. Local-first editing with Ollama-powered workflows.
        </p>
        <div className="flex flex-col gap-2">
          <button
            type="button"
            className="flex items-center justify-center gap-2 rounded-lg bg-axew-accent px-4 py-2.5 text-sm text-white hover:bg-axew-accentHover"
            onClick={handleNew}
          >
            <Plus size={16} />
            New Project
          </button>
          <button
            type="button"
            className="flex items-center justify-center gap-2 rounded-lg border border-axew-border px-4 py-2.5 text-sm text-axew-text hover:bg-axew-panel"
            onClick={handleOpen}
          >
            <FolderOpen size={16} />
            Open Project
          </button>
        </div>
      </div>
    </motion.div>
  )
}
