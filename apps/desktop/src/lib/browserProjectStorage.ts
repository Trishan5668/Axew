import type { Project } from '@shared/project'

const CURRENT_PROJECT_KEY = 'axew.currentProject'
const PROJECT_PREFIX = 'axew.project.'

export async function readProjectFile(file: File): Promise<Project> {
  const text = await file.text()
  const project = JSON.parse(text) as Project
  if (!project.transcripts) project.transcripts = {}
  return project
}

export function saveProjectToBrowser(project: Project): void {
  const data = JSON.stringify(project)
  localStorage.setItem(`${PROJECT_PREFIX}${project.id}`, data)
  localStorage.setItem(CURRENT_PROJECT_KEY, project.id)
}

export function loadLastProjectFromBrowser(): Project | null {
  const id = localStorage.getItem(CURRENT_PROJECT_KEY)
  if (!id) return null
  const data = localStorage.getItem(`${PROJECT_PREFIX}${id}`)
  if (!data) return null
  const project = JSON.parse(data) as Project
  if (!project.transcripts) project.transcripts = {}
  return project
}

export function downloadProjectFile(project: Project): void {
  const data = JSON.stringify(project, null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = project.path || `${project.name.replace(/[^a-zA-Z0-9-_]/g, '_')}.axew`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export async function pickProjectFile(): Promise<Project | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.axew,.json,application/json'
    input.onchange = async () => {
      const file = input.files?.[0]
      input.remove()
      if (!file) {
        resolve(null)
        return
      }
      try {
        resolve(await readProjectFile(file))
      } catch {
        resolve(null)
      }
    }
    input.click()
  })
}
