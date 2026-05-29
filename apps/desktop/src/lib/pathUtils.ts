export function basename(filePath: string): string {
  const parts = filePath.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || filePath
}

export function extname(filePath: string): string {
  const name = basename(filePath)
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}
